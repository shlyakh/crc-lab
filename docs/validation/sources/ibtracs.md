# IBTrACS tropical cyclone tracks: assessment

Generated from the records of the run of 2026-11-24T23:38:04Z against crc-framework 1.0.0, crc-sdk 1.0.0. **Draft: not yet reviewed.**
Do not edit: change the source file or re-run the assessment and rebuild.

- **What the framework adds:** Nothing is added to the values, and no unit is converted. crc-sdk downloads NOAA's file of all storms (ALL), keeps a checksummed copy, and for one agency returns two rows per track point: the agency's wind in knots and its pressure in hPa, as numbers, at IBTrACS's combined position, with longitudes moved into -180..180 and an H3 cell. A point the agency did not report keeps its rows, with no value and a failure code. Of NOAA's 174 columns six are read; the season, basin, name, track type and the agency's own position are not returned. Licence text, attribution, checksum and retrieval time travel with the output.
- **How it is compared:** NOAA's ALL file is downloaded independently and read with Python's csv module; for each of the ten agencies every row crc-sdk returns is recomputed from the file and compared field by field, in order (about 1.46 million rows per agency). The address, the bytes, the declared units and the provenance attached to the output are checked separately.
- **Purpose (the framework's documentation):** Native storm point observations for one reporting agency: its maximum sustained wind and minimum central pressure at each track point, as published, for inspection. Not asset winds or return-period curves.
- **Publisher:** NOAA NCEI · https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv
- **Entry points:** `IBTrACS`
- **Status:** exploration assessed, verification assessed, validation not assessed
- **Options, agency:** assessed BOM, CMA, HKO, NADI, NEWDELHI, REUNION, TOKYO, USA, WELLINGTON, WMO; not assessed none

## Exploration

### What is in the publisher's file

Counted from NOAA's ALL file by the reference reader.

| File | Rows | Storms | Seasons | Columns | Values missing | Last modified by publisher |
| --- | --- | --- | --- | --- | --- | --- |
| ALL | 730,694 | 13,637 | 1842 to 2027 | 174 | 82.4 % | Sun, 22 Nov 2026 14:58:29 GMT |

### What crc-sdk returns for each agency

Points and values counted from NOAA's file by the reference reader; rows and rows without a value as crc-sdk's report gives them. crc-sdk returns two rows per point of the file for every agency, with or without a value.

| Agency | Points in the file | Points with a wind | Points with a pressure | Storms with a value | Rows from crc-sdk | Rows without a value |
| --- | --- | --- | --- | --- | --- | --- |
| USA | 730,694 | 406,177 | 171,210 | 7,336 | 1,461,388 | 884,001 |
| TOKYO | 730,694 | 51,285 | 135,074 | 1,965 | 1,461,388 | 1,275,029 |
| CMA | 730,694 | 133,126 | 144,910 | 2,525 | 1,461,388 | 1,183,352 |
| HKO | 730,694 | 86,262 | 86,262 | 1,909 | 1,461,388 | 1,288,864 |
| NEWDELHI | 730,694 | 9,467 | 8,605 | 405 | 1,461,388 | 1,443,316 |
| REUNION | 730,694 | 34,288 | 33,626 | 503 | 1,461,388 | 1,393,474 |
| BOM | 730,694 | 42,162 | 55,193 | 1,090 | 1,461,388 | 1,364,033 |
| NADI | 730,694 | 7,829 | 8,151 | 194 | 1,461,388 | 1,445,408 |
| WELLINGTON | 730,694 | 23,472 | 23,285 | 431 | 1,461,388 | 1,414,631 |
| WMO | 730,694 | 170,343 | 174,031 | 7,474 | 1,461,388 | 1,117,014 |

Assessed by default: no selection, each agency read in full. The output covers every point of the file for every agency, so most rows of most agencies carry no value. The position is the combined LAT and LON of IBTrACS, not the agency's own position columns. Times are ISO_TIME with a T and no zone designator; NOAA's times are UTC. Where a track crosses the date line NOAA's longitudes exceed 180 (up to 266.9); crc-sdk moves them into -180..180. It does so by arithmetic on every longitude, so for many points (350,339 of 730,694 in the file of 2026-11-24) the delivered longitude is not the number nearest to NOAA's decimal value but differs from it by at most 3e-14 degrees; the identifier, which hashes the position, then cannot be rebuilt from NOAA's text. In NOAA's file SEASON runs to 2027 because southern-hemisphere seasons are labelled by their second year; crc-sdk does not return it.

## What the framework does (transformation statement)

| Step | What crc-sdk does | Code | Outcome |
| --- | --- | --- | --- |
| address | Requests one file for every agency: `<root>/ibtracs.ALL.list.v04r01.csv`, NOAA's file of all storms. No basin or period file can be chosen. | crc_sdk/_observed_sources.py:113, 923-930 | **confirmed** |
| bytes | Saves the response unchanged and identifies it by the SHA-256 of its bytes. No announced length or publisher checksum is compared. | crc_sdk/_source_io.py:261-289, 383-400 | **confirmed** |
| cache | `Runtime()` keeps no cache, so every read downloads the file again. With `Cache.reuse(path)` a file already indexed for the address is served by its recorded checksum without asking NOAA whether it has changed; `Cache.offline(path)` never downloads and fails if the file is not cached; `Cache.refresh(path)` downloads again. | crc_sdk/_runtime.py:167; crc_sdk/_source_io.py:325-382 | **not checked**. Read in the code, not shown on data: showing that a reused copy is stale needs NOAA to change the file between two runs. Left to monitoring. |
| columns | Reads six of NOAA's columns: SID, ISO_TIME, LAT, LON and the agency's `<AGENCY>_WIND` and `<AGENCY>_PRES`; the read fails if one is absent. The other columns (season, basin, name, nature, track type, distance to land, the agency's own position and radii) are not returned. | crc_sdk/_observed_decoders.py:467-478, 486-521 | **confirmed** |
| units | Reads line 2 of the file as units: the agency's wind must be `kts` or `knots` and its pressure `mb` or `hPa`, or the read fails. Declares the wind in knots and the pressure in hPa; no value is converted. The wind of agency USA is declared as a 60-second average; no averaging period is declared for the other agencies. | crc_sdk/_observed_decoders.py:479-485; crc_sdk/_observed_sources.py:318-345 | **confirmed** |
| schema | Returns observations with twelve columns: variable_id, scenario_id, period_id, support_id, cell_id, geometry, time, value, station_id, group_id, failure, coverage. The schema metadata of every batch carries the evidence metadata as JSON under `crc.evidence`. | crc_sdk/_evidence.py:432-470 | **confirmed** |
| trim | Removes leading and trailing whitespace from every value before it is used. | crc_sdk/_observed_decoders.py:486-491 | **confirmed** |
| time | The time is ISO_TIME with its space replaced by `T` (for example `2023-06-08T12:00:00`); it must parse as a date and time, or the read fails. No time zone is added. | crc_sdk/_observed_decoders.py:493-496; crc_sdk/_evidence.py:79-133 | **confirmed** |
| position | Parses LAT and LON as numbers; a longitude outside -180..360 or a latitude outside -90..90 fails the read. The longitude is moved into -180..180 as `(lon + 180) % 360 - 180`, so 180 becomes -180. The point is written as little-endian WKB. It is IBTrACS's combined position, not the agency's own. | crc_sdk/_observed_decoders.py:49-56, 66-68, 497-506 | **confirmed** |
| cell | Adds the H3 cell of resolution 9 that contains the point. | crc_sdk/_observed_decoders.py:74; crc_sdk/_observed_sources.py:1236 | **confirmed** |
| identifiers | variable_id is `ibtracs:<AGENCY>:maximum_sustained_wind` or `ibtracs:<AGENCY>:minimum_central_pressure`. support_id is `<SID>:<time>@` followed by the first 20 hexadecimal digits of the SHA-256 of the WKB point. group_id is the SID. station_id, scenario_id and period_id are null. | crc_sdk/_observed_decoders.py:66-76, 507-521; crc_sdk/_observed_sources.py:1530-1532 | **confirmed** |
| values | Parses the agency's wind and pressure as floating-point numbers; a value that is not a finite number fails the read. | crc_sdk/_observed_decoders.py:35-46, 518 | **confirmed** |
| missing | A value that is empty after trimming becomes a null value with the failure code `source_no_data` and the message 'The source reports no valid observation.'. coverage is null. | crc_sdk/_observed_decoders.py:35-37, 79-104 | **confirmed** |
| rows | Returns two rows for every data row of the file, the wind and then the pressure, in the file's order, whether or not the agency reported a value there. No row is dropped, merged or sorted; two rows with the same identity fail the read. | crc_sdk/_observed_decoders.py:486-522; crc_sdk/_observed_sources.py:1514-1547; crc_sdk/_evidence.py:672-674 | **confirmed** |
| provenance | Attaches a source identity to the metadata, to the report and to every batch's schema metadata: provider `ibtracs`, product `ibtracs_v04r01_tracks`, member the agency, and one resource with the address, the SHA-256, the licence text 'NOAA open-use terms; originator terms may apply', the attribution 'NOAA NCEI IBTrACS v04r01, doi:10.25921/82ty-9e16' and the retrieval time in UTC. The release is `ibtracs:selected-source-snapshot` with a SHA-256 over the sorted (address, checksum) pairs. | crc_sdk/_observed_sources.py:113-118, 864-867, 923-930, 1075-1083; crc_sdk/_source_io.py:356, 383-397, 514-532 | **confirmed** |

## Checks

### address

The address crc-sdk records for the file it read against the documented address of NOAA's ALL file, which the reference downloads. Steps: address. Tolerance: address: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| address | confirmed | the documented address |

### bytes

SHA-256 of an independent download of NOAA's file against the checksum crc-sdk records for the file it read, for every agency read. Steps: bytes. Tolerance: bytes: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| bytes | confirmed | 333,311,392 bytes; SHA-256 5dab06471138… on both sides |

### declaration

The variables crc-sdk declares for the agency against the file: their names, the unit NOAA gives on line 2 for the agency's wind and pressure columns, read through the reference's own table of unit names, and the measurement fields; the output columns and their types against the statement. Steps: units, schema. Tolerance: names, units, fields, columns: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| declaration[USA] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[TOKYO] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[CMA] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[HKO] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[NEWDELHI] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[REUNION] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[BOM] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[NADI] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[WELLINGTON] | confirmed | declared units hPa, knots; output columns as stated: True |
| declaration[WMO] | confirmed | declared units hPa, knots; output columns as stated: True |

### values

Every data row of NOAA's file, read with Python's csv module, turned into the two rows the statement describes (wind, then pressure, at the combined position), against every row crc-sdk yields, in order, field by field. The point is decoded from crc-sdk's WKB; the part of support_id after '@' is checked against the SHA-256 of that WKB. Steps: columns, trim, time, position, cell, identifiers, values, missing, rows. Tolerance: numbers: within 1e-09 (longitude, latitude); others exact; text: exact; null equals null only.

| Check | Outcome | Result |
| --- | --- | --- |
| values[USA] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[TOKYO] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[CMA] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[HKO] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[NEWDELHI] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[REUNION] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[BOM] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[NADI] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[WELLINGTON] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |
| values[WMO] | confirmed | 1,461,388 rows against 1,461,388; 23,382,208 values compared, 0 differ; largest numeric difference 2.8e-14 |

### provenance

The source identity crc-sdk attaches to the output (metadata, report and the schema metadata of the first batch) against the reference download: address, checksum, licence text present, attribution naming NOAA's DOI for v04r01, retrieval time with a time zone, and the release checksum recomputed from the (address, checksum) pair. Steps: provenance. Tolerance: facts: all true.

| Check | Outcome | Result |
| --- | --- | --- |
| provenance[USA] | confirmed | 12 of 12 facts hold |
| provenance[TOKYO] | confirmed | 12 of 12 facts hold |
| provenance[CMA] | confirmed | 12 of 12 facts hold |
| provenance[HKO] | confirmed | 12 of 12 facts hold |
| provenance[NEWDELHI] | confirmed | 12 of 12 facts hold |
| provenance[REUNION] | confirmed | 12 of 12 facts hold |
| provenance[BOM] | confirmed | 12 of 12 facts hold |
| provenance[NADI] | confirmed | 12 of 12 facts hold |
| provenance[WELLINGTON] | confirmed | 12 of 12 facts hold |
| provenance[WMO] | confirmed | 12 of 12 facts hold |

## Inputs

| Role | File | SHA-256 | Retrieved |
| --- | --- | --- | --- |
| reference download | ibtracs.ALL.list.v04r01.csv | 5dab0647113845f594bdf60f8d9b22af244da50010b272043341568c0125edff | 2026-11-24T23:18:56Z |
| crc-sdk resource | ibtracs.ALL.list.v04r01.csv | 5dab0647113845f594bdf60f8d9b22af244da50010b272043341568c0125edff | 2026-11-24T23:19:31.747584+00:00 |

## Findings

| Id | Kind | Finding | Basis | Status |
| --- | --- | --- | --- | --- |
| CRC-010-IBT | defect | The subset "active" is accepted but NOAA has no file under that name | reproduced | fixed in 0.11.2 |
| CRC-011-IBT | observation | The snapshot's manifest has a terms address and a citation but no licence field; the batches carry no provenance | reproduced | fixed in 1.0.0 |
| CRC-028-IBT | observation | An agency's wind and pressure are placed at the combined IBTrACS position, not at the position that agency reported | reproduced | open |
| CRC-029-IBT | observation | Every point of the file is returned for every agency, most of them as rows with no value | reproduced | open |
| CRC-030-IBT | doc-code difference | The documentation says an explicit agency; the constructor defaults to the United States agencies | code reading | open |

Details are in [the inventory](../inventory.md#findings).

## What this does not cover

- A `confirmed` outcome holds for these files, these options and crc-framework 1.0.0, crc-sdk 1.0.0.
- Verification says nothing about whether the publisher's values are right.
- Validation (fitness for a stated use) is not assessed.
