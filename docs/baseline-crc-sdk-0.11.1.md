# Baseline: crc-lab on crc-sdk 0.11.1

Written 2026-11-23, before the pin moves to crc-sdk 0.11.2. It records what crc-lab holds, how it uses
Climate Risk Commons (CRC), what was found in CRC on the way, and what is still unreviewed. It describes
commit `c72d708` on `main` (tagged `baseline-crc-sdk-0.11.1` together with this document).

Numbers are quoted from the reports and records named beside them; nothing here was re-run. Where two
places in the repository disagree, both are given.

| | |
| --- | --- |
| crc-sdk | 0.11.1 (PyPI; reference clone `../upstream/crc-sdk` at `v0.11.1`, commit `9c56bb0`) |
| crc-framework | 0.6.0 (PyPI; reference clone `../upstream/crc-framework-rs` at `v0.6.0`) |
| CRC Open release | `ssp585-global-2026-10-20-v1`, pathway `ssp585`, CC BY-NC 4.0 |
| Python | 3.12 |
| Offline tests | 331 passed (`docs/validation/reports/V8.5-summaries-and-map-links.md`) |
| Site | https://shlyakh.github.io/crc-lab/ |

## 1. What crc-lab is

Three projects in one repository, kept apart by `tests/test_projects.py`, plus shared code.

| Project | Package | Page | What it does |
| --- | --- | --- | --- |
| Texas hail risk | `src/crc_lab/` | `site/hail/` | Hail and gust curves from NOAA Storm Events, solar plants with value and hail exposure, a reporting-bias model, radar hail, impact curves v0 and loss per plant |
| CRC data explorer | `src/crc_data_explorer/` | `site/validation/explore/` | Maps of what crc-sdk already reaches: CRC Open hazards, IBTrACS, CO-OPS, GHCNh, ERA5, JRC flood; regions Texas, Fremont, Rhine |
| Source validation | `src/data_source_check/` | `site/validation/` | Explores and verifies crc-sdk's data sources against the publisher's originals; holds the findings register |
| Shared | `src/lab_common/` | `site/shared/`, `site/data/`, `site/layers.json` | Version pins, Texas boundary and cells, the horizon-file writer, the map viewer |

`site/index.html` is a landing page that forwards addresses from before the split (V5). `site/layers.json`
(hand-edited, 93 layers) is the registry of sources and layers; a layer's `origin` decides whether it shows
on the hail page (`crc-lab`) or the explorer (`crc-sdk`).

## 2. How each project uses CRC

crc-sdk is used through its public workflows almost everywhere. crc-framework is called directly in one
place only.

### Hail risk and explorer (`crc_lab`, `crc_data_explorer`, `lab_common`)

No private crc-sdk name and no `crc_framework` import in these three packages.

| Upstream | Where | Used for |
| --- | --- | --- |
| `HazardDataset.crc_open()`, `.catalog()`, `.for_area()`, `.hazards().materialize()` | `crc_data_explorer/build.py`, `hazards.py` | CRC Open: 8 hazards (`tx_max`, `tn_min`, `rx1day`, `rflood`, `wind_max_daily_max`, `fwi`, `spei`, `hot_days`) at horizons 2030, 2050, 2080; catalogue of all 63 |
| `.for_assets().return_periods().write_parquet()` | `hazards.py`, `sources.py`, `crc_lab/curves/fit.py` | The check that shipped values equal crc-sdk's own at sampled cells; return levels at cities and plants |
| `IBTrACSPlan("NA").years(1950, 2025)` | `crc_data_explorer/tracks.py` | North Atlantic tracks with wind radii |
| `NOAAExtremeWaterLevelPlan.for_station()` | `sources.py` | CO-OPS annual-exceedance levels, 39 Texas stations (9 publish levels) |
| `HazardDataset.ghcnh("temperature_max")` with `BlockExtremaPolicy.curated(minimum_years=15)` | `sources.py` | Station curves 2000–2024, first 40 USW stations (8 have enough years) |
| `HazardDataset.era5("txx", store="wb2-1p5")` | `sources.py` | Hottest-day baseline 1991–2020 on H3 r4 (1,439 cells) |
| `HazardDataset.glofas` / `.efas` with `JRCFloodPolicy.curated()` | `sources.py` (`build_jrc`) | River flood depth for five areas; the cell takes the maximum of its pixel rows |
| `HazardDataset.from_table()` with `CDFColumnSchema`, `CDFCurveFitPolicy`, `TemporalWindow`, `SourceProvenance` | `crc_lab/curves/fit.py`, `build.py` | Fitting our hail-size and gust curves into CRC's canonical format |
| `curve_quantiles`, `curve_quantiles_at`, `curve_parameters_from_row`, `return_periods_to_probabilities` | `lab_common/horizons.py`, `sources.py` | Evaluating curves in Python at return periods 2–500; the page never re-implements a curve |
| `read_hazard_metadata`, `read_hazard_dataset` | `lab_common/horizons.py`, `hazards.py`, `sources.py` | Reading canonical Parquet |
| `CRCCatalog` | `crc_data_explorer/catalog.py` | `site/data/catalog.json` |
| `crc_sdk.geometry.vector.polyfill_wkb` | `lab_common/texas.py`, `crc_lab/storm_events/geometry.py` | Texas boundary and storm-event geometry to H3 cells |
| `crc_sdk.impacts.ImpactExpression.tabulated()` | `crc_lab/impacts/crc_adapter.py` | The four hail curves as six tabulated impact expressions |

