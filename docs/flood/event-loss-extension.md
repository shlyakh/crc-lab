# crc_event_loss: an event-loss table for Climate Risk Commons

Design note, draft 1, 2026-11-27 (requirements FR9 to FR12, decision D17). For RiskThinking's
engineers, after Yuri's review; nothing in it has been sent or proposed upstream. The interface it
describes is in `src/crc_event_loss/` as signatures and docstrings only; no part is implemented
yet. This note is drafted before the code (plan F6, step 1) and will be corrected to match what is
built.

Versions read: crc-framework 1.1.0 and crc-sdk 1.1.0 (installed); crc-framework-rs pull request
#27 at commit 5466b84 and crc-sdk pull request #47 at commit 6821eae, both open and last updated
2026-11-24, read on 2026-11-27 (code and documentation, not run).

## 1. The gap

CRC 1.1.0 holds a hazard at a place as a curve (a `QuantileCurve`), a damage function as an
`Impact`, and a loss distribution as a `Distribution`, with every figure taken from it: exceedance,
quantile (VaR), CVaR, mean. Per asset it is complete: `Impact.pushforward` gives an asset's damage
distribution, `Impact.expectation` its expected damage.

What it does not have is the step from one asset to many when the hazard comes as **events**. A
storm catalogue, a stochastic event set from a catastrophe model or a set of historical footprints
all say, for each event, which assets it reaches and how hard. Two assets one street apart are hit
by the same storms; two assets in different basins are not. Their joint loss is in the events, and
it is lost as soon as each asset is reduced to its own curve. CRC 1.1.0 has no type that holds an
event set or a loss per event and asset, and no sum across assets other than `compute_risk`, which
adds independent two-state outcomes.

The extension adds three things and nothing else:

1. an **event set**: event identities, each in a synthetic year (years carry probability weights)
   or with an annual rate;
2. an **event-loss table**: loss per event and component, built from intensities through a CRC
   `Impact`, or given directly;
3. **sums**: within an event across components, and within a year across events, giving annual
   losses per year for the portfolio and per component, handed back to CRC as a `Distribution`.
   Around the sums: each component's share of VaR and CVaR (`RiskAttribution`), and two brackets,
   the same components added under full dependence and under independence.

No correlation is assumed or fitted. Components lose together when, and only when, an event
reaches them together.

## 2. Types

All public names are imported from `crc_event_loss`; modules are private (`_events`, `_table`,
`_aggregate`), as in crc-sdk.

| Name | What it is |
| --- | --- |
| `Timeline` | Enum: `SYNTHETIC_YEARS`, `ANNUAL_RATES` |
| `YearWeights` | Year ids and their probability mass; `equal(ids)`, `stratified({stratum: (years it stands for, years run)})` |
| `EventSet` | `synthetic_years({event: year}, years=, description=, provenance=)` or `annual_rates({event: rate}, ...)`; years without an event are part of the set |
| `Exposure` | `(component_id, value, impact)`: the amount a damage ratio of 1 corresponds to, and which impact applies |
| `EventLossTable` | `from_intensities(events, table, intensity=, exposures=, impacts=, currency=, valuation_basis=, label=, missing=)`, `from_losses(...)`, `to_arrow`, `write(path, overwrite=False)`, `read` |
| `MissingIntensity` | Enum: an absent (event, component) pair is `NO_LOSS` (counted) or an `ERROR` |
| `Failure`, `FailurePolicy` | A value the impact refused, with CRC's error code; aggregation either `REFUSE`s or `EXCLUDE_COMPONENT`s (named in the diagnostics) |
| `AnnualMeasure` | Enum: `AGGREGATE` (sum of a year's events), `OCCURRENCE` (the year's largest event) |
| `AnnualLosses` | `totals` and `components` aligned to the years, with `distribution()`, `component_distribution(id)`, `risk(levels)` giving CRC's `RiskLevel` with `RiskAttribution` |
| `annual_losses(table, measure=, failures=)` | The sums |
| `occurrence_distribution(table)` | For annual rates: the largest event of a year, exact |
| `IndependenceMethod`, `Bracket`, `brackets(annual, levels=, independence=, samples=, seed=)` | Full dependence and independence beside the events' own figure |
| `summary_inputs(annual)` | `totals` and `components` in the form pull request #27's `summarize_annual_losses` takes |

How each rule of crc-sdk's `AGENTS.md` is met:

- **Closed choices are enums**: the five above. Identities (event, year, component, impact, label,
  currency, valuation basis) are exact open strings with no normalisation.
- **Typed measurements**: the intensity is the `Measurement` the impact takes, checked equal to each
  impact's `input`; each impact's `output` must be a `Ratio`; the loss is
  `Measurement(quantity="loss", unit=<currency>)`. `currency` and `valuation_basis` are named as in
  #47's `PolicyColumns`.
