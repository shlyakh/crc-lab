# CRC 1.0: what changes, and what it means for crc-lab

Written 2026-11-23 from a reading of crc-sdk `v1.0.0a1`, crc-framework `v1.0.0-alpha.2` and crc-docs `main`
(commit `cda23cf`), all of that day. Nothing below was run unless it says so: it is what the code, the two
migration guides and the release notes show. crc-lab is on crc-sdk 0.11.2 and crc-framework 0.6.0.

**Since then (2026-11-24):** both packages were released as 1.0.0 and crc-lab's validation project moved to
them; `docs/reports/u3-crc-1.0.0.md` is the account of that, with what was run. Three statements below are
out of date for the final release:

- CRC Open can be read on 1.0.0: `CRCOpen().inspect()` lists 875 series in one release, and the
  identifiers were corrected (pull request #49).
- crc-docs now requires crc-sdk 1.x.
- A JRC read is not failed by one pixel whose depth decreases: the provider skips the pixel and counts it
  (CRC-023-JRC). `Dataset.from_raster` does fail the whole read (CRC-025-OWN).

The findings table below is a reading of the 1.0.0a1 code; what was measured on 1.0.0 is in
`docs/reports/v1-probes-1.0.0.md` and in the register.

Upstream pages to read first, in this order:

1. crc-sdk `docs/migration-v1.md` (the rename tables and what changed in behaviour)
2. crc-framework `docs/migration-v1.md`, section "Changes that alter results"
3. crc-sdk `docs/evaluation.md` and `docs/sources.md`
4. crc-sdk `docs/release-notes.md` (what is not published yet)

## The three things that matter most

1. **1.0 is a rewrite of both packages.** crc-sdk: "crc-sdk 1.0 is a rewrite of the public interface."
   crc-framework: "Version 1.0 replaces the 0.x Python and JavaScript interfaces. Most changes are renames
   into a smaller set of types, but a few change numbers silently." Every crc-sdk name crc-lab imports is
   gone or renamed: all of `crc_sdk.workflows`, `.providers` and `.connectors` are removed. Moving crc-lab is
   a port of each adapter and each build script, not a pin change followed by a re-run.
2. **The two packages move together.** crc-sdk 1.0.0a1 requires crc-framework 1.0.0a1 or later; crc-sdk
   0.11.2 requires crc-framework below 0.7. `just upstream-bump` refuses to move one without the other.
3. **CRC Open cannot be read on 1.0 yet.** 1.0 reads only Dataset format 2.0 ("There is no converter for 0.x
   files"), and "Production publication of CRC Open Dataset 2.0 resources and their release index is
   pending". The CRC Open part of the data explorer has nothing to read until that release exists. In
   1.0.0a1 twelve of the seventeen `CRCOpen.Variable` members also name identifiers CRC Open does not
   publish (`crc:txx` for the published `crc:tx_max`); pull request #49, the planned a2, corrects this.

crc-docs has not moved: it still requires `crc-sdk>=0.11.1,<1`, so its notebooks and skills show the old
interface. Its only change since our clone is a map tool (below).

## Versions

| Package | We use | Newer | Notes |
| --- | --- | --- | --- |
| crc-sdk | 0.11.2 | 1.0.0a1 (2026-11-23, pre-release) | #49 open for a2: `decode_curves(rows)` and the CRC Open identifiers. #47 insurance loss functions, work in progress |
| crc-framework | 0.6.0 | 1.0.0a1, 1.0.0a2 (both 2026-11-23, pre-releases; tags `v1.0.0-alpha.1`, `-alpha.2`) | #27 insurance loss framework, work in progress |
| crc-docs | `c6f78fb` (2026-11-07) | `cda23cf` (2026-11-17), 11 commits | Still on crc-sdk below 1 |

Upstream states no deprecation path for 1.x. crc-sdk `AGENTS.md`: "Superseded exports, historical
schemas, compatibility adapters, and alternate names are removed; do not add deprecation paths". At 0.11.2
the same file said "add, deprecate, then remove". No written stability promise for 1.x was found.

## What we call today, and its replacement

| 0.11 | 1.0 |
| --- | --- |
| `HazardDataset.crc_open()` | `CRCOpen(catalog=...)` |
| `.glofas()`, `.efas()` | `JRC(product=JRC.Product.GLOFAS / EFAS)` |
| `.era5()`, `.ghcnh()` | `ERA5(indicator=...)`, `GHCNh()` |
| `IBTrACSPlan`, `NOAAExtremeWaterLevelPlan` | `IBTrACS(agency=)`, `NOAAWaterLevels` |
| `for_area`, `hazards`, `horizons`, `pathways` | `select(area=, variables=, periods=, scenarios=)` |
| `for_assets(...).write_parquet` | `evaluate(Assets(...)).write` |
| `from_table(... CDFCurveFitPolicy)` | `Samples.from_table` then `fit(SampleFit)`, or `Dataset.from_quantiles` then `fit(QuantileFit)` |
| `read_hazard_dataset`, `read_hazard_metadata` | `Dataset.open(path)`, `.metadata` |
| `curve_quantiles`, `curve_quantiles_at`, `return_periods_to_probabilities` | `evaluate(...).return_periods()`, or `1 - 1/T` |
| `polyfill_wkb` | h3-py directly |
| `ImpactExpression.tabulated` | framework `Impact.tabulated` |
| `FittedDistribution("gumbel_r", ...)`, `.ppf` | `Distribution.parametric(DistributionFamily.GUMBEL_RIGHT, ...)`, `.quantile` |
| column names `hazard_name`, `pathway`, `horizon`, `source_id` | `variable_id`, `scenario_id`, `period_id`, `support_id` |

## Behaviour that changes

- **Evaluation output is long, not wide:** one row per asset, series and query, with `query_value` and
  `value`, in place of `value_rp*` columns.
- **Failures are rows, not errors.** An asset with no data keeps its row with `failure =
  no_covering_support`; a query outside a curve's knots gives `query_outside_support`.
- **Nothing is fitted unless asked.** "Supplied quantiles are used as they are; fitting is an explicit
  `fit(spec)`". JRC flood now returns the publisher's depths per pixel and no Gumbel curve; EDO returns its
  ten-day observations and no curve.
- **Fitting:** maximum likelihood is the default, with no silent fallback and no automatic choice of family.
  A fit returns a record of every attempt.
- **Provenance:** every acquired file carries its address, SHA-256, licence, attribution and retrieval
  time "when known", with "no invented default license or attribution".

### Changes that move numbers without an error

From crc-framework `docs/migration-v1.md` ("These changes do not raise an error"):

- **Between the knots of a return-period curve.** 0.x interpolated in log return period; 1.0 "interpolates
  linearly in probability". Upstream's example: 0.5 m at 10 years and 2.0 m at 100 years gave about 0.95 m
  at 20 years in 0.6 and gives 1.33 m in 1.0. Values at the knots do not change. This bears on our 21
  tabulated hail cells, the tabulated CRC Open cells and every JRC depth read between published return
  periods.
- `LinearImpact` is no longer clamped at 0 unless a minimum is given.
- `compute_risk` sums impacts where it took a weighted average.

Upstream's own parity check (framework pull request #32): on 47,194 curves, "1.0 values match framework
0.5.3 on every curve kind", with differences "at most 3e-8 absolute" near hurdle atoms.

## Our findings against 1.0

Twenty findings are open in `src/data_source_check/sources/crc_sdk/findings.toml`. No upstream commit names
any of them. The column below is what the 1.0.0a1 code shows, from two independent readings; where they
differed the more cautious one is given. None of it has been run by us: `just v1-probes` (report in
`docs/reports/v1-probes-<version>.md`) is how a line here becomes an observation.

| Finding | In 1.0.0a1 (code reading) | Reading |
| --- | --- | --- |
| CRC-002-FWK twenty-year minimum | The check on the request is gone; each cell is fitted on its own valid years, minimum 3 by default | Changed; reword |
| CRC-003-JRC no licence or checksum on JRC and EDO output | Licence, attribution, SHA-256 and retrieval time are set and written into the file. The checksum covers crc-sdk's crop, not the publisher's file | Apparently fixed |
| CRC-004-EDO, CRC-005-EDO | EDO returns dated ten-day records; no curve and no annual minimum in the provider | No longer applies |
| CRC-006-ERA5 unit not checked | A units attribute other than `m` or `K` raises | Apparently fixed |
| CRC-007-OPEN `retrieved_at` | Taken from the download, kept on cache replay. Cannot be checked until a 2.0 release exists | Apparently fixed |
| CRC-008-OSC | OS-Climate removed | No longer applies |
| CRC-009-CDL moving branch | Now the live USDA service with CC0, a checksum and a release hash; still not a versioned snapshot | Changed; reword |
| CRC-011-IBT no licence field | Licence (free text), attribution, checksum and retrieval time travel with the batches | Apparently fixed |
| CRC-012-NEX version 2.0 not requestable | The version argument is gone: the highest version on NASA's listing is read, so 2.0 is read and an older revision cannot be chosen | Changed; reword |
| CRC-013-FWK fit gives up on flat-then-rising depths | JRC is no longer fitted. An explicit fit raises, warns or keeps a failure row, so it is no longer silent. Whether the optimizer converges on the case cannot be read | Changed; needs a run |
| CRC-014-JRC flooded pixel with no curve | Pixels with two or more depths are delivered; fewer gives an aggregate count only. **A depth that decreases makes the whole read fail** | Changed; new behaviour to confirm |
| CRC-015-JRC curve far from the published depth | Output keeps the published depths; a query outside them is a failure row | Changed |
| CRC-016-JRC error outside coverage | No coverage error found: a box outside coverage appears to give zero rows with no diagnostic | Changed; needs a run |
| CRC-017-JRC release identification | The README version must equal a hard-coded value; ETag, Last-Modified and size are checked. Addresses still unversioned, no publisher checksum | Changed |
| CRC-018-JRC licence | Hard-codes `ODbL-1.0`, which matches the publisher's README and not its `copyright.txt` (CC BY 4.0) | Changed |
| CRC-019-JRC publisher's masks not read | Only depth files are requested | Unchanged |
| CRC-020-JRC `source_id` depends on the box | `support_id` is text built from the tile and the pixel's row and column in the publisher's file | Apparently fixed |
| CRC-021-JRC relative cache path | The cache path is made absolute | Apparently fixed |
| CRC-022-JRC 27 minutes for Texas | No worker pool; a per-pixel Python loop builds every row in memory before the first batch | Changed; needs a run |

By this reading: 6 apparently fixed, 3 no longer apply, 10 changed in a way that needs rewording or a run,
1 unchanged. Under the rules in `docs/upstream-updates.md` none becomes `fixed` before a run shows it.

Something new to confirm on data: in the Texas box 192,683 pixels had a depth that decreases with return
period at 0.11.1. In 1.0.0a1 one such pixel appears to fail the read of the whole box
(`crc_sdk/_climate_io.py:176-178`; upstream's own test `tests/test_raster_input.py:211-227` expects it).

What 1.0 still does not have (searched, no match): a hail measurement or hail model; confidence intervals
on fits; the Emanuel cubic (the sigmoid is still a logistic).

## New capabilities worth using

| Capability | Where documented | Use in crc-lab | Size of a first use |
| --- | --- | --- | --- |
| Out-of-range and uncovered queries become failure rows | sdk `docs/evaluation.md` | Replaces the workaround in `lab_common/horizons.py` and the cells skipped in verification | An hour on our own data |
| `QuantileCurve.complete(TailCompletion(...))`: beyond the knots as a recorded choice | framework `docs/python.md` | The tabulated hail cells | An hour |
| JRC as published depths with counts of skipped pixels | sdk `docs/sources.md` | Re-run of V8.1; simpler `build_jrc` | A day |
| `Samples.from_table` then `fit(ModelSelection(...))` with a fit record | sdk `docs/execution.md` | Phase 3 hail and gust curves, with Gumbel against GEV recorded per cell | A day |
| `ContextualImpact` with our own context bound to asset columns | sdk `docs/evaluation.md` | Glass class and stow as context of one hail model in place of six expressions | A day |
| `Impact.expectation`, `pushforward`, `statistics` with CVaR | framework `docs/python.md` | Expected damage per plant through CRC's numerical path | A day |
| `ResourceIdentity` on every file; `Cache.offline` | sdk `docs/data-licences.md` | The validation records and the monitor could read provenance instead of recomputing it | A day |
| Native observations: `IBTrACS(agency=)`, `GHCNh.observations()`, `NOAAWaterLevels.levels()` | sdk `docs/sources.md` | Reference comparisons one step closer to the publisher | A day per source |
| `SpatialMatch.nearest(max_distance=)` with the distance in the output | sdk `docs/evaluation.md` | Stations against plants and cities | An hour |
| crc-viz map and `tools/build_map_page.py` (crc-docs; works with 0.11 output) | crc-docs `docs/map/README.md` | A map of plants for a talk | An hour |

Not released yet: `decode_curves(rows)` (crc-sdk #49), the insurance loss work (crc-sdk #47, framework #27).

## Size of the port (measured on 1.0.0a1 in a scratch environment, 2026-11-23)

- Name check: 73 of the 75 upstream names our code uses are missing. The two that remain are `crc_sdk` and
  `crc_sdk.__file__`.
- Offline tests: 225 pass, 22 fail, 95 error. Apart from the pin guard, every failure is a removed module;
  none is a behaviour change, because nothing reaches the numbers yet.
- Statement files: all 25 upstream files cited by the 91 `code_ref` lines are deleted. Each reference has
  to be found again in a different file; none can be renumbered.
- Extras: `geometry` and `agriculture` are gone from crc-sdk; `polyfill_wkb` has no replacement (h3-py
  directly).
- Subsets of IBTrACS are gone (the provider reads `ALL` for one agency), and NEX takes no file version.
- Cheapest first step: `adapters/crc/enumerate.py` rewritten against `crc_sdk.__all__` and the provider
  enums unblocks the inventory, the monitor and the drafting brief.

## What this means for the lab

- crc-lab stays on 0.11.2 until the port is done; the published pages keep working from it.
- The port goes source by source in the validation project, since `adapters/crc/` is the only code there
  that calls crc-sdk. JRC flood first: most open findings are there and its behaviour changed most.
- The transformation statements describe 0.11 behaviour. For JRC, GHCNh and ERA5 they have to be written
  again, not re-run: several steps (fit, fit failure, knots) no longer exist on the default path.
- The hail curves and the explorer builds call 21 removed names between them; the CRC Open explorer waits
  for the 2.0 release.
- Records of both versions should stay side by side for a while: "what 1.0 changed in the numbers" is itself
  a result worth showing.
