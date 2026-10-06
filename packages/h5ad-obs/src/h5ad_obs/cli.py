"""The `h5ad-obs` command line.

stdout carries a JSON summary (row/column counts, byte accounting, output path);
obs itself goes to a file, because it is usually large. stderr carries progress.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse

from . import __version__
from .profile import DEFAULT_SAMPLE_N, DEFAULT_SCAN_N, as_text, profile_local, profile_remote
from .reader import ObsReadError, check_range_support, list_columns, read_obs


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


#: Portals that serve h5ad behind a landing page rather than at the URL you see.
#: This package stays free of portal-specific clients -- each of these has its own
#: tool for the lookup -- but recognising them turns a baffling HTML-parse failure
#: into a message saying exactly what to run.
#:
#: Keyed on the EXACT hostname, never a substring: CELLxGENE serves its actual
#: assets from datasets.cellxgene.cziscience.com, which contains the portal host
#: and would otherwise be rejected as a portal page.
_PORTAL_HINTS = {
    "celltype.info": (
        "That is a CAP dataset page, not an h5ad. Resolve it first:\n"
        "  h5ad-obs \"$(cap h5ad-url {target} --format text)\"\n"
        "`cap` comes from the cap-tools plugin "
        "(github.com/Cellular-Semantics/cap_skills). Note many CAP datasets expose "
        "no public h5ad at all; `cap expression --list-obs-columns` still works on "
        "those."),
    "cellxgene.cziscience.com": (
        "That is a CELLxGENE portal page, not an h5ad. The download URL is on the "
        "dataset's page, or from the API:\n"
        "  curl -s https://api.cellxgene.cziscience.com/curation/v1/collections/"
        "<collection_id>/datasets/<dataset_id> | jq -r '.assets[]|select(.filetype"
        '=="H5AD")|.url\''),
}


def check_target(target: str) -> None:
    """Fail early, and usefully, on a portal page handed over in place of a file."""
    host = (urllib.parse.urlparse(target).hostname or "").lower().removeprefix("www.")
    hint = _PORTAL_HINTS.get(host)
    if hint:
        raise ObsReadError(hint.format(target=target))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="h5ad-obs",
        description="Read obs from a remote h5ad via HTTP range reads, without "
                    "downloading the expression matrix.")
    ap.add_argument("--version", action="version", version=f"h5ad-obs {__version__}")
    ap.add_argument("target",
                    help="URL of a remote .h5ad, on a host honouring range requests. "
                         "With --profile this may instead be a local obs table "
                         "(.parquet/.csv/.tsv) previously written by this tool")
    ap.add_argument("--columns", nargs="+", help="Only these obs columns (default: all)")
    ap.add_argument("--list-columns", action="store_true",
                    help="List obs columns and exit (still reads HDF5 metadata: most of "
                         "the cost of a full obs read)")
    ap.add_argument("--out", help="Output path (default obs.parquet / obs.csv / obs.tsv)")
    ap.add_argument("--format", default="parquet", choices=["parquet", "csv", "tsv"],
                    help="Output file format for the obs table (default parquet)")
    ap.add_argument("--block-size", type=float, default=2.0, metavar="MB",
                    help="Range block size in MB (default 2; smaller = fewer bytes, "
                         "more requests)")
    ap.add_argument("--no-preflight", action="store_true",
                    help="Skip the range-support check")
    ap.add_argument("--profile", nargs="?", const="json", choices=["json", "text"],
                    metavar="json|text",
                    help="Print a per-column profile (kind, cardinality, sample values) "
                         "to stdout instead of reading obs. Profiling a local obs table "
                         "is free; profiling a URL costs about as much as --list-columns")
    ap.add_argument("--scan-rows", type=int, default=DEFAULT_SCAN_N, metavar="N",
                    help=f"Rows sampled per column when profiling (default {DEFAULT_SCAN_N}). "
                         "Rows are spread across the table, not taken from the head; "
                         "columns shorter than this are counted exactly")
    ap.add_argument("--sample-n", type=int, default=DEFAULT_SAMPLE_N, metavar="N",
                    help=f"Sample values shown per column in a profile "
                         f"(default {DEFAULT_SAMPLE_N})")
    return ap


def _is_url(target: str) -> bool:
    return urllib.parse.urlparse(target).scheme in ("http", "https", "s3", "gs")


def run_profile(args) -> int:
    """Profile a remote h5ad, or a local obs table already pulled from one."""
    if not _is_url(args.target):
        prof = profile_local(args.target, scan_n=args.scan_rows, sample_n=args.sample_n)
        stats = None
    else:
        check_target(args.target)
        total = None if args.no_preflight else check_range_support(args.target)
        prof, stats = profile_remote(args.target, scan_n=args.scan_rows,
                                     sample_n=args.sample_n,
                                     block_size_mb=args.block_size)
        stats.total_bytes = total
    if args.profile == "text":
        sys.stdout.write(as_text(prof) + "\n")
        return 0
    if stats is not None:
        prof = {**prof, **stats.as_dict()}
    json.dump(prof, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.profile:
            return run_profile(args)

        url = args.target
        check_target(url)

        total = None if args.no_preflight else check_range_support(url)

        if args.format == "parquet" and not args.list_columns:
            try:
                import pyarrow  # noqa: F401
            except ImportError as e:
                raise ObsReadError("--format parquet needs pyarrow; install it or pass "
                                   "--format csv / --format tsv.") from e

        if args.list_columns:
            cols, stats = list_columns(url, block_size_mb=args.block_size)
            stats.total_bytes = total
            json.dump({"h5ad_url": url, "n_obs_columns": len(cols), "obs_columns": cols,
                       **stats.as_dict()}, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0

        df, skipped, stats = read_obs(url, columns=args.columns,
                                      block_size_mb=args.block_size)
        stats.total_bytes = total

        out = args.out or f"obs.{args.format}"
        if args.format == "parquet":
            df.to_parquet(out)
        else:
            df.to_csv(out, sep="\t" if args.format == "tsv" else ",")

        json.dump({"h5ad_url": url, "out": out, "format": args.format,
                   "n_rows": int(df.shape[0]), "n_columns": int(df.shape[1]),
                   "columns": list(df.columns), "skipped_columns": skipped,
                   **stats.as_dict()}, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    except ObsReadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