- **No I/O in builders**; `write` is the only writer: Parquet, atomic, no overwrite by default, the
  event set, measurements, failures and diagnostics in the file's metadata under a format name
  (`crc-event-loss`) and version (`0.1`), read back equal.
- **Diagnostics and counts** travel through every result as CRC `Diagnostic`s: pairs taken as no
  loss, failures, excluded components, tied events.
- **Every figure of a distribution is CRC's.** The extension adds numbers and does not compute a
  quantile, a CVaR or a mean itself. Year weights decide which constructor:
  `Distribution.empirical` for equal weights, `Distribution.discrete(values, probabilities)` for
  unequal ones. Attribution is the one exception (CRC has none for an empirical distribution): the
  shares are computed here and checked to sum to CRC's CVaR.

Three behaviours of CRC 1.1.0 shape the table:

- `Impact.evaluate` refuses the **whole array** when one value lies outside a tabulated domain
  (`ImpactError` `out_of_domain`, observed 2026-11-27). The table evaluates each impact's values
  together and, on a refusal, value by value, so that the refused rows become `Failure`s and the
  others keep their ratios.
- `compute_risk` sums independent two-state outcomes exactly (default limit 2^20 branches). It is
  the exact independence bracket when every component has at most two annual loss values, and
  only then.
- `Distribution.quantile(q)` returns the smallest loss whose cumulative probability reaches q
  (checked on a discrete distribution with ties); CVaR is the mean of the upper tail mass 1 − q,
  with the year at the cutoff taken in part. The attribution follows the same convention.

## 3. Worked example

Four equally likely synthetic years, two components, three events; one damage curve.

```python
import crc_framework as cf
import pyarrow as pa
from crc_event_loss import (AnnualMeasure, EventLossTable, EventSet, Exposure, IndependenceMethod,
                            YearWeights, annual_losses, brackets)

years = YearWeights.equal(["y0", "y1", "y2", "y3"])
events = EventSet.synthetic_years({"e1": "y0", "e2": "y0", "e3": "y2"}, years=years,
                                  description="four synthetic years, made up")
depth = cf.DepthAboveGround(unit=cf.LengthUnit.METRE)
curve = cf.Impact.tabulated([(0, 0), (1, 0.5), (3, 1)], input=depth, output=cf.Ratio())
hits = pa.table({"event_id": ["e1", "e1", "e2", "e3"], "component_id": ["a", "b", "a", "b"],
                 "value": [1.0, 1.0, 0.5, 3.0]})
table = EventLossTable.from_intensities(
    events, hits, intensity=depth, impacts={"curve": curve},
    exposures=(Exposure("a", 100.0, "curve"), Exposure("b", 200.0, "curve")),
    currency="USD", valuation_basis="replacement cost", label="example")
annual = annual_losses(table, measure=AnnualMeasure.AGGREGATE)
# annual.totals == [175, 0, 200, 0]; components a == [75, 0, 0, 0], b == [100, 0, 200, 0]
law = annual.distribution()                     # a CRC Distribution
(level,) = annual.risk([0.75])                  # VaR 175, CVaR 200 (both from CRC)
# CVaR shares: a 0, b 200 (the tail is year y2); VaR shares: a 75, b 100 (year y0)
(bracket,) = brackets(annual, levels=[0.75], independence=IndependenceMethod.RESAMPLED,
                      samples=100_000, seed=1)
# full dependence: VaR 0 + 100 = 100, CVaR 75 + 200 = 275
```

The numbers in the comments are worked by hand and will be the first unit test. Year y0 has two
events (e1 and e2); its occurrence loss would be 150 (e1), its aggregate 175.

The last line shows a property the brackets do not have. Under full dependence, CVaR is the sum of
the components' CVaRs, and no other dependence gives a larger CVaR, so 200 ≤ 275 as it must be.
VaR has no such bound: here the events give a VaR of 175, above the 100 of full dependence, because
a's loss and b's moderate loss fall in the same year. The "brackets" bound CVaR from above; for
VaR they are two reference points, and the events' VaR may lie outside them.

## 4. Left out, on purpose

- **Policy terms and reinsurance**: deductibles, limits, shares, layers. Pull request #27 defines
  `PolicyTerms`; the extension's losses are ground-up and can be passed through those terms once
  they are released.
- **Damage variability within an event.** Each event gives one damage ratio per component, the
  impact's value. #27 draws a severity with a coefficient of variation (`damage_cv`); an
  event-based version would need a stated distribution per ratio and is left for later.
- **The aggregate annual loss of an annual-rate set.** The largest event of a year is exact for
  independent Poisson events (`occurrence_distribution`); the sum of a year's events needs a
  compound-Poisson calculation or a simulation, which this version does not choose.
