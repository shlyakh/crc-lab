# Loss rules: definitions and the rules the loss stage applies

Draft 1, 2026-11-27 (F6). Accepted by Yuri on 2026-11-27 (CH-29), except where a row says otherwise.
Section A and rule V-6 added 2026-11-28 (CH-31); their rows marked "proposed" await Yuri's decision.

This page is the one place that defines the quantities the loss stage uses and lists every rule it
applies to them. Each rule has an ID that does not change. The code cites these IDs, and the page
(later) will show them beside the numbers they produce. A rule is changed through
`docs/flood/changes.md`, never in code alone.

Tags: **[S]** stated by a source, **[I]** converted or computed by us, **[P]** our choice (a
placeholder until something better is known).

## Definitions

| ID | Term | Definition |
|---|---|---|
| D-1 | Depth at the building | Inundation depth above ground at the building's footprint centre, in metres, from the flood model (FR1). |
| D-2 | First-floor height | Height of the top of the finished first floor above the ground beside the building, in metres. Hazus's datum for building curves (CH-25). It can be negative (floor below grade). |
| D-3 | Depth above first floor | D-1 less D-2: the depth a Hazus building curve is read at. Hazus curves run from −4 ft to 24 ft (−1.22 m to 7.32 m) **[S]**. |
| D-4 | Basement | Y or N: whether the building has a floor below grade. It picks the curve (Hazus has separate basement curves) and decides rule BD-3. |
| D-5 | Estimated grade | A city-table row whose notes say "not visible": the city's surveyors could not see the ground or the floor and estimated one of them. The table does not say which. |
| D-6 | Building value | Depreciated replacement value of the structure, from the National Structure Inventory (FD5), in August 2025 prices **[S]**. |

## First-floor height (FF)

Code: `src/flood_lab/assets/floors_values.py` (`first_floors`). The order of sources is fixed:
the city's Building Elevation and Subgrade table (z_floor less z_grade), else the National
Structure Inventory's `found_ht` (the publisher's default by foundation type, tagged "default"),
else empty.

| ID | Rule | Threshold | Tag | Buildings in the study area **[I]** |
|---|---|---|---|---|
| FF-1 | The city's height is the main case, used as the table holds it. | none | **[S]** height, **[P]** rule | 16,159 |
| FF-2 | A city height above 3 m is used and flagged `above_3m`. | 3 m | **[P]** | 1,066 |
| FF-3 | A city height above 6 m is taken as a data error. It is not used (`ffh_city_m` keeps it for display); the building falls to the inventory's default, flag `city_suspect`. | 6 m | **[P]** | 5 (4 take the inventory default, 1 has none) |
| FF-4 | Where the grade is estimated (D-5), `ffh_alt_m` gives a second height: the first-floor elevation less our 1 m terrain at the footprint centre. It is used only in a sensitivity run; FF-3 applies to it too. Flag `grade_estimated`. | none | **[P]** | 4,893 flagged; 255 of the alternatives above 3 m, 171 below 0 m |
| FF-5 | A city height below 0 m is used and flagged `below_grade`. | 0 m | **[P]** | 17 |
| FF-6 | With no city height, the inventory's `found_ht` (feet to metres) is used and tagged "default", never S. | none | default | 717 (713 plus 4 from FF-3) |
| FF-7 | With neither, the height is empty, never 0. The building gets no loss and is reported (BD-5). | none | — | 868 |

The basement flag (D-4) is the city's subgrade flag, else Y where the inventory's foundation type
is B and N for any other stated type, else empty. The city's N means "none seen from the street".

Why most heights are large: Brooklyn row houses stand on a half-sunk basement, with the first floor
up a stoop. Buildings with a basement have a median height of 2.34 m; those without, 0.19 m
**[I]**. Hazus's basement curves cover water below such a floor, so a height of 2.5 m is not an
error. Of the 1,071 heights above 3 m before FF-3, 990 have the basement flag and 818 an estimated
grade **[I]**. For those, the city's grade lies a median 0.73 m below our terrain **[I]**: it may
have been taken at the sunken basement entrance.

