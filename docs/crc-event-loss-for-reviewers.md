# crc_event_loss: a guide for reviewers

**What this is.** A small Python package that adds event-based loss aggregation to Climate Risk
Commons (CRC). This page is for a reviewer who does not know the project behind it. It says what
the package does and the conventions it uses, how it was checked, how it compares with CLIMADA,
Oasis LMF and OpenQuake, and where a reviewer's judgement is wanted.

**Status (2026-11-27).** Implemented and tested in the `crc-lab` repository (branch `flood/f6`).
It has not been reviewed by CRC's authors and has not been proposed upstream. It is written against
crc-framework 1.1.0. Licence: as the repository's code, AGPL-3.0-or-later.

**Contents.**
1. The problem
2. What the package does
3. Conventions (the part most worth checking)
4. A worked example
5. How it was checked
6. Comparison with other frameworks
7. What is left out
8. Questions for the reviewer
9. Running it

---

## 1. The problem

CRC (crc-framework, crc-sdk) describes a hazard at one place as a curve (intensity by return
period), a damage function as an `Impact` (intensity → damage ratio), and a loss as a
`Distribution`, from which it reads exceedance, VaR, CVaR and mean. For a **single asset** this is
complete.

For **many assets** the joint loss depends on which assets are hit together. Hazard models that
produce **events** (a stochastic storm catalogue, a set of historical footprints) carry that
information: two buildings on one street are flooded by the same storms; two in different river
basins are not. Once each asset is reduced to its own curve, that information is gone. CRC 1.1.0
has no type for an event set or a loss per event and asset. Its only portfolio sum is
`compute_risk`, which assumes independent two-state outcomes.

