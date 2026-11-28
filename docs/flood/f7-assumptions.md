# F7 working assumptions (Yuri 2026-11-28: "will read today, now make assumptions")

Every value here is [P], labelled "assumption pending Yuri's reading of <source>", swept in the
tornado and break-even views, and replaced by the read value when Yuri gives it. None is [S].

## Project useful life (reading-list item 2)

Pending: BCA Reference Guide, Appendix D (standard project useful life), and FEMA P-1037 (2015),
whose ranges a search summary gave (not read at the source): elevating the lowest floor 30-50 y,
elevating utilities 15-20 y, passive dry floodproofing 15-30 y, floodwalls 50 y.

| Measure | Main case | Sweep | Basis of the assumption |
| --- | --- | --- | --- |
| FM1 raise substation equipment | 30 y | 15-50 y | between "elevating utilities" and "elevating the lowest floor" in the unread P-1037 ranges |
| FM2 perimeter wall at a substation | 50 y | 30-50 y | "floodwalls 50 y" in the unread P-1037 summary |
| FM8 dry floodproofing of buildings | 20 y | 15-30 y | "passive dry floodproofing 15-30 y" in the unread P-1037 summary |

## BCA Toolkit version (item 3)

Report states: "BCA Toolkit version not confirmed; FEMA announced an update on 2026-10-01; last
version number found: 6.0 (2019)".

## FM8 dry floodproofing (CH-32, Yuri 2026-11-28: add it)

- Sealed to H above the first floor: damage ratio 0 while curve depth (depth above first floor) < H;
  baseline Hazus curve once overtopped (the sealed building is treated as failed). Two points 1 mm
  apart at H, tested on both sides (as FM2).
- H main case 0.9 m (3 ft) [P], sweep 0.3-0.9 m: assumption pending FEMA's Dry Floodproofing
  Technical Review and P-1037 on the height limit for buildings.
- Applies to the curve above grade only; basement damage (curve depth below 0) unchanged [P].
- Main case: every building with a curve, as a "what if"; beside it the non-residential-only case
  (NFIP Technical Bulletin 3: dry floodproofing counts for non-residential buildings; pending Yuri).
- Cost: no source, and no number is assumed. F7 reports the break-even cost instead: the present
  value of avoided loss over the life, i.e. the most the measure could cost with BCR = 1, in total
  and per metre of footprint perimeter (perimeter from the cached footprints).

## Measure costs in general (FM3)

No cost is assumed for any measure. Every benefit-cost result is shown as break-even cost
(BCR = 1) and as BCR against cost over a stated sweep, so the reader can bring a cost.
