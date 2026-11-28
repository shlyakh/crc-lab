# Algorithms used in crc-lab

Written 2026-11-11. One entry per algorithm: what it is for, the rule or formula, what it averages over, its
parameters, its main weakness, and where the code is. [hail-data-processing.md](hail-data-processing.md)
follows the data from source to result; this page explains the calculations themselves.
[decisions.md](decisions.md) charts the choices; reports under [reports/](reports/) hold the numbers.

Parameters marked **placeholder** have no source. Parameters marked **chosen** were picked here from a
sensitivity run or by Yuri.

| # | Algorithm | Used for |
| --- | --- | --- |
| 1 | Annual maxima and neighbour pooling | Hail and gust curves per cell |
| 2 | Curve fit with a point mass at zero | The same curves, in CRC's format |
| 3 | Report circle (nearest-N density) | Hail rate and size mix at a plant |
| 4 | Clipping to the reporting region | Circles at the border and the coast |
| 5 | Footprint, hit area and covered share | From a rate per km² to events at a plant |
| 6 | Reporting-rate model | Correcting reports for where people are |
| 7 | Bias correction per cell | Corrected rate at a plant, local |
| 8 | Bias correction per region | Corrected rate at a plant, smooth |
| 9 | Radar hail days and the 25 km mean | Radar figures at a plant and per cell |
| 10 | Radar swath areas | Checking the footprint |
| 11 | Damage curves | Hail size to share of value lost |
| 12 | Annual loss: events added, capped | Expected loss and its distribution |
| 13 | Class breaks | Map colours and legends |
| 15 | Flood event-loss table | Loss per storm and asset (flood lab F6) |
| 16 | Flood annual losses and their figures | Expected annual loss, VaR, CVaR, 1 in T |
| 17 | Flood bootstrap within strata | Sampling intervals on the flood figures |
| 18 | Flood dependence brackets | Full dependence and independence beside the events |
| 19 | Flood curve routes at an asset | Expected damage and loss at T from CRC's curves |

## 1. Annual maxima and neighbour pooling

**For:** a stable sample of "largest hail of the year" for each H3 resolution-5 cell (about 253 km²).

**Rule.** For each cell and each year 1996–2025, take the largest reported hail size among reports touching
the cell, or zero if there was none. A cell's sample is then its own 30 values plus the 30 values of each of
its six neighbours: 210 values.

**Averages over:** seven cells, about 35 km across. Years are not averaged; each is one observation.

**Parameters:** one ring of neighbours (chosen; no pooling and two rings were compared in
[reports/3-curves-sensitivity.md](reports/3-curves-sensitivity.md)); first year 1996 (chosen: the first full
year of the modern record).

**Weakness.** 73% of cell-years are zero, mostly because nobody reported, not because no hail fell. Pooling
steadies the estimate but smooths real differences. Neighbouring cells see the same storms, so the 210 values
are not independent.

**Code:** `src/crc_lab/curves/annual_maxima.py`, `fit.py` (`pooled_samples`).

## 2. Curve fit with a point mass at zero

**For:** a hazard curve per cell in CRC's canonical format, so `for_assets` can read a 1-in-N-year hail size.

**Rule.** The pooled sample is passed to crc-sdk (`HazardDataset.from_table` with a curve-fit policy). The
share of zero years becomes a point mass at zero; the positive values are fitted with a Gumbel distribution
bounded below at zero. Where the fit is refused the SDK keeps a tabulated curve.

    P(annual maximum ≤ x) = p0 + (1 − p0) × Gumbel(x)        for x > 0,   p0 = share of hail-free years

**Parameters:** Gumbel family (chosen; a three-parameter alternative was compared); horizon 2025, pathway
`observed`.

**Weakness.** The curve describes reports in a cell and its neighbours, not hail at a point.

**Code:** `src/crc_lab/curves/fit.py`; the fitting itself is crc-sdk's.

## 3. Report circle (nearest-N density)

**For:** the local hail report rate and the local mix of hail sizes at a plant.