An open pull request to crc-framework-rs (#27) takes another route. It simulates annual losses per
location and ties locations together with a Gaussian copula whose correlation decays with distance.
`crc_event_loss` is the route for when a hazard model already gives events. Dependence is read off
the events, and nothing is assumed or fitted.

## 2. What the package does

Three steps:

1. **Event set** (`EventSet`). The events, placed in time in one of two ways:
   - each event in a synthetic year, where years carry probability weights (`YearWeights`; equal,
     or by stratum when only some years of each stratum were simulated); or
   - each event with an annual rate (independent Poisson occurrence).
2. **Event-loss table** (`EventLossTable`). Loss per event and component (asset). It is built from
   intensities through a CRC `Impact` times each component's value, or given directly. Values the
   impact refuses (outside its domain) are kept as `Failure` rows with CRC's error code, never
   dropped and never counted as zero.
3. **Sums** (`annual_losses`). Within each event across components, then within each year across
   events. Each year gets either the **sum** of its events (`AGGREGATE`, the industry's AEP basis)
   or its **largest** event (`OCCURRENCE`, the OEP basis). The result (`AnnualLosses`) holds
   annual losses for the portfolio and for each component, aligned by year.

From the annual losses:
- the portfolio distribution, as a CRC `Distribution`;
- VaR and CVaR at chosen levels, each with every component's share;
- two reference figures, **brackets**: the same components' losses added as if fully dependent
  (comonotonic), and as if independent.

Public names: `EventSet`, `Timeline`, `YearWeights`, `EventLossTable`, `Exposure`, `Failure`,
`FailurePolicy`, `MissingIntensity`, `AnnualMeasure`, `AnnualLosses`, `annual_losses`,
`occurrence_distribution`, `IndependenceMethod`, `Bracket`, `brackets`, `summary_inputs`. Closed
choices are enums, and identities are open strings, as crc-sdk's conventions require. The package
imports only crc_framework, numpy and pyarrow, and a test checks that nothing in it names a hazard,
place or asset type.

## 3. Conventions

These are the places where a reasonable implementation could differ. Each is stated precisely.

| Topic | Convention |
|---|---|
| Who computes the risk figures | CRC. The package only adds losses and builds `Distribution.empirical` (equal year weights) or `Distribution.discrete(values, weights)` (unequal). VaR is `quantile(q)`, CVaR is `statistics(metrics=[Statistic.CVAR], level=q)`. |
| VaR | CRC's **lower quantile**: the smallest loss whose cumulative probability reaches q. No interpolation between years. |
| CVaR | The mean of the upper tail of mass 1 − q. When the cutoff falls inside a year's mass, that year is counted in part. |
| Years without an event | Part of the set, with loss 0 and their full mass. |
| Year weights | Positive, summing to 1 within 1e-12. A stratum of N years with n simulated has mass N / (n × total years) per simulated year. |
| Levels beyond the catalogue | A level whose tail mass 1 − q is smaller than the smallest year's mass is **refused**, with an error naming the highest level supported. The relative slack is 1e-9, so q = 0.9 with ten years is admitted. |
| Attribution | **Euler allocation** (Tasche, arXiv:0708.2542). A component's CVaR share is its weighted mean loss over the tail years, with the boundary year counted in the same part as for CVaR. Shares are checked to sum to CRC's CVaR within 1e-9 relative. A component's VaR share is its mean loss in the years whose total equals VaR. |
| Occurrence and ties | The year's largest event is the one with the largest total. A tie is broken by event id and counted in the diagnostics. Components take their loss in that event, so they still sum to the total. |
| Annual rates | `occurrence_distribution`: P(largest ≤ x) = exp(−Σ rates of events with loss > x), exact for independent Poisson events. The aggregate annual loss of a rate set is not provided (see §7). |
| Missing intensities | An (event, component) pair absent from the input means no loss (counted), or is an error, by explicit choice. |
| Refused intensities | Never clamped to the curve's end. A refused value becomes a `Failure`. Aggregation then either refuses or excludes the failing components, by explicit choice, and names them. |
| Full-dependence bracket | VaR and CVaR at q are each the **sum** of the components' own VaR and CVaR at q, read from CRC. |
| Independence bracket | Exact via CRC's `compute_risk` when every component has at most two annual values. Otherwise, years resampled independently per component, with a stated seed and sample count. |
| Storage | Parquet, written atomically, with no overwrite by default. The event set, measurements, failures and diagnostics are stored in the file metadata (format `crc-event-loss`, version 0.1), and the file reads back equal. |

**What the brackets promise.** Full dependence gives the largest possible **CVaR** for given
component distributions, so the event-based CVaR must lie at or below it. A CVaR above it is a
defect. **VaR has no such bound.** The event-based VaR can exceed the full-dependence VaR (the
example in §4 does), and independence is not a lower bound for either measure. The package reports
VaR against both brackets without judging it.

## 4. A worked example

Four equally likely years, two components (a, value 100; b, value 200), three events, and one
damage curve through (0, 0), (1, 0.5), (3, 1):

| Event | Year | Depth at a | Depth at b | Loss a | Loss b |
|---|---|---|---|---|---|
| e1 | y0 | 1.0 | 1.0 | 50 | 100 |
| e2 | y0 | 0.5 | — | 25 | 0 |
| e3 | y2 | — | 3.0 | 0 | 200 |

Annual losses:

| Measure | y0 | y1 | y2 | y3 |
|---|---|---|---|---|
| Aggregate total | 175 | 0 | 200 | 0 |
| Aggregate a | 75 | 0 | 0 | 0 |
| Aggregate b | 100 | 0 | 200 | 0 |
| Occurrence total | 150 | 0 | 200 | 0 |

At q = 0.75 (aggregate):

| Figure | Value |
|---|---|
| VaR | 175 |
| CVaR | 200 (the tail of mass 0.25 is year y2) |
| CVaR shares | a 0, b 200 |
| VaR shares | a 75, b 100 (year y0) |
| Full dependence: VaR | 0 + 100 = 100 |
| Full dependence: CVaR | 75 + 200 = 275 |

These numbers were worked by hand before the code was written. The test reproduces them exactly
from CRC. The example shows the event-based VaR (175) above the full-dependence VaR (100), while
the event-based CVaR (200) stays below the full-dependence CVaR (275).

## 5. How it was checked

- **Hand-worked tests** (`tests/event_loss/`, 19 tests, under 2 s):
  - the example above;
  - a stratified-weights example;
  - occurrence against aggregate, with ties;
  - refused intensities and both failure policies;
  - the refusal of levels beyond the catalogue;
  - a Parquet round trip and no-overwrite;
  - the Poisson occurrence formula;
  - the exact independence bracket against the resampled one;
  - shares summing to CVaR.
- **Independent implementation.** The same year-loss tables are passed to Oasis LMF's own
  exceedance-table code (oasislmf 2.5.10, BSD-3; `write_ept`, `write_ept_weighted`), and the AEP,
  OEP and TVaR are compared (12 more tests, run only with Oasis installed). They agree on:
  - the ranked losses and the return period of each rank (1 / cumulative weight);
  - CRC's VaR lying inside each rank's interval of levels.

  They differ in three known, explained ways:
  1. Oasis interpolates linearly between ranks, and CRC does not.
  2. At a level that falls exactly on a rank, they take different ends of the flat part of the
     curve (question 1 in §8).
  3. Oasis's TVaR ignores period weights, even in its weighted routine (question 3 in §8).
- **Not done:** no comparison against a commercial catastrophe model. There is no run on a real
  portfolio yet (the flood study that motivates the package is the first one).

## 6. Comparison with other frameworks

Read at CLIMADA 6.2.0, Oasis LMF (commit 66d4d55e, 2026-11-26) and OpenQuake 3.27.0. Full notes,
with file and line citations: `docs/research/event-loss-prior-art.md`.

| | CLIMADA | Oasis LMF | OpenQuake | crc_event_loss |
|---|---|---|---|---|
| Timeline | rate per event | periods, optional weights | implicit rate 1/effective time | weighted years or rates |
| Year sum / largest event | sum only (per-event curve) | both (AEP, OEP) | both | both |
| Return-period loss | interpolated (log-log) | interpolated (linear) | interpolated (log) | CRC lower quantile |
| Beyond the catalogue | — | dropped | NaN | refused |
| Tail mean | — | TCE (unweighted) | — | CRC CVaR (weighted) |
| Tail attribution | — | — | — | Euler shares |
| Dependence | shared events | shared events plus correlated damage sampling | shared events plus 0/1 asset correlation | shared events |
| Full dependence / independence brackets | — | — | — | yes |
| Intensity above the curve | clamped | pre-binned | clipped | refused (failure) |
| Licence | GPL-3.0 | BSD-3 | AGPL-3.0 | AGPL-3.0 |

The design follows the common practice where one exists:
- sum within the event, then the year, then rank;
- AEP and OEP as two named measures;
- year weights, as in Oasis;
- refusing levels beyond the catalogue, as in OpenQuake.

Two things in the package have no counterpart in the three frameworks: the Euler attribution and
the brackets. The package is also stricter than all three about intensities outside a curve.

## 7. What is left out, on purpose

- Policy terms and reinsurance (deductibles, limits, layers). Losses are ground-up. Pull request #27
  defines policy terms, and losses could be passed through them once that is released.
- Damage variability within an event. Each event gives one damage ratio per component (the
  impact's mean). Oasis and OpenQuake sample it.
- The aggregate annual loss of an annual-rate event set. It needs a compound-Poisson calculation
  or a simulation, and neither is chosen yet. CLIMADA simulates and then silently rescales every
  year so the mean matches. If this is added, any such correction will be reported, not applied
  silently.
- Fitting of any kind: no dependence parameter, curve or rate is estimated.

## 8. Questions for the reviewer

1. **Which loss is "1 in T"?** At q = 1 − 1/T, CRC's lower quantile is the next loss down from the
   one catastrophe tools report whenever 1/T is a whole number of years' mass. With 1,000 equal
   years, CRC's 1-in-100 is the 11th largest annual loss; Oasis and OpenQuake (return period of
   the k-th largest = years / k) give the 10th. Both are valid quantiles at an atom. The package
   reports CRC's. Should a "return-period loss" in the industry's convention also be offered, and
   should it come from CRC (an upper quantile) rather than from this package? Our current choice:
   report CRC's figure and show the tools' figure beside it, labelled.
2. **Weighted years upstream.** Pull request #27's annual-loss summary treats every trial as
   equally likely. Should it accept year weights, as Oasis does, or should weighted catalogues be
   expanded to equal-weight trials first? The package refuses the silent expansion.
3. **Oasis's weighted TVaR.** In oasislmf 2.5.10, `write_ept_weighted` weights the return periods
   but not the running mean behind TVaR. Is that intended? This concerns Oasis, not CRC.
4. **Independence for many-state components.** The exact route covers only two-state components;
   otherwise the bracket is resampled and has sampling error. Is there a preferred exact method,
   such as a convolution on a stated grid?
5. **Strictness at the curve's ends.** Refusing an intensity above a curve's last point is safer
   but unusual; the three frameworks clamp or clip it. Is a stated clamp option wanted?
6. **Storage.** Parquet with metadata, or the annual-loss artifact format of crc-sdk pull request
   #47 (`annual-loss-1.0`, unreleased)? An export in Oasis's Open Results Data layout is possible
   later.

## 9. Running it

```sh
uv sync                                   # crc-framework 1.1.0 and the rest, pinned
uv run pytest -q tests/event_loss         # the package's tests
just event-loss-crosscheck                # the same, plus the Oasis LMF comparison (oasislmf 2.5.10)
```

Code: `src/crc_event_loss/` (`_events.py`, `_table.py`, `_aggregate.py`, `_format.py`). The
engineering design note, with the types and their relation to pull requests #27 and #47:
`docs/flood/event-loss-extension.md`.
