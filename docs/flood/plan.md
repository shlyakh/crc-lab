# Plan: Flood Loss & Trigger Lab

Draft, 2026-11-24. Companion to `docs/flood/requirements.md`, whose IDs (FG1, FH3, ...) are cited here.
Nothing is started. Stages run in order, one at a time; each ends with a visual test on the gallery, a
report in `docs/flood/reports/`, and a stop for Yuri's review.

## How to work

1. Read `AGENTS.md`, then the requirements, then this plan. All repository rules apply.
2. Before a stage: restate its goal and list anything in "Verify before use" (requirements §9) that falls
   in it. Check those first.
3. During a stage: write code under `src/flood_lab/`, tests under `tests/flood/`, a `just flood-<stage>`
   target, and the stage's check script under `src/flood_lab/checks/`.
4. End of a stage: run `just flood-checks`, `just test`, `just lint`. Write the report: what was built,
   numbers with their tags, the visual test figure, pass or fail against the rule, what was not done,
   questions for Yuri. Then stop.
5. If a source cannot be reached, a pass rule fails, or a number would have to be invented: stop and
   report. Do not work around it.
6. Hours are estimates for one person with AI coding tools. If a stage reaches 150% of its hours, stop
   and report with the overrun rule's cut applied or proposed.

## Visual tests

Each stage has a script `checks/f<n>_<slug>.py` that writes figures to `docs/flood/figures/f<n>/` and one
record `site/flood/tests/records/f<n>.json` (inputs with checksums, numbers, thresholds, pass or fail).
`site/flood/tests/index.html` is a static page that renders one card per record: title, figure, numbers,
badge. Map-type checks are also registered as layers in `site/layers.json` (origin `crc-lab`, group
`flood`) so they can be inspected in the existing viewer. Figures use plotly, as elsewhere in the repo,
with the depth colour scale of FP7. Thresholds marked *proposed* are starting values; if one looks wrong
once real numbers exist, say so in the report and propose a new one. Do not change a threshold silently.

## Tiers and budget

| Tier | Stages | Hours | Running total |
| --- | --- | --- | --- |
| 1. Core | F0–F8, F11 | 68 | 68 |
| 2. Emulator and cross-checks | F9, F10 | 23 | 91 |
| 3. Optional | F12, F13, F14 | 18 | 109 |

| Stage | Title | Hours | Depends on |
| --- | --- | --- | --- |
| F0 | De-risk, time the solver, choose the area, gallery skeleton | 4 | none |
| F1 | Terrain and assets | 6 | F0 |
| F2 | Three sources into CRC with reference readers | 5 | F0 |
| F3 | Solver model, drainage calibration, two storm replays | 8 | F1, F2 |
| F4 | Storm catalogue and batch runs | 8 | F3 |
| F5 | Validation against observations; who saw the flood | 7 | F3, F2 |
| F6 | Curves, event-loss table and risk in CRC | 9 | F4, F1 |
| F7 | Resilience measures, outage cost, benefit-cost | 6 | F6 |
| F8 | Triggers, fused labels, basis risk | 8 | F4, F5, F6 |
| F9 | Emulator and extended catalogue | 10 | F4, F6 |
| F10 | Engine agreement: FloodAdapt, CLIMADA, Oasis | 13 | F6, F7 |
| F11 | The page | 7 | F5–F8 (F9, F10 if built) |
| F12 | Fremont chapter | 5 | F8 |
| F13 | Own news extraction | 8 | F5 |
| F14 | Sewer-uncertainty ensemble | 5 | F3 |

**Cut order if behind:** F14, F13, Oasis within F10 (to a design note, saves about 6 hours), F12, the
rainfall index in F8, the emulator's uncertainty estimate in F9. Never cut a visual test; cut the stage's
scope and say so.

**Order note.** F11 comes after F8 in Tier 1 so a public page exists before Tier 2. When F9 or F10 finish
later, each adds its panel to the page as its last step.

## Package layout

