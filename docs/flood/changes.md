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

## Versions of the requirements

| Version | Date | Tag | What changed |
| --- | --- | --- | --- |
| 1 | 2026-11-25 | `flood-requirements-v1` | First reviewed version: moved to crc-sdk 1.0.0, source validation levels, flow diagrams, change procedure |