**Rule.** Grow a circle around the plant until it holds N located hail reports, but never smaller than a
minimum radius or larger than a maximum.

    radius = clamp(distance to the N-th nearest report, r_min, r_max)
    rate   = reports inside ÷ (reporting area × years)          reports per km² per year
    sizes  = the sizes of the reports inside

If fewer than N reports lie within r_max the plant is flagged "too few reports".

**Averages over:** the circle and the 30 years. Where reports are dense the circle is small (10 km in towns);
where they are sparse it is wide (up to 75 km).

**Parameters:** N = 100, r_min = 10 km, r_max = 75 km (chosen; varied in
[reports/4-hail-exposure-sensitivity.md](reports/4-hail-exposure-sensitivity.md)).

**Weakness.** The rate follows where people report. Without r_min, a circle in a town shrinks to 2–3 km and
measures population. The method counts reports, not storms: one storm can leave many reports.

**Code:** `src/crc_lab/assets/exposure.py` (`local_reports`, `at_point`).

## 4. Clipping to the reporting region

**For:** plants near Mexico, the Gulf or the edge of the event table, where part of the circle cannot hold
reports.

**Rule.** The reporting region is Texas plus Oklahoma, New Mexico, Arkansas and Louisiana (reports from all
five are used). The circle's area in the rate above is the part of the circle inside that region.

    reporting area = π × radius² × share of the circle inside the region

**Weakness.** Other neighbours are not included. Offshore hail is simply unknown.

**Code:** `exposure.py` (`reporting_region`, `clipped_fraction`).

## 5. Footprint, hit area and covered share

**For:** turning a rate of reports per km² into hail events at a plant.

**Rule.** A report is a point. It is taken to stand for hail of its size over a disc of area A_f, the
footprint. The plant is a disc of its array area A_p. A footprint touches the plant when its centre falls
inside a disc of radius r_f + r_p:

    hit area = π × (r_f + r_p)²                 r_f = √(A_f/π),  r_p = √(A_p/π)
    events touching the plant per year = rate × hit area
    annual chance of hail of size ≥ s = 1 − exp(−rate(≥ s) × hit area)

When a footprint touches the plant it covers only part of it. The covered share is the overlap of the two
discs divided by A_p, with the footprint's centre uniform over the hit area. One identity follows and is
checked in the build for every plant:

    mean covered share × hit area = A_f

so the expected damage per year is rate × A_f × mean damage ratio, whatever the plant's size. A larger plant
is hit more often, but each hit covers a smaller share of it.

**Parameters:** A_f = 25 km² (**placeholder**, chosen by Yuri; radar swaths of 30 mm or more in Texas measure
16 km² at the median and 61 km² at the mean). Plant area from the solar database polygon, or estimated from
capacity where there is none.

**Weakness.** Real hail swaths are long and narrow, not discs. The report's size is assumed over the whole
footprint, while it is the largest stone seen at one point. Loss scales in proportion to A_f.

**Code:** `exposure.py` (`hit_area_km2`); `src/crc_lab/impacts/annual.py` (`covered_shares`).

## 6. Reporting-rate model

**For:** estimating what share of hail days gets reported in each cell.

**Rule.** Texas is divided into the 2,566 resolution-5 cells, grouped into 73 regions (their resolution-3
parents, about 12,000 km²). A hail day is a local calendar day with at least one located report touching the
cell.

    hail days in cell i ~ Poisson(years × true_rate[region of i] × ρ_i)
    ρ_i = floor + (1 − floor) × (1 − exp(−(b_pop × people per km² + b_road × road km per km²)))

Given ρ, the best true rate of a region has a closed form (its hail days ÷ (years × Σ ρ_i)), so only floor,
b_pop and b_road are searched, by maximum likelihood. The fitted values are floor 0.059, b_pop 0.0104,
b_road 1.214; five-fold held-out likelihood prefers this model over population alone or roads alone.

**Identifying assumption.** Inside one region the hail climate is the same in every cell. Any difference
between cells of a region that lines up with people or roads is counted as reporting.

