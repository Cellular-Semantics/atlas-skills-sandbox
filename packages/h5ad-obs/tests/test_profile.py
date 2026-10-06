"""Profile tests: the column summary an agent reads to decide what a column is.

Runs against the same localhost range server as the reader tests, so the remote
path is exercised for real without touching the network.
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from h5ad_obs.cli import main
from h5ad_obs.profile import _spread, as_text, profile_frame, profile_local, profile_remote


def by_name(prof: dict) -> dict:
    return {c["name"]: c for c in prof["columns"]}


# --- the sampling rule -------------------------------------------------------

def test_spread_covers_the_whole_table_not_the_head():
    idx = _spread(1_000_000, 10)
    assert idx[0] == 0 and idx[-1] == 999_999
    assert len(idx) == 10


def test_spread_returns_every_row_when_the_table_is_small():
    assert list(_spread(5, 2000)) == [0, 1, 2, 3, 4]


def test_head_sampling_would_have_lied_about_a_sorted_column():
    """Why the sample is spread and not the head. obs is routinely sorted by
    donor or cluster; the first 20 rows of a sorted column show one value, which
    reads as a constant column when it is nothing of the kind."""
    df = pd.DataFrame({"cluster": ["A"] * 500 + ["B"] * 500})
    col = by_name(profile_frame(df))["cluster"]
    assert col["n_unique"] == 2
    assert set(col["sample"]) == {"A", "B"}


# --- the remote path ---------------------------------------------------------

def test_remote_profile_shape(served):
    url, _server = served
    prof, stats = profile_remote(url, block_size_mb=0.05)
    assert prof["source_kind"] == "remote-h5ad"
    assert prof["n_rows"] == 500
    assert stats.requests > 0
    assert {c["name"] for c in prof["columns"]} == {
        "cell_type", "donor_id", "n_genes", "is_doublet", "weird"}


def test_remote_profile_reports_each_encoding(served):
    url, _server = served
    prof, _stats = profile_remote(url, block_size_mb=0.05)
    cols = by_name(prof)

    cat = cols["cell_type"]
    assert cat["kind"] == "categorical"
    assert cat["n_categories"] == 2 and cat["n_unique"] == 2
    assert cat["n_unique_estimated"] is False
    assert set(cat["sample"]) == {"Tuft Cells", "Tuft Progenitors"}

    assert cols["donor_id"]["kind"] == "string"
    assert cols["donor_id"]["n_unique"] == 5
    assert cols["n_genes"]["kind"] == "array"

    # nullable masked: masked entries are null, not False
    assert cols["is_doublet"]["kind"] == "nullable"
    assert cols["is_doublet"]["n_null"] > 0

    # an encoding the reader does not understand is reported, not fatal
    assert cols["weird"]["kind"] == "unknown"


def test_remote_profile_is_cheaper_than_reading_obs(served):
    """The whole reason the remote path exists. Only category tables and a
    bounded sample per column are fetched."""
    from h5ad_obs.reader import read_obs

    url, _server = served
    _prof, pstats = profile_remote(url, block_size_mb=0.01)
    _df, _skipped, rstats = read_obs(url, block_size_mb=0.01)
    assert pstats.bytes <= rstats.bytes


def test_remote_profile_never_touches_the_matrix(served):
    """The point of the whole route. X is most of the fixture file; profiling
    must fetch a small fraction of it."""
    url, server = served
    server.served_ranges.clear()
    profile_remote(url, block_size_mb=0.01)
    fetched = sum(end - start for start, end in server.served_ranges)
    assert fetched < len(server.payload) * 0.5, (
        f"fetched {fetched} of {len(server.payload)} bytes -- the matrix is being read")


# --- the local path ----------------------------------------------------------

def test_local_profile_matches_the_remote_one(served, tmp_path):
    """The two sources must be interchangeable -- an agent that profiles a
    previously-pulled obs table must see what it would have seen over the wire."""
    from h5ad_obs.reader import read_obs

    url, _server = served
    df, _skipped, _stats = read_obs(url, block_size_mb=0.05)
    out = tmp_path / "obs.parquet"
    df.to_parquet(out)

    remote, _stats = profile_remote(url, block_size_mb=0.05)
    local = profile_local(out)

    assert local["n_rows"] == remote["n_rows"]
    rem, loc = by_name(remote), by_name(local)
    # `weird` is skipped by the reader, so it cannot appear in the pulled table.
    for name in set(rem) & set(loc):
        assert loc[name]["n_unique"] == rem[name]["n_unique"], name
        assert set(loc[name]["sample"]) == set(rem[name]["sample"]), name


def test_constant_column_is_flagged():
    df = pd.DataFrame({"lineage": ["Epithelial"] * 300, "sub": list("ab") * 150})
    cols = by_name(profile_frame(df))
    assert cols["lineage"]["constant"] is True
    assert cols["sub"]["constant"] is False


def test_constant_is_not_claimed_from_a_partial_scan():
    """`constant` means every row was seen. A sample that happens to be uniform
    is not evidence, and saying so would make the picker drop a real column."""
    df = pd.DataFrame({"c": ["x"] * 9999 + ["y"]})
    col = by_name(profile_frame(df, scan_n=50))["c"]
    assert col["n_unique_estimated"] is True
    assert col["constant"] is False


def test_numeric_cluster_ids_stay_distinguishable_from_labels():
    """Rule 3 in the picker: string-encoded integers are cluster indices, not
    labels. The profile must preserve the difference rather than stringify it."""
    df = pd.DataFrame({"seurat_clusters": pd.Categorical([str(i % 30) for i in range(600)]),
                       "author_cell_type": pd.Categorical(["L2/3 IT", "CD8+ T cell"] * 300)})
    cols = by_name(profile_frame(df))
    assert all(v.isdigit() for v in cols["seurat_clusters"]["sample"])
    assert not any(v.isdigit() for v in cols["author_cell_type"]["sample"])


def test_nan_becomes_null_not_the_string_nan():
    df = pd.DataFrame({"x": [1.0, np.nan, 3.0]})
    assert None not in by_name(profile_frame(df))["x"]["sample"]
    assert by_name(profile_frame(df))["x"]["n_null"] == 1


def test_local_profile_rejects_an_h5ad_path():
    from h5ad_obs.reader import ObsReadError

    with pytest.raises(ObsReadError, match="parquet"):
        profile_local("something.h5ad")


# --- the text rendering ------------------------------------------------------

def test_text_rendering_is_data_only(served):
    """The table must carry no picking instructions. Those live in the skill and
    the picker agent; duplicating them here is how the two drift apart."""
    url, _server = served
    prof, _stats = profile_remote(url, block_size_mb=0.05)
    text = as_text(prof)
    assert "cell_type | categorical[2 cats] | 2 |" in text
    assert "weird | unknown encoding" in text
    for word in ("pick", "author", "DO NOT", "rule"):
        assert word.lower() not in text.lower()


def test_text_marks_a_constant_column():
    df = pd.DataFrame({"lineage": ["Epithelial"] * 300})
    assert "(constant)" in as_text(profile_frame(df))


def test_text_marks_an_estimate():
    df = pd.DataFrame({"x": [str(i) for i in range(10_000)]})
    assert "| ~" in as_text(profile_frame(df, scan_n=100))


# --- measurement: telling an age from a score --------------------------------

def test_a_per_cell_score_is_continuous_and_an_age_is_bounded():
    """The whole point of the flag. Both columns are numbers; only the number
    of distinct values says which one is a property of the donor."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "percent_mito": rng.random(20_000),
        "n_genes": rng.integers(500, 12_000, 20_000),
        "age_years": rng.choice([23, 30, 37, 55, 64], 20_000),
    })
    cols = by_name(profile_frame(df))
    assert cols["percent_mito"]["bounded"] is False
    assert cols["n_genes"]["bounded"] is False
    assert cols["age_years"]["bounded"] is True


