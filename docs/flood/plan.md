# Plan: Flood Loss & Trigger Lab

Version 3, 2026-11-25, tag `flood-requirements-v6` (version 2 is tag `flood-requirements-v2`); first draft 2026-11-24. Companion to
`docs/flood/requirements.md`, whose IDs (FG1, FH3, ...) are cited here. Revised for crc-sdk 1.0.0 and
crc-framework 1.0.0 (`docs/flood/crc-1.0-mapping.md`). F0, F1 and F2 are built and merged. Stages run one
at a time; each ends with a visual test on the gallery and a report in `docs/flood/reports/`. Until
2026-12-04 the order, the scope and the stop after each stage are as the section "Until 4 December" says;
the stage texts below are the full form each returns to.

## How to work

### A stage

1. One stage, one session, one branch. The stage is built on `flood/f<n>`, made from `main`, pushed for
   backup, and merged into `main` only on Yuri's go at the stop (D14). The count of parked tests
   (`tests/conftest.py`: 8 files and 3 tests) must not grow.
2. Before a stage: read `AGENTS.md`, the requirements, this plan and the last report. Restate the stage's
   goal and list anything in "Verify before use" (requirements §9) and any source fact (FS6) that falls
   in it. Check those first.
3. During a stage: code under `src/flood_lab/`, tests under `tests/flood/`, a `just flood-<stage>` target,
   and the stage's check script under `src/flood_lab/checks/`.
4. End of a stage: run `just flood-checks`, `just test`, `just lint`. Assess the open rows of
   `docs/flood/changes.md` (D16). Write the report: what was built, numbers with their tags, the visual test
   figure, pass or fail against the rule, what was not done, the outcome of each source check, the
   assessment of each open change, questions for Yuri, and which model did which task with its tokens.
   Then stop.
5. If a source cannot be reached, a pass rule fails, a fact differs from the requirements, or a number
   would have to be invented: stop and report. Do not work around it.
6. Hours are estimates for one person with AI coding tools; they are not a forecast of agent run time,
   which each report states as measured. If a stage reaches 150% of its hours, stop and report with the
   overrun rule's cut applied or proposed.

### Who does what

The main model of the session coordinates (Claude Fable 5.2 as of this version). Agents are given a model
by what the task needs, not the main model's by default.

1. **The main model fixes the contracts first**: record fields, table columns, function signatures, the
   files each agent may touch. Then it writes each brief.
2. **The main model keeps what is costly to get wrong**: every call into CRC 1.0.0, calibration,
   frequency and risk arithmetic, label fusion, pass-or-fail verdicts, the verdict on every source fact,
   findings, the stage report, and any debugging that outlives one retry by an agent.
3. **Opus builds** well-specified modules against those contracts, with tests. **Sonnet** does lookups in
   primary sources, downloads with checksums, data cards and mechanical edits. **Haiku** only lists or
   counts.
4. **Independent means a different agent.** A second reader (FS4) and the hand recomputation (FR7) are
   written by an agent that is not shown the code they check. The main model compares the results.
5. **Shared files have one writer**, the main model: `justfile`, `pyproject.toml`, `site/layers.json`,
   `curves.yaml`, `records.py`, `findings.toml`, `AGENTS.md`, `docs/algorithms.md`, the public interface
   of `crc_event_loss`, the requirements and this plan. Agents return what they need added.
6. **Parallel only where files are disjoint**, each agent in its own worktree made from the stage branch.
   Otherwise one at a time.
7. **Long runs are commands, not agents**: solver batches, training and large downloads run in the
   background under `caffeinate -i`, resumable, one record per run (FG10).
8. **Every brief carries**: the requirement IDs, the contract, the files the agent may touch, "never
   invent a number; if a source cannot be reached, stop and say so", and the checks to run before
   returning. A lookup returns the passage it read and its address, not only the value.
9. **Before each stop** the main model reads every figure and has one fresh Opus agent review the stage's
   diff for defects, without being told what to expect.
10. **Tokens are reported** per agent as the tool gives them. The main session's own tokens are not
    visible to it and are reported as not available.

### Models by stage, Tier 1

