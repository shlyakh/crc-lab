# F5 (second part). The Jamaica Bay map and who saw the flood

Date: 2026-11-26 · branches `flood/f5b`, then `flood/f5c` (sections 3 to 5) · crc-sdk 1.0.0,
crc-framework 1.0.0 · model frozen at F3 (constant loss rate 30 mm/h)

The second part of stage F5 in `docs/flood/plan.md`: FV3 (the published Jamaica Bay depth map) and FV5 ("who
saw the flood"). The first part, on the surveyed marks and the sensors, is `F5-marks-and-sensors.md`.
Yuri asked for this part on 2026-11-26. The numbers here come from the record `f5-who-saw`
(`site/flood/tests/records/f5-who-saw.json`). The gallery shows the record with its three figures.
`just flood-f5-who-saw` rebuilds it offline from the cache. No solver was run, and no parameter was changed
(FV4).

Yuri asked for three refinements the same day (F5c): combine reports of the same flooding into sightings
(section 3), look for late 311 calls after each storm (section 4), and count Groundsource places near the
square, with one map per storm (section 5). The record keeps its id. It gains new tables and figures; the
earlier counts do not change.

## Result against the pass rule

| Rule | Result |
| --- | --- |
| FV3: compare with the Jamaica Bay map where it overlaps the square, using the shapefile | **Not applicable.** None of the map's 109,875 points lies in the square. The map's cells cover 0 m² of it. The nearest point is 2,046 m south of the square |
| FV3: the shapefile is the publisher's | **Pass.** The .shp, .shx, .dbf, .prj and .cpg files match the SHA-256 checksums in the Mendeley record. So do the other four files |
| FV5: counts and locations for each storm from five sources, on one chart and one map | **Reported, not judged** (table below; figures `who_saw_counts.png`, `who_saw_map.png`) |
| FV5 / FT5 facts row: Storm Events clock rule stated; zone events read | **Done.** See section 2 |
| FV5 / FT5 facts row: 311 counts both naming schemes | **Done, with a finding.** On 29 Sep 2023 most requests appear once under each scheme. Section 2 |
| F5c: reports of the same flooding combined into sightings, every member kept | **Reported.** Ida: 68 sightings from 69 requests and 11 marks. 29 Sep 2023: 91 sightings from 121 requests and 5 FloodNet events. Section 3 |
| F5c: late 311 calls against dry days | **Ida: the day after is clearly above the baseline (18 requests; dry-day mean 1.67, maximum 5). 29 Sep 2023: it is not (3; mean 1.95, maximum 7).** Section 4 |
| F5c: Groundsource places by relation to the square | **Reported.** Main count unchanged: centroid inside (10 and 11). Section 5 |
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
    - Each twin was created 189 s or less after its partner (317 s before the pairing fix of the review), with a different `unique_key`. 95 of the
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
- The single map `who_saw_map.png` is replaced by one map per storm (section 5).

## 3. Sightings: reports of the same flooding combined

Several reports can describe one flooding: two callers about one flooded corner, a call at a FloodNet sensor,
a surveyed mark beside a call. The new module `src/flood_lab/observations/sightings.py` combines them. Its
rule statement is in the module and in the record (`tables.sighting_rule`). `docs/algorithms.md`
holds the hail project's algorithms only, with no flood entries, so none was added there.

**The rule.**

1. **Observation.** One report of water at a place and time: its source, an id with the row ids it stands
   for, a kind, a time window on the New York clock, and a position in metres (EPSG:32618). The point
   sources are:
   - 311 requests (time: `created_date`);
   - FloodNet events at sensors in the square that started on a storm day (time: start to end);
   - USGS marks in the square. A mark has no time, so it spans the storm days.
2. **Duplicates, the strict case.** Rows that record one report twice are paired first: the 311 twin rows
   of section 2. The pairing is now `sightings.duplicate_pairs`, and `nyc_311.twins` calls it. The rule is
   the same: other scheme, same kind, created within 600 s **[P]**, same address or within 25 m **[P]**,
   closest in time first, each row used once. A pair becomes one observation that keeps both row ids.
3. **Near, the general case.** Two observations are near when they lie within 50 m **[P]** of each other
   and their time windows are within 12 h **[P]**. Sources and kinds may differ.
4. **Sighting.** Observations joined by a chain of near pairs form one sighting (single linkage: A near B
   and B near C makes one sighting even if A is far from C). Every member is kept with its source and row
   ids. The record gives each sighting's extent, the largest distance between two members, so a long chain
   would show.
5. **Area reports.** Groundsource places and Storm Events events name an area, not a spot. They join no
   sighting and link none. Each sighting lists the area reports whose shape holds one of its members:
   - Groundsource: the polygon of a place centred in the square, on the storm days;
   - Storm Events: the hull of the points of an event with a point in the square, over its begin to end.

A sighting says that these reports are close enough to be about one flooding. It does not prove that they
are.

**Counts per storm** (record `tables.sightings_summary`):

| | Ida, 1-2 Sep 2021 | 29 Sep 2023 |
| --- | --- | --- |
| 311 rows, both schemes | 69 | 225 |
| 311 requests, twins paired | 69 | 121 |
| Observations: 311 requests, FloodNet events, marks | 69 + 0 + 11 = 80 | 121 + 5 + 0 = 126 |
| **Sightings** | **68** | **91** |
| of more than one observation | 9 | 18 |
| of more than one kind | 3 | 10 |
| of more than one source | 1 | 4 |
| largest: observations, extent | 3, 54.4 m | 5, 51.7 m |
| inside a Groundsource place centred in the square | 45 | 57 |
| inside the hull of a Storm Events event | 0 | 7 |

**Sightings by the sources that saw them:**

| Sources | Ida, 1-2 Sep 2021 | 29 Sep 2023 |
| --- | --- | --- |
| 311 only | 62 | 86 |
| marks only | 5 | 0 |
| 311 and marks | 1 | 0 |
| FloodNet only | 0 | 1 |
| 311 and FloodNet | 0 | 4 |

- In 2023, four of the five FloodNet sensors that recorded an event have 311 calls within 50 m in the same
  hours. For example, sighting `sep29_2023-002` holds the event at Wallabout St and Throop Ave and three
  street-flooding calls, all within 13.9 m of each other.
- On Ida, one mark site (two marks) and a sewer-backup call form sighting `ida_2021-006`, 54.4 m across. The 11 marks fall
  into 6 sightings, one per site.

**Sensitivity to the two thresholds.** Number of sightings (record `tables.sightings_sensitivity`). In
brackets: the same with kinds kept apart, so that only reports of one kind combine.

| Distance | Ida, 1 h | Ida, 3 h | Ida, 12 h | Ida, 24 h | 2023, 1 h | 2023, 3 h | 2023, 12 h | 2023, 24 h |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 m | 79 (80) | 79 (80) | 79 (80) | 77 (78) | 120 (122) | 116 (118) | 116 (118) | 116 (118) |
| 25 m | 73 (74) | 72 (73) | 71 (72) | 69 (70) | 109 (118) | 102 (111) | 99 (108) | 98 (108) |
| 50 m | 72 (74) | 71 (73) | **68** (72) | 65 (70) | 103 (113) | 95 (106) | **91** (103) | 90 (103) |
| 100 m | 68 (71) | 66 (69) | 60 (65) | 58 (63) | 88 (107) | 80 (100) | 76 (93) | 75 (93) |
| 200 m | 64 (69) | 61 (67) | 50 (61) | 40 (57) | 76 (97) | 63 (85) | 49 (71) | 49 (71) |

- From 0 m to 50 m the count falls by 11 for Ida and by 25 for 2023 (at 12 h). Beyond 50 m it keeps
  falling, as separate floodings on nearby streets start to join.
- The time threshold matters less than the distance up to 50 m. In 2023 almost all calls came within a few
  hours, so 12 h and 24 h give nearly the same count.
- The proposed values, 50 m and 12 h, are marked **[P]**. They follow the brief's "a few tens of metres".

**Fit with the label fusion of F8 (FT5, FT6).** Sightings do not replace the per-source labels of FT5. A
source still says "flood here on this day" when it has at least one report. Sightings give F8 two things: a
count of distinct floodings in place of a count of calls, and which sources saw the same flooding, which is
the agreement a latent-class model reads. Area reports are kept apart, as FT6 treats a missing news report
as unlabelled, not as negative.

## 4. Late calls: the days after each storm

**Question.** Do flooding calls keep coming the day after a storm, above what an ordinary day brings?

**Data.**

- **311.** The flooding-related requests of the same 12 types, placed in the same box, for four weeks each
  side of each storm: 2021-08-04 to 2021-09-29 and 2023-09-01 to 2023-10-27. A new query of the same
  endpoint, with the flooding types in the query (`nyc_311.fetch_flood`), fetched on 2026-11-26 at
  22:00 UTC. Raw pages and `query.json` are cached under `data/cache/flood/nyc-311/around_<storm>/`.
  The counts are inside the square, with twin rows paired. The storm-day counts equal those of section 2
  (29 and 40; 121).
- **Rain.** The cached MRMS hours cover only the storm hours, and the AORC copy is in the F4 cache, which
  this work may not touch. So dry days were chosen from GHCN-Daily rain (NOAA NCEI) at Central Park,
  LaGuardia and JFK, 8.2 to 18.4 km from the square's centre. New reader `sources/ghcn_daily.py`, new facts
  file `ghcn-daily.toml` and data card. Fetched 2026-11-26 at 22:01 UTC.
- **Dry day [P].** Less than 1 mm at every station on the day and on each of the two days before. Days
  with no report are not dry.
- **Baseline.** The dry days of the four weeks each side, other than the storm days and the 7 days after
  **[P]**. A week is kept out because Ida's calls stayed raised for about a week (figure).
- **Clearly above [P].** More requests than on any baseline day, and at least twice the baseline mean.

**Result** (record `tables.late_calls`):

| Day | Rain, mm (largest of 3 stations) | 311 requests (rows) | Same weekday, dry days | Clearly above? |
| --- | --- | --- | --- | --- |
| **Ida** baseline: 18 dry days, mean 1.67, median 1.0, maximum 5 | | | | |
| Wed 1 Sep 2021, storm | 181.1 | 29 (29) | 2, 3 | yes |
| Thu 2 Sep 2021, storm | 5.3 | 40 (40) | 1, 1, 3 | yes |
| Fri 3 Sep 2021, day 1 after | 0.0 | **18** (18) | 1, 1 | **yes** |
| Sat 4 Sep 2021, day 2 after | 0.0 | 8 (8) | 0, 2, 0 | yes |
| **29 Sep 2023** baseline: 20 dry days, mean 1.95, median 2.0, maximum 7 | | | | |
| Fri 29 Sep 2023, storm | 204.5 | 121 (225) | 1, 2, 2 | yes |
| Sat 30 Sep 2023, day 1 after | 5.6 | **3** (6) | 1, 3 | **no** |
| Sun 1 Oct 2023, day 2 after | 0.0 | 6 (11) | 0 | no |

- After Ida, the day after holds 18 requests, more than ten times the baseline mean (1.67). The second day holds 8,
  still above every dry day.
- After 29 Sep 2023 the next two days are within the range of dry days.
- Figure `late_calls.png` shows every day of the eight weeks.

**With the day after added** (record `tables.extended_window`; the counts of sections 2 and 3 do not use
it):

| | Ida, 1-3 Sep 2021 | 29-30 Sep 2023 |
| --- | --- | --- |
| 311 rows | 87 | 231 |
| 311 requests | 87 | 124 |
| sightings | 85 | 94 |

**Recommendation.** Extend each storm's 311 window by the day after its last storm day, for both storms, as
one rule: Ida 1 to 3 September 2021, the other storm 29 and 30 September 2023. The rule is simple and
uniform, and it catches Ida's 18 late requests. For 2023 it adds 3 requests, about what a dry day brings
(mean 1.95). A second day is not proposed: it is above the baseline only for Ida (8 requests), and each
day added brings about two ordinary requests (the baseline mean) to every storm. The window used in this record is
unchanged until Yuri decides.

## 5. Groundsource near the square, and the maps

**Relation of each place to the square** (record `tables.groundsource_relations`). Places of the storm
days, read from the publisher's file with a box 0.01° wider than the square on each side. Distance is
between the place polygon and the square in EPSG:32618; a place that overlaps is at 0 m. Each row counts
the places of the rows above it too.

| Relation | Ida, 1-2 Sep 2021 | 29 Sep 2023 |
| --- | --- | --- |
| **centroid inside the square (main count)** | **10** | **11** |
| overlapping the square | 20 | 26 |
| within 250 m **[P]** | 23 | 32 |
| within 500 m **[P]** | 27 | 36 |
| the same four, places no larger than the square (16 km²) | 10, 16, 19, 23 | 11, 22, 28, 32 |

**Why the centroid stays the main count.**

- A Groundsource polygon is the place a news report named, not the flood. A place whose centre lies in the
  square is a place mostly about the square.
- "Overlapping" adds places much larger than the square: 4 in each storm, the largest 3,438.8 km². Their overlap
  says nothing about where in the square the water was.
- "Within 250 m" and "within 500 m" add places that only border the square, such as the next
  neighbourhood. They are context, not reports from the square.
- The centroid rule gives one point per place, like the point sources, and it is the rule of section 2, so
  the earlier count stands.
- Its weakness: a small place that straddles the edge, with its centre just outside, is left out. The
  "no larger than the square" row shows how many such places there are.

**Maps.** `who_saw_map_ida_2021.png` and `who_saw_map_sep29_2023.png`, one per storm, replacing
`who_saw_map.png`.

- Background: that storm's modelled maximum inundation depth from 0.05 m (frozen F3 replay), on a colour
  scale. For orientation only; nothing is compared.
- Shown: 311 requests (a twin pair drawn once), sightings of more than one report as rings (with the number
  of reports for three or more), FloodNet sensors (filled when they recorded an event), USGS marks,
  Groundsource places (solid when centred in the square; dashed when within 500 m and no larger than the
  square) and the hull of the Storm Events event with a point in the square.
- The 2023 map draws the 2023 replay, not Ida's (open question 1).

## Limits

- FV3 gives no test of the model. The only published depth map does not reach the square.
- Groundsource places are named places, from parks to whole boroughs. The centroid rule keeps the small
  ones, so a large place that held the flood is only in the context count. The publisher's own review found
  60% of 400 rows accurate in both place and dates (facts `groundsource`).
- Storm Events counts entries by forecasters, by county. Most points lie outside the square even when the
  event names a place near it.
- 311 counts calls, not water. Its count depends on who calls and where. The twin rule is the lab's, and a
  pair across the square's edge would be counted twice.
- The storm windows are calendar days. Requests made the day after a storm are not counted. Section 4
  measures what this misses and proposes adding the day after.
- Sightings are the lab's grouping. Two floodings 40 m apart in the same night become one sighting; one
  flooding reported 60 m apart becomes two. The sensitivity table shows how much this moves the count.
- The dry days come from three gauges 6 to 16 km from the square's edge. Rain on the square alone would
  be missed.
- The 311 rows are those that the API returned on 2026-11-26. The table is updated daily. The rows for
  the late calls were fetched about an hour after the storm rows; the storm-day counts agree.

## Checks

- First part (`flood/f5b`): `just lint` passed; `uv run pytest -q tests/flood` gave 281 passed and 1
  skipped; 12 new tests in `tests/flood/test_f5_who_saw.py`; `just site-flood` passed with 16 records and
  32 sources.
- F5c (`flood/f5c`): `just lint` passes. `uv run pytest -q tests/flood` passes: 291 passed and 1 skipped.
  Of these, 10 tests are new, in `tests/flood/test_sightings.py`, on small made-up fixtures:
  - exact twins become one observation that keeps both row ids, and a later caller joins as a near report;
  - a duplicate with one candidate pairs with the closest, and two requests at one address are not paired
    crosswise (added after the review);
  - a chain A near B near C is one sighting, and breaks at a tighter distance;
  - different kinds and sources at one spot combine, and stay apart when kinds are kept apart;
  - the same spot on different days stays apart, and a mark joins a call at its spot;
  - grouping does not depend on order, and a disc's radius counts;
  - area reports hold members but link nothing;
  - the dry-day rule, the late-call baseline and the Groundsource distances.
- `uv run python -m flood_lab.gallery` and `just site-flood` pass: 16 records, 33 sources (GHCN-Daily is
  new).
- Review: a fresh Opus agent reviewed the F5c code blind (without this report). It found distances in
  metres, time zones, GHCN units, day windows, grouping and counts correct, checked on the cached data.
  Fixed: twins were paired closest-first, which at 296 Broadway (29 Sep 2023) paired two requests
  crosswise; they are now paired by one assignment over all candidates. No count changes; the largest
  twin gap is 189 s, was 317 s. Not fixed, stated: the dry-day baseline excludes the week after this
  storm only, so a day after Henri (22-23 Aug 2021) can enter the Ida baseline (one request on 26 Aug).
- No solver, no F3 or F4 check, and nothing under `data/cache/flood/f4/` was run or touched.

## Open questions

1. The brief asks for the model's Ida depth under every map. Each map draws its own storm's replay. Should
   the 2023 map show Ida's depth instead?
2. Extend the 311 window by the day after (section 4)? If yes, CH-24 says so and the main counts move to
   the extended window.
3. Should the sighting rule carry over to F8 with 50 m and 12 h, or should F8 tune them on more storms?
4. GHCN-Daily is a new source. It needs a row in the requirements' source table, through the change log.

## Models and tokens

| Task | Model | Tokens |
| --- | --- | --- |
| Coordination, brief (both parts) | main session | not available |
| First part: FV3 fetch and overlap, FV5 readers, check, figures, tests, facts, report | Opus 5.5 (one agent, no sub-agents) | not available to the agent |
| Blind review of F5c, and the pairing fix (fix by the main session) | Opus | 80,901 |
| F5c: sighting module, late-call fetch and baseline, GHCN-Daily reader and facts, Groundsource relations, maps, tests, this report | Opus 5.5 (one agent, no sub-agents) | not available to the agent |
