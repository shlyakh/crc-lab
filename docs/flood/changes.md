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
| CH-5 | 2026-11-25 | Yuri, demo plan | Run the full 150-storm catalogue unattended from the calibration freeze; keep every run's whole peak-depth grid and storm descriptors as training data for the emulator; figures made before the catalogue completes print the number of storms used (at least 60) and are rebuilt afterwards (`docs/flood/demo-plan.md`, DP4) | FH5, FH7, FG10, FE1; plan F4, F6 | F4 not started, nothing to re-run. More disk for whole grids: check against the F0 budget before starting | open | none |
| CH-6 | 2026-11-25 | Yuri, demo plan | F5 in two parts: surveyed marks and sensors before 2026-12-01; "who saw the flood" (FV5) after | FV5; plan F5 | Nothing built. Splits the stage; no change in total hours | open | none |
| CH-7 | 2026-11-25 | Yuri, demo plan | New FM7: a break-even view. Benefit-cost ratio as a function of replacement value, the placeholder range of FD4 shaded, the break-even value marked, at 7% and 3.1%; results that need no replacement value (damage ratio, loss as a share of value) shown apart from those that do (DP7) | New FM7; FD4, FM3, FM4, FP3; plan F7 | F7 not started. About 2 h | open | none |
| CH-8 | 2026-11-25 | Yuri, demo plan | New FA1 to FA5, a thin prototype of composable assets, after F7 passes and time-boxed to 5 h. FA1: one substation as three components (control house, switchgear, transformers), each with a height above ground, a share of value and its own depth-damage curve. FA2: whole-asset damage is the value-weighted sum of component damage, computed through CRC impact functions. FA3: a recombination test, the components together must reproduce the single-curve Hazus-type result of FR2 within a stated tolerance, or the difference is reported. FA4: a measure applied to one component only. FA5: value shares and per-component curves are placeholders **[P]** on every figure unless a source is found; a proposal note on how CRC 1.0.0 would express a composite asset is written whether or not the prototype is built (DP6) | New FA1 to FA5; FR2, FM1, FM2, D17 | Nothing built. 5 h, cut first if F7 is late. No new data source unless component curves are sourced, which would need FS6 | open | none |
| CH-9 | 2026-11-25 | Yuri, demo plan | F8 deferred until after 2026-12-01; the 2023-09-29 trigger panel (FT4) may be pulled forward if F7 and the prototype finish early. F9 moves ahead of F10 and F11's full form, for a second demo on 2026-12-04 (DP3, DP10) | D13; plan order, F8, F9 | Changes the order of Tier 1 and brings one Tier 2 stage forward; D13 said tiers 2 and 3 are decided at the F8 stop, so this needs Yuri's decision recorded | open | none |
| CH-10 | 2026-11-25 | Yuri, demo plan | F11 in two parts. Before 2026-12-01: lead-substation card, loss curves, break-even chart, flow diagram, test gallery. New FP10: a single-asset path that re-runs F6 and F7 for one substation and one raise height in under a minute and regenerates its card and test record. The storm player (FP2) and the rest after. Daily review in place of a stop after every stage: a stage whose checks pass may proceed; a failing check, a differing fact or a number that would have to be invented still stops (DP8, DP11) | FG6, FP1 to FP9, new FP10; D11, D14; plan "A stage" | Changes the way of working, so it needs Yuri's explicit decision. FP10 about 2 to 3 h | open | none |

## Versions of the requirements

| Version | Date | Tag | What changed |
| --- | --- | --- | --- |
| 1 | 2026-11-25 | `flood-requirements-v1` | First reviewed version: moved to crc-sdk 1.0.0, source validation levels, flow diagrams, change procedure |
| 2 | 2026-11-25 | `flood-requirements-v2` | CH-1: loss statistics come from CRC. CH-2: the event-loss extension of CRC |
| 3 | 2026-11-25 | `flood-requirements-v3` | CH-3: corrections from the F0 fact checks (section 14). CH-4: decisions at the F0 stop, the study area among them |
