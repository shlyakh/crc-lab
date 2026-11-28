# F6 (part). Curves, the event-loss table and risk

Date: 2026-11-28 · branch `flood/f6b` · plan F6 steps 3, 4, 5 and 7 and the visual test · requirements
FR1–FR8, FH7, §15 · record `site/flood/tests/records/f6.json` · figures `docs/flood/figures/f6/`

Every figure rests on **N = 150 catalogue storms** (one storm per synthetic year, M = 1,000 years) and says
so. Money is 2026 USD (V-2). Tags: **[S]** source, **[I]** computed here, **[P]** placeholder or our
choice. Every figure below is **[I]**, computed from inputs whose own tags are in the asset table
(building values NSI **[S]** or Hazus substitutes A-8; substation values **[P]**).

## What was built

- `src/flood_lab/risk/event_loss.py` — the event set and the event-loss tables (FR4). One event per
  catalogue run, event id = year id = run label, year mass = the F4 block weight / 1,000. The runs are the
  150 of `f4/selection.json` (CH-26, `f4/frequency_cover/per_run/`); the folder holds 162 files, the other
  12 being the design storms `ds_{1,3}h_{2,5,10,25,100,500}y`, which are not read. Weights sum to 1,000
  (30 × 1 + 60 × 2 + 59 × 14 + 1 × 24). Wall depths are joined to assets by `doitt_id` (F1's
  `buildings_detail.csv`); their order was checked against the footprint key stored in every per-run file
  (the key F4 wrote from `f3_model.study_footprints`); units metres above ground (`at_assets`).
  Buildings: one table, Hazus curve read at `building_depth.curve_depth` (BD-1..BD-5), ratio from CRC's
  `Impact.evaluate`. Substations: one table per family (C-3), the site's curve by C-5 (role), read at the
  lead depth.
- `src/flood_lab/risk/metrics.py` (`python -m flood_lab.risk.metrics`) — sums by `crc_event_loss`,
  figures from CRC (`Distribution.discrete`: mean, quantile, CVaR, exceedance), the tools' 1 in T beside
  CRC's, bootstrap (FR8), brackets (FR6), both curve routes of FH7 at the assets, sensitivities.
- `src/flood_lab/checks/f6_risk.py` — figures and the record.
- Step 3 (exporters to CRC): `crc_adapter` already turns every curve of `curves.yaml` into
  `Impact.tabulated`; substation tables run 0–6 m (C-4), building tables −4 to 24 ft. The test against the
  catalogue: deepest lead depth at a substation 0.504 m, deepest wall depth 4.71 m (both below the tables'
  ends); no CRC `out_of_domain` occurred in any table (0 refusals). Nothing new was needed in step 3.