| Stage | Main model | Opus | Sonnet |
| --- | --- | --- | --- |
| F0 | The CRC 1.0.0 block; record format; `lab_common/io.py`; area scoring rule and the choice put to Yuri; the verdict on every source fact; budgets | Solver and HydroMT environment with the timed toy model; package skeleton and gallery; FloodAdapt and Oasis trials, time-boxed | Source probes and fact checks in parallel, a few sources per agent, each with its data card and the passages read |
| F1 | Grid and datum decisions; review of the substation contact sheet before Yuri sees it | Terrain and sub-grid; then the buildings join and the asset table | Search for a public substation cost source |
| F2 | The CRC loaders; comparison verdicts; the primer | Second readers, by an agent that does not see the loaders; fault tests | Dataset fields and licence terms |
| F3 | Model design, loss-rate calibration, the freeze | Scripted build, water-balance and monotonicity tests, figures | Atlas 14 values for §9 item 4 |
| F4 | Transposition domain and its justification; depth frequency and the load into CRC | RainyDay environment, batch runner, design storms | Rainfall record download and card |
| F5 | Reading of the errors; the statement FV4 may require; each loader against its second reader | Comparisons and figures; second readers for the marks and the radar rainfall, by an agent that does not see the loaders | 311 and Storm Events loads |
| F6 | The extension's interface and design note, after reading upstream's two pull requests; curve values against primary sources; CRC damage, expectation and loss statistics; `docs/algorithms.md` | The extension's modules and tests against the fixed interface; bootstrap resampling, cards; a second agent for the blind hand recomputation | Fetch of the curve spreadsheet and the Hazus tables |
| F7 | Identity tests; the investment one-pager | Measures, benefit-cost, outage cost | FEMA useful life and toolkit version |
| F8 | Label fusion and scoring; what may be said of the pilot | Indices, payout, planted tests; claims with the date rule | Primary sources for §9 item 6 |
| F11 | Captions and limits; final check with Yuri | The page | Smoke script, document lists |

Work that may run in parallel in Tier 1: the F0 probes and fact checks; F1 beside F2 (both need only F0),
if Yuri wants to review them together; inside F2 and F5, the second readers beside the loaders. Tiers 2
and 3 get their table at the F8 stop. F10 is the natural fan-out: one Opus agent per engine, each in its
own environment.

## Until 4 December

Two demos set the order and the scope until 2026-12-04: `docs/flood/demo-plan.md` (what is shown, to
whom, the exhibits, the fallback decided on Sunday 29 November) and requirements section 15 (changes
CH-8 to CH-13). Where this section and a stage's text below disagree, this section holds.

| Order | Stage | For Tuesday 1 December | Change |
| --- | --- | --- | --- |
| 1 | F3 Solver, calibration on the Limited and Moderate maps, two replays | Yes | The first real run re-measures the time per storm; the Ida replay shows whether any substation is wet (the lead-asset rule) |
| 2 | F4 Storm catalogue | Running; at least 60 storms | Its build (RainyDay environment, rainfall record, transposition domain) starts beside F3. All 150 run unattended from the calibration freeze; whole peak-depth grids and storm descriptors are kept |
| 3 | F5, first part | Surveyed marks and sensors | "Who saw the flood" (FV5) after 1 December |
| 4 | F6 Curves, event-loss extension, risk | Yes | Figures print the number of storms they rest on |
| 5 | F7 Measures, outage cost, benefit-cost | Yes | Break-even view (FM7), 2 h. Outage in customer-hours while no customer count exists |
| 6 | Component prototype (FA1 to FA5) | If F7 has passed by Sunday evening | New, 5 h, time-boxed; the note is written in any case |
| 7 | F11, first part | Yes | Lead-asset card, loss curves, break-even chart, flow diagram, gallery, the single-asset re-run (FP10), a recorded walk-through |
| 8 | F9 Emulator | For Friday 4 December | Brought forward from Tier 2 |
| 9 | F8 Triggers, fused labels | For 4 December, as far as it goes | Deferred from Tier 1's order; the 2023-09-29 panel first |
| 10 | F11, second part; rest of F5; F10 | After 4 December | |

**Way of working until then.** Each stage still has its own session, branch, visual test and report.
Yuri reviews once a day. When every check of a stage passes, the next may start without waiting for his go,
on a branch made from the finished stage's branch; merges into `main` stay on his go (D14), at the daily
review. A failing check, a fact that differs from the requirements,
or a number that would have to be invented stops everything until he decides ("A stage", step 5). Nothing
goes to RiskThinking without his review; the second round of issues is raised with him on or after Monday
30 November.

**Waiting on a person.** Four passages that their publishers' sites refuse to automated reading (FEMA's
project useful life, the BCA Toolkit version, the Hazus functional depth, the Williams values at 3 m) are
listed with instructions in the demo plan, §11. Until read they stay labelled placeholders.