```
src/flood_lab/
  domain.py            study area, grid, CRS                          FD1
  records.py           record writer (reuse lab_common atomic writer)  FG2
  reference/           independent readers; never import crc          FS1-FS4
    nyc_flood_maps.py  groundsource.py  floodnet.py
  sources/             loaders that call crc-sdk                       FS1-FS3
  hazard/
    base.py            HazardSource                                   FH1
    city_maps.py
    sfincs_model.py    build with HydroMT-SFINCS (own environment)    FH2
    calibrate.py       drainage allowance                             FH3
    replay.py          storm replays                                  FH4
    catalogue.py       RainyDay transposition, batch runs             FH5
    design_storms.py   Atlas 14 comparison                            FH6
    frequency.py       per-cell depth frequency -> CRC curves         FH7
  assets/
    substations.py  buildings.py  values.py  oed.py                   FD3-FD7
  curves/
    curves.yaml  load.py  export.py                                   FR1-FR3
  risk/
    event_loss.py  metrics.py  dependence.py  crc_adapter.py          FR4-FR8
  measures/
    measures.yaml  apply.py  bca.py  outage.py                        FM1-FM6
  trigger/
    index.py  payout.py  labels.py  fuse.py  score.py                 FT1-FT8
  emulator/            own environment (PyTorch)                      FE1-FE6
    dataset.py  model.py  train.py  evaluate.py  generate.py
  crosscheck/          never import crc; exchange files only          FX1-FX5
    floodadapt_run/  climada_run/  oasis_run/  compare.py
  fremont/             connected area on JRC maps; reanalysis index   FC1-FC3
  news/                optional                                       FN1-FN4
  checks/              one script per stage
site/flood/            index.html, flood.js, tests/
docs/flood/            requirements.md, plan.md, reports/, figures/, data-cards/
tests/flood/
```

## F0. De-risk, time the solver, choose the area (4 h)

**Goal.** Prove every risky assumption cheaply, pick the study area by a rule, and stand up the gallery.

**Steps.**

1. Create the package skeleton, the separation test (FG1), `records.py`, and an empty gallery page.
2. Download and checksum: flood maps, FloodNet events and sensors, Ida high-water marks, Groundsource,
   OpenStreetMap substations for Brooklyn and Queens. Write a data card for each (FG3).
3. Verify items 1, 2, 3 and 5 of requirements §9. Record what the sources actually say.
4. Score candidate areas of 10–20 km² (a sliding window inside the Jamaica Bay watershed, then all of
   Brooklyn and Queens): high-water marks, sensors with an event on 2023-09-29, sensors with an event on
   2021-09-01, substations, hectares in the deep class of the 2.13 in/hr current map, Groundsource rows
   on each date.
5. Install SFINCS (Docker; see FH2 for which release and which two to avoid) and HydroMT-SFINCS in
   their own environment. Build a 1 km² toy model, run one
   two-hour storm, and time it. Extrapolate to the full area at 5 m. Set the catalogue size for F4 from
   this: target 150 runs if a run takes under 10 minutes, about 100 otherwise.
6. Push one made-up tabulated damage curve through CRC's impact path for three points and read back a mean.
7. Build Oasis's PiWind example end to end. Time-box two hours; record the result (FX4).
8. Install the `flood-adapt` Python package in its own environment; read its LICENSE file and its
   dependency pins; try loading the toy model without the GUI.

**Visual test.** Candidate map with the top five areas outlined; a count table per area; a bar of solver
run time against cell count from the toy model.

**Pass.** An area has at least 8 high-water marks, 5 sensors with a 2023-09-29 event and 3 substations
(*proposed*); the toy model runs; the CRC impact call returns a mean. If no area passes, report the best
three with their trade-offs and stop.

**Stop.** Yuri confirms the area and decisions D1, D2, D9, D10, D12, and the tier.

## F1. Terrain and assets (6 h)

**Steps.**

1. Fetch 1 m terrain; build the 5 m grid with sub-grid tables; record datum and vintage (FD2).
2. Substations (FD3): points, yards, voltage; a contact sheet of each over aerial imagery; review it,
   record removals and the indoor flag.