def test_an_age_stored_as_a_categorical_of_numerals_is_still_a_measurement():
    """How ages actually arrive: numerals in a category table beside a sentinel.
    A test that looked at the dtype would call this text and stop."""
    values = ["Not applicable"] + [str(w) for w in range(6, 22)]
    df = pd.DataFrame({"Gestational_age_pcw": pd.Categorical(values * 50)})
    col = by_name(profile_frame(df))["Gestational_age_pcw"]
    assert col["numeric"]["min"] == 6.0 and col["numeric"]["max"] == 21.0
    assert col["numeric"]["fraction"] < 1.0      # the sentinel did not parse
    assert col["bounded"] is True


def test_a_categorical_is_characterised_from_its_categories_not_the_scan():
    """A rare category -- one late gestational age in a 2M-cell adult atlas --
    never shows up in a 2000-row scan. The category table is exact, so the
    range must include it anyway."""
    common = ["6"] * 200_000
    rare = ["40"]
    df = pd.DataFrame({"age": pd.Categorical(common + rare)})
    col = by_name(profile_frame(df, scan_n=2000))["age"]
    assert col["numeric"]["max"] == 40.0


def test_a_text_column_has_no_measurement():
    df = pd.DataFrame({"Organ": pd.Categorical(["Uterus", "Ovary"] * 50)})
    assert by_name(profile_frame(df))["Organ"]["numeric"] is None