Texas is 2,566 H3 r5 cells and 118,482 r7 cells (those intersecting the state polygon).

### Source validation (`data_source_check`)

`adapters/crc/` is the only code that calls crc-sdk, with one exception: `draft.py:64-78` imports it to
look up the file and line of an entry point for a drafting brief. `core/` and `reference/` never import
it; a test enforces this.

- `enumerate.py` reads the option tables of the providers and the list of plans in
  `crc_sdk.workflows.__all__`; this is how the inventory notices a new entry point or option.
- One adapter per source: `ibtracs.py`, `ghcnh.py`, `nex.py`, `era5.py`, `noaa_water_levels.py`,
  `jrc_flood.py`.
- crc-framework: `jrc_flood.py:278-284` calls
  `crc_framework.distributions.FittedDistribution.from_parameters("gumbel_r", ...)` to evaluate fitted
  curves. This is the only direct call in the repository.
- Installed versions come from `importlib.metadata`, not from `PINNED`.

## 3. What was built

### Hail risk and explorer, 2026-11-10 to 11-11

Reports are in `docs/reports/`.

| Phase | Report | Built | Headline |
| --- | --- | --- | --- |
| 0 | `0-setup.md` | Repository, pins, reference clones, nine checks | 63 hazards in the release |
| 1 | `1-explorer.md` | Data build and map page for 8 CRC Open hazards | 960 shipped values checked against `for_assets`, 0 mismatches |
| 2 | `2-storm-events.md`, `2-storm-events-comparison.md` | NOAA Storm Events snapshot, parser, geometry to H3, event table; comparison with the Source Cooperative copy | 166,214 Texas events 1950–2026; builds from NCEI direct, copy kept as cross-check |
| 3 | `3-curves.md`, `3-curves-sensitivity.md` | Annual maxima per cell, ring pooling, Gumbel fit through `HazardDataset.from_table` | 2,566 cells; hail: 2,531 hurdle, 21 tabulated, 14 point-mass |
| 4 | `4-assets.md`, `4-hail-exposure-sensitivity.md`, `4-radar-hail.md`, `4-real-estate-fort-bend.md` | Solar plants, replacement value, hail exposure by local report density, MRMS radar, Fort Bend buildings comparison | 250 plants, 34,779 MW AC, $45.2 billion |
| 5 | `5-reporting-bias.md`, `5-hail-impact.md` | Reporting-rate model; four v0 hail impact curves; loss per plant on three bases | $82.43 million a year from reports as they are (0.182% of value); $321.84 million after bias correction (0.712%) |
| 6 | `6-explorer-redesign.md` | One page, two projects; ranked plant table, Methods, tour | 74 of 250 plants hidden by default (under 20 MW) |
| E2–E5 | `E2`…`E5-*.md` | Source-centric explorer, wind radii and storm player, groups and About, four-source hail comparison | 91 storms; events layer 166,214 records |
| S1 | `S1-sources.md` | Probes of 13 crc-sdk sources; four explorer layers | NEX temperature failure first seen here |
| u1 | `u1-nex-bytes-fix.md` | The NEX fix in the fork | Sent as pull request #42 on 2026-11-12 |

