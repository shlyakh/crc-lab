# F6 (part). Exposures: occupancy, storeys, values and the substitutes for the gaps

Date: 2026-11-28 · branch `flood/f6b` · change CH-31 · rules A-1 to A-12 and V-6 of
`docs/flood/loss-rules.md`

Yuri's decision of 2026-11-28: use a better source where one exists; where there is none, use a
substitute, document it, and show for every asset which values are substitutes and of what kind.
Built: the PLUTO tax lots as a cached source (`src/flood_lab/sources/nyc_pluto.py`, facts file
`nyc-pluto`, data card `docs/flood/data-cards/nyc-pluto.md`) and the exposures table
(`src/flood_lab/assets/exposures.py`), written to `site/flood/data/exposures.csv` (7.3 MB, beside
the asset table, which is 5.8 MB and committed the same way) with every count in
`site/flood/data/exposures_summary.json`. Rebuild: `python -m flood_lab.assets.exposures`
(`--fetch` asks the PLUTO API again). Every number below is **[I]** unless tagged.

## What each route covers

| Route | Buildings | Occupancy from | Value from |
|---|---|---|---|
| `nsi` | 11,902 | NSI occtype | NSI val_struct, 4Q25 → 4Q26 |
| `nsi suffix` | 426 | NSI occtype without its suffix (A-1) | NSI val_struct |
| `pluto` | 5,360 | PLUTO building class (A-2, A-3) | Hazus cost per ft² (A-8) |
| `neighbour` | 56 | most common NSI class within 100 m (A-6) | Hazus cost per ft² |
| substations | 6 | — | V-1/V-5 (4 kept with a value; Building 390 removed; one unnamed site without value) |

The 5,416 buildings without an NSI point: PLUTO has a lot for 5,408 (joined on the footprint's
`mappluto_bbl`, then `base_bbl`; on `base_bbl` alone 5,053, the figure of the first look). Their gap
causes reproduce the first look exactly: A 1,180, B 3,446, C 790.

Curves: 16,888 buildings get a Hazus structure curve by FAST's rule (11,902 `nsi`, 426 suffix, 4,536
`pluto`, 24 `neighbour`). The other 856 have no known basement and no first-floor height (no row in
the city table; 444 are garages or small footprints), so BD-5 already fails them (A-12). Values: all
17,744 buildings have a mid value; 355 RES1 substitutes also have low and high.

## What is a substitute

Substitute kinds (`asset_substitute_class`, an asset can carry several):

| Kind | Buildings |
|---|---|
| Hazus cost per ft² (value) | 5,416 |
| PLUTO class (occupancy) | 5,360 |
| suffix base class (occupancy) | 426 |
| neighbour mode class (occupancy) | 56 |
| study-area mode class | 0 |
| storeys from roof height (A-7) | 1,467 |
| PLUTO lot floors, tallest building, on a shared lot (A-4) | 578 |
| neighbour mode storeys | 8 |
| NSI default first-floor height (FF-6, unchanged) | 717 |

Combinations: none 11,205; NSI default height only 697; suffix base class 406 (and 20 with the default
height); PLUTO class + Hazus value 3,354; + lot floors 578; + roof-height storeys 1,421; + neighbour
storeys 7; neighbour class + Hazus value 9, + roof-height storeys 46, + neighbour storeys 1.

Substitute values add $10.76 billion (2026) to the $49.68 billion the NSI holds for the study area.

Checks of the substitute against stated figures:

- Floor area: for the 3,369 buildings without NSI that stand alone on their lot, PLUTO's `BldgArea`
  over footprint area × storeys has median 0.965 (p10 0.62, p90 1.34): the area term holds.
- Cost: for the 12,328 NSI buildings, NSI's 2026 value over the Hazus substitute at NSI's own floor
  area has median 1.12 (p10 0.66, p90 1.54). NSI's values carry location factors and depreciation,
  the substitute neither.
- Storeys: NSI `num_story` equals PLUTO `NumFloors` for only 26% of the NSI buildings alone on their
  lot and is lower for 68%. A-7 is therefore calibrated on PLUTO (12.62 ft per storey), not on NSI
  (19.5 ft per storey). NSI's storeys still drive the NSI buildings' curves (C-2, unchanged).

## Double counting on shared lots (A-11)

1,180 buildings on 768 lots stand beside a footprint to which NSI already gave points. The main case
includes them (`lot_shared_with_nsi` = True drops them as a sensitivity). Per lot, the NSI value
already there over the Hazus value of every study building on the lot has median 0.69 (p10 0.34,
p25 0.49, p75 1.02, p90 1.25). On 566 lots the NSI value is below the Hazus estimate for the whole
lot, so the substitutes fill a gap. On 202 lots (213 added buildings) NSI alone already reaches it:
there the substitutes add $37.8 million, and the lot total becomes a median 1.31 (p90 1.51) times
the Hazus estimate, the likely double count. Over all shared lots the substitutes add $2.16 billion
beside $6.79 billion of NSI value; dropping them is the sensitivity.

## Suffix pre-step (A-1)

Of the 426 suffixed NSI codes, the storeys in the suffix agree with `num_story` for every building
of 3 storeys or fewer (373); the 53 others have 4 to 7 storeys and carry 3, FAST's own cap. The
suffix's basement disagrees with our flag for 155 (139 WB against the city's N, 16 NB against Y);
our flag is used, as decided.

## Known biases

- PLUTO is per lot: on the 1,986 buildings without NSI that share a lot, class and units are the
  lot's, `NumFloors` is the tallest building's.
- Hazus costs are national averages for 2022 without the county location factor (Kings County's is
  in the Hazus database, not in the manual) and without depreciation; NSI's are depreciated.
- PLUTO's mixed classes (S\*, C7, D6, D7, K4, RM) map to residential by units; NSI gives
  comparable buildings commercial classes more often (S2: 62 of 149 NSI buildings COM4).
- Roof heights include parapets and bulkheads; 12.62 ft per storey is a median.

## Open choices for Yuri

1. The PLUTO class table (A-2, every row [P]), mixed-use classes above all.
2. A-3 (units on the lot), A-4 on shared lots, A-5's restriction to single-building 1–3 family lots.
3. A-6 radius 100 m; A-7 storeys from roof height.
4. A-8: apply a location factor (none is stated in the manual) or depreciation (Hazus 6.4 needs the
   age), or neither as now.
5. A-9: Economy / Average / Luxury as low / mid / high for RES1.
6. A-10: drop minor structures (480) from the main case or keep.
7. A-11: main case with the shared-lot buildings (as decided) or without on the 202 lots where NSI
   already reaches the Hazus estimate.
8. A-12: a substitute basement for the 856 without (they also lack a first-floor height).
9. V-6: 4Q22 as the quarter of Hazus's "2022".
