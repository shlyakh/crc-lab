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
| CH-3 | 2026-11-25 | F0 fact checks | Corrections where a publisher differs from the requirements: 29 rows in requirements section 14 (marks and sites, lidar, substations, flood-map classes and format, Groundsource file, FloodNet clock, claims version and place, curve values, ICE terms, solver image, licences not stated) | FV1, FV3, FV5, FD2, FD3, FS1 to FS3, FH2, FH3, FH5, FR2, FR3, FM4, FM5, FT5, §7 to §9 | Nothing built on the wrong statements. Each is small; the open ones (Limited Flood map, storm duration, Williams values, ICE terms) are in the F0 report | proposed; decided at the F0 stop | 3 if accepted |

## Versions of the requirements

| Version | Date | Tag | What changed |
| --- | --- | --- | --- |
| 1 | 2026-11-25 | `flood-requirements-v1` | First reviewed version: moved to crc-sdk 1.0.0, source validation levels, flow diagrams, change procedure |
| 2 | 2026-11-25 | `flood-requirements-v2` | CH-1: loss statistics come from CRC. CH-2: the event-loss extension of CRC |