- Outputs, committed under `site/flood/data/f6/` (2.4 MB): `annual_losses.csv` (150 runs × every
  portfolio column), `buildings.csv` (one row per building: cases, failure reason, EAL by the event table
  and both routes, depth and loss at 10/100/500 y), `substations.csv`, `substation_event_losses.csv` (every
  run × site × family), `hand_check_inputs.csv`, `metrics.json`, and `distributions/*.json` (CRC's
  `to_json` of the four main portfolio distributions, FR5). The full event-loss tables (Parquet, the
  extension's format) are in the cache, `data/cache/flood/f6/`, not committed.
- Tests `tests/flood/test_f6_risk.py`: sums by hand on two buildings and three runs, failure reasons,
  weights summing to M and the catalogue files, the tools' rank against CRC's, the CVaR bracket
  inequality, the bootstrap, the building impact against the event-table rule, and a reconciliation of the
  committed outputs.
- `docs/algorithms.md` entries 15–19; `docs/flood/event-loss-extension.md` §7 corrected.

## The dry threshold: a choice made here, for Yuri

Read literally, BD-1 ("a depth of 0 or less means no loss") makes about **10,900 buildings wet in every
run**, the smallest storms included, by wall depths of 1e-6 to 4e-5 m (float32 differences of water level
and ground). A building with a basement then reads its basement curve at −4 ft every year. The main case
therefore sets depths below **0.05 m** (`catalogue.WET_M`, the wet rule of the F4 frequency, so also of
CRC's curves at the assets) to 0 before BD-1 **[P]**. The literal reading is a sensitivity: portfolio EAL
$1,240.9 M instead of $88.9 M. This is a reading of D-1/BD-1 that Yuri has not decided (question 1).

## Main figures (portfolio = 16,827 buildings + 4 valued substations, mid value)

The four substation families change the portfolio by at most 1.3%: substations are 4 of 16,831 assets.

| Substations on | EAL | 1 in 100, CRC VaR | 1 in 100, tools | CVaR 99% | 1 in 500, CRC / tools | 1 in 10, CRC VaR / CVaR |
|---|---|---|---|---|---|---|
| Nirandjan F2 (low) | $88.90 M | $2,299.7 M | $2,379.0 M | $3,076.3 M | $3,213.8 M / $3,771.0 M | $31.4 M / $885.1 M |
| Williams max (high) | $90.05 M | $2,322.6 M | $2,399.9 M | $3,118.8 M | $3,260.2 M / $3,825.2 M | $31.4 M / $896.5 M |
| Williams min | $89.31 M | $2,307.8 M | $2,386.4 M | $3,091.5 M | $3,230.4 M / $3,790.4 M | $31.4 M / $889.2 M |
| Bor 2026 | $88.81 M | $2,297.4 M | $2,376.9 M | $3,074.1 M | $3,211.5 M / $3,769.3 M | $31.4 M / $884.2 M |

Buildings alone: EAL $88.78 M on $57.6 billion of value in the sums.

- **Occurrence = aggregate.** One storm per synthetic year: the extension's two sums are equal year by
  year (checked).
- **1 in T.** CRC's VaR at q = 1 − 1/T (lower quantile) and the tools' convention (largest loss with
  P(L ≥ x) ≥ 1/T, Oasis/OpenQuake/RainyDay, and the convention of the F4 depth frequency) are both shown
  (design-note question 7). At 1 in 100 they differ by 3%, at 1 in 500 by 17%: in T1 each run is its own
  year, so they are neighbouring runs.
- **Highest return period (P-2).** Smallest year mass 1/1,000 (T1): up to 1,000 years supported.
- **Bootstrap (FR8)**, 1,000 resamples within strata, seed 20261128, 5–95% (Nirandjan; the others within
  1%): EAL $72.6–104.9 M; 1-in-100 CRC VaR $1,999–2,939 M; tools $2,132–2,976 M; CVaR 99%
  $2,651–3,409 M.
- **Per substation EAL** (event table = point route; mid value **[P]**): Farragut $18.5k (Bor) –
  $846.7k (Williams max); Hudson Avenue $10.4k–$234.4k; Plymouth $0.1k–$185.1k; Water Street $0–$4.8k. The
  envelope spans a factor of about 10 (Nirandjan to Williams max) at every site. S-861227475 (no value, no
  curve) and S-1540230931 (removed) are not in the sums.
- **Brackets (FR6)** at 1 in 100 (Nirandjan), independence resampled (20,000 draws, seed 20261128, over the
  5,844 assets with any loss): CVaR 99%: independence $227.6 M, event table $3,076.3 M, full dependence
  $3,153.1 M. VaR 99%: $202.2 M, $2,299.7 M, $2,426.1 M. At 1 in 10 the event table's VaR ($31.4 M) lies
  above full dependence ($0.1 M), as the design note says VaR may (CH-28): no verdict.

## Pass rule, item by item

| Item | Result |
|---|---|
| Hand recomputation of three assets (FR7) | **pass**: `docs/flood/notebooks/F6-hand-recomputation.ipynb` (blind agent, Opus 5.5), 2,568 checks, 0 differences to the cent and 1e-9 relative (see below) |
| Event-table CVaR 99% ≤ full-dependence bracket (CH-28) | **pass**, all four families (e.g. $3,076.3 M ≤ $3,153.1 M) |
| 1-in-100 against both brackets | shown, no verdict (independence < events < full dependence at 1 in 100 for all four families) |
| EAL event table vs CRC curves, point route, within 5% | **pass**: buildings +1.7e-8, substations ≤ 6.7e-8 relative (the same depths; differences from the 1e-9 step width of the knots) |
| EAL event table vs CRC curves, grid route | **outside 5%, explained; verdict Yuri's**. The grid reads a 5 m cell at the asset's point: of 16,827 buildings only 169 have a footprint centroid in a read cell (the others are in roofed cells, which F4 leaves out: CRC `no_covering_support`), and on those the grid gives $0.41 M against $2.66 M from the event table (−85%); 2 of 4 substation outline centroids fall in a read cell, both dry at every probability, against the lead depth (the depth exceeded on 25 m² of the site's open ground), so the grid route gives 0. The grid route measures a different depth (a cell centre, not the wall or the lead depth), at eight probabilities with linear interpolation, and is not a loss route (FH7: loss figures use the point route) |
| Every failure row accounted for | **pass**: CRC refused no value (0 failure rows in every table); 488 buildings left out, each named with its reason in `buildings.csv` |

The record's overall verdict is "not judged" (`passed: null`) because two items wait: the hand
recomputation and Yuri's verdict on the grid route's explanation.

## Failures (buildings left out of every sum, never counted as zero)

| Reason | Buildings |
|---|---|
| no structure curve (A-12) and wet in some run | 421 |
| wall band has no readable pixel (F4's `buildings_not_read`) | 53 |
| no footprint in the hazard's set (F3/F4 select footprints by representative point, F1 by centroid) | 7 |
| BD rule failed when wet (all 7 are BD-5, no first-floor height) | 7 |
| **Total** | **488**, value $2.43 billion |

Of 2,661,600 (run, building) pairs: 238,833 read, 2,405,710 no loss, 17,057 failed. 93,384 of the reads
are a basement read at −4 ft (BD-3). 13 footprints of the hazard's set are no asset (million BINs and
duplicates F1 dropped).

## Sensitivities (Nirandjan family; the others move alike)

| Run | EAL | 1 in 100 CRC VaR | CVaR 99% |
|---|---|---|---|
| Main | $88.90 M | $2,299.7 M | $3,076.3 M |
| Value low (low where stated, else mid: 355 RES1 substitutes and the substations) | $88.79 M | $2,297.3 M | $3,072.1 M |
| Value high (same rule) | $89.60 M | $2,314.3 M | $3,102.5 M |
| Substation families | $88.81–90.05 M | $2,297.4–2,322.6 M | $3,074.1–3,118.8 M |
| C-5 basis `hazus_kv` (Williams max) | $90.05 M (substations $1.2701 M vs $1.2710 M) | $2,322.5 M | $3,119.2 M |
| FF-4 alternative first-floor heights | $95.86 M | $2,464.0 M | $3,254.6 M |
| Without `lot_shared_with_nsi` (1,180 dropped) | $87.63 M | $2,263.8 M | $3,027.8 M |
| Without substitute values (5,416 dropped) | $71.57 M | $1,881.1 M | $2,546.1 M |
| Dry threshold 0 (BD-1 literal) | $1,240.86 M | $2,750.9 M | $3,440.6 M |

Value high moves Williams max to $96.8 M (substation high values are $403–628 M, placeholders).

## Hand recomputation (FR7)

Done 2026-11-28 by an agent that did not see the code: the notebook
`docs/flood/notebooks/F6-hand-recomputation.ipynb` recomputes the three assets from the per-run depths,
`exposures.csv`, `curves.yaml` and the rules: 2,568 checks, 0 differences. Two notes from it: (1) the
per-asset `loss_*y_point` columns are in the tools' convention (above); (2) `eal_point` differs from
Σw·L/1000 by up to 4.5e-8 relative, CRC's expectation on the step knots. It also notes that no rule in
`loss-rules.md` states the 0.05 m dry cut (question 1) or that the 138 kV sites take Bor's HV >345 kV
row (C-3 says only "Bor 2026"). Three assets (`metrics.json` → `hand_check`):

- **Substation** S-383102724 (Hudson Avenue, the deepest lead depth of the valued sites, 0.504 m),
  all four families.
- **Ordinary building**: B-3000013 (NSI value $1,001,436, no substitute of any kind, curve hazus_struct_204, first floor 0.16 m, no basement, read in 3 runs, EAL $390.32).
- **Substitute value with a −4 ft basement read**: B-3000650 (Hazus substitute value $557,217 (A-8), curve hazus_struct_110, first floor 3.844 m, basement Y, read in 17 runs, some at −4 ft, EAL $300.90).

Inputs: `data/cache/flood/f4/selection.json` (label, rank, stratum, weight), the per-run files
`data/cache/flood/f4/frequency_cover/per_run/cat_r*.npz` (`site_lead` in `site_ids` order; `walls` in the
order of `f3_model.study_footprints`, joined by `doitt_id` through `data/cache/flood/assets/buildings_detail.csv`;
the raw depths are copied in `site/flood/data/f6/hand_check_inputs.csv`), `site/flood/data/exposures.csv`
(`ffh_m`, `basement`, `curve_id`, `value_mid_usd_2026`), `src/flood_lab/curves/curves.yaml` (points),
`docs/flood/loss-rules.md` (BD rules) and the dry threshold 0.05 m. Outputs to match to the cent:

- `site/flood/data/f6/substation_event_losses.csv`: `depth_used_m`, `damage_ratio`, `loss_usd_2026` per
  run and family for the substation;
- `site/flood/data/f6/substations.csv`: `eal_event_table`, `eal_point`, `loss_{10,100,500}y_point`,
  `depth_{10,100,500}y_point` (depth at T read on the point route's step curve; at a level that falls
  exactly on a year, the step knots of CH-23 give the upper end of the flat part, i.e. the tools'
  convention, return period of the k-th largest = 1,000 / cumulative weight; found by the hand
  recomputation; no per-asset figure in CRC's lower-quantile convention is written);
- `site/flood/data/f6/buildings.csv`: `runs_read`, `runs_no_loss`, `runs_failed`, `eal_event_table`,
  `eal_point`, `depth_*y_point`, `loss_*y_point` for the two buildings;
- `site/flood/data/f6/annual_losses.csv`: `main__buildings` and `main__low` (with `mass`) for the
  portfolio EAL $88,902,633 (`metrics.json` `results.main.families.low.eal`).

## Changes to the design note

`docs/flood/event-loss-extension.md` §7: the year weights are the catalogue's block weights given
directly to `YearWeights` (stratum T3's last block stands for 24 years, the others 14), not
`YearWeights.stratified`; the portfolio adds the buildings' and a family's `AnnualLosses` through the
public constructor (the interface has no `combine`, a candidate addition); the building rules' failures are
kept outside the extension; brackets leave out all-zero components. The extension's interface was not
changed.

## Questions for Yuri

1. **The dry threshold.** Main case: depth below 0.05 m (the F4 wet rule) counts as 0 before BD-1. Accept,
   or another value (a rule BD-0)? Literal BD-1 multiplies the EAL by 14.
2. **The −4 ft basement read.** 93,384 of 238,833 reads (39%) are a basement read at −4 ft (BD-3): water
   at the wall, not at the floor, pays the basement curve's value at −4 ft. Keep?
3. **Grid route**: accept the explanation (a different depth at a different point), or should the grid
   be evaluated at a point in each building's wall band?
4. **Which 1 in T leads** on the page: CRC's (as the extension reports) or the tools' (as the F4 depth
   frequency and Oasis/OpenQuake)?
5. **A-12's 421 buildings** with no curve that get wet ($2.16 billion of value): a substitute basement
   would bring them in.
6. The bootstrap interval on the 1-in-100 loss is wide ($2.0–2.9 billion): the tail rests on the 30 runs
   of T1.

## Recipe lines (for the justfile; not edited here)

```
# Flood lab F6: event-loss tables, risk figures, curve routes (writes site/flood/data/f6/)
flood-f6:
    uv run --extra flood python -m flood_lab.risk.metrics
    uv run --extra flood --with matplotlib python -m flood_lab.checks.f6_risk
    uv run python -m flood_lab.gallery
```

## Run time

`flood_lab.risk.metrics` 233 s (grid route 120 s, brackets 4 × 21 s); `checks.f6_risk` about 30 s.