**Weakness.** The floor (the reporting rate of an empty cell, about 6%) carries the largest corrections and
is the least certain number. Counts are more variable than Poisson (dispersion 4.0), so the intervals are too
narrow. Population is a 2020 snapshot; reporting practice changed over 30 years. The model corrects how
often hail is reported, not the reported size.

**Check.** Against five years of radar: at the median plant, radar hail days ÷ report-based rate is 2.7
before correction and 0.9 after.

**Code:** `src/crc_lab/assets/reporting_bias.py`. Report: [reports/5-reporting-bias.md](reports/5-reporting-bias.md).

## 7. Bias correction per cell (local)

**For:** a corrected hail rate at a plant that keeps local detail.

**Rule.** Keep the plant's report circle (algorithm 3). Take the mean of ρ over the cells whose centres lie
inside the circle, and divide the rate by it. Sizes are unchanged.

    corrected rate = rate from the circle ÷ mean ρ of the cells in the circle

**Averages over:** the circle, for both the reports and the reporting rate.

**Weakness.** It multiplies a noisy local rate by a factor that is itself largest where it is least certain:
3.0 at the median plant, up to 13.2. Plants with a factor above 5 are flagged in the explorer.

**Code:** `src/crc_lab/assets/build.py` (`reporting_rates`, `corrected`); `src/crc_lab/impacts/build.py`.

## 8. Bias correction per region (smooth)

**For:** a corrected hail rate that does not depend on how many reports happen to lie near the plant. Tried on
2026-11-11 at Yuri's request; shown beside the per-cell value, which stays the default.

**Rule.** Drop the circle. Use the plant's model region (algorithm 6) and apply the same closed form to
reports instead of hail days:

    corrected rate = reports in the region ÷ (years × Σ over its cells of ρ_i × cell area_i)
    sizes          = the sizes of all reports in the region

Every plant in a region gets the same rate and size mix. Plants then differ only by glass type, mounting and
area.

**Averages over:** about 12,000 km² (roughly 110 km across) and 30 years.

**Result.** Portfolio loss is close to the per-cell value ($312 million against $322 million a year), but
single plants move: the regional ÷ per-cell ratio runs from 0.56 to 2.05 between the 10th and 90th
percentile. The ranking of plants agrees at 0.86 (Spearman). The largest movers are small plants in or near
towns, pulled toward their region's value. See the section in
[reports/5-hail-impact.md](reports/5-hail-impact.md).

**Weakness.** It assumes one hail climate over 110 km and erases real gradients inside a region. Regions at
the state border hold only their Texas cells, and reports from neighbouring states are not used here. ρ was
fitted on hail days and is applied to report counts.

**Code:** `src/crc_lab/assets/regional.py`; `src/crc_lab/impacts/build.py`.

## 9. Radar hail days and the 25 km mean

**For:** a hail record that does not depend on people.

**Rule.** The source is one grid per day: the 24-hour maximum of radar-estimated hail size (MRMS MESH),
about 1 km cells, from 15 October 2020. A grid cell has a hail day when the value reaches the threshold.

- **Over a plant:** days on which the maximum over the grid cells within the plant's array radius reaches the
  threshold.
- **25 km mean:** hail-day counts of all grid cells within 25 km of the plant, averaged, divided by the years
  of record. This is the figure used to compare with reports.
- **Per H3 cell:** for the four-source comparison, hail days in the resolution-5 cell.

**Parameters:** threshold 30 mm, with 50 mm beside it (chosen; confirmed 2026-11-11). Averaging radius 25 km
(chosen: five years is too short for a single 1 km cell).

**Weakness.** Radar hail size is an estimate built to exceed most observed stones. Five years is short: 90 of
250 plants have no radar hail day over them. A second radar record, hail signatures from 1995, is kept as a
separate source and is not merged, because one storm is seen by several radars on many scans.

**Code:** `src/crc_lab/radar/analysis.py`, `build.py` (`smoothed_rate`), `compare_cells.py`.

## 10. Radar swath areas