def test_a_mostly_text_column_with_a_few_numerals_has_no_measurement():
    """`disease` with a '2' in it is not a measurement, and a range over the
    stray numerals would be noise the picker has to read past."""
    values = ["control", "endometriosis", "teratoma", "2"]
    df = pd.DataFrame({"Disease": pd.Categorical(values * 50)})
    assert by_name(profile_frame(df))["Disease"]["numeric"] is None


def test_a_boolean_is_not_a_measurement():
    """True is not 1. A bool column read as numeric would render as a bounded
    measurement spanning 0..1, which is exactly what a fraction looks like."""
    df = pd.DataFrame({"predicted_doublet": [True, False] * 100})
    assert by_name(profile_frame(df))["predicted_doublet"]["numeric"] is None


def test_the_floor_lets_a_small_table_through():
    """8 distinct ages in 60 rows is 13% -- over the ratio. Without the absolute
    floor every small dataset would have its age column called continuous."""
    df = pd.DataFrame({"age": [20, 25, 30, 35, 40, 45, 50, 55] * 8})
    assert by_name(profile_frame(df))["age"]["bounded"] is True


def test_a_cluster_index_is_bounded_too():
    """The flag is a filter, not a verdict: `seurat_clusters` passes it. What
    rejects a cluster index is its values, and those are in the profile."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"seurat_clusters": pd.Categorical(
        rng.integers(0, 30, 5000).astype(str))})
    assert by_name(profile_frame(df))["seurat_clusters"]["bounded"] is True


def test_text_shows_the_shape_and_the_range():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({
        "percent_mito": rng.random(20_000),
        "age_years": rng.choice([23, 64], 20_000),
    })
    text = as_text(profile_frame(df))
    assert "| continuous 0" in text
    assert "| bounded 23..64 |" in text


def test_text_reports_the_numeric_fraction_only_when_it_is_short():
    whole = pd.DataFrame({"age": pd.Categorical(["30", "40"] * 50)})
    assert "% numeric" not in as_text(profile_frame(whole))
    mixed = pd.DataFrame({"age": pd.Categorical(["30", "40", "unknown"] * 50)})
    assert "(67% numeric)" in as_text(profile_frame(mixed))


def test_text_stays_readable_for_a_column_that_is_not_a_measurement():
    """An empty cell, not the word 'None' -- 50 of them in a profile is noise."""
    df = pd.DataFrame({"Organ": pd.Categorical(["Uterus"] * 50)})
    line = next(ln for ln in as_text(profile_frame(df)).splitlines()
                if ln.startswith("Organ |"))
    assert line.endswith("|  | 'Uterus', 'Uterus', 'Uterus', 'Uterus', 'Uterus', "
                         "'Uterus', 'Uterus', 'Uterus', 'Uterus', 'Uterus', ...")


# --- the CLI contract --------------------------------------------------------

def test_cli_profile_json(served, capsys):
    url, _server = served
    assert main([url, "--profile", "--block-size", "0.05"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_rows"] == 500
    assert payload["mb_fetched"] >= 0  # byte accounting is carried through
    assert {"name", "kind", "n_unique", "sample"} <= set(payload["columns"][0])


def test_cli_profile_text(served, capsys):
    url, _server = served
    assert main([url, "--profile", "text", "--block-size", "0.05"]) == 0
    assert "obs profile:" in capsys.readouterr().out


def test_cli_profiles_a_local_table_without_a_url(tmp_path, capsys):
    out = tmp_path / "obs.parquet"
    pd.DataFrame({"cell_type": ["Tuft"] * 4}).to_parquet(out)
    assert main([str(out), "--profile"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_kind"] == "local-table"
    assert "mb_fetched" not in payload  # nothing was fetched; do not pretend otherwise


def test_cli_still_rejects_a_portal_page_when_profiling(capsys):
    assert main(["https://celltype.info/project/1/dataset/2", "--profile"]) == 1
    assert "cap h5ad-url" in capsys.readouterr().err


def test_cli_help_mentions_profile():
    out = subprocess.run([sys.executable, "-m", "h5ad_obs.cli", "--help"],
                         capture_output=True, text=True)
    assert "--profile" in out.stdout


# --- regressions -------------------------------------------------------------

def test_a_constant_categorical_is_flagged_on_a_table_too_big_to_scan():
    """A category table is exact however few rows were sampled. Tying the flag
    to scan coverage instead left it off for every dataset over `scan_n` rows --
    which is most of them, and the picker's constant-column rule needs it."""
    df = pd.DataFrame({"Lineage": pd.Categorical(["Lymphoid_T/NK"] * 110_000)})
    col = by_name(profile_frame(df, scan_n=2000))["Lineage"]
    assert col["n_unique"] == 1
    assert col["n_unique_estimated"] is False
    assert col["constant"] is True
    assert "(constant)" in as_text(profile_frame(df, scan_n=2000))


