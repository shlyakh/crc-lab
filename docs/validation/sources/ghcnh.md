# NOAA GHCNh station temperatures: assessment

Generated from the records of the run of 2026-11-25T01:55:26Z against crc-framework 1.0.0, crc-sdk 1.0.0. **Draft: not yet reviewed.**
Do not edit: change the source file or re-run the assessment and rebuild.

- **What the framework adds:** From NOAA's hourly station reports crc-sdk makes, per station position and year, the highest daily maximum or the lowest daily minimum temperature of the year, using its own rules for which reports, days and years count. By default a day counts only when all 24 hours hold an accepted report and a year only when every day counts; a year that falls short keeps its row with no value, its coverage and the reason. No curve is fitted unless the user asks for one. The hourly reports themselves are not in the output.
- **How it is compared:** Every station-year of forty Texas stations, 2000 to 2024, is recomputed in Python from NOAA's files with the stated rules and compared with crc-sdk's annual samples, field by field, for both indicators, at the default completeness and at a relaxed one (90 per cent of days); a sample is recomputed again from NOAA's second file format. The stations crc-sdk selects in the box are compared with NOAA's station list, the metadata with the statement, and the checksums crc-sdk records with the reference's own downloads.
- **Purpose (the framework's documentation):** Annual extremes of hourly station temperature per station and year, as a local check on gridded curves.
- **Publisher:** NOAA NCEI · https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/access/by-year
- **Entry points:** `GHCNh`
- **Status:** exploration assessed, verification assessed, validation not assessed
- **Options, indicator:** assessed annual_maximum_daily_maximum_temperature, annual_minimum_daily_minimum_temperature; not assessed none

## Exploration

### From stations to annual values

Selection: the 40 stations assessed at crc-sdk 0.11.2 (the first forty USW stations of the station list in the box), years 2000 to 2024. Counted from NOAA's files by the reference reader. No curve is fitted by default.

| Stage | Count |
| --- | --- |
| Stations crc-sdk's inventory selects in the box | 699 |
| Stations assessed | 40 |
| Station-years requested | 1,000 |
| Station-years NOAA has a file for | 592 |
| Station-years with a value by default (every day has 24 hours) | 0 |
| Station-years with a value at Coverage.minimum_fraction(0.9) | 339 |
| Station-years complete by the rules of crc-sdk 0.11 (18 hours, 90 % of days) | 427 |
| Station-years with more than one reported position | 0 |

### Hourly reports and the rules that exclude them

A rule with no row excluded nothing in these files.

| Reports | Count | Share |
| --- | --- | --- |
| All reports | 13,885,491 | 100 % |
| Accepted | 13,703,240 | 98.69 % |
| Excluded: no temperature | 174,166 | 1.2543 % |
| Excluded: outside the physical range | 7 | 0.0001 % |
| Excluded: quality code not accepted | 8,078 | 0.0582 % |

### Stations

Complete years: by default, at Coverage.minimum_fraction(0.9), and by the rules of crc-sdk 0.11.

| Station | Name | First year | Last year | Years with a file | Complete (default) | Complete (0.9) | Complete (0.11 rules) | Reports | Accepted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| USW00000127 | BEEVILLE MUNI AP | 2007 | 2024 | 18 | 0 | 13 | 13 | 433,029 | 98.9 % |
| USW00000129 | HEREFORD MUNI AP | 2007 | 2024 | 18 | 0 | 14 | 16 | 448,189 | 99.4 % |
| USW00000130 | PLEASANTON MUNI AP | 2007 | 2024 | 18 | 0 | 10 | 17 | 445,569 | 99.4 % |
| USW00000134 | KICKAPOO DOWNTOWN AP | 2007 | 2024 | 18 | 0 | 15 | 15 | 434,266 | 99.3 % |
| USW00000137 | ANGEL FIRE AP | 2008 | 2024 | 17 | 0 | 15 | 16 | 437,893 | 99.8 % |
| USW00000166 | LAGO VISTA RUSTY ALLEN AP | 2008 | 2024 | 17 | 0 | 13 | 15 | 414,066 | 99.8 % |
| USW00000172 | STAN STAMPER MUNI AP | 2012 | 2024 | 13 | 0 | 5 | 7 | 283,064 | 99.7 % |
| USW00000175 | RUSK COUNTY AP | 2008 | 2024 | 17 | 0 | 8 | 13 | 396,482 | 99.5 % |
| USW00000176 | STEPHENS COUNTY AP | 2008 | 2024 | 17 | 0 | 11 | 16 | 413,350 | 99.9 % |
| USW00000177 | CASTROVILLE MUNI AIRPORT | 2013 | 2024 | 12 | 0 | 8 | 8 | 286,720 | 98.1 % |
| USW00000181 | ZAPATA COUNTY AP | 2008 | 2024 | 17 | 0 | 6 | 12 | 400,840 | 99.6 % |
| USW00000188 | HOUSTON DUNN HELISTOP | 2008 | 2024 | 17 | 0 | 10 | 12 | 387,224 | 99.8 % |
| USW00000208 | HOUSTON EXECUTIVE AP | 2009 | 2024 | 16 | 0 | 10 | 14 | 386,976 | 97.1 % |
| USW00000209 | BOWIE MUNI AP | 2013 | 2024 | 12 | 0 | 11 | 11 | 303,444 | 99.8 % |
| USW00000213 | PAMPA MESA VISTA AP | 2009 | 2024 | 16 | 0 | 7 | 9 | 387,369 | 98.1 % |
| USW00000214 | STIGLER REGIONAL AP | 2009 | 2024 | 16 | 0 | 9 | 12 | 374,971 | 98.6 % |
| USW00000215 | CLARENCE E PAGE MUNI AP | 2009 | 2024 | 16 | 0 | 6 | 13 | 372,096 | 99.5 % |
| USW00000223 | HOUSTON SOUTHWEST AP | 2009 | 2024 | 16 | 0 | 11 | 13 | 397,371 | 99.6 % |
| USW00000225 | HORSESHOE BAY RESORT AP | 2009 | 2024 | 16 | 0 | 14 | 15 | 399,038 | 99.8 % |
| USW00000229 | LAMPASAS AP | 2009 | 2024 | 16 | 0 | 5 | 10 | 354,386 | 99.7 % |
| USW00000230 | AUSTIN EXECUTIVE AP | 2009 | 2024 | 16 | 0 | 8 | 14 | 390,321 | 98.9 % |
| USW00000239 | OZONA MUNI AP | 2009 | 2024 | 16 | 0 | 11 | 13 | 381,040 | 100.0 % |
| USW00000246 | E BREAKS OIL PLATFORM | 2009 | 2022 | 14 | 0 | 1 | 2 | 260,614 | 95.7 % |
| USW00000247 | GUNNISON OIL PLATFORM | 2009 | 2024 | 16 | 0 | 6 | 8 | 354,281 | 92.9 % |
| USW00000255 | SABINE OIL PLATFORM | 2010 | 2019 | 10 | 0 | 1 | 2 | 178,203 | 97.0 % |
| USW00000259 | GALVESTON 424 OIL PLATFORM | 2010 | 2016 | 7 | 0 | 0 | 1 | 106,325 | 98.6 % |
| USW00000260 | HIGH IS 376 | 2010 | 2020 | 11 | 0 | 2 | 3 | 244,388 | 92.5 % |
| USW00000262 | MUSTANG IS A85A | 2010 | 2020 | 11 | 0 | 1 | 6 | 237,922 | 97.6 % |
| USW00000263 | BOERNE STAGE FIELD AP | 2013 | 2024 | 12 | 0 | 11 | 11 | 303,415 | 99.4 % |
| USW00000270 | FAITH RCH AP | 2010 | 2024 | 15 | 0 | 4 | 7 | 313,231 | 96.0 % |
| USW00000272 | BOOMVANG SPAR OIL PLATFORM | 2010 | 2024 | 15 | 0 | 7 | 7 | 345,175 | 98.5 % |
| USW00000276 | COLEMAN MUNI AP | 2010 | 2024 | 15 | 0 | 14 | 14 | 365,044 | 99.9 % |
| USW00000306 | HIGH IS 179 OIL PLATFORM | 2010 | 2020 | 11 | 0 | 3 | 6 | 228,984 | 97.4 % |
| USW00000308 | N PADRE IS | 2010 | 2014 | 5 | 0 | 0 | 2 | 88,484 | 98.8 % |
| USW00000313 | BEAUMONT MUNI AP | 2011 | 2024 | 14 | 0 | 8 | 9 | 350,602 | 97.9 % |
| USW00000349 | ANDREWS COUNTY AP | 2013 | 2024 | 12 | 0 | 10 | 10 | 298,309 | 99.7 % |
| USW00000351 | CAMERON MUNI AP | 2012 | 2024 | 13 | 0 | 11 | 11 | 328,174 | 98.9 % |
| USW00000357 | HAMILTON MUNI AP | 2008 | 2024 | 17 | 0 | 13 | 14 | 426,836 | 99.9 % |
| USW00000362 | GATESVILLE MUNI AP | 2004 | 2024 | 21 | 0 | 15 | 17 | 504,758 | 98.8 % |
| USW00000364 | THOMAS P STAFFORD AP | 2007 | 2024 | 18 | 0 | 12 | 13 | 423,042 | 97.9 % |

Assessed on the sample of crc-sdk 0.11.2, so that the two versions can be compared: the first forty USW stations of NOAA's station list in the Texas box, 2000 to 2024. These are small airports whose records begin around 2005 (592 of 1,000 station-years had a file at the 0.11.2 run). What crc-sdk 1.0 returns by default is checked: annual samples, not a fitted curve. Two default rules are stricter than in 0.11: a day needs all 24 hours (0.11: 18) and a year needs every day (0.11: 90 per cent), so few station-years of these airports carry a value by default; the assessment therefore also checks Coverage.minimum_fraction(0.9), which matches 0.11's year rule but not its day rule. Days are UTC days: in Texas a UTC day runs from the local evening to the next. The values are extremes of sampled hourly temperature, not of an instrument's daily maximum and minimum.

## What the framework does (transformation statement)

| Step | What crc-sdk does | Code | Outcome |
| --- | --- | --- | --- |
| stations | Selects stations from NOAA's station list `hourly/doc/ghcnh-station-list.csv` (GHCN_ID, NAME, LONGITUDE, LATITUDE): by identifier, where an identifier not in the list stops the read, or by area, keeping the stations whose listed position lies in the box, edges included, in the list's order. A listed position with a coordinate missing or outside WGS84 is dropped, so that station is never selected by area; a blank name is replaced by the identifier. | crc_sdk/_observed_sources.py:503-542, 545-556, 633-656 | **confirmed** |
| files | Requests one Parquet file per station and year, `hourly/access/by-year/<year>/parquet/GHCNh_<station>_<year>.parquet`, downloads the whole file (60-second timeout, no second try) and keeps it in its cache under its SHA-256. A file NOAA does not have (HTTP 404) is recorded as absent; any other HTTP or network error stops the read. | crc_sdk/_observed_sources.py:895-910; crc_sdk/_source_io.py:261-290, 345-352, 452-468 | **confirmed** |
| columns | Reads seven columns: STATION, DATE, LATITUDE, LONGITUDE, temperature, temperature_Quality_Code and temperature_Source_Code. A file without them stops the read. ELEVATION is not read. | crc_sdk/_observed_decoders.py:390-404 | **confirmed** |
| refusal | Stops the read of the whole selection, with no rows, when a file holds a report of another station or of another year, a DATE it cannot read, a coordinate missing or outside WGS84, a temperature that is not a finite number, or two reports with the same time at the same position. A report with no temperature is kept with no value. | crc_sdk/_observed_decoders.py:35-57, 409-421; crc_sdk/_evidence.py:505-512, 672-674 | **confirmed** |
| quality | Uses a temperature when its quality code (spaces stripped) is blank, or is 1 from one of fourteen listed source codes, or is 5 from one of eight listed source codes. Any other code keeps the report with no value. | crc_sdk/_observed_decoders.py:318-321, 417-430 | **confirmed**. Unchanged from 0.11. In NOAA's files the source lists may not be put to the test (at 0.11.2 no report had code 1 or 5 from an unlisted source); the offline tests exercise them on constructed files. |
| range | Uses a temperature only if it lies between -93.2 and 61.8 degrees Celsius inclusive; outside, the report is kept with no value. | crc_sdk/_observed_decoders.py:431-445 | **confirmed** |
| units | Takes the temperature in degrees Celsius as published; nothing is converted. The output variable is `noaa:ghcnh:<indicator>`, declared as a temperature in degC. | crc_sdk/_observed_sources.py:157-171, 196-210 | **confirmed** |
| day | Groups the accepted reports of each position by the calendar day of DATE as published, which is UTC; no time zone is applied. For each day it counts the distinct clock hours that hold an accepted report. | crc_sdk/_station_reduction.py:40-55, 64-72 | **confirmed** |
| valid-day | Counts a day as complete only when all 24 clock hours hold an accepted report; several reports in one hour count once. The daily maximum (or minimum) is taken over every accepted report of a complete day; an incomplete day has no value. This rule is fixed: `Coverage` does not change it. | crc_sdk/_station_reduction.py:65-75, 108-117 | **confirmed** |
| valid-year | Counts a year as complete by the `Coverage` given to `GHCNh`: by default `Coverage.complete()`, every day of the year complete (365 of 365, 366 of 366); with `Coverage.minimum_fraction(f)`, complete days divided by the days of the year at least f. A year with no complete day is never complete. | crc_sdk/_aggregation.py:95-116, 772-776; crc_sdk/_observed_sources.py:752, 1458-1462 | **confirmed** |
| annual-value | For a complete year, takes the highest daily maximum (`annual_maximum_daily_maximum_temperature`) or the lowest daily minimum (`annual_minimum_daily_minimum_temperature`) over the complete days. An incomplete year keeps its row with no value, failure `incomplete_year`, and its coverage: complete days, days of the year and the fraction required. | crc_sdk/_aggregation.py:777-822 | **confirmed** |
| location | Gives each distinct reported position its own support: `<station>@` and the first 20 hexadecimal digits of the SHA-256 of the position as a little-endian WKB point, with its H3 cell at resolution 9. A station that moves within a year gets one row per position, each reduced over its own reports only; no move is refused and positions are not merged. Elevation is not carried. | crc_sdk/_observed_decoders.py:66-76; crc_sdk/_station_reduction.py:40-55 | **confirmed** |
| output | Returns `Samples`: one row per position and year, with the year as time, the value, its coverage and failure, the station and support identifiers, the H3 cell and the point; declared as annual values with an upper tail for the maximum and a lower tail for the minimum. A station-year with no file, or with a file holding no report, has no row: it is an `UnavailableStationYear` diagnostic, counted as requested and incomplete. The report counts requested, produced, no-data, usable and incomplete years. No curve is fitted: that needs an explicit `fit(SampleFit(...))`. | crc_sdk/_observed_sources.py:1142-1244, 1374-1513; docs/sources.md:93-96, 252-257 | **confirmed** |
| provenance | Records with the output every resource read: the station list and every station-year file requested, absent ones included, each with its address, SHA-256, retrieval time, the licence text `NOAA open-use terms; originator terms may apply` and the attribution `NOAA National Centers for Environmental Information; original source records retained.` (CO-OPS no longer named since crc-sdk 1.0.1), and a release identifier with a SHA-256 over them all. No GHCNh version is recorded. | crc_sdk/_observed_sources.py:118-122, 895-910, 1352-1366, 1549-1555 | **confirmed** |

## Checks

### stations

Stations of NOAA's station list whose position lies in the Texas box, read with the standard library, against the stations crc-sdk's inspect() returns for the same box: identifier, name and position, in order. Steps: stations. Tolerance: values: exact equality, numbers included.

| Check | Outcome | Result |
| --- | --- | --- |
| stations[box] | confirmed | 699 stations in the box by NOAA's list, 699 by crc-sdk; 0 values differ |

### annual

Every station-year: the annual rows (one per station position) recomputed in Python from NOAA's Parquet file, read without crc-sdk or pyarrow, against crc-sdk's read() with Coverage.complete() (default), field by field; and the station-years with no row, the refused stations and the report's counts. Steps: files, columns, refusal, quality, range, day, valid-day, valid-year, annual-value, location, output. Tolerance: values: exact equality, numbers included.

| Check | Outcome | Result |
| --- | --- | --- |
| annual[temperature_max] | confirmed | 592 station-year rows against 592; 6,512 values compared, 0 differ; 0 rows carry a value; 408 station-years have no file |
| annual[temperature_max, coverage 0.9] | confirmed | 592 station-year rows against 592; 6,512 values compared, 0 differ; 339 rows carry a value; 408 station-years have no file |
| annual[temperature_min] | confirmed | 592 station-year rows against 592; 6,512 values compared, 0 differ; 0 rows carry a value; 408 station-years have no file |
| annual[temperature_min, coverage 0.9] | confirmed | 592 station-year rows against 592; 6,512 values compared, 0 differ; 339 rows carry a value; 408 station-years have no file |

### second-format

A seeded sample of station-years recomputed from NOAA's pipe-separated file with the standard library only, against crc-sdk's read() with Coverage.complete() (default). Steps: files, columns, refusal, quality, range, day, valid-day, valid-year, annual-value, location, output. Tolerance: values: exact equality, numbers included.

| Check | Outcome | Result |
| --- | --- | --- |
| second-format[temperature_max] | confirmed | 8 station-year rows against 8; 88 values compared, 0 differ |
| second-format[temperature_max, coverage 0.9] | confirmed | 8 station-year rows against 8; 88 values compared, 0 differ |
| second-format[temperature_min] | confirmed | 8 station-year rows against 8; 88 values compared, 0 differ |
| second-format[temperature_min, coverage 0.9] | confirmed | 8 station-year rows against 8; 88 values compared, 0 differ |

### metadata

The kind, variable, unit, probability convention, sampling and the list of operations in the metadata of crc-sdk's default read(), against the values the statement gives; a fit among the operations would differ. Steps: units, output. Tolerance: fields: identical to the statement.

| Check | Outcome | Result |
| --- | --- | --- |
| metadata[temperature_max] | confirmed | metadata as stated |
| metadata[temperature_min] | confirmed | metadata as stated |

### provenance

The resources crc-sdk records with its output: every station-year file requested, absent ones included, and the station list; the SHA-256 of each against the reference's own download of the same address; and a licence, attribution and retrieval time on each. Steps: provenance, files. Tolerance: checksums: identical; fields: all present (their wording is recorded, not judged); files: identical sets of addresses.

| Check | Outcome | Result |
| --- | --- | --- |
| provenance[temperature_max] | confirmed | 1,000 files recorded for 1,000 requested; 592 checksums compared, 0 differ; licence NOAA open-use terms; originator terms may apply |
| provenance[temperature_min] | confirmed | 1,000 files recorded for 1,000 requested; 592 checksums compared, 0 differ; licence NOAA open-use terms; originator terms may apply |

## Inputs

| Role | File | SHA-256 | Retrieved |
| --- | --- | --- | --- |
| reference download (station list) | ghcnh-station-list.csv | 812ea50bd5efd1b9cc09d5800c55825b3d43b3c5aa75ab17b2848f43b1bfaaef | 2026-11-24T23:30:27Z |
| crc-sdk inspect() | ghcnh-station-list.csv |  |  |
| reference download (Parquet) | by-year (592 files) | 0f445170ef39f1b6557ff6180c85111faf3fb394817bc6a07a3ab70852954cbf | 2026-11-23T17:52:31Z |
| crc-sdk read() of the annual indicator | by-year |  | 2026-11-25T00:49:51Z |
| reference download (pipe-separated) | by-year (8 files) | 335618cc39cb4e85a4ec7009f9383981ffa475fbe3989302893ac7c34df01522 | 2026-11-23T18:24:31Z |

## Findings

| Id | Kind | Finding | Basis | Status |
| --- | --- | --- | --- | --- |
| CRC-035-GHC | observation | With the default completeness rule no station-year of forty Texas airport stations carries a value | reproduced | reported upstream |
| CRC-036-GHC | observation | One unusable report in one station's file stops the read of every selected station | reproduced | open |
| CRC-037-GHC | observation | GHCNh files are attributed to 'NOAA NCEI and NOAA CO-OPS', with a generic licence text and no dataset version | reproduced | fixed in 1.0.1 |

Details are in [the inventory](../inventory.md#findings).

## What this does not cover

- A `confirmed` outcome holds for these files, these options and crc-framework 1.0.0, crc-sdk 1.0.0.
- Verification says nothing about whether the publisher's values are right.
- Validation (fitness for a stated use) is not assessed.
