# Flood lab: what each requirement asks of CRC 1.0.0

Written 2026-11-25 for crc-sdk 1.0.0 and crc-framework 1.0.0. Companion to `docs/flood/requirements.md`.

**Status of every row but two: read, not run** (the two that were run say so). The calls were read in the reference clones (`../upstream/crc-sdk`
and `../upstream/crc-framework-rs`, both at `v1.0.0`, identical to the installed wheels). None has been run
for the flood lab. Stage F0 runs each once (requirements §9, item 12) and fills the last column; a row that
does not behave as read stops the stage until this file and the requirement are corrected.

Paths: **sdk** is `../upstream/crc-sdk/crc_sdk/`, **fw** is
`../upstream/crc-framework-rs/python/crc_framework/`. Everything public is imported from `crc_sdk` or
`crc_framework`; the underscore files are where the code lives, cited so a line can be found.

## Calls

| Need | Requirement | 1.0.0 call | Where | Read in the code | F0 result |
| --- | --- | --- | --- | --- | --- |
| Depth-frequency curves on the project grid | FH7 | `Dataset.from_raster({probability: path}, variable=, probability=)` | sdk `_recipes.py:1946`, decoder `_climate_io.py:43-215` | One single-band GeoTIFF per non-exceedance probability, all on one grid. Any coordinate system if stated (`:90-94`). Each pixel becomes a WGS84 polygon in a Python loop (`:142-169`). Masked values are dropped; a pixel with fewer than two valid knots is skipped and counted. One pixel whose value falls as probability rises fails the whole read (CRC-025-OWN). The probability set is the same for every pixel | |
| Curves with knots that differ per place | FH7, FR5 | `Dataset.from_quantiles(table, ...)` | sdk `_recipes.py:1992`, `_table_input.py:579-641` | Long table: support, longitude, latitude, probability, value. Supports are points; assets match by `SpatialMatch.nearest(max_distance=)`; an exact tie between two points is an error | |
| What a curve is | FH7 | `QuantileCurve` | fw `_distribution.py:819` | Knots of probability and value, probabilities strictly increasing, values non-decreasing, flat runs allowed (a dry-year mass is a run of zeros from 0 to the dry probability). Linear in probability between knots. Nothing is fitted unless `fit()` is called | |
| A curve over the whole probability range | FR5 | `QuantileCurve.complete(TailCompletion(lower=, upper=))` | fw `_distribution.py:937`, `:88` | Adds the end points at probability 0 and 1; the end values must contain the supplied ones; a supplied end point cannot be replaced | |
| Damage curve from a table | FR1 to FR3, FM1, FM2 | `Impact.tabulated(points, input=, output=)` | fw `_impacts.py:295` | Linear between points. A depth outside the table is an error (a failure row inside an evaluation), so a table must reach the largest depth it can meet | |
| Damage ratio at known depths | FR4 | `Impact.evaluate(values)` | fw `_impacts.py:351` | Array in, array out. This is the only per-event call: 1.0.0 has no event set and no event-loss table | |
| Expected annual damage ratio | FR5 | `Impact.expectation(law)` | fw `_impacts.py:544` | Needs a law over the full probability range (hence `complete`). Exact, not sampled, for a table over a piecewise-linear law. An error if the law reaches past the table | |
| Damage at a return period, per asset | FR5 | `dataset.evaluate(assets).return_periods([...]).impact(name, model, variable=)` then `.read()` | sdk `_evaluation.py:1071`, `:1079` | Query at probability 1 − 1/T. Long output: one row per asset, series and query. A query outside the knots, or an asset no pixel covers, keeps its row with a `failure` value. The value is a ratio; money is ours to multiply | |
| Assets | FD6 | `Assets(table, id_column=, location=PointColumns(longitude=, latitude=), columns=)` | sdk `_assets.py:315`, `:137` | WGS84 only; another declared coordinate system is refused | |
| Curves out of a dataset | FR5 | `decode_curves(rows)` | sdk `_curves.py:11` | From rows to framework curves, as upstream's own pipeline does before `expectation` | |
| Independence bracket (to be tested) | FR6 | `compute_risk(...)` | fw `_risk.py:114` | A sum of independent two-state outcomes with VaR, CVaR and attribution. It is not an annual loss. Default limit 2^20 branches | |
| A loss distribution and its figures | FR5, FR8 | `Distribution.empirical(samples)`; `.exceedance(values)`, `.quantile(level)`, `.statistics(metrics=[MEAN, CVAR], level=, tail=)`; `.to_json()` | fw `_distribution.py:292`, `:400`, `:451` | The structure that holds a loss distribution: annual losses in, then the exceedance curve, VaR (a quantile), CVaR and mean, exact on the sample, ties kept as atoms. Run on 2026-11-25 on 1,000 made-up annual losses: VaR, CVaR, mean and exceedance equal a numpy recomputation; the JSON form reads back equal | Run once, agrees |
| Damage distribution of one asset | FR5 | `Impact.pushforward(law)` | fw `_impacts.py:564` | The distribution of the damage ratio from a completed depth curve, with the same methods. Run on 2026-11-25 on one made-up curve: its mean equals `Impact.expectation` | Run once, agrees |
| Sensor events | FS3 | `Observations.from_table(table, TimeSeriesColumns(...))` | sdk `_evidence_recipes.py:245`, `_table_input.py:64` | Dated values at longitude and latitude points, with a station and a group. Cannot go through `evaluate` or `impact` | |
| City flood-map classes | FS1 | `Layer.from_table(...)` | sdk `_evidence_recipes.py:453` | Geometry with attributes, no time, no curve. Shown and joined, not evaluated | |
| River flood maps, Fremont | FC1 | `JRC(product=JRC.Product.GLOFAS).select(area=Bounds(...)).read()` | sdk `_climate_sources.py:179-200`, `_providers/jrc.py:59-66` | The publisher's depths at 10, 20, 50, 75, 100, 200 and 500 years; no curve. Pixels with one depth or a decreasing depth get no row (CRC-023-JRC) | |