**For:** measuring how large an area one hail event covers, to check the footprint (algorithm 5).

**Rule.** On each daily grid, connected groups of grid cells at or above the threshold are one swath; its
area is the sum of its cells' areas. Groups of fewer than five cells are dropped as noise.

**Result:** for 30 mm or more in Texas, median 16 km², mean 61 km².

**Weakness.** A daily maximum merges separate storms that cross the same ground on one day.

**Code:** `src/crc_lab/radar/analysis.py`.

## 11. Damage curves

**For:** the share of an asset's value lost to hail of a given size. Specified in
[requirements-hail-impact-v0.md](requirements-hail-impact-v0.md), where every number carries a source tag.

**Solar plant.** Three steps:

    P_break(D)   piecewise linear through laboratory breakage rates, by glass type
    D_eff        = D × (cos stow angle)^(2/3.5)                    a tilted module takes less normal energy
    damage ratio = cost share × [ p_stow × P_break(D_eff) + (1 − p_stow) × P_break(D) ]

**Buildings and cars.** Swiss insurance-claim curves of the form S × v³/(1 + v³) with
v = max(D − threshold, 0)/(half-point − threshold); and a roof curve, roof cost share × lognormal CDF.

**Per-plant rules.** Glass type by the year the plant came online (2.0 mm glass-glass from 2021, 3.2 mm
glass with backsheet before). Trackers use the stow mixture; fixed-tilt plants use their reported tilt all
the time. Thin-film plants have no breakage table and follow the year rule; they are flagged.

**Parameters:** stow angle 60°, p_stow 0.8, module cost share 0.40, roof cost share 0.10 (all
**placeholders**).

**Weakness.** Laboratory breakage is applied to the largest reported stone, which overstates damage to
unstowed modules. The glass rule decides a great deal: all plants on the weaker glass give 13% more loss, all
on the stronger 69% less. There is not enough evidence yet to do better; noted for later.

**Code:** `src/crc_lab/impacts/hail_curves.py`, parameters in `hail_v0.json`.

## 12. Annual loss: events added, capped

**For:** expected loss per year and the loss exceeded once in N years.

**Rule.** Events touching the plant arrive as a Poisson process with rate λ = rate × hit area. Each event's
damage is (damage ratio of a report size drawn from the local or regional size mix) × (a covered share from
algorithm 5). A year's damages are added and the total is capped at 1.

    annual damage ratio = min(1, sum of the year's event damages)
    expected loss       = E[annual damage ratio] × plant value

The distribution is computed exactly on a grid of 4,000 steps by convolution, not by simulation.

**Weakness.** Events are taken as independent, and a plant damaged in spring is assumed fully repaired before
the next storm. The cap matters little at today's rates (it changes the portfolio total by about $0.01
million).

**Code:** `src/crc_lab/impacts/annual.py`.

## 13. Class breaks

**For:** map colours and legends that print exact ranges.

**Rule.** For each measure, take the 20th, 40th, 60th and 80th percentiles of the positive values over all
plants and all three bases together, round each to the nearest of 1, 1.5, 2, 3, 5, 7 times a power of ten,
and drop duplicates. The same breaks are used whichever basis is shown, so switching the bias correction
darkens or lightens plants instead of re-ranking the colours.

**Code:** `src/crc_lab/risk_layer.py` (`class_breaks`).

## 14. Reports near a storm's track (storm player)

**For:** showing, while a tropical cyclone is played, only the storm reports that plausibly belong to it.

**Rule.** A located report is near the track if its point lies inside the storm's 34 kt wind radius: the
largest of the four quadrant radii at the fix nearest in time to the report, measured from the storm centre
interpolated to that time. Where that fix has no 34 kt radii, the report must lie within 120 nautical miles
(222 km) of the track line. Reports with no point (county or zone reports) cannot be tested and are left out,
with their number stated under the timeline. A checkbox shows all Texas reports again.

**Parameters:** 120 nmi is computed from the data when the page loads: the median largest-quadrant 34 kt
radius over the fixes in the tracks file that have one, rounded to 5 nmi.

