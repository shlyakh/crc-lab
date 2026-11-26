# F5 (second part). The Jamaica Bay map and who saw the flood

Date: 2026-11-26 · branch `flood/f5b` · crc-sdk 1.0.0, crc-framework 1.0.0 · model frozen at F3
(constant loss rate 30 mm/h)

The second part of stage F5 in `docs/flood/plan.md`: FV3 (the published Jamaica Bay depth map) and FV5 ("who
saw the flood"). The first part, on the surveyed marks and the sensors, is `F5-marks-and-sensors.md`.
Yuri asked for this part on 2026-11-26. The numbers here come from the record `f5-who-saw`
(`site/flood/tests/records/f5-who-saw.json`). The gallery shows the record with its three figures.
`just flood-f5-who-saw` rebuilds it offline from the cache. No solver was run, and no parameter was changed
(FV4).

## Result against the pass rule

| Rule | Result |
| --- | --- |
| FV3: compare with the Jamaica Bay map where it overlaps the square, using the shapefile | **Not applicable.** None of the map's 109,875 points lies in the square. The map's cells cover 0 m² of it. The nearest point is 2,046 m south of the square |
| FV3: the shapefile is the publisher's | **Pass.** The .shp, .shx, .dbf, .prj and .cpg files match the SHA-256 checksums in the Mendeley record. So do the other four files |
| FV5: counts and locations for each storm from five sources, on one chart and one map | **Reported, not judged** (table below; figures `who_saw_counts.png`, `who_saw_map.png`) |
| FV5 / FT5 facts row: Storm Events clock rule stated; zone events read | **Done.** See section 2 |
| FV5 / FT5 facts row: 311 counts both naming schemes | **Done, with a finding.** On 29 Sep 2023 most requests appear once under each scheme. Section 2 |
| FV4: no retuning | **Kept** |

## 1. FV3: the Jamaica Bay map

- **The fetch.** The six missing files of the shapefile (.shp, .shx, .dbf, .cpg, .sbn, .sbx) were fetched
  from the Mendeley record on 2026-11-26. Each matches the size and SHA-256 that Mendeley gives. The fetch is
  recorded in `src/flood_lab/facts/jamaica-bay-ida-depth-map.toml`, with two new facts (`flood_dept_unit`
  and `extent_vs_square`).
- **What the file is.** The map is 109,875 points, one per map cell, in New York State Plane feet
  (EPSG:2263). The median distance between neighbouring points is 33.55 m. That spacing is used as the
  side of each point's cell.
- **The overlap.** Not one point is in the square. The cells cover 0 m² of it. The nearest point is
  2,046 m from the square's south edge, at about 40.668 N, 73.941 W. So FV3 does not apply to this
  square. Nothing was stretched to make
  it apply.
- **The unit of `flood_dept`: metres.** The metadata does not state it. The file shows it:
  - In 106,281 of the 109,875 rows, `flood_dept` equals `water_elev` less `dem_m` within 0.001. The
    metadata states that `dem_m` is in metres.
  - The other 3,594 rows are all class 3, where `flood_dept` is exactly 0.91. The value is capped at the
    class-3 bound.
  - Every row lies inside the bounds of its class, and the metadata gives those bounds in metres.
  - So the map holds no depth above 0.91 m.

  This is an inference from the numbers, not something the publisher states.
- **Figure** `jamaica_bay_overlap.png`: the map's points near the square, with the shortest distance drawn.
  The map is shown with credit under CC BY 4.0.

## 2. FV5: who saw the flood

Storm days: Ida, 1 and 2 September 2021; the other storm, 29 September 2023. Everything is counted inside
the model square (EPSG:32618, 585,500 to 589,500 E and 4,504,500 to 4,508,500 N), west and south edges in.

| Source | What is counted | Ida, 1-2 Sep 2021 | 29 Sep 2023 |
| --- | --- | --- | --- |
| Groundsource (news) | places centred in the square (places touching it) | 10 (20) | 11 (26) |
| NOAA Storm Events | flood events with a point in the square (flood events in the square's counties and zones) | 0 (12) | 1 (7) |
| 311 service requests | flooding-related requests, twin rows paired (rows of both schemes) | 69 (69) | 121 (225) |
| FloodNet | sensors that recorded an event (sensors in service) | 0 (1) | 5 (7) |
| USGS high-water marks | marks (sites) | 11 (6) | no survey in the cache |

Counts are reported, not judged. A source with no entry is not evidence that there was no flood.

### Each source's rules

- **Groundsource.**
  - Time: a row counts when its date range holds a storm day. The dates are days only, with no time
    and no zone.
  - Place: the main count is the place polygon's centroid inside the square. The context count is any
    polygon that touches the square. The polygon is the named place in the news report, not the flood.
  - Of the places that touch the square, 4 are larger than the square in each storm, such as a whole
    borough.
  - Read with the F2 reader (`sources/groundsource.py`), from the publisher's file.
- **NOAA Storm Events.**
  - **Clock rule.** Every New York City row says `EST-5`, also in September, when New York is on daylight
    time. The reader takes the offset from `CZ_TIMEZONE`, turns the time into UTC and then into New York
    wall-clock time. An event counts when its begin-to-end span holds a storm day on that clock. Here the
    rule changes no count: matching on the clock as written gives the same 12 and 7 events.
  - **Counties and zones.** Both are read: counties Kings (47) and New York (61), and NWS forecast zones
    75, Kings (Brooklyn), and 72, New York (Manhattan). The square holds 12.5 km² of Brooklyn and 1.6 km²
    of Manhattan land (from the city's 2020 neighbourhood layer). No zone event occurs on either storm's
    days. Every event counted is a Flash Flood.
  - **Inside.** An event counts as inside when its begin point, its end point or one of its points in the
    locations file lies in the square. The one 2023 event inside (event 1135768, Williamsburg) has its begin
    and end points and its five locations-file points in the square. For Ida, none of the 12
    events in Kings and New York has a point in the square.
  - New reader: `sources/storm_events.py`.
- **311.**
  - **Fetch.** NYC Open Data `erm2-nwe9`, through the Socrata API, on 2026-11-26. The query took every
    request created on the storm days inside a latitude-longitude box round the square. The raw responses
    are cached in `data/cache/flood/nyc-311/<storm>/`, with `query.json` holding the query, the addresses
    and the fetch times. They are also listed in the facts file.
  - Time: `created_date` has no zone. It is read as New York wall-clock time, as written.
  - Place: the request's latitude and longitude lie in the square. Requests with no location cannot be
    placed. In the two boroughs as a whole there were 8 such flooding-related requests on the Ida days
    and 23 on 29 Sep 2023. They are not in the counts.
  - Flooding-related: street flooding, highway flooding, sewer backup, catch basin clogged, manhole
    overflow and water in basement, under both naming schemes (`FLOOD_TYPES` in `sources/nyc_311.py`).
    The mapping between the schemes is the lab's.
  - **Finding: the two schemes often hold the same request twice.**
    - On 29 Sep 2023, 104 of the 106 current-scheme rows in the square have a legacy-scheme row of the
      same kind.
    - Each twin was created 317 s or less after its partner, with a different `unique_key`. 95 of the
      pairs share an address; the other 9 lie within 25 m.
    - So counting rows of both schemes counts most requests twice: 225 rows, 121 requests.
    - The pairing rule (same kind; same address or within 25 m; within 600 s) is a proposed value **[P]**.
    - On the Ida days only the legacy scheme occurs in the square, so rows and requests are equal (69).
- **FloodNet.**
  - Sensors in service on a storm day, and those with an event that started on that day, New York time.
  - Ida: 1 sensor in service, none recorded. 29 Sep 2023: 7 in service, 5 recorded. These agree with the
    first part of F5.
- **USGS high-water marks.**
  - The Ida survey: 11 marks at 6 sites in the square, as in the first part of F5.
  - The cache holds no survey for 29 Sep 2023. Whether USGS surveyed marks for that storm was not checked:
    the STN service did not answer a probe.

### Figures

- `who_saw_counts.png`: one panel per source. Dark bars are the main count, light bars the context count.
- `who_saw_map.png`: one panel per storm.
  - Shown: Groundsource places centred in the square, 311 requests (twins drawn once), Storm Events points,
    FloodNet sensors and the marks.
  - Underneath, for orientation only, is the frozen F3 replay's maximum inundation depth of at least
    0.1 m.

## Limits

- FV3 gives no test of the model. The only published depth map does not reach the square.
- Groundsource places are named places, from parks to whole boroughs. The centroid rule keeps the small
  ones, so a large place that held the flood is only in the context count. The publisher's own review found
  60% of 400 rows accurate in both place and dates (facts `groundsource`).
- Storm Events counts entries by forecasters, by county. Most points lie outside the square even when the
  event names a place near it.
- 311 counts calls, not water. Its count depends on who calls and where. The twin rule is the lab's, and a
  pair across the square's edge would be counted twice.
- The storm windows are calendar days. Requests made the day after a storm are not counted.
- The 311 rows are those that the API returned on 2026-11-26. The table is updated daily.

## Checks

- `just lint` passes. `uv run pytest -q tests/flood` passes: 281 passed and 1 skipped. Of these, 12 tests
  are new, in `tests/flood/test_f5_who_saw.py`, on small made-up fixtures. They cover:
  - the Storm Events clock rule, zone events and the locations file;
  - 311 schemes, twins and the query text;
  - the Groundsource, FloodNet and mark counting;
  - the Jamaica Bay overlap and unit evidence, including depths in feet breaking the class bounds.
- `just site-flood` passes: 16 records, 32 sources.
- No solver, no F3 or F4 check, and nothing under `data/cache/flood/f4/` was run or touched.

## Models and tokens

| Task | Model | Tokens |
| --- | --- | --- |
| Coordination, brief | main session | not available |
| FV3 fetch and overlap, FV5 readers, check, figures, tests, facts, this report | Opus 5.5 (one agent, no sub-agents) | not available to the agent |
