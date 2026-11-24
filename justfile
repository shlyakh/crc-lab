# crc-lab task runner. `just` lists targets. G5: `just all` rebuilds every data file and the site.

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the pinned environment
setup:
    uv sync --all-extras --group dev

# Offline tests, including the version-pin guard
test:
    uv run pytest -q

# Lint and format check
lint:
    uv run ruff check src tests
    uv run ruff format --check src tests

# Fix lint and formatting in place
fix:
    uv run ruff check --fix src tests
    uv run ruff format src tests

# Releases of crc-sdk and crc-framework newer than the pins, with notes (network; changes nothing)
upstream-check *flags:
    uv run python tools/upstream.py check {{flags}}

# Move one pin to the next release: clone tag, hand-written versions, changelog row, uv lock and sync (--dry-run first)
upstream-bump package version *flags:
    uv run python tools/upstream.py bump {{package}} {{version}} {{flags}}

# Upstream names our code uses that the installed crc-sdk or crc-framework no longer has (offline; exit 1 if any)
upstream-surface:
    uv run python tools/crc_surface.py check

# After a pin move, in minutes: names we use that are gone, offline tests, quick staged re-runs (network)
release-check:
    uv run python tools/crc_surface.py check
    -uv run pytest -q
    uv run python -m data_source_check.monitor --rerun --profile quick

# Our findings probed against crc-sdk 1.0 in a throwaway environment (never the project's; network unless --offline):
# just v1-probes 1.0.0a1 1.0.0a2 [--only <id>] [--list] [--offline]; report in docs/reports/v1-probes-<sdk>.md
v1-probes sdk_version framework_version *flags:
    uv run --no-project --python 3.12 --prerelease allow \
        --with "crc-sdk[zarr,raster,netcdf]=={{sdk_version}}" \
        --with "crc-framework=={{framework_version}}" \
        --with "rasterio<1.5.2; sys_platform == 'darwin'" \
        python -B tools/probes/v1/run.py {{flags}}

# Rebuild every explorer data file from CRC Open and the Census boundary (needs the network)
data:
    uv run python -m crc_data_explorer.build

# Same, then check shipped values against crc-sdk's for_assets at sampled cells
verify:
    uv run python -m crc_data_explorer.build --verify

# NOAA Storm Events: snapshot (about 400 MB, cached), Texas event table, explorer layer
storm-events:
    uv run python -m crc_lab.storm_events.build

# Same, plus the two-source comparison report (needs the Source Cooperative copy in the cache)
storm-events-compare:
    uv run python -m crc_lab.storm_events.build --compare
# Sources track: IBTrACS tracks, CO-OPS water-level stations, GHCNh station curves (network, ~10 min)
sources:
    uv run python -m crc_data_explorer.sources --verify

# Hail-size and thunderstorm-gust curves from the Storm Events table, into CRC and the explorer
curves:
    uv run python -m crc_lab.curves.build

# Same, plus the sensitivity note (pooling ring, start year, family) at ten cities
curves-sensitivity:
    uv run python -m crc_lab.curves.build --sensitivity

# Solar plants (USPVDB), replacement value (NREL ATB), hail exposure by local report density
assets:
    uv run python -m crc_lab.assets.build

# Same, plus the exposure sensitivity note
assets-sensitivity:
    uv run python -m crc_lab.assets.build --sensitivity

# First reporting-bias correction for hail reports: population and roads (report 5)
reporting-bias:
    uv run python -m crc_lab.assets.reporting_bias

# Radar hail: MRMS daily maxima (needs the 'radar' extra), hail signatures 1995 on, plant table, source comparison
radar:
    uv run --extra radar python -m crc_lab.radar.mrms
    uv run python -m crc_lab.radar.swdi
    uv run python -m crc_lab.radar.build
    uv run python -m crc_lab.radar.compare_cells

# Phase 5: hail loss per solar plant from the v0 impact curves (after assets, reporting-bias and radar)
impacts:
    uv run python -m crc_lab.impacts.build
    uv run python -m crc_lab.risk_layer

# The decisions document with its charts (after all builds)
decisions:
    uv run python -m crc_lab.decisions

# Source validation project: inventory, findings and page data from the installed crc-sdk (no network)
validation:
    uv run python -m data_source_check.build

# Source validation: assess one source against its publisher (network; then rebuilds the page data)
validation-assess source:
    uv run python -m data_source_check.build {{source}} --live

# Source validation: has a publisher file or the framework changed since each assessment? (network)
validation-monitor:
    uv run python -m data_source_check.monitor

# Source validation: also re-run what is stale into a staging folder (does not publish)
validation-monitor-rerun *flags:
    uv run python -m data_source_check.monitor --rerun {{flags}}

# Source validation: publish a staged re-run after reading docs/validation/monitoring.md
validation-accept source:
    uv run python -m data_source_check.monitor --accept {{source}}

# Source validation: what the inventory knows about an unassessed source, for whoever drafts its assessment
validation-brief source:
    uv run python -m data_source_check.draft brief {{source}}

# Source validation: run a drafted assessment into the draft folder (never the page); add --live by hand to download
validation-draft source:
    uv run python -m data_source_check.build {{source}} --draft

# Source validation: is a draft complete? (deterministic gate)
validation-draft-check source:
    uv run python -m data_source_check.draft check {{source}}

# Source validation: read a draft as the page would show it, from a throwaway copy of the site (http://127.0.0.1:8772/validation/)
validation-draft-preview source:
    uv run python -m data_source_check.draft preview {{source}}
    python3 -m http.server 8772 --bind 127.0.0.1 --directory data/cache/validation/drafts/preview/site

# Source validation: the per-cell review maps of the JRC flood findings, for the map explorer (from the caches)
validation-maps:
    uv run python -m data_source_check.assessments.jrc_flood_areas --maps

# Source validation: a person publishes a complete draft's records
validation-draft-accept source:
    uv run python -m data_source_check.draft accept {{source}}

# Check that the static site is complete, project by project
site: site-hail site-explorer site-validation

# Texas hail risk: page files and the layers of origin crc-lab
site-hail:
    uv run python -m crc_lab.check_site

# Texas CRC data explorer (under the validation project): page files and the layers of origin crc-sdk
site-explorer:
    uv run python -m crc_data_explorer.check_site

# Source validation: the assessments page and its records
site-validation:
    uv run python -m data_source_check.check_site

# Everything: all data, then site
all: data storm-events curves assets sources site

# Serve the site locally (http://127.0.0.1:8000)
serve:
    mkdir -p site/explainers && cp docs/explainers/*.html docs/explainers/README.md site/explainers/
    python3 -m http.server 8000 --bind 127.0.0.1 --directory site

# Serve the site from one container (http://127.0.0.1:8080)
up:
    docker compose up --build
