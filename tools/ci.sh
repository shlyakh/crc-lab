#!/usr/bin/env bash
# The checks the pages workflow runs, in one place. The workflow calls this script and so do
# `just ci` and the pre-push hook for main (.githooks/pre-push), so local and CI checks cannot drift.
# Offline. Generated files are compared, never rewritten here: run `just regen` first.
set -euo pipefail
cd "$(dirname "$0")/.."
step() { printf '\n== %s\n' "$*"; "$@"; }
step uv sync -q --group dev --extra flood --extra radar
step uv run pytest -q
step uv run ruff check src tests
step uv run ruff format --check src tests
# Source validation: rebuild the inventory offline so it matches the pinned crc-sdk (date-stamped,
# so it is rebuilt here, not compared)
# date-stamped, so it is put back afterwards: a check must not leave the tree changed
step uv run python -m data_source_check.build
git checkout -q -- docs/validation/inventory.md site/validation/data/inventory.json
step uv run python -m crc_lab.check_site
step uv run python -m crc_data_explorer.check_site
step uv run python -m data_source_check.check_site
step uv run python -m flood_lab.check_site
echo "ci: all checks passed"