### Source validation, 2026-11-11 to 11-17

Reports are in `docs/validation/reports/`. Method: `docs/validation/method.md` (version 0.2, not yet
reviewed). Verification means a transformation statement, one line per step with a code reference, plus an
independent recomputation by a reader that shares nothing with the framework. Outcomes come from the
comparison and its tolerance, never from a language model.

| Stage | Built | Headline |
| --- | --- | --- |
| V0 | Method, record format, inventory of 20 entries, first 9 findings | 19 sources, none assessed at that point |
| V1 IBTrACS | Reference reader, adapter, 12-step statement | 71 checks: 70 confirmed, 1 differs |
| V2 GHCNh | Station-year recomputation from NOAA's files, 14-step statement | 1,000 station-years, 22,000 values, 0 differ |
| V3 NEX-GDDP-CMIP6 | One model, Texas box, 11 cases, 15-step statement | 15,106 rainfall cell values at the installed version, 0 differ; 24 checks: 19 confirmed, 5 differ |
| V4 | Monitor, staged re-runs, weekly workflow | 1,026 publisher files asked in 7 seconds |
| V5 | Split into projects and pages | 175 tests at the time |
| V6 | Drafting skill and gate; trial drafts of NOAA water levels and ERA5 | Both drafts unreviewed, not on the page |
| V8.1 JRC flood | Reference TIFF reader, 44 checks, 15-step statement, findings CRC-013 to CRC-022 | 1,447,885,064 pixel values compared, 0 differ; 10,240,052 curves refitted |
| V8.2 | Explorer regions, fitted layers, review layers | — |
| V8.3 | Comparisons with FEMA zones, USGS gauges, Harvey marks; no outcomes | 829 Harvey marks, 694 with a height |
| V8.4 | Layer picking, origin tags, findings on the map; draft accepted onto the page | 88 explorer layers |
| V8.5 | Summary opening each assessment, table-to-map links | Published at Yuri's word, review not finished |

There is no V7 (validation tier for climate projections); it waits for criteria.

The four assessed sources, from `site/validation/data/records/`:

| Source | Run | Tier | Checks | Statement steps | Findings |
| --- | --- | --- | --- | --- | --- |
| `ibtracs` | 2026-11-12 | 1 | 71: 70 confirmed, 1 differs | 12: 10 confirmed, 1 differs, 1 not checked | CRC-010, CRC-011 |
| `ghcnh` | 2026-11-12 | 1 | 8: all confirmed | 14: all confirmed | none |
| `nex-gddp-cmip6` | 2026-11-12 | 2 | 24: 19 confirmed, 5 differ | 15: 12 confirmed, 2 differ, 1 not checked | CRC-001, CRC-012 |
| `jrc-flood` | 2026-11-17 | 2 | 44: 40 confirmed, 4 differ | 15: 11 confirmed, 4 differ | CRC-003, CRC-014 to CRC-022; cause of the differing curves is CRC-013-FWK |

All four are exploration and verification "assessed", validation "not assessed", and all four are
unsigned drafts.

### Planned, not built

- Phase 7, loss from radar hail, and Phase 8, Fort Bend buildings: `docs/plan-radar-loss-and-buildings.md`
  (draft, six unanswered questions).
- A Storm Events adapter for crc-sdk with three design questions for the maintainers:
  `docs/plan-upstream-storm-events.md`.
- V7, and replacing the four placeholders of the hail impact curves (stow angle, chance stowed, module
  cost share, footprint).

## 4. Findings in CRC, and contributions

Register: `src/data_source_check/sources/crc_sdk/findings.toml`. 22 findings, all found at crc-sdk 0.11.1.
By kind: defect, doc-code difference, observation. By basis: 15 reproduced, 7 from code reading.

