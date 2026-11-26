# F4. Storm catalogue and batch runs

Date: 2026-11-26 · branch `flood/f4` · crc-sdk 1.0.0, crc-framework 1.0.0 · SFINCS v2.5.0 · RainyDay ff2b809 ·
AORC v1.1 2002–2025 · model frozen at F3 (constant loss rate 30 mm/h)

Stage F4 of `docs/flood/plan.md`: the storm catalogue (FH5), the six design storms (FH6), depth frequency
loaded into CRC by both routes (FH7). How the events are made, with diagrams and references, is in
`docs/flood/simulated-events.md`; this report gives the results and the decisions. Numbers come from the record
`f4` at **60 of 150 catalogue runs**. This is the copy Demo 1 rests on: tag `flood-f4-demo1-60runs`, and the
outputs are frozen in `data/cache/flood/f4/snapshot_60/`. The batch continues unattended; the full 150, and
the run-on comparison on the 5 km model, come as an addendum to this report.

## Result against the pass rule

| Rule (plan F4) | Result |
| --- | --- |
| Catalogue rainfall at the area inside the Atlas 14 band, 2 to 100 years (*proposed*) | **Fails at 2–10 years, accepted (CH-19).** 31.3 / 43.2 / 53.1 mm against lower bounds 35.8 / 46.7 / 54.9. Inside the band at 25, 50 and 100 years |
| Every batch run has a record | **Pass.** 60 catalogue and 12 design runs; the largest water-balance residual is 0.017% of the rain |
| Depth non-decreasing with return period in 99% of cells before the clean-up | **Pass,** 100% |
| … in every cell after it, with cells changed reported | **Pass,** 0 cells changed |
| Curves read back from CRC equal those loaded | **Pass,** both routes. Grid route (`from_raster`): 379,976 cells written and read back, 0 differ. Point route (`from_quantiles`): 17,701 assets, 0 differ |
| CRC reads the catalogue's depth from the point route (CH-23, added) | **Pass.** 17,701 assets at the seven probabilities, largest difference 0 m |
| Overrun: not below 60 storms | **60 reached** at 13:14. The rest finish tonight |

## 1. Catalogue (FH5)

- **Transposition domain B**, 39.3–41.6 N and 75.6–71.8 W, land only. 94% of its pixels are within 15% of the
  study area's mean annual 3-hour maximum, and 90% at 1 hour. The choice among five candidates is in
  `simulated-events.md` §3.2.
- **RainyDay:** 960 storms of 3 hours (40 a year, at least 24 h apart), 1,000 synthetic years, one storm a
  year, uniform transposition.
- **Rainfall.** The catalogue is drier than Atlas 14 at short return periods. The cause is the rainfall
  record, not RainyDay's settings: AORC's own observed box maxima are low too (median 38.1 mm), and the values
  barely move from 20 to 40 storms a year. Accepted as CH-19, and to be stated wherever the catalogue is shown.
- **Selection:** 150 synthetic years in three strata by rank: all 30 of the top 30 ranks, 60 of ranks 31–150,
  and 60 of ranks 151–1000. Each run is weighted by the years it stands for. At 60 runs the strata have 12, 24
  and 24 finished, and the weights are interim (years in the stratum divided by runs finished in it).

## 2. Results at 60 runs

| Return period | 2 y | 5 y | 10 y | 25 y | 50 y | 100 y | 200 y | 500 y |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Catalogue: 5 m cells wet (≥ 0.05 m) | 0 | 0 | 0 | 3,796 | 12,197 | 19,650 | 31,517 | 44,101 |

- **Nothing floods at 10 years.** Only 120 of the 1,000 synthetic years have an hour wetter than the 30 mm/h
  constant loss rate (the water the sewers and the ground take away). Flooding therefore starts at around
  20–25 years. This is a result of the calibrated loss rate and of the low catalogue rainfall (CH-19), not a
  fault. A "10-year map" from the catalogue is blank, and the demo should say why.
- **Design storms (FH6),** cells wet at 0.05 m:
  - 1 hour: 0 / 22,054 / 38,638 / 54,344 / 71,034 / 87,865 at 2 / 5 / 10 / 25 / 100 / 500 years.
  - 3 hours: 0 up to 25 years, then 30,981 at 100 years and 61,014 at 500 years.
  - Every 3-hour storm up to 25 years rains below the loss rate.