## What CRC 1.0.0 does not hold

Looked for in both packages and not found. Each is built in `flood_lab` or left out, as the requirement
named says.

| Not in 1.0.0 | Requirement | What the lab does |
| --- | --- | --- |
| An event set, an event-loss table, annual rates per event | FR4, FR10 | The extension `crc_event_loss` (D17); ratios from `Impact.evaluate` |
| Adding the losses of assets that flood together (`compute_risk` adds independent two-state outcomes only); the split into occurrence and aggregate | FR5, FR6, FR10 | The extension's sums per event and per synthetic year; the sums go into `Distribution.empirical` and CRC gives the exceedance curve, VaR and CVaR |
| A record with a date and a polygon | FS2 | Groundsource stays a `flood_lab` table |
| Resilience measures | FM1, FM2 | A measure is a second damage table |
| Uncertainty of a result, intervals on a fit | FR8 | Bootstrap over synthetic years, own code |
| A second try for a dropped download | FC1 | `caffeinate -i`, resumable steps, a local copy of the publisher's files where one is kept (CRC-038-FWK) |

## Upstream work in progress on the same ground

Seen on 2026-11-25, both open, neither released; read from the descriptions only, not from the code
(FR11 reads the code before the extension's interface is fixed).

| Pull request | What its description says | Bearing |
| --- | --- | --- |
| crc-framework-rs #27, "Insurance loss framework" | Annual loss simulation for primary policies (`PolicyTerms`, `simulate_annual_losses`, a separate-peril variant), Gaussian dependence across space that decays with great-circle distance and across perils, `summarize_annual_losses` (VaR, CVaR, exceedance, diversification, attribution per component), an `annual-loss` format | Its summary is where the extension's annual losses per component should be able to go. Its dependence is assumed by distance; ours comes from a storm catalogue. The two can be compared on the same assets |
| crc-sdk #47, "Insurance loss SDK functions" (draft) | Depends on #27; adds `_loss.py`, `_loss_inputs.py`, `_loss_artifact.py` | The SDK side of the same work; names to stay clear of |

## Register findings that bear on the lab

From `src/data_source_check/sources/crc_sdk/findings.toml`, as of 2026-11-25.

| Finding | Status | Bearing |
| --- | --- | --- |
| CRC-025-OWN | reported upstream | Our own rasters: every cell must be non-decreasing before `from_raster` |
| CRC-022-JRC | open | The pixel loop that serves `from_raster`; F0 times 600,000 cells |
| CRC-023-JRC | reported upstream | Fremont: 1,234 of 10,603 flooded pixels get no row |
| CRC-024-JRC | reported upstream | A box outside coverage returns nothing and reports success |
| CRC-038-FWK | open | No second try for a download |
| CRC-019-JRC | open | The publisher's permanent-water mask is not read |
| CRC-017-JRC, CRC-027-FWK | open | How a release and a file are identified in the output |