| Id | Kind, basis | Title (the register's wording) | Status |
| --- | --- | --- | --- |
| CRC-001-NEX | defect, reproduced | Temperature recipes (txx, tnn) fail on real NEX files | reported upstream, [#42](https://github.com/RiskThinking/crc-sdk/pull/42) |
| CRC-002-FWK | doc-code, code reading | The 20-year minimum counts the years requested, not the years valid in each cell | open |
| CRC-003-JRC | doc-code, reproduced | JRC flood and EDO output files do not carry licence, attribution, retrieval time or checksum | open |
| CRC-004-EDO | doc-code, code reading | EDO drought curves are labelled with the last year of the record, not the centre year | open |
| CRC-005-EDO | observation, code reading | The EDO annual minimum has no completeness rule | open |
| CRC-006-ERA5 | observation, code reading | ERA5 values are converted without checking the unit the store declares | open |
| CRC-007-OPEN | observation, code reading | retrieved_at in a CRC Open file is the time the file was written, not the time the data were downloaded | open |
| CRC-008-OSC | doc-code, code reading | The OS-Climate licence is documented as read from layer metadata; no code that reads it was found | open |
| CRC-009-CDL | observation, code reading | The Cropland Data Layer is read from a moving branch and its output records no provenance | open |
| CRC-010-IBT | defect, reproduced | The subset "active" is accepted but NOAA has no file under that name | reported upstream, [#43](https://github.com/RiskThinking/crc-sdk/pull/43) |
| CRC-011-IBT | observation, reproduced | The snapshot's manifest has a terms address and a citation but no licence field; the batches carry no provenance | open |
| CRC-012-NEX | observation, reproduced | NASA serves files of version 2.0, which cannot be requested | open (mentioned in the text of #42) |
| CRC-013-FWK | defect, reproduced | The quantile fit gives up on depths that are flat and then rise, and crc-sdk then drops the pixel without a message | open |
| CRC-014-JRC | observation, reproduced | A pixel the publisher shows flooded gets no curve, and no message, when it has fewer than four depths, equal depths or a decreasing depth | open |
| CRC-015-JRC | observation, reproduced | The fitted curve can be positive where the publisher's map is dry, below zero where it is wet, and metres away from the published depth | open |
| CRC-016-JRC | observation, reproduced | A request outside a dataset's coverage ends with an error that does not name the coverage, and the error differs with the cache mode | open |
| CRC-017-JRC | observation, reproduced | The release is identified by one line of the publisher's README; the file addresses hold no version and no publisher checksum is taken | open |
| CRC-018-JRC | doc-code, reproduced | crc-sdk states CC BY 4.0 for the JRC flood maps; the publisher's README names the Open Database License | open |
| CRC-019-JRC | observation, reproduced | The publisher's masks of spurious depths and permanent water are not read | open |
| CRC-020-JRC | observation, reproduced | With a cache, a pixel's source_id depends on the box asked for | open |
| CRC-021-JRC | defect, reproduced | A cache made under a relative path cannot be read offline from another working folder | open |
| CRC-022-JRC | observation, reproduced | A state-sized box is fitted pixel by pixel in one process: 27 minutes and 5.8 GB of memory for the Texas box | open |

Contributions so far: pull requests #42 (NEX units) and #43 (IBTrACS `active`), sent 2026-11-12 from
`github.com/shlyakh/crc-sdk`, merged 2026-11-13 and released in crc-sdk 0.11.2 the same day. They are the
whole content of that release. The register still says "reported upstream" for both at this baseline; the
move to 0.11.2 is where they become `fixed`.

Twenty findings have not been sent. Draft texts wait in `local/upstream-review.md` (15 entries).

Limits of CRC met in the hail work and not entered as findings (`docs/reports/1-explorer.md`,
`3-curves.md`, `5-hail-impact.md`):

- A tabulated curve cannot be evaluated outside its knots (`ValueError`); `for_assets` raises on such cells.
- All 63 CRC Open hazards declare `tail: upper`, including `tn_min` and `spei`.
- The fits give no confidence intervals.
- No hail hazard factor exists; the impact context carries no glass class, stow or roof class;
  `SigmoidImpact` is a logistic, not the Emanuel cubic. Our curves are therefore tabulated expressions and
  loss is not computed through CRC's return-level path.

## 5. Where our code leans on upstream behaviour

These are the places a new release can break or make redundant.

- **NEX detour.** At 0.11.1 the temperature recipes fail, so `assessments/nex.py` re-runs the failing cases
  in a subprocess with `PYTHONPATH` pointing at `../forks/crc-sdk` (`FIXED_CLONE`, `build.py:34`). Four
  checks named `annual-fixed-clone[...]` carry the version label "0.11.1 with the fix of CRC-001-NEX (local
  clone)" and count towards no step. The detour runs only for cases that fail on the installed version.
- **Private crc-sdk names read by the validation adapters:** `workflows.ibtracs._SUBSETS`,
  `workflows.noaa_sea_level._SCENARIOS`, `workflows._remote.file_checksum`,
  `connectors.adapters._source_id`, and a plan's `_directory`.
- **Names stubbed by offline tests:** `workflows.nex._open_backend`, `workflows.ibtracs.urlopen`,
  `workflows.noaa_water_levels.urlopen`, `providers.ghcnh.urlopen`, `providers.ghcnh.fsspec`; the adapters
  also swap entries of `ERA5_STORES` and `JRC_DATASETS` at run time.
- **Tabulated curves:** `lab_common/horizons.py:59-91` evaluates them knot by knot and writes null outside
  the support; verification samples skip tabulated cells.
- **JRC reduction:** `build_jrc` takes the maximum over a cell's pixel rows and leaves return periods below
  10 empty.
- **rasterio** is held below 1.5.2 on macOS (`pyproject.toml`).
- **Hand-written text that names the version:** `site/sources.json`, `README.md`, `AGENTS.md`,
  `../README.md`.

## 6. Running it

Every recipe is in the `justfile`; `just` alone lists them.

| Recipe | Does | Cost where a report states it |
| --- | --- | --- |
| `just test`, `just lint` | Offline tests with the pin guard; ruff | — |
| `just data`, `just verify` | CRC Open explorer files; plus the `for_assets` check | about 46 s, 14.5 MB |
| `just storm-events` | Storm Events snapshot, event table, explorer layer | 231 files, 360 MB, 614 s on the first run |
| `just curves`, `just assets`, `just reporting-bias`, `just radar`, `just impacts`, `just decisions` | The hail pipeline, in this order | not stated |
| `just sources` | IBTrACS, CO-OPS, GHCNh, ERA5, JRC layers through crc-sdk | 434 s on 2026-11-17; ERA5 about 11 minutes uncached |
| `just validation` | Inventory, findings and page data, offline | — |
| `just validation-assess <id>` | One live assessment against the publisher | caches: IBTrACS 1.6 GB, GHCNh 0.8 GB, NEX 2.6 GB, JRC 4.2 GB |
| `just validation-monitor`, `-rerun`, `validation-accept <id>` | Has anything changed; stage a re-run; publish it | a re-run downloads afresh; JRC repeats the Texas fit, 1,604 s and 5.8 GB of memory |
| `just site` | Checks the three pages are complete | — |

`just all` runs `data storm-events curves assets sources site`; it does not run `radar`,
`reporting-bias`, `impacts` or `decisions`, although its comment says it rebuilds every data file.

Run a crc-sdk plan from a module or a file, never from `python -`: its worker pool fails to start.

## 7. Unreviewed and undecided

- Every assessment is an unsigned draft, and `method.md` itself is unreviewed.
- Every phase and stage report is marked "awaiting review" except V5, V6 (no such line) and V8.5.
- `local/review-queue.md`: 33 questions with an empty decision line.
- `local/upstream-review.md`: 15 draft texts for upstream, none decided beyond the two that were sent.
- `local/next-steps.md`: 17 to-do rows, 9 of them Yuri's to decide.
- `docs/open-questions.md`: one question open (the 20 MW capacity threshold), plus the six in the radar
  and buildings plan.

## 8. Known inconsistencies at this baseline

Listed so they are not mistaken for changes made by a later release.

- IBTrACS values compared: 323,350,290 in the V1 report, 323,369,778 in the record and in V8.5. The record
  is the later run (accepted re-run against NOAA's files of 2026-11-12).
- `docs/validation/monitoring.md` is from 2026-11-12 and has no `jrc-flood` row. The JRC record holds no
  publisher file addresses, so the monitor can flag it only through a version change.
- `site/validation/data/records/nex-gddp-cmip6.json` contains absolute paths of this machine
  (`crc_sdk_path`), flagged in V8.5.
- `CHANGELOG-upstream.md` lists #42 and #43 as open.
- `docs/handover-plan.md` and `docs/data-sources.md` use paths from before the split
  (`crc_lab/explorer/...`); `docs/implementation-plan.md` shows Phase 5 as proposed.
- `local/next-steps.md` and `local/review-queue.md` say work is uncommitted; it is committed and pushed.
- The comment on `just sources` omits ERA5 and JRC.