3. Values (FD4): look for a public cost source by voltage class; otherwise enter the placeholder range
   with its tag.
4. Buildings (FD5): join footprints, elevation table and structure inventory; report match rates.
5. Customers served (FD7).
6. Write `assets_oed.csv` (FD6) and its data card.

**Visual test.** Hillshade with footprints and yards; histogram of first-floor height above ground, split
by subgrade flag; the substation contact sheet; a bar of asset counts by type and voltage.

**Pass.** Every asset has a ground elevation; at least 95% of footprints matched (*proposed*); every
substation has been looked at and the sheet is in the report.

**Overrun.** Limit buildings to blocks touched by any flood-map polygon.

## F2. Three sources into CRC (5 h)

**Steps.**

1. Reference readers for the flood maps, Groundsource and FloodNet (FS1–FS3), with offline tests on small
   constructed files and deliberate faults (FS4).
2. Loaders: flood-map classes through `from_raster`; Groundsource as an event source in the style of
   `crc_lab.storm_events`; FloodNet as a point-event table.
3. Inventory entries and transformation statements under `src/data_source_check/sources/crc_sdk/` only if
   the loader goes through crc-sdk; otherwise under `docs/flood/data-cards/`. Do not publish to the
   validation page without Yuri's word.
4. Add a Groundsource section to `docs/primers/event-sources-in-crc.md`.

**Visual test.** Per scenario, a difference map between loader and reference reader (must be empty); a map
of Groundsource rows for 2021-09-01/02 in the New York box coloured by polygon size; a histogram of the
latest dates in the file; a map of sensors coloured by whether they recorded each storm.

**Pass.** Zero differing cells and rows; a shifted polygon and a dropped row are both caught.

## F3. Solver model, calibration, replays (8 h)

**Steps.**

1. Scripted model build (FH2): terrain and sub-grid, roughness, buildings, boundaries open at the
   shoreline, rainfall forcing, allowance parameter.
2. Three intensity runs matching the flood-map scenarios' rainfall. Calibrate the allowance on the two
   current-sea-level maps (FH3); report the 3.66 in/hr run as a check.
3. Verify item 4 of §9: place the three intensities on the Atlas 14 curve for the area.
4. Freeze the allowance; record it with its fit.
5. Replays of both storms from radar rainfall (FH4).
6. Monotonicity and water-balance tests (FH8).
7. `hazard/base.py` with the three implementations registered (FH1).

**Visual test.** Calibration curve: flooded area per class against allowance, with the city-map area as a
line, for each scenario. Hit, miss and false-alarm map against each current-sea-level map. Water-balance
bar per run. Peak-depth maps for the two replays, with radar rainfall totals beside them.

**Pass.** Water balance within 1%; critical success index of 0.5 or better against the two calibration
maps (*proposed*). If one allowance cannot reach it, try per-district values once, then report the
mismatch as a finding and continue with the best fit.

## F4. Storm catalogue and batch runs (8 h)

**Steps.**

1. RainyDay over the gridded rainfall record (FH5): choose and justify the transposition domain (compare
   storm statistics inside it for homogeneity); generate synthetic years; keep the storms that matter.
2. Batch-run the solver over the kept storms, resumable, one record per run.
3. Six Atlas 14 uniform design storms (FH6).
4. Per-cell depth frequency from the catalogue with a dry-year point mass; load as CRC curves (FH7).
5. Compare frequency from the catalogue with frequency from the design storms.

**Visual test.** Storm-centre map over the transposition domain; rainfall frequency at the area from the
catalogue against Atlas 14 (they should agree before depth is compared); a strip of depth maps at 10, 100
and 500 years from the catalogue beside the design-storm maps; a count of buildings wet at 100 years under
each method.

**Pass.** Catalogue rainfall frequency at the centroid within the Atlas 14 confidence band for 2 to 100
years (*proposed*); every batch run has a record; depth non-decreasing with return period in 99% of cells.

**Overrun.** Fewer storms (not below 60), and say what tail that supports.

