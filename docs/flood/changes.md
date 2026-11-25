# Flood lab: proposed changes to the requirements

How a new data source, a technique or a correction enters `docs/flood/requirements.md` after version 1.
The requirements stay open to outside evaluation while the lab is built; this file is where its results
arrive.

## Procedure

1. Anyone adds a row below at any time. Yuri's outside evaluations go here, either entered by him or
   handed over and entered for him.
2. A row is not acted on in the middle of a stage, with one exception: if it shows the current stage is
   building on something wrong, the stage stops and says so.
3. At each stage stop every open row is assessed: which finished stages would have to be run again, what
   changes in later stages, the hours and data it adds, and whether a new source needs the fact check of
   FS6 or a second reader (FS4).
4. Yuri decides: **accepted** (the requirements get the next version number and the row records it),
   **deferred** to a tier or stage, or **declined** with the reason kept.
5. Requirement IDs are never reused or renumbered. A withdrawn requirement keeps its ID with "withdrawn in
   version n".

## Proposals

| ID | Date | From | What | Requirements touched | Assessment | Decision | Entered in version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CH-0 | 2026-11-25 | example | *Example row, not a proposal:* add a second rainfall record as a check on the catalogue | FH5, §7 | F4 not started, nothing to re-run; one more download and data card, about 2 h; needs FS6 | none | none |
| CH-1 | 2026-11-25 | Yuri | Correction: version 1 said exceedance curves, VaR and CVaR are `flood_lab` code. CRC 1.0.0 has them: a loss distribution is a `Distribution` (`empirical`, `exceedance`, `quantile`, `statistics` with CVaR, `to_json`), and `Impact.pushforward` gives an asset's damage distribution. Only the event-loss table and the sums across assets per event and year are the lab's | D3, FR5, FR6, FR8, §10, flow diagram, mapping | Nothing built, nothing to re-run. Less own code in F6, same hours. Checked by a run on made-up numbers against numpy | accepted | 2 |
| CH-2 | 2026-11-25 | Yuri | Build the event-loss table and the adding of losses of assets that flood together as an extension of CRC, usable with it and offered upstream later after review, not as lab code | New D17, FR9 to FR12; FG1, FR4, FR5, §10, flow diagram, mapping; plan F6 | Nothing built, nothing to re-run. A package of its own with a design note; reads upstream pull requests #47 and #27 first. F6 from 10 to 13 h | accepted | 2 |
| CH-3 | 2026-11-25 | F0 fact checks | Corrections where a publisher differs from the requirements: 29 rows in requirements section 14 (marks and sites, lidar, substations, flood-map classes and format, Groundsource file, FloodNet clock, claims version and place, curve values, ICE terms, solver image, licences not stated) | FV1, FV3, FV5, FD2, FD3, FS1 to FS3, FH2, FH3, FH5, FR2, FR3, FM4, FM5, FT5, §7 to §9 | Nothing built on the wrong statements. Each is small; the open ones (Limited Flood map, storm duration, Williams values, ICE terms) are in the F0 report | accepted | 3 |
| CH-4 | 2026-11-25 | F0 stop | Decisions at the F0 stop: study area (D1) is the Williamsburg square; D2 and D12 confirmed; monotonicity rule of FH8 given a 1 mm tolerance; substations counted as sites, rail traction left out (FD3); the Limited Flood map tried through ESRI's library in F2 with calibration on the Moderate map alone as the fallback; outage cost through the ICE Calculator's public API with customer-hours beside it (FM5); the catalogue confirmed at 150 runs (D9) | D1, D2, D9, D12, FD3, FH3, FH8, FM5 | F0 was built before these; nothing to re-run except the solver record's verdict | accepted. Yuri chose the area and said to proceed; the others follow the recommendations of the F0 report and can be reversed | 3 |
| CH-5 | 2026-11-25 | F1 build and its review | FD3: a named substation is one asset (the code's rule), with neighbours' distances recorded; FD5: a building's value is the sum of its inventory records, and an unmeasured value stays empty; FD6: Open Exposure Data 5.0.0, and no placeholder in an OED column | FD3, FD5, FD6 | F1 rebuilt with these rules before its stop | accepted | 4 |
| CH-6 | 2026-11-25 | F1 stop | Decisions at the F1 stop, all as the F1 report recommended: the 95% match rule is judged on buildings proper, garages being outside the city's elevation table; the four Con Edison substations at Vinegar Hill are the study's substation case, as one complex; substation values stay a labelled placeholder range for the first public version (answers question 4 of section 12); buildings with no value stay without a loss until F6 shows how many get wet; building values summed over inventory records, with the split by how the records are tied shown | FD4, FD5, plan F1 pass rule, §12 question 4 | The assets record was rebuilt with the rule on buildings proper | accepted by Yuri ("agree with recommendations") | 4 |
| CH-7 | 2026-11-25 | F2 build and its stop | FS1: the Limited Flood map is read from an export made through ESRI's File Geodatabase library (Apache 2.0), with a proof on the Moderate map and a reading of its one curved segment; FH3 calibrates on the Limited and Moderate maps. FS3: in CRC the sensor is support and station, and the lab's table holds duration; peak depth is the publisher's column, with the events whose profile disagrees flagged. FS2: the dated places stay in the cache until the page needs them. FS4: the Limited map's second reader covers the step from the export to the grid | FS1 to FS4, FH3, §14 | F2 built with these; nothing to re-run | accepted by Yuri ("2-6 agree") | 5 |

## Versions of the requirements

| Version | Date | Tag | What changed |
| --- | --- | --- | --- |
| 1 | 2026-11-25 | `flood-requirements-v1` | First reviewed version: moved to crc-sdk 1.0.0, source validation levels, flow diagrams, change procedure |
| 2 | 2026-11-25 | `flood-requirements-v2` | CH-1: loss statistics come from CRC. CH-2: the event-loss extension of CRC |
| 5 | 2026-11-25 | `flood-requirements-v5` | CH-7: the Limited Flood map is read; decisions at the F2 stop |
| 4 | 2026-11-25 | `flood-requirements-v4` | CH-5: asset rules as built in F1. CH-6: decisions at the F1 stop |
| 3 | 2026-11-25 | `flood-requirements-v3` | CH-3: corrections from the F0 fact checks (section 14). CH-4: decisions at the F0 stop, the study area among them |