def test_a_declared_but_unused_category_is_not_called_constant():
    """Conservative on purpose: categories are declared, not observed, so a
    second unused level is enough to withhold the claim."""
    values = pd.Categorical(["A"] * 100, categories=["A", "B"])
    col = by_name(profile_frame(pd.DataFrame({"c": values})))["c"]
    assert col["n_unique"] == 2
    assert col["constant"] is False


def test_a_stringified_nan_category_is_not_a_number():
    """`float('nan')` succeeds. obs categoricals routinely carry a literal
    'nan' category from a stringified missing value, and letting it through put
    a NaN in the range and crashed the text profile on a fifth of CELLxGENE."""
    values = ["nan", "6", "11", "nan"]
    df = pd.DataFrame({"age": pd.Categorical(values * 50)})
    col = by_name(profile_frame(df))["age"]
    assert col["numeric"]["min"] == 6.0 and col["numeric"]["max"] == 11.0
    as_text(profile_frame(df))        # must not raise


def test_an_all_nan_string_column_is_not_a_measurement():
    df = pd.DataFrame({"x": pd.Categorical(["nan", "NA", "inf"] * 50)})
    assert by_name(profile_frame(df))["x"]["numeric"] is None


def test_the_remote_path_measures_a_numeric_column_too(served):
    """The two paths must agree. `profile_frame` normalises through .tolist()
    and the remote path does not, so building the vocabulary from raw values
    classified every numeric column in every *remote* profile as not-a-number
    -- invisible to every local-path test in this file."""
    url, _server = served
    prof, _stats = profile_remote(url, block_size_mb=0.05)
    n_genes = by_name(prof)["n_genes"]
    assert n_genes["numeric"] is not None, "a numeric column read remotely lost its range"
    assert n_genes["numeric"]["fraction"] == 1.0


def test_both_paths_agree_on_the_measurement(served):
    """Read obs whole, profile the frame, and compare against the profile taken
    over range reads. This is the shape the skill actually uses."""
    url, _server = served
    remote, _stats = profile_remote(url, block_size_mb=0.05)
    from h5ad_obs.reader import read_obs
    df, _skipped, _stats2 = read_obs(url, block_size_mb=0.05)
    local = profile_frame(df)
    for name, col in by_name(remote).items():
        if col["kind"] == "unknown":
            continue
        assert col["numeric"] == by_name(local)[name]["numeric"], name
        assert col["bounded"] == by_name(local)[name]["bounded"], name


def test_sample_values_are_plain_strings():
    """numpy's str_ is a str subclass whose repr is `np.str_('x')`. Passing it
    through rendered that in the text profile, which the picker then has to read
    past on every single row."""
    df = pd.DataFrame({"c": pd.Categorical([np.str_("Mono"), np.str_("CD8 T")] * 50)})
    prof = profile_frame(df)
    assert all(type(v) is str for v in by_name(prof)["c"]["sample"])
    assert "np.str_" not in as_text(prof)
    assert "'Mono'" in as_text(prof)
