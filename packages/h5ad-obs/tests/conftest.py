"""A real h5ad on disk, and a local HTTP server that honours range requests.

Nothing here reaches the internet: the range-read path is exercised end to end
against localhost, which is the only way to test the byte accounting and the
blockcache behaviour that make this package worth having.
"""
from __future__ import annotations

import http.server
import threading

import h5py
import numpy as np
import pytest

N_CELLS = 500


@pytest.fixture(scope="session")
def h5ad_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "mini.h5ad"
    rng = np.random.default_rng(0)
    with h5py.File(path, "w") as f:
        obs = f.create_group("obs")
        obs.attrs["column-order"] = np.array(
            ["cell_type", "donor_id", "n_genes", "is_doublet"], dtype=h5py.special_dtype(vlen=str))
        obs.create_dataset("_index", data=np.array([f"cell{i}" for i in range(N_CELLS)],
                                                   dtype="S12"))

        # categorical: the commonest obs encoding
        cats = obs.create_group("cell_type")
        cats.create_dataset("categories", data=np.array([b"Tuft Cells", b"Tuft Progenitors"]))
        cats.create_dataset("codes", data=(np.arange(N_CELLS) % 2).astype("i1"))

        obs.create_dataset("donor_id", data=np.array(
            [f"donor{i % 5}".encode() for i in range(N_CELLS)]))
        obs.create_dataset("n_genes", data=rng.integers(200, 5000, N_CELLS))

        # nullable boolean: values + mask
        nb = obs.create_group("is_doublet")
        nb.create_dataset("values", data=(np.arange(N_CELLS) % 7 == 0))
        nb.create_dataset("mask", data=(np.arange(N_CELLS) % 11 == 0))

        # an encoding the reader does not understand, which must be skipped
        weird = obs.create_group("weird")
        weird.create_dataset("something_else", data=np.zeros(N_CELLS))

        # a matrix, to prove it is never read
        f.create_dataset("X", data=rng.random((N_CELLS, 300)), chunks=(50, 300))
    return path


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler ignores Range; this adds the 206 path."""

    def log_message(self, *args):  # keep the test output quiet
        pass

    def do_GET(self):
        body = self.server.payload
        rng = self.headers.get("Range")
        if not rng:
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.send_header("accept-ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)
            return
        start, _, end = rng.partition("=")[2].partition("-")
        start = int(start)
        end = int(end) if end else len(body) - 1
        chunk = body[start:end + 1]
        self.server.served_ranges.append((start, end))
        self.send_response(206)
        self.send_header("content-range", f"bytes {start}-{end}/{len(body)}")
        self.send_header("content-length", str(len(chunk)))
        self.send_header("accept-ranges", "bytes")
        self.end_headers()
        self.wfile.write(chunk)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("content-length", str(len(self.server.payload)))
        self.send_header("accept-ranges", "bytes")
        self.end_headers()


@pytest.fixture(scope="session")
def served(h5ad_path):
    """(url, server) for the h5ad, over a localhost range-capable server."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    server.payload = h5ad_path.read_bytes()
    server.served_ranges = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/mini.h5ad", server
    server.shutdown()


@pytest.fixture(scope="session")
def no_range_url():
    """A server that does not advertise range support, for the preflight test."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("content-length", "10")
            self.end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/whole.h5ad"
    server.shutdown()
