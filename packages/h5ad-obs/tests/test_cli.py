import json

import pytest

from conftest import N_CELLS
from h5ad_obs import cli


def run(capsys, argv, code=0):
    assert cli.main(argv) == code
    return capsys.readouterr()


def test_list_columns_json(capsys, served):
    url, _server = served
    out = run(capsys, [url, "--list-columns"])
    payload = json.loads(out.out)
    assert payload["n_obs_columns"] == 5
    assert payload["obs_columns"][0] == {"name": "cell_type", "kind": "categorical"}
    assert payload["range_requests"] > 0
    assert payload["file_bytes"] > 0


def test_writes_parquet_and_reports_it(capsys, served, tmp_path):
    url, _server = served
    out_path = tmp_path / "obs.parquet"
    out = run(capsys, [url, "--out", str(out_path)])
    payload = json.loads(out.out)
    assert payload["n_rows"] == N_CELLS and payload["n_columns"] == 4
    assert payload["skipped_columns"] == ["weird"]
    assert payload["out"] == str(out_path)
    import pandas as pd
    assert pd.read_parquet(out_path).shape == (N_CELLS, 4)


def test_writes_tsv(capsys, served, tmp_path):
    url, _server = served
    out_path = tmp_path / "obs.tsv"
    run(capsys, [url, "--format", "tsv", "--out", str(out_path),
                 "--columns", "cell_type", "donor_id"])
    header = out_path.read_text().splitlines()[0]
    assert header.split("\t") == ["cell_id", "cell_type", "donor_id"]


def test_column_subset(capsys, served, tmp_path):
    url, _server = served
    out = run(capsys, [url, "--columns", "cell_type", "--out", str(tmp_path / "o.parquet")])
    assert json.loads(out.out)["columns"] == ["cell_type"]


def test_unknown_column_exits_nonzero(capsys, served, tmp_path):
    url, _server = served
    out = run(capsys, [url, "--columns", "nope", "--out", str(tmp_path / "o.parquet")], code=1)
    assert "error: Unknown obs column" in out.err


def test_no_range_support_exits_nonzero(capsys, no_range_url):
    out = run(capsys, [no_range_url], code=1)
    assert "does not advertise range support" in out.err


def test_no_preflight_skips_the_head(capsys, served, tmp_path):
    url, _server = served
    out = run(capsys, [url, "--no-preflight", "--out", str(tmp_path / "o.parquet")])
    assert json.loads(out.out)["file_bytes"] is None


def test_a_cap_portal_url_says_what_to_run_instead(capsys):
    """A portal page is not an h5ad. Parsing HTML as HDF5 fails incomprehensibly, so
    the known portals are caught up front and answered with the fix."""
    assert cli.main(["https://celltype.info/project/1030/dataset/3400"]) == 1
    err = capsys.readouterr().err
    assert "cap h5ad-url" in err
    assert "celltype.info/project/1030/dataset/3400" in err, "the hint should be runnable"


def test_a_cellxgene_portal_url_says_what_to_run_instead(capsys):
    assert cli.main(["https://cellxgene.cziscience.com/collections/abc"]) == 1
    assert "curation/v1/collections" in capsys.readouterr().err


def test_a_plain_h5ad_url_is_not_intercepted(capsys, served, tmp_path):
    """The portal check must not catch ordinary file URLs."""
    url, _server = served
    out = run(capsys, [url, "--out", str(tmp_path / "o.parquet")])
    assert json.loads(out.out)["n_rows"] == N_CELLS


@pytest.mark.parametrize("url", [
    # The bug this pins: a substring match on "cellxgene.cziscience.com" rejects
    # CELLxGENE's own asset host, which is the single most likely URL a user will
    # pass. Found by running the published artifact, not by the offline suite.
    "https://datasets.cellxgene.cziscience.com/28ef397e-0819.h5ad",
    "https://api.cellxgene.cziscience.com/something.h5ad",
    # Nor should a portal name appearing elsewhere in the URL trigger it.
    "https://example.org/mirror/celltype.info/copy.h5ad",
    "https://example.org/f.h5ad?from=cellxgene.cziscience.com",
])
def test_portal_check_matches_the_host_not_a_substring(url):
    from h5ad_obs.cli import check_target
    check_target(url)  # must not raise


@pytest.mark.parametrize("url", [
    "https://celltype.info/project/1/dataset/2",
    "https://www.celltype.info/project/1/dataset/2",
    "https://CELLTYPE.INFO/project/1/dataset/2",
    "https://cellxgene.cziscience.com/collections/abc",
])
def test_portal_check_catches_portal_hosts(url):
    from h5ad_obs.cli import check_target
    from h5ad_obs.reader import ObsReadError
    with pytest.raises(ObsReadError):
        check_target(url)


def test_version_matches_the_installed_distribution():
    """__version__ was hand-maintained and drifted from pyproject.toml during the
    split out of cap_skills, so --version reported a release that did not exist."""
    from importlib import metadata

    from h5ad_obs import __version__
    assert __version__ == metadata.version("h5ad-obs")


def test_version(capsys):
    from h5ad_obs import __version__
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out