## Reading a building curve (BD)

Code: `src/flood_lab/risk/building_depth.py` (`curve_depth`). Each building ends in one of three
cases: the curve is read, no loss, or failed (reported, never counted as zero).

| ID | Rule | Tag |
|---|---|---|
| BD-1 | Dry building: a depth at the building (D-1) of 0 or less means no loss, whatever the curve gives at negative depths. | **[P]** |
| BD-2 | The curve is read at the depth above first floor (D-3). | **[S]** (Hazus datum) |
| BD-3 | Below the curve's lowest point (−4 ft): with a basement, the curve is read at −4 ft; without, no loss; basement unknown, failed. | **[P]** |
| BD-4 | Above the curve's highest point (24 ft): failed. A curve is never extrapolated. | **[P]** |
| BD-5 | No first-floor height: failed. | **[P]** |

## Damage curves (C)

Code: `src/flood_lab/curves/envelope.py`, `src/flood_lab/curves/build.py`; output `curves.yaml`.

| ID | Rule | Tag | Decision |
|---|---|---|---|
| C-1 | Building curves: the Hazus structure curves, as SPHERE (Niyam IT, MIT licence) ships them. FEMA's FAST tool (GPL-3.0) is the cross-check; the two are identical for every curve used. | **[S]** values | Yuri 2026-11-27 (CH-29) |
| C-2 | A building's curve follows FAST's default assignment from occupancy, storeys and basement (riverine). SPHERE's own cross-reference gives the same curve for every building but one (B-3000349, 1,900 storeys in the inventory). | **[S]** | CH-25, CH-29 |
| C-3 | Substations get four curve families, never one: Nirandjan F2 (low), Williams's max for the voltage tier (high), Williams's min, and Bor 2026. | **[S]** points, **[P]** construction | CH-27 |
| C-4 | Every substation table runs from 0 m to 6 m; a curve whose source stops short holds its last value; Williams is 0 at 0 m. | **[P]** | CH-27 |
| C-5 | Williams's curve for a substation follows its role, as OpenStreetMap tags it: `substation=transmission` takes "grid exit point" (Farragut, 345 kV), `substation=distribution` takes "substation" (Water Street, Hudson Avenue, Plymouth, 138 kV). Williams's "distribution substation" ("low-voltage substation", p. 6) is used for none. No stated role, no curve (Building 390 and one unnamed site, which have no value either). Sensitivity: Hazus's voltage classes instead (below). | **[S]** roles (OSM), **[P]** mapping | Yuri 2026-11-28 (CH-30) |
| C-6 | A depth above 6 m at a substation is an error that the test against the catalogue must catch. | **[P]** | CH-27 |

**Hazus voltage classes (the C-5 sensitivity).** Hazus 7.0 Inventory Technical Manual (June 2025), p. 9-15 **[S]**: high voltage 350 kV and above, medium 150–350 kV, low 34.5–150 kV; no class below 34.5 kV. Williams labels its components "grid exit point [high-voltage substation]", "substation [medium-voltage substation]" and "distribution substation [low-voltage substation]" (p. 6) **[S]** but gives no kV, so matching them to Hazus's classes is our step **[P]**. On this basis Farragut (345 kV, just under the 350 kV line) takes "substation" and the three 138 kV sites "distribution substation". High side of the envelope at 0.5 m and 3 m **[S]** (Williams Data S4, maximum hazard condition): grid exit point 34.1% and 69.7%, substation 33.4% and 75.5%, distribution substation 34.7% and 76.5%. Code: `envelope.tier_for(kv, kind, basis)`, `basis="role"` (main case) or `"hazus_kv"`.

## Values and price year (V)

Code: `src/flood_lab/assets/floors_values.py` (`asset_values`).

