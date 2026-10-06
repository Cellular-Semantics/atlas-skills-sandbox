"""The range-read obs reader.

Works against any host that honours range requests (`accept-ranges: bytes`):
GCS, S3, Sanger COG, plain static hosts.
"""
from __future__ import annotations

import ssl
import time
import urllib.request
from dataclasses import dataclass

import certifi
import fsspec
import fsspec.implementations.http as fsh
import h5py
import numpy as np
import pandas as pd

CTX = ssl.create_default_context(cafile=certifi.where())


class ObsReadError(Exception):
    """The file could not be read, or is not shaped like an h5ad."""


@dataclass
class ReadStats:
    """How little was actually transferred -- the whole point of this route."""

    requests: int = 0
    bytes: int = 0
    seconds: float = 0.0
    total_bytes: int | None = None

    def as_dict(self) -> dict:
        return {"range_requests": self.requests, "bytes_fetched": self.bytes,
                "mb_fetched": round(self.bytes / 1e6, 1), "seconds": round(self.seconds, 1),
                "file_bytes": self.total_bytes}


# fsspec gives no per-file hook for byte accounting, so the HTTPFile class is
# swapped for a counting subclass. _ACTIVE is the stats object the current read
# is accumulating into; reads are serial, so one slot is enough.
_ACTIVE: list[ReadStats | None] = [None]


class _CountingHTTPFile(fsh.HTTPFile):
    def _fetch_range(self, start, end):
        stats = _ACTIVE[0]
        if stats is not None:
            stats.requests += 1
            stats.bytes += end - start
        return super()._fetch_range(start, end)


fsh.HTTPFile = _CountingHTTPFile


async def _get_client(**kwargs):
    # aiohttp does not read the macOS keychain, so an explicit certifi context is
    # required or GCS/S3 fail with CERTIFICATE_VERIFY_FAILED.
    import aiohttp

    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=CTX), **kwargs)


def check_range_support(url: str) -> int | None:
    """Preflight: range reads are the whole point, so fail loudly without them."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            accept = (r.headers.get("accept-ranges") or "").lower()
            size = r.headers.get("content-length")
    except Exception as e:
        raise ObsReadError(f"Could not HEAD {url}: {e}") from e
    if accept != "bytes":
        raise ObsReadError(
            f"Host does not advertise range support (accept-ranges: {accept or 'absent'}). "
            "Reading obs remotely needs range requests; this file must be downloaded whole.")
    return int(size) if size else None


def decode(arr):
    """h5py gives bytes for HDF5 string types; decode to str."""
    if getattr(arr, "dtype", None) is not None and arr.dtype.kind in ("S", "O"):
        return np.array([x.decode() if isinstance(x, bytes) else x for x in arr])
    return arr


def read_column(node):
    """Handle the three AnnData obs column encodings. None means unrecognised."""
    if isinstance(node, h5py.Group):
        keys = set(node.keys())
        if {"categories", "codes"} <= keys:
            cats = list(decode(node["categories"][:]))
            return pd.Categorical.from_codes(node["codes"][:], categories=cats)
        if {"values", "mask"} <= keys:  # nullable integer / boolean
            values = node["values"][:].astype("object")
            values[node["mask"][:]] = None
            return values
        return None
    return decode(node[:])


def column_order(obs) -> list[str]:
    order = [c if isinstance(c, str) else c.decode()
             for c in obs.attrs.get("column-order", [])]
    names = order or [k for k in obs.keys() if k != "_index"]
    for extra in obs.keys():  # column-order can lag the actual contents
        if extra != "_index" and extra not in names:
            names.append(extra)
    return names


def _open(url: str, block_size_mb: float):
    fs = fsspec.filesystem("http", get_client=_get_client)
    # blockcache is essential: fsspec's default readahead cache keeps only the
    # current block, so h5py's scattered chunk reads refetch endlessly.
    return fs.open(url, block_size=int(block_size_mb * 1024 * 1024),
                   cache_type="blockcache", cache_options={"maxblocks": 4096})


def list_columns(url: str, *, block_size_mb: float = 2.0,
                 opener=None) -> tuple[list[dict], ReadStats]:
    """The obs columns and their storage kind. Still reads HDF5 metadata, which is
    most of the cost of a full obs read."""
    stats = ReadStats()
    _ACTIVE[0] = stats
    t0 = time.time()
    try:
        with h5py.File((opener or _open)(url, block_size_mb), "r") as h5:
            if "obs" not in h5:
                raise ObsReadError("No /obs group in this file -- is it really an h5ad?")
            obs = h5["obs"]
            out = [{"name": n,
                    "kind": "categorical" if isinstance(obs[n], h5py.Group) else str(obs[n].dtype)}
                   for n in column_order(obs)]
    finally:
        stats.seconds = time.time() - t0
        _ACTIVE[0] = None
    return out, stats


def read_obs(url: str, *, columns: list[str] | None = None, block_size_mb: float = 2.0,
             opener=None) -> tuple[pd.DataFrame, list[str], ReadStats]:
    """Read obs (or just `columns`) into a DataFrame.

    Returns (df, skipped_column_names, stats).

    `opener` is an injection point for tests: a callable (url, block_size_mb) ->
    file-like. Production always uses the fsspec HTTP path.
    """
    stats = ReadStats()
    _ACTIVE[0] = stats
    t0 = time.time()
    try:
        with h5py.File((opener or _open)(url, block_size_mb), "r") as h5:
            if "obs" not in h5:
                raise ObsReadError("No /obs group in this file -- is it really an h5ad?")
            obs = h5["obs"]
            names = column_order(obs)
            if columns:
                unknown = [c for c in columns if c not in names]
                if unknown:
                    raise ObsReadError(f"Unknown obs column(s): {', '.join(unknown)}. "
                                       "Use --list-columns.")
                names = columns
            index = decode(obs["_index"][:]) if "_index" in obs else None
            cols, skipped = {}, []
            for name in names:
                value = read_column(obs[name])
                if value is None:
                    skipped.append(name)
                else:
                    cols[name] = value
    finally:
        stats.seconds = time.time() - t0
        _ACTIVE[0] = None

    df = pd.DataFrame(cols)
    if index is not None:
        df.index = pd.Index(index, name="cell_id")
    return df, skipped, stats
