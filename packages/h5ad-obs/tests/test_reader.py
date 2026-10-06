import json

import numpy as np
import pandas as pd
import pytest

from conftest import N_CELLS
from h5ad_obs import read_obs
from h5ad_obs.reader import ObsReadError, check_range_support, decode, list_columns


def test_decode_bytes_to_str():
    out = decode(np.array([b"a", b"b"]))
    assert list(out) == ["a", "b"]


def test_decode_leaves_numbers_alone():
    arr = np.arange(3)
    assert decode(arr) is arr


def test_preflight_accepts_a_range_server(served):
    url, _server = served
    assert check_range_support(url) > 0


def test_preflight_rejects_a_server_without_ranges(no_range_url):
    with pytest.raises(ObsReadError, match="does not advertise range support"):
        check_range_support(no_range_url)


def test_preflight_reports_an_unreachable_host():
    with pytest.raises(ObsReadError, match="Could not HEAD"):
        check_range_support("http://127.0.0.1:1/nope.h5ad")


def test_list_columns(served):
    url, _server = served
    cols, stats = list_columns(url)
    assert [c["name"] for c in cols] == ["cell_type", "donor_id", "n_genes",
                                         "is_doublet", "weird"]
    assert cols[0]["kind"] == "categorical"
    assert stats.requests > 0 and stats.bytes > 0


def test_read_obs_all_columns(served):
    url, _server = served
    df, skipped, stats = read_obs(url)
    assert df.shape == (N_CELLS, 4)
    assert skipped == ["weird"], "an unrecognised encoding is skipped, not fatal"
    assert df.index.name == "cell_id"
    assert df.index[0] == "cell0"
    assert list(df.columns) == ["cell_type", "donor_id", "n_genes", "is_doublet"]
    assert stats.requests > 0


def test_categorical_round_trip(served):
    url, _server = served
    df, _skipped, _stats = read_obs(url, columns=["cell_type"])
    assert isinstance(df["cell_type"].dtype, pd.CategoricalDtype)
    assert set(df["cell_type"].cat.categories) == {"Tuft Cells", "Tuft Progenitors"}
    assert df["cell_type"].iloc[0] == "Tuft Cells"


def test_nullable_boolean_mask_becomes_none(served):
    url, _server = served
    df, _skipped, _stats = read_obs(url, columns=["is_doublet"])
    # cell0 is masked (0 % 11 == 0) so it must be null, not False.
    assert df["is_doublet"].iloc[0] is None
    assert df["is_doublet"].iloc[7] is True


def test_column_subset_reads_less(served):
    url, server = served
    _df, _s, all_stats = read_obs(url)
    server.served_ranges.clear()
    _df, _s, one_stats = read_obs(url, columns=["cell_type"])
    assert one_stats.bytes <= all_stats.bytes


def test_the_matrix_is_never_fetched(served):
    """The point of the whole package: X's byte ranges must not be touched.

    The block size has to be well below the file size for this to mean anything
    -- the fixture file is ~1.2 MB, so the 2 MB production default would fetch it
    whole in one range. Real atlases are 400 MB+.
    """
    url, server = served
    server.served_ranges.clear()
    _df, _skipped, stats = read_obs(url, columns=["cell_type"], block_size_mb=0.05)
    fetched = sum(end - start for start, end in server.served_ranges)
    assert fetched < len(server.payload) * 0.5, (
        f"fetched {fetched} of {len(server.payload)} bytes -- the matrix is being read")
    assert stats.bytes == pytest.approx(fetched, rel=0.1)


def test_unknown_column(served):
    url, _server = served
    with pytest.raises(ObsReadError, match="Unknown obs column"):
        read_obs(url, columns=["no_such_column"])


def test_not_an_h5ad(tmp_path):
    """The opener injection point lets this run against a local file: no server
    state to disturb."""
    import h5py
    other = tmp_path / "plain.h5"
    with h5py.File(other, "w") as f:
        f.create_dataset("X", data=np.zeros(3))
    with other.open("rb") as handle, pytest.raises(ObsReadError, match="No /obs group"):
        read_obs("ignored", opener=lambda url, bs: handle)


def test_stats_as_dict_shape():
    from h5ad_obs.reader import ReadStats
    d = ReadStats(requests=3, bytes=2_000_000, seconds=1.234, total_bytes=10).as_dict()
    assert d == {"range_requests": 3, "bytes_fetched": 2_000_000, "mb_fetched": 2.0,
                 "seconds": 1.2, "file_bytes": 10}
    json.dumps(d)