## Visual tests

Each stage has a script `checks/f<n>_<slug>.py` that writes figures to `docs/flood/figures/f<n>/` and one
record `site/flood/tests/records/f<n>.json` (inputs with checksums, numbers, thresholds, pass or fail).
`site/flood/tests/index.html` is a static page that renders one card per record: title, figure, numbers,
badge. It also has one card per source with the outcome of each fact (FS6) and, where there is one, of
the second reader (FS4), the two levels named apart (FS7). Map-type checks are also registered as layers
in `site/layers.json` (origin `crc-lab`, under a flood heading) so they can be inspected in the existing
viewer. Figures use plotly, as elsewhere in the repo,
with the depth colour scale of FP7. Thresholds marked *proposed* are starting values; if one looks wrong
once real numbers exist, say so in the report and propose a new one. Do not change a threshold silently.

## Tiers and budget

| Tier | Stages | Hours | Running total |
| --- | --- | --- | --- |
| 1. Core | F0–F8, F11 | 79 | 79 |
| 2. Emulator and cross-checks | F9, F10 | 23 | 102 |
| 3. Optional | F12, F13, F14 | 18 | 120 |

Tier 1 was 68 hours in the first draft. The revision of 2026-11-25 adds 8: four for crc-sdk 1.0.0 (the
F0 block of calls, the primer in F2, the two curve routes in F6) and four for source validation (fact
checks in F0, two more second readers in F5). CH-2 adds 3 in F6: the event-loss table and the aggregation are
built as an extension of CRC with a design note (D17), not as lab code.

| Stage | Title | Hours | Depends on |
| --- | --- | --- | --- |
| F0 | De-risk, CRC 1.0.0 calls, source facts, time the solver, choose the area, gallery skeleton | 8 | none |
| F1 | Terrain and assets | 6 | F0 |
| F2 | Sources: what goes into CRC and what does not, with second readers | 6 | F0 |
| F3 | Solver model, loss-rate calibration, two storm replays | 8 | F1, F2 |
| F4 | Storm catalogue and batch runs | 8 | F3 |
| F5 | Validation against observations; who saw the flood | 9 | F3, F2 |
| F6 | Curves, the event-loss extension of CRC, and risk | 13 | F4, F1 |
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
  records.py           own record format; writer from lab_common/io.py FG2
  depth_scale.py       the one set of depth class breaks              FP7
  check_site.py        what the pages workflow runs                   FG8
  reference/           independent readers; never import crc          FS4
    nyc_flood_maps.py  groundsource.py  floodnet.py
    high_water_marks.py  radar_rainfall.py  storm_events.py
  facts/               one file per source: facts and outcomes        FS6
  sources/             loaders; CRC Layer and Observations            FS1-FS3
  hazard/
    base.py            HazardSource                                   FH1
    city_maps.py
    sfincs_model.py    build with HydroMT-SFINCS (own environment)    FH2
    calibrate.py       constant loss rate                             FH3
    replay.py          storm replays                                  FH4
    catalogue.py       RainyDay transposition, batch runs             FH5
    design_storms.py   Atlas 14 comparison                            FH6
    frequency.py       depth frequency -> from_raster, from_quantiles FH7
  assets/
    substations.py  buildings.py  values.py  oed.py                   FD3-FD7
  curves/
    curves.yaml  load.py  export.py                                   FR1-FR3
  risk/
    event_loss.py      depths and curves -> the extension's table     FR4
    metrics.py         the extension's sums -> CRC Distribution       FR5, FR8
    crc_adapter.py     Impact.tabulated, evaluate, expectation,
                       pushforward; Distribution.empirical            FR1-FR5
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
docs/flood/            requirements.md, plan.md, crc-1.0-mapping.md, changes.md,
                       reports/, figures/, data-cards/
docs/primers/          point-observations.md                          FS5
src/lab_common/io.py   atomic writers (new, shared)                   FG2
src/crc_event_loss/    extension of CRC; imports crc_framework only   FR9-FR11
  events.py            event set                                      FR10
  table.py             event-loss table                               FR10
  aggregate.py         sums, annual Distributions, attribution,
                       brackets                                       FR10
