# Loss rules: definitions and the rules the loss stage applies

Draft 1, 2026-11-27 (F6). Accepted by Yuri on 2026-11-27 (CH-29), except where a row says otherwise.

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
| C-5 | A substation's voltage tier follows Hazus's classes (high ≥ 350 kV, medium 150–350 kV, low 34.5–150 kV); unknown voltage, no curve. | **[S]** classes, **[P]** mapping | open (question to Yuri) |
| C-6 | A depth above 6 m at a substation is an error that the test against the catalogue must catch. | **[P]** | CH-27 |

## Values and price year (V)

Code: `src/flood_lab/assets/floors_values.py` (`asset_values`).

| ID | Rule | Tag | Decision |
|---|---|---|---|
| V-1 | Values are taken as the asset table holds them (low, mid, high), with their tag and source. An unknown value is empty, never zero. | as the value | CH-5 |
| V-2 | Every value is converted to 2026 dollars with the USACE Civil Works Construction Cost Index System (EM 1110-2-1304; tables of 31 March 2026, facts file `usace-cwccis`): cost × index(target quarter) / index(source quarter), both from Table 1 (fiscal quarters) and the same feature code. | **[S]** index, **[I]** conversion | index: Yuri 2026-11-27 (CH-29) |
| V-3 | Target quarter: 4Q26 (July–September 2026), the latest 2026 quarter in the tables. Every 2026 value there is an OMB-based projection, marked * by USACE; the page says so. | **[S]** projected, **[P]** choice | Yuri 2026-11-28 (CH-29) |
| V-4 | Feature code 19 "Buildings, grounds & utilities" for every asset; code 07 "Power plant" as a sensitivity for substations. USACE has no code for private buildings or substations. | **[P]** | Yuri 2026-11-28 (CH-29) |
| V-5 | Source quarter: buildings 4Q25 (July–September 2025, holding August 2025 **[S]**); substation figures 4Q24 (July–September 2024, the middle of calendar 2024), since neither source states one price year (MISO's guide says both 2023 and 2024; Con Edison states none). | **[P]** | Yuri 2026-11-28 (CH-29) |
