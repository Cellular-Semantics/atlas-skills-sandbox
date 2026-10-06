#!/usr/bin/env bash
# Set up the package for local development and run every offline check CI runs.
#
#   ./dev.sh              offline suites (a localhost range server; no network)
#   ./dev.sh -m live      also read a real remote h5ad
#   ./dev.sh -q -k obs    any other pytest arguments pass straight through
set -euo pipefail
cd "$(dirname "$0")"

uv venv -q --allow-existing packages/h5ad-obs/.venv
uv pip install -q --python packages/h5ad-obs/.venv/bin/python -e "packages/h5ad-obs[test]"

packages/h5ad-obs/.venv/bin/python -m pytest packages/h5ad-obs "$@"
# The release tooling, against throwaway git repos.
packages/h5ad-obs/.venv/bin/python -m pytest tests "$@"
python3 scripts/versions.py report --check docs/pins.md
if command -v claude >/dev/null; then
  claude plugin validate . && for p in plugins/*/; do claude plugin validate "$p"; done
fi