**Where radii are missing.** At fixes with no 34 kt radii a single dashed circle is drawn from the agency
record: the radius of the outermost closed isobar if present, otherwise the radius of maximum wind. It is
labelled an average radius, not an observed wind extent. Of the 16 storms with no 34 kt radii at all, only one
has an outermost closed isobar; the other 15 have only a radius of maximum wind (10–20 nmi), which is the
storm's inner core, not its outer size.

**Weakness.** "Near" is a screen filter, not attribution: a hail report inside the radius need not be caused
by the storm.

**Code:** `site/shared/views/tracks.js` (`nearDistance`), `time.js`.

## 15. Flood event-loss table

**For:** the loss of every asset in every storm of the flood catalogue (requirements FR4), held in
`crc_event_loss`'s `EventLossTable`.

**Rule.** One event per catalogue run; each run is one synthetic year's largest storm, so event and year
are the same id, with the year's mass = run weight / M (the F4 block weights: 30 runs of 1 year, 60 of 2,
59 of 14 and one of 24, M = 1,000). For each building, the water depth at its walls d (F4, metres above
ground) is first set to 0 when below the dry threshold (0.05 m, the catalogue's wet rule), then read by
rules BD-1 to BD-5 (`docs/flood/loss-rules.md`):

    d ≤ 0                         → no loss                      (BD-1)
    a = d − first-floor height                                   (BD-2)
    a < −4 ft: basement Y → a = −4 ft; N → no loss; unknown → failed   (BD-3)
    a > 24 ft, or no height        → failed                      (BD-4, BD-5)
    damage ratio = CRC Impact.evaluate(Hazus curve, a);  loss = ratio × value

Substations: the lead depth (the depth exceeded on 25 m² of open ground) read on each of the four curve
families (C-3, by role C-5), one table per family. A building with any failed (event, building) case, no
curve while wet, no readable wall band or no footprint in the hazard's set is left out of every sum and
named with its reason; CRC's own refusals (`ImpactError`) are kept as failure rows by the extension.

**Parameters:** dry threshold 0.05 m **placeholder** (the F4 wet rule); value level mid (low and high as
sensitivities, mid where they are not stated).

**Weakness.** One depth per building per storm (the deepest readable pixel by its walls) and one storm per
year (RainyDay's largest 3-hour storm); damage is deterministic given depth. The dry threshold matters: read
literally (0 m), BD-1 makes about 10,900 buildings "wet" in every run by depths under 0.1 mm, and every
basement building then loses its −4 ft basement value every year.

**Code:** `src/flood_lab/risk/event_loss.py`; `src/crc_event_loss/`.

## 16. Flood annual losses and their figures

**For:** the portfolio's expected annual loss (EAL), VaR and CVaR at 1 in 10, 100 and 500 years, and the
exceedance curve (FR5).

**Rule.** The extension adds losses across assets within an event, then across the events of a year
(aggregate) or takes the year's largest event (occurrence); with one storm per year the two are equal and
are checked equal. The 150 annual totals with their masses become `Distribution.discrete` (CRC), which gives
every figure: mean (EAL), `quantile(1 − 1/T)` (VaR, the smallest loss whose cumulative mass reaches q),
CVaR at q (mean of the upper tail of mass 1 − q, the year at the cutoff taken in part), `exceedance`.
Beside CRC's VaR, the tools' 1 in T is shown: the largest loss x with P(L ≥ x) ≥ 1/T (with M equal years
the k-th largest has return period M/k, as Oasis LMF, OpenQuake and RainyDay rank).

**Parameters:** return periods 10, 100, 500 years; the smallest year mass, 1/1,000, bounds the highest
return period the catalogue supports (1,000 years; rule P-2 of the extension refuses levels beyond it).

**Weakness.** 150 runs stand for 1,000 years; the tail above 1 in 30 rests on the 30 runs of stratum T1,
each one year. CRC's and the tools' 1 in T differ by one rank where 1/T is a whole number of year masses.

**Code:** `src/flood_lab/risk/metrics.py` (`figures`, `tools_level`); `crc_event_loss.annual_losses`.

## 17. Flood bootstrap within strata

**For:** sampling intervals on the portfolio EAL and the 1-in-100 figures (FR8).

**Rule.** In each stratum (T1, T2, T3), draw as many runs as it has, with replacement; each drawn run keeps
its block weight, rescaled so the stratum keeps the years it stands for. The resample's annual totals and
masses become a CRC distribution and give EAL, VaR and CVaR at 99%; the interval is the 5% and 95% of the
resamples (CRC's `Distribution.empirical(...).quantile`).

**Parameters:** 1,000 resamples, seed 20261128 (both **placeholders**); interval 5–95%.

**Weakness.** It measures how much the figures depend on which storms were run, not the error of the flood
model, the curves or the values. Within T1 each run is its own year, so the 1-in-100 interval comes from
the 30 largest-rainfall years.

**Code:** `src/flood_lab/risk/metrics.py` (`bootstrap`).

## 18. Flood dependence brackets

**For:** where the event table's portfolio figures sit against two stated dependences (FR6, CH-28).

**Rule.** `crc_event_loss.brackets`: full dependence adds the assets' own VaR and CVaR (each from CRC on the
asset's annual losses); independence draws each asset's year independently by the year masses
(`RESAMPLED`) and reads VaR and CVaR from CRC on the drawn totals. Assets whose loss is 0 in every year are
left out (they add 0 under any dependence). The pass rule: the event table's CVaR at 99% at or below full
dependence, which must hold; VaR is shown without a verdict.

**Parameters:** 20,000 draws, seed 20261128 (**placeholders**).

**Weakness.** The independence bracket carries sampling error; VaR has no bound from either bracket.

**Code:** `src/flood_lab/risk/metrics.py` (`bracket_figures`).

## 19. Flood curve routes at an asset

**For:** expected annual damage, the damage distribution and the loss at 10, 100 and 500 years from CRC's
per-asset depth curves (FR5, FH7), to compare with the event table.

**Rule.** Point route: each asset's catalogue depths as an exact step function (`crc_load.asset_knots`,
F4) through `Dataset.from_quantiles`. Grid route: the F4 rasters at eight probabilities through
`Dataset.from_raster`, evaluated at the asset point (substation outline centroid, building footprint
centroid). The curve is completed with depth 0 at non-exceedance 0 and the last knot held to 1
(`TailCompletion`), then

    expected damage   = Impact.expectation(completed curve)
    damage law        = Impact.pushforward(completed curve)
    loss at T         = ratio at the depth evaluate(...).return_periods([T]) gives × value

For a building the impact is its own: the Hazus curve shifted by its first-floor height, written on depth
above ground with the dry threshold and BD-1 to BD-5 as knots (a jump is two knots 1e-9 m apart; the domain
ends at 24 ft above the floor, so a deeper depth is CRC's `out_of_domain`).

**Parameters:** tail completion **placeholder**.

**Weakness.** The point route reproduces the event table by construction (it is the same depths); the grid
route uses a 5 m cell's depth at one point (for most buildings the centroid falls in a roofed cell, which
the grid does not read), eight probabilities with linear interpolation between them, and the tail
completion, so it differs.

**Code:** `src/flood_lab/risk/metrics.py` (`building_impact`, `complete`, `evaluated`).

## What is averaged over what: a summary

| Quantity | Space | Time |
| --- | --- | --- |
| Hail curve per cell | cell plus six neighbours (about 35 km) | 30 annual maxima per cell |
| Report rate at a plant | circle of 10–75 km holding 100 reports | 1996–2025 |
| Reporting rate ρ | one cell (253 km²) | 1996–2025, population as of 2020 |
| Corrected rate, per cell | the plant's circle | 1996–2025 |
| Corrected rate, per region | one region (about 12,000 km²) | 1996–2025 |
| Radar hail days at a plant | 25 km around the plant | October 2020 to 2025 |
| Radar hail days per cell | cell (253 km²) | October 2020 to 2025 |