## F5. Validation against observations (7 h)

**Steps.**

1. Sample Ida replay depth at each high-water mark (FV1).
2. Sensor comparison for both storms (FV2).
3. Jamaica Bay map comparison after reading its licence (FV3).
4. Who saw the flood (FV5): load 311 and Storm Events for both dates; count and map all five sources.
5. No retuning (FV4).

**Visual test.** Modelled against surveyed depth with a one-to-one line, bias and error printed, the
published 0.20 m marked. One small panel per sensor: measured depth through the storm with the modelled
peak. Error map. The who-saw-the-flood bar chart and map for each storm.

**Pass.** None is forced; the stage reports. Above 0.5 m root-mean-square error (*proposed*) the report
states that substation-level claims are not supported and proposes what to do (classes only, or F14).

## F6. Curves, event-loss table and risk in CRC (9 h)

**Steps.**

1. Verify item 7 of §9. Enter the substation curve envelope (FR2) and the building curves in `curves.yaml` with
   sources and tags (FR1–FR3). Unit tests: monotone, bounded, zero below threshold.
2. Exporters to CRC first; the others in F10.
3. Event-loss table through CRC's impact functions (FR4).
4. Metrics from the table (FR5), the per-cell route through `compute_risk`, and the dependence brackets
   (FR6).
5. Hand recomputation of three assets in a notebook (FR7); bootstrap intervals (FR8).
6. Add entries to `docs/algorithms.md` for every new calculation.

**Visual test.** A card per substation: depth-frequency curve with catalogue points, the damage-curve
envelope with that asset's 10-, 100- and 500-year depths marked, loss by return period as a band. Portfolio
occurrence and aggregate exceedance curves with bootstrap bands. A bracket chart: 1-in-100 loss under full
dependence, from the event table, and under independence. A bar pair: expected annual loss from the event
table and from per-cell curves.

**Pass.** Hand recomputation matches; the event-table 1-in-100 loss lies between the two brackets; the two
expected-annual-loss routes are within 5% or the difference is explained (*proposed*).

## F7. Measures, outage cost, benefit-cost (6 h)

**Steps.**

1. Measures as curve modifications (FM1, FM2); costs (FM3).
2. Verify item 8 of §9; benefit-cost at 7% and 3.1%; distribution from synthetic years (FM4).
3. Outage cost (FM5), separate from physical damage.
4. Identity tests (FM6).

**Visual test.** Each damage curve before and after each measure. Exceedance curve before and after. A
tornado chart of what moves the ratio most (value, cost, curve choice, discount rate, project life). A
histogram of the ratio across synthetic years. One draft investment one-pager.

**Pass.** Zero-height measure equals baseline to machine precision; no asset's loss rises under any
measure; every placeholder on the one-pager is marked.

## F8. Triggers, fused labels, basis risk (8 h)

**Steps.**

1. Verify items 6 and 9 of §9.
2. Four indices per event and per candidate day (FT1); thresholds from the catalogue (FT2); payout (FT3).
3. Planted-flood tests: a rectangle of known area returns that area and that share; a value just under and
   just over a threshold flips the payout.
4. Labels (FT5): load claims and correct dates; build the day-by-source table over all candidate days
   (FT6).
5. Fuse with a latent-class model; report per-source sensitivity and specificity with intervals.
6. Score (FT7); the 2023-09-29 panel (FT4).

**Visual test.** For each storm, the four indices through time with thresholds on one aligned panel. A
2016–2025 strip of candidate days: each source as a row of ticks, the fused probability beneath, each
index's payouts beneath that. Precision-recall curve per index with bootstrap band. A two-by-two table per
index. Payout against modelled loss.

**Pass.** Planted tests pass; both storms appear as fused positives; sample sizes are printed on every
figure.

**Overrun.** Drop index (d), then replace the latent-class model with a two-of-N vote and say so.

## F9. Emulator and extended catalogue (10 h)

**Steps.**