- **Anything about a particular hazard, place or asset type.** A test checks that no such word,
  and no path into this repository, appears in the package.
- **Fitting.** No dependence parameter, curve or rate is estimated here.

## 5. How it relates to pull requests #27 and #47

Both are open. #27 adds to crc-framework an annual-loss simulator for primary policies
(`simulate_annual_losses`, `simulate_separate_peril_losses`), a summary of annual losses
(`summarize_annual_losses`, giving `AnnualLossSummary`: average annual loss, VaR and CVaR with
boundary-year weighting, aggregate exceedance points, diversification, contributions per
component), `PolicyTerms`, `InsuredInterest`, `AnnualLossSpec` and `PerilDependence`. #47 adds to
crc-sdk a lazy recipe (`LossRun`, with `PolicyColumns`) that resolves an evaluation's damage curves
and runs #27's simulator, with a result (`LossResult`: `totals`, `components`) and an annual-loss
artifact format.

In #27 each location draws one severity a year from its damage curve, and locations are tied by a
Gaussian copula whose correlation decays with great-circle distance (reference: peak 0.4, decay
length 150 km). There is no event: dependence is a stated model. The extension is the other
route, for when a hazard model gives events: dependence is read off the events.

| Concern | #27 / #47 | crc_event_loss |
| --- | --- | --- |
| Where annual losses come from | Simulated per location from a damage curve, copula by distance | Summed from an event-loss table |
| Annual losses per component | `AnnualLossSimulation.components`, `LossResult.components` | `AnnualLosses.components` (same name, same alignment to years) |
| Summary figures | `summarize_annual_losses` (own VaR, CVaR, AEP) | CRC 1.1.0's `Distribution`; attribution as `RiskAttribution` |
| Year weights | None: every trial has equal mass | `YearWeights`, for stratified catalogues |
| Policy terms | `PolicyTerms` | None (ground-up) |

Names were chosen so that nothing in the extension repeats under another name what the pull
requests define: no `Summary`, `Simulation`, `PolicyTerms`, `Interest` or `LossRun`. The one
overlap is attribution, which #27's summary also does; it is here because #27 is not released.
When #27 is released: `summary_inputs(annual)` passes the extension's years to
`summarize_annual_losses` directly (equal weights only), the attribution moves onto it, and a change
proposal follows (FR11). A comparison worth showing then: the same assets' annual losses from a
storm catalogue against #27's dependence by distance.

## 6. Open questions

1. **Weighted years upstream.** #27's summary treats every trial as equally likely. A catalogue
   sampled by stratum (as in the study that motivates this, where 150 of 1,000 synthetic years are
   run) has unequal weights. Should the summary take weights, or should such catalogues be
   expanded to equal-weight trials before summarising? The extension refuses the expansion rather
   than doing it silently.
2. **Independence bracket.** `EXACT_TWO_STATE` uses `compute_risk` and is exact but applies only to
   components with at most two annual loss values. `RESAMPLED` draws each component's year
   independently, with a stated seed and sample count; its figures come from CRC on the resampled
   totals, and carry sampling error. Is there a preferred exact route for many-state components
   (for example a convolution on a stated grid)?
3. **What the brackets promise.** They bound CVaR (full dependence from above); they do not bound
   VaR (section 3). The study's plan has a pass rule that the events' 1-in-100 loss lies between
   the brackets; that rule can fail without any error. A change proposal (CH-28) puts the rule on
   CVaR and reports VaR against the brackets without a verdict.
4. **One curve per table.** FR4 of the study's requirements lists a damage ratio for each curve in
   one table. The interface keeps one impact choice per table, named by `label`, and several
   tables side by side over one event set, so that a table's sums are never mixed across curves.
5. **Occurrence ties.** When two events of a year have equal total loss, the year's occurrence
   components come from the event with the smaller id, and the tie is counted. An alternative is
   to split the components equally between tied events.
6. **Storage.** Parquet with the metadata in the schema, or #47's annual-loss artifact format,
   whose schema (`annual-loss-1.0`) is also unreleased?

## 7. Use in the study

`flood_lab` builds one event set from the F4 catalogue (one storm per synthetic year; the 150 run
years weighted by stratum, each standing for the years of its stratum that were not run, which
`YearWeights.stratified` expresses: a run in a stratum of N years with n runs has mass
N / (n × 1,000)), one event-loss table per damage curve of the
substation envelope and for the buildings, with depths from the runs and impacts from CRC, then
`annual_losses` for occurrence and aggregate (equal here, one storm a year), `risk` and `brackets`.
The flood-specific parts (depths at assets, curve choice, first-floor heights, values) stay in
`flood_lab`.