- **Buildings wet at the wall at 100 years** (of 17,750 in the study area):

  | Method | ≥ 0.05 m | ≥ 0.3 m |
  | --- | --- | --- |
  | Catalogue (each building's own curve at AEP 0.01) | 6,388 | 1,452 |
  | 1-hour design storm, 100 years | 11,659 | 5,839 |
  | 3-hour design storm, 100 years | 9,525 | 2,752 |

  The catalogue wets about half the buildings the 1-hour design storm does. A design storm puts a whole
  return period's rain on every cell at once, while a catalogue storm's rain varies in space and time.

- **Substations, lead depth over 25 m² of open ground:**

  | Substation | 100 y | 500 y | Wet in a year |
  | --- | --- | --- | --- |
  | Farragut | 0.29 m | 0.43 m | 6.8% |
  | Hudson Avenue | 0.15 m | 0.50 m | 2.8% |
  | Plymouth | 0.13 m | 0.17 m | 4.3% |
  | Water Street | 0 | 0.06 m | 0.3% |

  None of the five is wet at 10 years.
- **Error to quote beside these depths:** F5's test against Ida gives an RMSE of about 0.2 m
  (`F5-marks-and-sensors.md`).
- **Figures** (gallery, record `f4`): `domain`, `rainfall_frequency`, `depth_strip`, `buildings_wet`,
  `wet_runs`, `progress`, and the event figures `synthetic_years` and `parent_storms`.

## 3. Loading into CRC (FH7)

- **Grid route:** `Dataset.from_raster`, one GeoTIFF per probability (seven annual exceedance probabilities
  from 0.5 to 0.002, given to CRC as non-exceedance), nodata −9999.
  - The 260,024 cells CRC skips are exactly the cells the model does not read (buildings, pits, water,
    standing water).
  - Dry cells go in as 0 m, as FH7 requires. The read-back is equal.
  - It takes 97 s.
- **Point route:** `Dataset.from_quantiles`, each asset's exact empirical distribution, with the dry share as
  its own step. Each step is two knots of equal depth, one at each end (CH-23).
  - 17,701 assets: 5 substations and 17,696 buildings, since 54 buildings have no readable ground in their
    wall band and carry no curve.
  - The read-back is equal, in under 5 s.
- **Steps, not slopes (CH-23, accepted).** CRC's quantile curve interpolates linearly in probability between
  knots. With one knot per storm, CRC read below the catalogue between two storms, most at the tail:

  | Substation | 100 y (catalogue / CRC, one knot per storm) | 200 y | 500 y |
  | --- | --- | --- | --- |
  | Farragut | 0.287 / 0.279 m | 0.385 / 0.324 m | 0.433 / 0.395 m |
  | Hudson Avenue | 0.153 / 0.152 m | 0.381 / 0.165 m | 0.504 / 0.406 m |

  With two knots per step, a new check reads every asset's curve back through CRC's `QuantileCurve` at the
  seven probabilities: all 17,701 assets equal the catalogue, largest difference 0 m. CRC's step and linear
  options belong to its damage functions (depth to damage), not to a hazard curve, so the steps are made
  by the knots. Only F6's loss figures use this route.

## 4. Changes in this stage

| Change | What | Status |
| --- | --- | --- |
| CH-19 | Catalogue settings; rainfall below the Atlas 14 band at 2–10 years accepted | Accepted by Yuri |
| CH-20 | A 5 m cell's ground is never below its lowest sub-grid level (865 cells read wet in every storm). F3 outcomes unchanged (CSI 0.3073 / 0.4082) | Accepted by Yuri |
| CH-21 | The same rule at the 1 m pixels around buildings and at substation sites: the false floor of about 2,930 buildings wet in storms below the loss rate is gone. Ida lead sites still meet the 0.3 m rule (Farragut 0.39 m, Hudson Avenue 0.415 m, was 0.447) | Accepted by Yuri |
| CH-22 | Requirements, plan, demo plan and reports F3 to F5 reworded with the hydrology terms of `docs/flood/terminology.md` | Accepted by Yuri, done before the demos |
| CH-23 | Point-route knots as steps | Accepted by Yuri, done: both routes read the catalogue's depth |

## 5. Review before the stop

A fresh Opus agent reviewed the stage's code diff without being shown the report or the change log. It found
the rank, return-period, probability, weight, north–south, unit and time-alignment logic correct, and
checked them on real files.

| Finding | Done |
| --- | --- |
| A building with no readable pixel in its wall band was loaded as dry (0 m) at every probability (54 buildings) | Fixed: NaN, no curve, counted in the record (`buildings_not_read`) |
| The per-run cache key missed the model rasters, the site outlines and the depth-rule code (the same cause as a stale building count caught earlier the same day) | Fixed: the key covers them |
| The point route reads below the catalogue between knots | Fixed by CH-23 |
| Forcing and run folders are reused by label (`cat_r<rank>`), so a new catalogue would silently reuse old rain and old runs | Not fixed; stated here. Any new catalogue must use a new runs folder (`FLOOD_RUNS`) |
| Bands of touching buildings share their street pixels with one owner, so a row house can read low | Not fixed; stated as a limit |
| Wording: depth definition without CH-20; tie at the wet probability; smoothing window (25 km north–south, about 19 km east–west); the plotted box rainfall is a plain mean, not RainyDay's ranking value | Fixed |

## 6. Limits

- The largest-rainfall storm of a synthetic year is taken as its worst flood.
- One storm duration (3 hours).
- **Run-on** (a convention: water flowing onto an area from upslope). The square model has an outflow
  boundary on land, so no run-on from the contributing area outside it. The 5 km run-on comparison runs
  tonight and reports what that leaves out.
- **Uncertainty.** Each frequency rests on the runs finished. At 60 runs the 100-year and rarer values rest
  on the 12 of the 30 top-ranked runs finished so far, each standing for 2.5 years.

## Checks

- `just test` passes: 505 in the full suite before F5, 267 flood tests after it.
- `just lint` and `just site-flood` pass.
- `just flood-f4-status` shows the batch.

## Models and tokens

| Task | Model | Tokens |
| --- | --- | --- |
| Domain choice, selection and frequency arithmetic, CRC loading, CH-19–CH-23 diagnoses, coordination, terminology and events documents, report | Opus 5.5 (main session) | not available to the session |
| AORC and RainyDay lookups | Sonnet | 56,487 |
| RainyDay pipeline | Opus | 237,816 |
| F4 check and figures | Opus | 232,157 |
| 5 km run-on model | Opus | 204,166 |
| Hydrology terms lookup | Sonnet | 56,022 |
| Blind review of the stage | Opus | 137,038 |
| Hydrology rewording, CH-22 | Opus | 136,221 |
| Validation monitor fix (side task, branch `validation/living-files`) | Opus | 115,444 |