1. Dataset from F4 runs: static channels, storm vector, peak depth; tiles; splits by storm and one spatial
   block (FE1, FE2).
2. Train; record hardware, time, seed (FE6).
3. Evaluate on both splits; uncertainty and calibration (FE3).
4. Generate synthetic years; extend the event-loss table; recompute F6 metrics with and without (FE4).
5. Add the emulator as a `HazardSource`.

**Visual test.** For six held-out storms: solver, emulator and difference side by side. Scatter of asset
depth, emulator against solver. Scores by split. Reliability diagram. Exceedance curve with and without
the emulator.

**Pass.** Critical success index at 0.1 m of 0.6 or better on held-out storms (*proposed*); F6 expected
annual loss with the emulator within the bootstrap interval of the solver-only value, or the difference is
explained. Whatever the spatial-block score is, it is reported, with FE5's statement.

**Overrun.** Drop the ensemble; keep one model with dropout.

## F10. Engine agreement (13 h)

**Steps.**

1. Exporters for FIAT, CLIMADA and Oasis from `curves.yaml` and `assets_oed.csv`.
2. FloodAdapt (4 h): load the F3 model and a FIAT model built from the same assets; one event, one measure
   (FX2).
3. CLIMADA (4 h): hazard from event depths with catalogue frequencies; impact; one measure through
   cost-benefit (FX3).
4. Oasis (5 h, or a one-hour design note per F0): model files; run; read tables (FX4).
5. `compare.py`: records with tolerances (FX5); a deliberate-fault test per engine.

**Visual test.** Per asset, one dot per engine for the Ida loss and for the 1-in-100 loss. A table of
expected annual loss by engine with tolerance flags. A list of differences found, each with its cause.

**Pass.** FX5 tolerances met or each miss explained; every deliberate fault is caught.

## F11. The page (7 h)

**Steps.**

1. `site/flood/` with FP1–FP5, generated from records; register layers; link from the landing page.
2. Finalise the gallery (FP6).
3. Extend `tools/smoke.mjs` (FP9); record a three-minute walk-through with `tools/record-demo.mjs`.
4. Update `README.md`, `AGENTS.md` (a "Flood lab" entry under Projects) and `docs/index.md`.

**Visual test.** Smoke-test screenshots at desktop and phone width, committed and compared on rebuild.

**Pass.** Smoke test green; every figure has a caption with its limit (FP8); a reader new to the project
can name the most exposed substation and say whether raising it pays, within two minutes (Yuri judges).

## F12. Fremont chapter (5 h)

**Steps.** FC1 with the F8 index code; verify item 11 of §9; FC2 if a reach exists; FC3.

**Visual test.** Largest connected flooded area against return period with the 0.58 square mile line, and
the map at the crossing. If the reach exists: winter 2017 flow from reanalysis, gauge and GloFAS, each
with its ten-year level; annual maxima against gauge peaks.

**Pass.** The planted-rectangle test; if FC2 is built, the February 2017 peak within one day of the gauge.

## F13. Own news extraction (8 h)

**Steps.** FN1–FN4 for the two New York storms; add the result as a sixth source in the F8 label table and
re-run the fusion to see what changes.

**Visual test.** Extracted reports over sensors and high-water marks for Ida; precision and recall table;
per-source sensitivity before and after adding it.

**Pass.** Precision measured by hand on 50 items and reported; no article text in the repository.

## F14. Sewer-uncertainty ensemble (5 h)

**Steps.** FU1.

**Visual test.** Depth difference maps across the three networks and against F3; a table of substations
whose wet or dry state changes.

**Pass.** None; the stage reports a spread.

## First half hour of F0

1. `duckdb` over `groundsource_2026.parquet`: row counts and `area_km2` quantiles for the New York box on
   2021-09-01, 2021-09-02 and 2023-09-29; `max(end_date)`.
2. Flood-map download: list layers, scenario names, class codes.
3. FloodNet events: count of sensors with an event on each date, by borough.
4. Docker pull of SFINCS and a hello-world run.

If any of the first three contradicts the requirements, stop and report before going further.