tests/event_loss/
tests/flood/
```

## F0. De-risk, CRC 1.0.0 calls, source facts, choose the area (8 h)

**Goal.** Prove every risky assumption cheaply, pick the study area by a rule, and stand up the gallery.

**Steps.**

1. The CRC 1.0.0 block, first, by the main model (§9 item 12; F2, F4 and F6 rest on it). On toy data,
   each call of `docs/flood/crc-1.0-mapping.md` once, its last column filled:
   - `Dataset.from_raster` on a small EPSG:32618 raster set with dry cells and a nodata value that is not
     0; then with one decreasing cell, to see the failure of CRC-025-OWN and confirm the clean-up rule;
   - `Dataset.from_quantiles` at three points with a dry-year knot; the difference between the two routes;
   - `Impact.tabulated`, `evaluate` at three depths, `expectation` after `complete(TailCompletion(...))`,
     and a depth beyond the table;
   - `evaluate(Assets).return_periods([10, 100, 500]).impact(...)`, with one asset outside the grid and
     one query outside the knots, to see the failure rows;
   - `compute_risk` on three assets, against a hand sum, for FR6;
   - `Distribution.empirical` on made-up annual losses: `exceedance`, `quantile`, `statistics` with CVaR,
     `to_json` and back; `Impact.pushforward` on one curve (both were run once on 2026-11-25 and agreed
     with a numpy recomputation; F0 keeps them as tests);
   - `Observations.from_table` and `Layer.from_table` on ten rows each, read back;
   - the time and memory of a 600,000-cell `from_raster` read.
   Anything that differs from the mapping is corrected there and in the requirement, and is a candidate
   finding (FG9).
2. Create `src/lab_common/io.py` (FG2), the package skeleton, the separation tests (FG1), `records.py`,
   and an empty gallery page.
3. Download and checksum: flood maps, FloodNet events and sensors, Ida high-water marks, Groundsource,
   OpenStreetMap substations for Brooklyn and Queens. Write a data card for each (FG3).
4. Source facts (D15, FS6) for every source of Tier 1 in the requirements' §7 table, from the primary source,
   one outcome per fact, by Sonnet agents in parallel with the main model giving each verdict. This
   covers items 1, 2, 3 and 5 of §9 and the F0 rows of §9's "not checked" table. Record what the sources
   actually say.
5. Set the disk and memory budget (FG7) from the sizes found in steps 3 and 4.
6. Score candidate areas of 10–20 km² (a sliding window inside the Jamaica Bay watershed, then all of
   Brooklyn and Queens): high-water marks, sensors with an event on 2023-09-29, sensors with an event on
   2021-09-01, substations, hectares in the deep class of the 2.13 in/hr current map, Groundsource rows
   on each date.
7. Install SFINCS (Docker; see FH2 for which release and which two to avoid) and HydroMT-SFINCS in
   their own environment. Build a 1 km² toy model, run one
   two-hour storm, and time it. Extrapolate to the full area at 5 m. Set the catalogue size for F4 from
   this: target 150 runs if a run takes under 10 minutes, about 100 otherwise. Record whether the image
   runs natively on Apple Silicon or under emulation.
8. Build Oasis's PiWind example end to end. Time-box two hours; record the result (FX4).
9. Install the `flood-adapt` Python package in its own environment; read its LICENSE file and its
   dependency pins; try loading the toy model without the GUI.

**Visual test.** Candidate map with the top five areas outlined; a count table per area; a bar of solver
run time against cell count from the toy model. The mapping table with its result column, one row per
CRC call. A source table: one row per Tier 1 source, one cell per fact, coloured by outcome.

**Pass.** An area has at least 8 high-water marks, 5 sensors with a 2023-09-29 event and 3 substations
(*proposed*); the toy model runs; every CRC call in the mapping has a result, and each one that differs
from the reading has its requirement corrected; no fact of a Tier 1 source is left "not checked" without
a reason. If no area passes, report the best three with their trade-offs and stop.

**Stop.** Yuri confirms the area and decisions D1, D2, D9, D10, D12, the budgets, and any requirement
corrected in this stage.

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

**Pass.** Every asset has a ground elevation; at least 95% of buildings proper matched to the city's
elevation table (*proposed*; garages are outside that table, decided at the F1 stop); every substation
has been looked at and the sheet is in the report.

**Overrun.** Limit buildings to blocks touched by any flood-map polygon.

## F2. Sources: what goes into CRC and what does not (6 h)

**Steps.**

1. Second readers for the flood maps, Groundsource and FloodNet (FS4), with offline tests on small
   constructed files and deliberate faults. Written by an agent that does not see the loaders.
2. Loaders (D8): flood-map classes rasterised onto the project grid, and the polygons into CRC with
   `Layer.from_table` (FS1); FloodNet as a per-sensor, per-event table and into CRC with
   `Observations.from_table` (FS3); Groundsource as a `flood_lab` table of dated places (FS2).
3. A transformation statement for each loader, in `docs/flood/data-cards/`. These sources are the lab's
   own, not crc-sdk's, so nothing is added to the validation inventory or its page.
4. The primer `docs/primers/point-observations.md` with its script (FS5), and a link to it from
   `docs/primers/event-sources-in-crc.md`.
5. In the report, a table "what CRC 1.0.0 held and what it did not" for the three sources, with what a
   type for dated polygons would need. Candidate findings follow FG9.

**Visual test.** Per scenario, a difference map between loader and reference reader (must be empty); a map
of Groundsource rows for 2021-09-01/02 in the New York box coloured by polygon size; a histogram of the
latest dates in the file; a map of sensors coloured by whether they recorded each storm.

The primer's figures count as part of the test: they are made by its script from cached data.

**Pass.** Zero differing cells and rows; a shifted polygon and a dropped row are both caught; what was
loaded into CRC reads back equal to what was put in; the primer's script runs offline.

## F3. Solver model, calibration, replays (8 h)

**Steps.**

1. Scripted model build (FH2): terrain and sub-grid, roughness, buildings, a water-level boundary at the
   shoreline, rainfall forcing, and a constant loss rate (the water the sewers and the ground take away,
   earlier called the drainage allowance) as a parameter.
2. Three intensity runs matching the flood-map scenarios' rainfall. Calibrate the loss rate on the two
   current-sea-level maps (FH3); report the 3.66 in/hr run as a check.
3. Verify item 4 of §9: place the three intensities on the Atlas 14 curve for the area.
4. Freeze the loss rate; record it with its fit.
5. Replays of both storms from radar rainfall (FH4).
6. Monotonicity and water-balance tests (FH8).
7. `hazard/base.py` with the three implementations registered (FH1).

**Visual test.** Calibration curve: flooded area per class against loss rate, with the city-map area as a
line, for each scenario. Hit, miss and false-alarm map against each current-sea-level map. Water-balance
bar per run (rain against losses, boundary outflow and change in storage). Maps of maximum inundation
depth for the two replays, with radar rainfall totals beside them.

**Pass.** Water balance within 1%; critical success index of 0.5 or better against the two calibration
maps (*proposed*). If one loss rate cannot reach it, try per-district values once, then report the
mismatch as a finding and continue with the best fit.

## F4. Storm catalogue and batch runs (8 h)

**Steps.**

1. RainyDay over the gridded rainfall record (FH5): choose and justify the transposition domain (compare
   storm statistics inside it for homogeneity); generate synthetic years; keep the storms that matter.
2. Batch-run the solver over the kept storms, resumable, one record per run.
3. Six Atlas 14 uniform design storms (FH6).
4. Per-cell depth frequency from the catalogue with a dry-year point mass; load into CRC by both routes
   of FH7 (`from_raster` for the grid after the non-decreasing clean-up, `from_quantiles` at the asset
   points) and read back.
5. Compare frequency from the catalogue with frequency from the design storms.

**Visual test.** Storm-centre map over the transposition domain; rainfall frequency at the area from the
catalogue against Atlas 14 (they should agree before depth is compared); a strip of depth maps at 10, 100
and 500 years from the catalogue beside the design-storm maps; a count of buildings wet at 100 years under
each method.

**Pass.** Catalogue rainfall frequency at the centroid within the Atlas 14 confidence band for 2 to 100
years (*proposed*); every batch run has a record; depth non-decreasing with return period in 99% of cells
before the clean-up, and in every cell after it, with the number of cells changed reported; the curves
read back from CRC equal the ones loaded.

**Overrun.** Fewer storms (not below 60), and say what tail that supports.

## F5. Validation against observations (9 h)

**Steps.**

1. Second readers for the high-water marks and for the radar rainfall of one replay window (FS4), by an
   agent that does not see the loaders; deliberate-fault tests; outcomes on the source cards. This comes
   first: FV1's figures rest on the marks.
2. Sample Ida replay depth at each high-water mark (FV1).
3. Sensor comparison for both storms (FV2).
4. Jamaica Bay map comparison after reading its licence (FV3).
5. Who saw the flood (FV5): load 311 and Storm Events (the `flood_lab` reader) for both dates; count and
   map all five sources.
6. No retuning (FV4).

**Visual test.** Modelled against surveyed depth with a one-to-one line, bias and error printed, the
published 0.20 m marked. One small panel per sensor: measured depth through the storm with the modelled
peak. Error map. The who-saw-the-flood bar chart and map for each storm.

**Pass.** The two second readers agree with their loaders, and a deliberate fault in each is caught. For
the model against observations none is forced; the stage reports. Above 0.5 m root-mean-square error (*proposed*) the report
states that substation-level claims are not supported and proposes what to do (classes only, or F14).

## F6. Curves, the event-loss extension of CRC, and risk (13 h)

**Steps.**

1. The extension (D17). Read crc-sdk pull request #47 and crc-framework-rs #27 as they stand that day
   (FR11) and record what they define. Draft the design note `docs/flood/event-loss-extension.md` (FR12)
   with the interface. Then build `src/crc_event_loss/` (FR9, FR10) with tests on small made-up tables
   whose sums can be checked by hand: two assets that always flood together, two that never do, a year
   with two events, a tie at the VaR cutoff. Correct the note to match what was built.
2. Verify item 7 of §9. Enter the substation curve envelope (FR2) and the building curves in `curves.yaml` with
   sources and tags (FR1–FR3). Unit tests: monotone, bounded, zero below threshold.
3. Exporters to CRC first (`Impact.tabulated`, every table to the stated maximum depth; FR1); the others
   in F10.
4. Event-loss table (FR4): damage ratios from CRC's `Impact.evaluate`, held in the extension's table.
5. Metrics (FR5): sums per event and per synthetic year by the extension, then exceedance curves, VaR,
   CVaR and expected annual loss from CRC's `Distribution.empirical`; per asset from CRC's curves, the
   damage distribution by `pushforward`, expected annual damage by `complete` and `expectation` and loss at 10, 100 and 500 years by `evaluate(...).impact(...)`, with
   failure rows counted; the two curve routes of FH7 compared at the assets; the dependence brackets
   (FR6), with `compute_risk` if F0 showed it fits.
6. Hand recomputation of three assets in a notebook, by an agent that does not see the code (FR7);
   bootstrap intervals (FR8).
7. Add entries to `docs/algorithms.md` for every new calculation.

**Visual test.** A card per substation: depth-frequency curve with catalogue points, the damage-curve
envelope with that asset's 10-, 100- and 500-year depths marked, loss by return period as a band. Portfolio
occurrence and aggregate exceedance curves with bootstrap bands. A bracket chart: 1-in-100 loss under full
dependence, from the event table, and under independence. A bar pair: expected annual loss from the event
table and from CRC's curves, the latter by both routes of FH7.

**Pass.** Hand recomputation matches; the event-table CVaR at 99% is at or below the full-dependence
bracket (CH-28; the 1-in-100 loss is shown against both brackets without a verdict); the two
expected-annual-loss routes are within 5% or the difference is explained (*proposed*); every failure row
CRC returned is accounted for.

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

1. Dataset from F4 runs: static channels, storm vector, maximum inundation depth; tiles; splits by storm and one spatial
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

1. `site/flood/` with FP1–FP5, generated from records; register layers; link from the landing page,
   keeping the strings `tests/test_projects.py` checks there.
2. Finalise the gallery (FP6), with the source cards.
3. `tools/smoke-flood.mjs` (FP9); record a three-minute walk-through with `tools/record-demo.mjs`.
4. `flood_lab.check_site` into `just site` (`site-flood`) and `.github/workflows/pages.yml` (FG8).
5. Update `README.md`, `AGENTS.md` (a "Flood lab" entry under Projects) and `docs/index.md`.

**Visual test.** Smoke-test screenshots at desktop and phone width, committed and compared on rebuild.

**Pass.** Smoke test green; every figure has a caption with its limit (FP8); a reader new to the project
can name the most exposed substation and say whether raising it pays, within two minutes (Yuri judges).

## F12. Fremont chapter (5 h)

**Steps.** FC1 with the F8 index code, on the publisher's depths at seven return periods as crc-sdk 1.0.0
returns them, read under `caffeinate -i` or from the copy the validation project keeps; source facts
(FS6) for the reanalysis and the gauge; verify item 11 of §9 and the back-test wording; FC2 if a reach
exists; FC3.

**Visual test.** Largest connected flooded area against return period with the 0.58 square mile line, and
the map at the crossing, with the flooded pixels that get no row from crc-sdk marked. If the reach exists: winter 2017 flow from reanalysis, gauge and GloFAS, each
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

If any of the first three contradicts the requirements, stop and report before going further. The CRC
1.0.0 block (step 1) follows directly; it needs no download.
