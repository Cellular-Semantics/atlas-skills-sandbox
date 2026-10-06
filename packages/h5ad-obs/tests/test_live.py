"""Live tests: a real remote h5ad over the network. Excluded from CI.

    ./dev.sh -m live
    H5AD_OBS_LIVE_URL=https://my-host/file.h5ad pytest -m live   # your own host

The default subject is a 385-cell CELLxGENE Patch-seq dataset (~30 MB) --
deliberately tiny, so the suite stays quick and polite to the host while still
exercising the whole range-read path against a real CDN.

The asset URL embeds a dataset *version* id that changes whenever CELLxGENE
revises the dataset, so it is resolved at run time from the two **stable** ids
below rather than hardcoded. That costs one small API call and means an upstream
revision does not break the suite.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request

import certifi
import pytest

from h5ad_obs.reader import ObsReadError, check_range_support, list_columns, read_obs

pytestmark = pytest.mark.live

# "Human cortical expansion involves diversification and specialization of
# layer 2/3 neurons" -- 385 cells, Patch-seq, Homo sapiens.
CXG_API = "https://api.cellxgene.cziscience.com/curation/v1"
COLLECTION_ID = "4f586cb6-972b-4ef7-a4ef-3c3800a3c004"
DATASET_ID = "86b37b3c-1e5e-46a9-aecc-2d95b6a38d4b"
EXPECTED_CELLS = 385

# The default 2 MB block fetches a third of a file this small; the package is
# tuned for 400 MB+ atlases. A small block shows the selectivity properly.
BLOCK_MB = 0.125


def _resolve_cellxgene() -> str:
    url = f"{CXG_API}/collections/{COLLECTION_ID}/datasets/{DATASET_ID}"
    req = urllib.request.Request(url, headers={"user-agent": "h5ad-obs tests"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        payload = json.load(r)
    asset = next((a for a in payload.get("assets", []) if a.get("filetype") == "H5AD"), None)
    if not asset:
        pytest.skip("CELLxGENE no longer publishes an H5AD asset for this dataset")
    return asset["url"]


@pytest.fixture(scope="module")
def url() -> str:
    return os.environ.get("H5AD_OBS_LIVE_URL") or _resolve_cellxgene()


@pytest.fixture(scope="module")
def is_default(url) -> bool:
    """Whether we are reading the known dataset, so its shape can be asserted."""
    return not os.environ.get("H5AD_OBS_LIVE_URL")


def test_host_honours_range_requests(url):
    assert check_range_support(url) > 0


def test_list_columns(url, is_default):
    cols, stats = list_columns(url, block_size_mb=BLOCK_MB)
    assert cols and stats.requests > 0
    if is_default:
        names = {c["name"] for c in cols}
        assert {"cell_type", "donor_id", "assay"} <= names, sorted(names)


def test_read_obs_whole_table(url, is_default):
    df, skipped, _stats = read_obs(url, block_size_mb=BLOCK_MB)
    assert df.shape[0] > 0 and df.shape[1] > 0
    assert skipped == [], f"unrecognised obs encodings: {skipped}"
    if is_default:
        assert df.shape[0] == EXPECTED_CELLS
        assert str(df["cell_type"].iloc[0]) == "glutamatergic neuron"


def test_only_a_fraction_of_the_file_is_fetched(url):
    """The whole claim of the package. On the default dataset this is ~4%."""
    total = check_range_support(url)
    _df, _skipped, stats = read_obs(url, block_size_mb=BLOCK_MB)
    assert stats.bytes < total, "fetched at least the whole file -- no saving at all"
    assert stats.bytes < total * 0.5, (
        f"fetched {stats.bytes / 1e6:.1f} MB of {total / 1e6:.1f} MB; range selectivity "
        "has regressed")


def test_column_subset_is_readable(url):
    cols, _stats = list_columns(url, block_size_mb=BLOCK_MB)
    name = cols[0]["name"]
    df, _skipped, _stats = read_obs(url, columns=[name], block_size_mb=BLOCK_MB)
    assert list(df.columns) == [name]


def test_a_missing_file_fails_at_preflight():
    with pytest.raises(ObsReadError):
        check_range_support("https://datasets.cellxgene.cziscience.com/"
                            "00000000-0000-0000-0000-000000000000.h5ad")