| ID | Rule | Tag | Decision |
|---|---|---|---|
| V-1 | Values are taken as the asset table holds them (low, mid, high), with their tag and source. An unknown value is empty, never zero. | as the value | CH-5 |
| V-2 | Every value is converted to 2026 dollars with the USACE Civil Works Construction Cost Index System (EM 1110-2-1304; tables of 31 March 2026, facts file `usace-cwccis`): cost × index(target quarter) / index(source quarter), both from Table 1 (fiscal quarters) and the same feature code. | **[S]** index, **[I]** conversion | index: Yuri 2026-11-27 (CH-29) |
| V-3 | Target quarter: 4Q26 (July–September 2026), the latest 2026 quarter in the tables. Every 2026 value there is an OMB-based projection, marked * by USACE; the page says so. | **[S]** projected, **[P]** choice | Yuri 2026-11-28 (CH-29) |
| V-4 | Feature code 19 "Buildings, grounds & utilities" for every asset; code 07 "Power plant" as a sensitivity for substations. USACE has no code for private buildings or substations. | **[P]** | Yuri 2026-11-28 (CH-29) |
| V-5 | Source quarter: buildings 4Q25 (July–September 2025, holding August 2025 **[S]**); substation figures 4Q24 (July–September 2024, the middle of calendar 2024), since neither source states one price year (MISO's guide says both 2023 and 2024; Con Edison states none). | **[P]** | Yuri 2026-11-28 (CH-29) |
| V-6 | Price quarter of the Hazus substitute values (A-8): Hazus 7 Inventory TM Tables 6-2 and 6-3 state "(2022)" and no month **[S]**; the middle of calendar 2022, July–September 2022, is fiscal 4Q22 (index 1143.96, Table 1 p. 22 of the March 2026 tables **[S]**), as V-5 does for "2024". Factor to 4Q26: 1.055151 **[I]**. | **[P]** | proposed |

## Occupancy, storeys and value gaps (A)

Code: `src/flood_lab/assets/exposures.py`; output `site/flood/data/exposures.csv` (one row per asset,
17,750 rows) and `site/flood/data/exposures_summary.json` (every count below **[I]**, 2026-11-28).
PLUTO: `src/flood_lab/sources/nyc_pluto.py`, facts file `nyc-pluto`. Report:
`docs/flood/reports/F6-exposures.md`.

Each quantity of a row (occupancy, storeys, basement, first-floor height, value, curve) has a
`*_source` and a `*_substitute` flag: True when the value is a substitute rather than stated for
this asset. `asset_substitute_class` lists every substitute kind that applies. The first-floor
heights are those of FF-1 to FF-7, unchanged (the inventory's default height, FF-6, is listed as the
substitute kind "NSI default first-floor height").

Every building takes exactly one route:

| Route | Buildings **[I]** | Occupancy | Storeys | Value |
|---|---|---|---|---|
| `nsi` | 11,902 | NSI occtype | NSI num_story | NSI val_struct (V-1, V-2) |
| `nsi suffix` | 426 | A-1 | NSI num_story | NSI val_struct |
| `pluto` | 5,360 | A-2, A-3 | A-4, A-7 | A-8, A-9 |
| `neighbour` | 56 | A-6 | A-4, A-7 | A-8, A-9 |

| ID | Rule | Tag | Assets **[I]** | Decision |
|---|---|---|---|---|
| A-1 | Suffix pre-step: an NSI occupancy `RES1-<n>S<WB\|NB>` takes the base class RES1, storeys from `NumberOfStoreys`, basement from our flag (the city's subgrade flag first, as `first_floors` does). The suffix itself is not used. FAST caps RES1 at 3 storeys. Of the 426, the suffix's storeys agree with `num_story` for all 373 of 3 storeys or fewer; the other 53 have 4 to 7 storeys and carry the suffix 3 (the same curve after FAST's cap). The suffix's basement disagrees with our flag for 155 (139 suffix WB, flag N; 16 suffix NB, flag Y). | **[S]** class, **[P]** rule | 426 (RES1-3SWB 225, RES1-2SWB 159, RES1-1SWB 17, RES1-3SNB 13, RES1-2SNB 11, RES1-1SNB 1) | Yuri 2026-11-28 (CH-31) |
| A-2 | A building without an NSI point takes the PLUTO lot it stands on (the footprint's `mappluto_bbl`, the layer's key to MapPLUTO; else `base_bbl`) and its building class maps to a Hazus specific occupancy by the table below. Hazus occupancies: Inventory TM Table 4-1, p. 4-2 **[S]**; PLUTO classes: data dictionary 26v3 Appendix C, pp. 51–54 **[S]**. A class not in the table stops the build. | **[P]** mapping | 5,408 with a lot (5,053 on `base_bbl` alone); 5,360 mapped | route: Yuri 2026-11-28 (CH-31); table rows proposed |
| A-3 | Classes marked "RES3 by units" take the Hazus RES3 class of the lot's residential units (Table 4-1 **[S]**: RES3A duplex, RES3B 3–4, RES3C 5–9, RES3D 10–19, RES3E 20–49, RES3F 50+); one or two units give RES3A; no units known, route `neighbour`. On a lot with several buildings the units are the lot's sum. | **[S]** classes, **[P]** use | 1,877 | proposed |
| A-4 | Storeys from PLUTO `NumFloors` ("for the tallest building on the tax lot" **[S]**) where the lot has one building (PLUTO `NumBldgs` = 1 and one footprint on it), not flagged. On a lot with several buildings, `NumFloors` goes to the lot's largest footprint only, flagged substitute ("PLUTO lot floors (tallest building)"); the other footprints take A-7. Partial floors round half up. | **[P]** | 3,363 single-building; 578 largest on a shared lot | single-building: Yuri 2026-11-28 (CH-31); several buildings: proposed |
| A-5 | Basement from PLUTO `BsmtCode` (0 → N; 1, 2, 3, 4 → Y; 5 unknown **[S]**, dictionary p. 32) only on a single-building lot of a one-, two- or three-family class (A\*, B\*, C0: the dictionary says the code is available for such structures and not verified for others); else the city's subgrade flag; else empty. | **[S]** codes, **[P]** restriction | 406 BsmtCode (127 disagree with the city flag), 4,154 city flag, 856 empty | order: Yuri 2026-11-28 (CH-31); restriction proposed |
| A-6 | No PLUTO lot, or a class that names no building use (vacant land V\*, Z0, Z7, Z9, empty) or no units: the most common NSI base class (after A-1) among NSI buildings whose centre lies within 100 m; none there, the study area's most common class (RES3B). | **[P]** radius | 56 (8 without a lot); study-area mode used for 0 | proposed |
| A-7 | Storeys of a footprint that A-4 does not cover: the city's roof height (footprints `height_roof`, feet) divided by 12.62 ft per storey, rounded half up, at least 1. 12.62 ft is the median of roof height over `NumFloors` of the 14,098 study buildings alone on their lot **[I]**. No roof height: the most common NSI storeys within 100 m. | **[I]** storey height, **[P]** rule | 1,467 roof height; 8 neighbours | proposed |
| A-8 | Value of a building without an NSI point: Hazus 7 Inventory TM Table 6-2 cost per ft² of its occupancy (Table 6-3 for RES1) × footprint area (city footprint, projected) × storeys, converted by V-2 from 4Q22 (V-6). Full replacement cost, not depreciated (NSI values are depreciated, D-6). The manual's costs are national averages "prior to the application of location factors" (Equations 6-1 and 6-3); the county factors are in the Hazus database table `hzCountyLocationFactor` (Section 6.3, p. 6-11 **[S]**) and the manual gives none for Kings County, so none is applied (known bias: US average). | **[S]** cost, **[I]** value | 5,416 | substitute: Yuri 2026-11-28 (CH-31); details proposed |
| A-9 | RES1 levels: low, mid and high are Table 6-3's Economy, Average and Luxury classes (its full range); a basement Y takes the unfinished-basement column, as Hazus assumes when the finish is not known (Equation 6-1 text, p. 6-8 **[S]**); N the no-basement column; unknown, Hazus's Middle Atlantic weights (Table 6-8: 58% with, 42% without **[S]**; NY in Middle Atlantic, Table 3-1). Above three storeys, the three-story row. Other occupancies have one figure (mid); low and high stay empty. | **[S]** costs, **[P]** levels | 355 | proposed |
| A-10 | Garages (feature code 5110) and footprints under 40 m² without an NSI point follow the same rules and are flagged `minor_structure`, so the loss stage can drop them; Hazus's RES1 cost already includes a garage (Table 6-4 text). | **[P]** | 480 (416 garages, 334 under 40 m², 270 both) | proposed |
| A-11 | Shared lots: a building without an NSI point on a lot (`base_bbl`) where NSI put points on another footprint is flagged `lot_shared_with_nsi`. NSI points are not moved and F1's table is not changed. The main case includes these buildings with their A-2 class and A-8 value; a sensitivity drops them (`lot_shared_with_nsi == True`). The check per lot (summary `lot_check`) compares the 2026 NSI value already on the lot with the Hazus value of every study building on it (NSI buildings at NSI's own floor area `sqft`). | **[P]** | 1,180 on 768 lots | Yuri 2026-11-28 (CH-31) |
| A-12 | A building whose basement is not known gets no structure curve (FAST's rule, C-2): no substitute basement. All 856 also have no first-floor height (no row in the city table), so BD-5 already fails them. | **[P]** | 856 (444 minor) | proposed |

Diagnosis behind the routes (gap causes, `gap_cause`, F1's 15 m join repeated over every footprint
of the box **[I]**): A 1,180 (another footprint on the same tax lot holds NSI points), B 3,446 (an
NSI point within 15 m went to a footprint on a neighbouring lot), C 790 (no NSI point within 15 m).

Substations: no new rule. Curves by C-5 (`envelope_for(kv, kind)`, basis "role"); values by V-1, V-2,
V-4 and V-5 (4Q24 to 4Q26, factor 1.060723 **[I]**). Building 390 (removed) and the unnamed site
keep no value and no curve.

### PLUTO building class to Hazus occupancy (A-2)

Every class in the 15,590 lots fetched (161 classes). "Buildings without NSI" counts the study
buildings without an NSI point on a lot of that class (5,408; 8 more have no lot).

| PLUTO class | Hazus occupancy | Reason (Appendix C wording, shortened) | Lots fetched | Buildings without NSI | Tag |
|---|---|---|---|---|---|
| (empty) | — (route `neighbour`, A-6) | no building class | 5 | 4 | **[P]** |
| A1 | RES1 | one family dwelling | 37 | 6 | **[P]** |
| A2 | RES1 | one family dwelling | 4 | 0 | **[P]** |
| A3 | RES1 | one family dwelling | 4 | 2 | **[P]** |
| A4 | RES1 | one family dwelling | 178 | 12 | **[P]** |
| A5 | RES1 | one family dwelling | 184 | 22 | **[P]** |
| A7 | RES1 | one family dwelling | 3 | 1 | **[P]** |
| A9 | RES1 | one family dwelling | 224 | 187 | **[P]** |
| B1 | RES3A | two family dwelling: duplex | 665 | 39 | **[P]** |
| B2 | RES3A | two family dwelling: duplex | 376 | 41 | **[P]** |
| B3 | RES3A | two family dwelling: duplex | 929 | 56 | **[P]** |
| B9 | RES3A | two family dwelling: duplex | 1,042 | 127 | **[P]** |
| C0 | RES3B | three families: 3-4 units | 2,713 | 249 | **[P]** |
| C1 | RES3 by units | walk-up apartments, size from the lot's units | 1,046 | 181 | **[P]** |
| C2 | RES3C | five to six families: 5-9 units | 738 | 97 | **[P]** |
| C3 | RES3B | four families: 3-4 units | 966 | 108 | **[P]** |
| C4 | RES3 by units | walk-up apartments, size from the lot's units | 142 | 29 | **[P]** |
| C5 | RES3 by units | walk-up apartments, size from the lot's units | 75 | 7 | **[P]** |
| C6 | RES3 by units | walk-up apartments, size from the lot's units | 161 | 35 | **[P]** |
| C7 | RES3 by units | walk-up apartments, size from the lot's units | 268 | 240 | **[P]** |
| C9 | RES3 by units | walk-up apartments, size from the lot's units | 7 | 1 | **[P]** |
| CB | RES3 by units | walk-up apartments, size from the lot's units | 3 | 4 | **[P]** |
| D0 | RES3 by units | elevator apartments, size from the lot's units | 2 | 0 | **[P]** |
| D1 | RES3 by units | elevator apartments, size from the lot's units | 176 | 26 | **[P]** |
| D2 | RES3 by units | elevator apartments, size from the lot's units | 10 | 13 | **[P]** |
| D3 | RES3 by units | elevator apartments, size from the lot's units | 70 | 10 | **[P]** |
| D4 | RES3 by units | elevator apartments, size from the lot's units | 33 | 4 | **[P]** |
| D5 | RES3 by units | elevator apartments, size from the lot's units | 37 | 19 | **[P]** |
| D6 | RES3 by units | elevator apartments, size from the lot's units | 78 | 52 | **[P]** |
| D7 | RES3 by units | elevator apartments, size from the lot's units | 115 | 78 | **[P]** |
| D8 | RES3 by units | elevator apartments, size from the lot's units | 6 | 0 | **[P]** |
| D9 | RES3 by units | elevator apartments, size from the lot's units | 68 | 12 | **[P]** |
| DB | RES3 by units | elevator apartments, size from the lot's units | 3 | 1 | **[P]** |
| E1 | IND2 | warehouse: Table 6-2 warehouse model | 118 | 89 | **[P]** |
| E2 | IND2 | warehouse: Table 6-2 warehouse model | 3 | 2 | **[P]** |
| E7 | IND2 | self-storage warehouse: Table 6-2 warehouse model | 9 | 9 | **[P]** |
| E9 | IND2 | warehouse: Table 6-2 warehouse model | 87 | 78 | **[P]** |
| F1 | IND1 | heavy or fireproof factory | 11 | 11 | **[P]** |
| F2 | IND1 | heavy or fireproof factory | 2 | 2 | **[P]** |
| F4 | IND1 | heavy or fireproof factory | 12 | 8 | **[P]** |
| F5 | IND2 | light manufacturing | 103 | 89 | **[P]** |
| F9 | IND2 | miscellaneous factory | 26 | 24 | **[P]** |
| G0 | COM10 | residential garage | 14 | 11 | **[P]** |
| G1 | COM10 | parking garage | 40 | 26 | **[P]** |
| G2 | COM3 | auto body or repair | 37 | 32 | **[P]** |
| G3 | COM1 | gas station with retail store | 1 | 1 | **[P]** |
| G4 | COM3 | gas station with auto repair | 8 | 3 | **[P]** |
| G5 | COM1 | gas station | 5 | 1 | **[P]** |
| G6 | COM10 | licensed parking lot | 1 | 1 | **[P]** |
| G7 | COM10 | unlicensed parking lot | 10 | 8 | **[P]** |
| G8 | COM1 | car sales with showroom | 2 | 2 | **[P]** |
| G9 | COM3 | miscellaneous garage or gas station | 17 | 11 | **[P]** |
| GU | COM1 | car sales without showroom | 1 | 1 | **[P]** |
| GW | COM3 | car wash or lubritorium | 2 | 2 | **[P]** |
| H1 | RES4 | hotel: temporary lodging | 3 | 1 | **[P]** |
| H2 | RES4 | hotel: temporary lodging | 8 | 6 | **[P]** |
| H3 | RES4 | hotel: temporary lodging | 4 | 2 | **[P]** |
| H4 | RES4 | hotel: temporary lodging | 1 | 1 | **[P]** |
| H8 | RES5 | dormitory | 3 | 0 | **[P]** |
| H9 | RES4 | hotel: temporary lodging | 1 | 1 | **[P]** |
| HB | RES4 | boutique hotel | 4 | 0 | **[P]** |
| HH | RES4 | hostel | 2 | 0 | **[P]** |
| HR | RES4 | single room occupancy | 1 | 0 | **[P]** |
| I1 | COM6 | hospital | 4 | 1 | **[P]** |
| I5 | COM7 | health centre, clinic | 15 | 11 | **[P]** |
| I6 | RES6 | nursing home | 2 | 0 | **[P]** |
| I7 | RES6 | adult care facility | 6 | 5 | **[P]** |
| I9 | COM7 | miscellaneous health | 13 | 10 | **[P]** |
| J2 | COM9 | theatre | 2 | 1 | **[P]** |
| J3 | COM9 | theatre | 1 | 1 | **[P]** |
| J5 | COM9 | theatre | 1 | 1 | **[P]** |
| J6 | COM4 | television studio | 1 | 6 | **[P]** |
| J7 | COM9 | theatre | 1 | 0 | **[P]** |
| J8 | COM9 | theatre | 1 | 1 | **[P]** |
| J9 | COM9 | theatre | 2 | 2 | **[P]** |
| K1 | COM1 | store building: retail trade | 177 | 132 | **[P]** |
| K2 | COM1 | store building: retail trade | 65 | 60 | **[P]** |
| K4 | COM1 | store building: retail trade | 230 | 221 | **[P]** |
| K5 | COM8 | stand-alone food establishment (Table 6-2 model: restaurant) | 5 | 1 | **[P]** |
| K6 | COM1 | store building: retail trade | 1 | 0 | **[P]** |
| K7 | COM5 | banking facility | 5 | 4 | **[P]** |
| K8 | COM1 | store building: retail trade | 1 | 0 | **[P]** |
| K9 | COM1 | store building: retail trade | 3 | 2 | **[P]** |
| M1 | REL1 | church, synagogue, mission, parsonage, convent | 130 | 88 | **[P]** |
| M3 | REL1 | church, synagogue, mission, parsonage, convent | 32 | 22 | **[P]** |
| M4 | REL1 | church, synagogue, mission, parsonage, convent | 7 | 6 | **[P]** |
| M9 | REL1 | church, synagogue, mission, parsonage, convent | 60 | 55 | **[P]** |
| N2 | RES6 | asylum or home | 6 | 2 | **[P]** |
| N9 | RES6 | asylum or home | 7 | 5 | **[P]** |
| O1 | COM4 | office building | 6 | 5 | **[P]** |
| O2 | COM4 | office building | 59 | 44 | **[P]** |
| O3 | COM4 | office building | 3 | 1 | **[P]** |
| O4 | COM4 | office building | 3 | 0 | **[P]** |
| O5 | COM4 | office building | 74 | 69 | **[P]** |
| O6 | COM4 | office building | 28 | 22 | **[P]** |
| O7 | COM4 | office building | 8 | 10 | **[P]** |
| O8 | RES3 by units | office with apartments only (land use 04) | 10 | 13 | **[P]** |
| O9 | COM4 | office building | 10 | 9 | **[P]** |
| P2 | COM8 | lodge rooms | 4 | 2 | **[P]** |
| P5 | COM8 | community centre | 10 | 3 | **[P]** |
| P6 | COM8 | amusement place | 1 | 1 | **[P]** |
| P7 | COM8 | museum | 1 | 1 | **[P]** |
| P8 | EDU1 | library (Table 4-1: schools/libraries) | 6 | 1 | **[P]** |
| P9 | COM8 | miscellaneous place of assembly | 6 | 4 | **[P]** |
| Q1 | COM8 | outdoor recreation facility | 15 | 18 | **[P]** |
| Q2 | COM8 | outdoor recreation facility | 7 | 5 | **[P]** |
| Q9 | COM8 | outdoor recreation facility | 1 | 0 | **[P]** |
| QG | COM8 | community garden | 1 | 1 | **[P]** |
| R0 | RES3 by units | condominium billing lot | 5 | 4 | **[P]** |
| R1 | RES3 by units | residential condominium unit | 501 | 51 | **[P]** |
| R2 | RES3 by units | residential condominium unit | 52 | 72 | **[P]** |
| R3 | RES3 by units | residential condominium unit | 32 | 52 | **[P]** |
| R4 | RES3 by units | residential condominium unit | 186 | 22 | **[P]** |
| R5 | COM1 | miscellaneous commercial condominium | 3 | 1 | **[P]** |
| R6 | RES3 by units | residential condominium unit | 151 | 21 | **[P]** |
| RA | COM4 | cultural, medical, educational condominium | 4 | 1 | **[P]** |
| RB | COM4 | office condominium | 10 | 0 | **[P]** |
| RC | COM1 | commercial condominium | 8 | 2 | **[P]** |
| RD | RES3 by units | residential condominium | 56 | 26 | **[P]** |
| RK | COM1 | retail condominium | 2 | 0 | **[P]** |
| RM | RES3 by units | mixed residential and commercial condominium | 425 | 110 | **[P]** |
| RR | RES3 by units | condominium rentals | 4 | 1 | **[P]** |
| RW | IND2 | warehouse/factory/industrial condominium | 1 | 0 | **[P]** |
| RX | RES3 by units | mixed residential, commercial and industrial condominium | 4 | 0 | **[P]** |
| RZ | RES3 by units | mixed residential and warehouse condominium | 3 | 1 | **[P]** |
| S0 | RES1 | primarily one family with two stores or offices | 10 | 10 | **[P]** |
| S1 | RES1 | primarily one family with one store or office | 125 | 115 | **[P]** |
| S2 | RES3A | primarily two family with one store or office | 804 | 713 | **[P]** |
| S3 | RES3B | primarily three family with one store or office | 344 | 313 | **[P]** |
| S4 | RES3B | primarily four family with one store or office | 175 | 173 | **[P]** |
| S5 | RES3C | primarily five to six family with one store or office | 228 | 230 | **[P]** |
| S9 | RES3 by units | single or multiple dwelling with stores or offices | 295 | 342 | **[P]** |
| T2 | IND2 | pier, dock, bulkhead | 1 | 18 | **[P]** |
| T9 | IND2 | miscellaneous transportation facility | 2 | 2 | **[P]** |
| U0 | IND2 | utility property | 2 | 10 | **[P]** |
| U1 | IND2 | utility property | 1 | 0 | **[P]** |
| U2 | IND2 | utility property | 6 | 21 | **[P]** |
| U4 | IND2 | utility property | 3 | 0 | **[P]** |
| U7 | IND2 | utility property | 8 | 2 | **[P]** |
| U9 | IND2 | utility property | 2 | 5 | **[P]** |
| V0 | — (route `neighbour`, A-6) | vacant land: names no building use | 10 | 8 | **[P]** |
| V1 | — (route `neighbour`, A-6) | vacant land: names no building use | 22 | 16 | **[P]** |
| V9 | — (route `neighbour`, A-6) | vacant land: names no building use | 1 | 1 | **[P]** |
| W1 | EDU1 | school | 41 | 15 | **[P]** |
| W2 | EDU1 | school | 45 | 35 | **[P]** |
| W3 | EDU1 | school | 4 | 3 | **[P]** |
| W4 | EDU1 | school | 1 | 0 | **[P]** |
| W5 | EDU2 | city university | 1 | 0 | **[P]** |
| W6 | EDU2 | other college and university | 14 | 38 | **[P]** |
| W7 | EDU2 | theological seminary | 1 | 1 | **[P]** |
| W8 | EDU1 | school | 3 | 4 | **[P]** |
| W9 | EDU1 | school | 19 | 16 | **[P]** |
| Y1 | GOV2 | fire department | 9 | 6 | **[P]** |
| Y2 | GOV2 | police department | 4 | 0 | **[P]** |
| Y4 | GOV1 | selected government installation | 1 | 0 | **[P]** |
| Y6 | GOV1 | selected government installation | 2 | 0 | **[P]** |
| Y7 | GOV1 | selected government installation | 1 | 0 | **[P]** |
| Y9 | GOV1 | selected government installation | 1 | 0 | **[P]** |
| Z0 | — (route `neighbour`, A-6) | tennis court, pool, shed: names no building use | 2 | 2 | **[P]** |
| Z3 | GOV1 | post office | 2 | 1 | **[P]** |
| Z9 | — (route `neighbour`, A-6) | other: names no building use | 18 | 13 | **[P]** |
