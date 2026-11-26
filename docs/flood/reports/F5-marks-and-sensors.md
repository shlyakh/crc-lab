# F5 (first part). Validation against the surveyed marks and the sensors

Date: 2026-11-26 · branch `flood/f4` · crc-sdk 1.0.0, crc-framework 1.0.0 · SFINCS v2.5.0 · model frozen at F3
(constant loss rate 30 mm/h)

Stage F5 of `docs/flood/plan.md`, reduced for Demo 1 to the surveyed marks and the sensors (demo plan DP5,
CH-9). The Jamaica Bay map (FV3) and "who saw the flood" (FV5) come after Demo 1. Yuri asked for F5 to start in
the same session as F4 (2026-11-26). Numbers come from the record `f5` (`site/flood/tests/records/f5.json`);
the gallery shows it with its three figures. `just flood-f5` rebuilds it from the cache, offline.

## Result against the pass rule

| Rule (plan F5) | Result |
| --- | --- |
| The two second readers agree with their loaders (FS4) | **Pass.** Marks: 159 of 159 rows, every column, 0 differences. Radar rainfall of the Ida window: 29,750 of 29,750 values within 0.0000057 mm, the precision the file's packing and float32 storage allow; 17 of 17 file checksums match |
| A deliberate fault in each is caught | **Pass.** One height left in feet: differs. Hours shifted by one: differs. One cell plus 1 mm: differs |
| Model against observations | **Reported, not judged** (the plan forces no pass) |
| FV4: above 0.5 m RMSE the depth layer cannot support substation-level claims (*proposed* threshold) | **Not triggered.** Depth RMSE at the marks is 0.21 m |
| FV4: no retuning | **Kept.** No parameter changed; the replays are F3's |

## 1. Second readers (FS4)

Each was written by an agent that was not shown the loader.

- **USGS Ida high-water marks** (`src/flood_lab/reference/usgs_hwm.py`): the standard library's `csv` and
  pyproj, against the loader `src/flood_lab/sources/usgs_hwm.py` (pandas). Every mark is NAVD88; heights and
  elevations are in feet, converted with 0.3048 m. The metadata says US survey feet where the data dictionary
  says feet; the two differ by 2 parts per million (0.01 mm on a 4 m level), so this changes nothing.
  7 of the 159 marks have no height above ground; none of them is in the square.
- **MRMS radar rainfall, Ida window** (`src/flood_lab/reference/mrms.py`): ecCodes on the raw GRIB2 files,
  against the replay's rain file built with GDAL. The grid alignment is tight: shifting the window by one row
  or column gives differences of 18 mm and 11 mm. The meaning of the codes −1 and −3 comes from NSSL's product
  table (cached, checksum in the facts file); neither occurs in this window. **Not checked:** that each hour
  ends at its time stamp. The GRIB message carries no accumulation interval, so this rests on the product
  name, as in F3.

## 2. Ida against the surveyed marks (FV1)

11 marks at 6 sites lie in the square, all in two places: around Wallabout Street and Flushing Avenue (5
sites), and McCarren Park (1 site). Errors are model less surveyed, in metres.

| | n | Bias | RMSE | MAE |
| --- | --- | --- | --- | --- |
| Depth, per mark | 11 | −0.11 | **0.21** | 0.14 |
| Depth, per site | 6 | −0.10 | 0.18 | 0.13 |
| Water level (NAVD88), per mark | 11 | −0.09 | 0.23 | 0.17 |
| Depth, per mark, 6 unflagged marks | 6 | −0.06 | 0.18 | 0.12 |

- **Depth** (inundation depth) is the modelled water level less the model's ground at the mark's 1 m pixel (ground never below the
  cell's lowest sub-grid level, CH-21), against the surveyed height above ground. **Water level** compares
  the 5 m cell's peak level with the surveyed mark elevation; it also carries any error of the terrain.
- **Flags.** Five marks are flagged:
  - Two marks on a construction wall at Harrison Avenue fall inside a building footprint. There the model's
    ground is the raised roof, so the model reads 0 m against 0.34–0.40 m surveyed.
  - One mark is in a cell with a building at its centre, and its quality is Poor.
  - The two McCarren Park marks have a survey uncertainty of 0.15 m.
  - No mark lies in a cell the model leaves dry.
- **The published figure.** Kasaei et al. 2025 (HESS 29:2043) report 0.20 m for their Jamaica Bay model of
  Ida. That figure is the error after calibrating on 8 marks: a fitted figure, not an independent test. The
  same model had 0.40 m before calibration. This model's constant loss rate (the water the sewers and the
  ground take away) was calibrated on the city's flood maps,
  not on marks. **Its 0.21 m is therefore an independent test**, on a smaller and clustered sample.
- **What it supports.** The marks sit 2.6–3.2 km east of the two lead substations (Farragut and Hudson
  Avenue), in other neighbourhoods. They show that the model reproduces Ida's depth where it was measured. They do not
  measure the error at the substations themselves.

## 3. Sensors (FV2)

| Storm | In service in the square | Recorded | Error at the pixel (bias / RMSE) |
| --- | --- | --- | --- |
| Ida, 1 Sep 2021 | 1 | 0 | none to compare |
| 29 Sep 2023 | 7 | 5 | −0.08 m / 0.19 m |

- **29 September 2023.** The five sensors measured peaks of 0.30–0.64 m; the model gives 0.16–0.69 m at their
  pixels. The largest misses are Walton Street and Marcy Avenue (0.55 m measured, 0.24 m modelled) and Kent
  Avenue and Wallabout Street (0.30 against 0.16 m).
  - **Positions.** Sensor positions are approximate. The deepest modelled depth within 10 m is shown beside
    the pixel's value and gives a bias of +0.20 m, so the model's answer depends on the exact spot by about
    as much as its error.
  - **My expectation was wrong.** Before this check I said the model might fall well short of the sensors
    on 29 September 2023, because the F3 replay left the substation sites under 0.04 m. It does not: the
    sensors stand in the Wallabout low ground, where that storm's water gathers in the model too.
- **Two sensors in service recorded nothing.** At Wallabout Street and Harrison Avenue the model has 0.68 m,
  and at Wythe Avenue 0.15 m. A sensor recording nothing does not prove the street was dry (the sensor may
  have been offline). It is reported, not counted as an error.
- **Profiles.** The cached FloodNet table carries each event's depth profile, so the figure shows the
  measured depth through each event against the modelled peak. The model's own time series at the sensors
  is not drawn.

## 4. What this means for Demo 1

- **Depths at the lead substations can be shown with an error statement:** about 0.2 m RMSE at the 11
  surveyed marks and the 5 sensors. That is as good as the published model's fitted figure, from a test the
  model was not tuned on. Bias is slightly low (−0.06 to −0.11 m).
- **Limits.**
  - The sample is small and clustered: 6 mark sites and 5 sensors, in two neighbourhoods.
  - It covers one storm with marks (Ida) and one storm with sensors (29 Sep 2023).
  - The model was not tested near the substations.
  - Marks were surveyed weeks after the storm, and their positions are phone fixes.

## Checks

- `just test` and `just lint` pass: 267 flood tests, of which 27 are new and include the deliberate faults.
- `just site-flood` passes: 15 records.

## Models and tokens

| Task | Model | Tokens |
| --- | --- | --- |
| Scope, contracts for the second readers, feasibility counts, verification of each agent's result, report | Opus 5.5 (main session) | not available to the session |
| Mark loader, F5 check, figures, tests | Opus | 173,604 |
| Second reader, marks | Sonnet | 43,349 |
| Second reader, radar rainfall | Opus | 74,204 |
