# JRC flood hazard maps (GloFAS, EFAS): assessment

Generated from the records of the run of 2026-11-25T12:37:22Z against crc-framework 1.0.0, crc-sdk 1.0.0. **Draft: not yet reviewed.**
Do not edit: change the source file or re-run the assessment and rebuild.

- **What the framework adds:** From crc-sdk 1.0 nothing is added to the depths: each pixel of JRC's maps comes back with the depths the publisher gives at its return periods, placed at probabilities 1 - 1/T, with an identifier built from the pixel's position, the H3 cell of its centre and its outline. A pixel with fewer than two depths, or with a depth lower than one at a shorter return period, is left out and counted. Up to 0.11 crc-sdk fitted a Gumbel curve per pixel; that assessment is kept as the previous version.
- **How it is compared:** JRC's files are read whole by an independent reader. In five areas (Texas, Houston, Austin, Fremont, the Rhine) the reader decides for every pixel whether it should be delivered and with which depths, and that is compared with crc-sdk's rows pixel by pixel. The pixels requested, the files read, the identifiers, the cells, the release, the licence and the recorded provenance are checked separately, as is a box outside a product's coverage.
- **Purpose (the framework's documentation):** River flood depth at the publisher's return periods, per pixel of the publisher's maps, as the knots of a quantile curve. Nothing is fitted unless the user asks.
- **Publisher:** European Commission JRC, Copernicus Emergency Management Service · https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard and CEMS-EFAS/flood_hazard
- **Entry points:** `JRC`
- **Status:** exploration assessed, verification assessed, validation not assessed
- **Options, product:** assessed efas, glofas; not assessed none

## Exploration

### Pixels by area

Counted from the publisher's files by the reference reader. A pixel is delivered when it has two or more depths and none is lower than an earlier one. crc-sdk reports the three other groups as one number.

| Area | Pixels in the box | Dry | One depth | A depth decreases | Delivered by crc-sdk | of them: fewer than four depths | of them: equal depths | Skipped, as crc-sdk reports it |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Texas box | 201,757,502 | 190,071,292 | 424,212 | 192,687 | 11,069,311 | 517,035 | 698,318 | 190,688,191 |
| Houston | 1,298,281 | 1,019,627 | 22,086 | 3,990 | 252,578 | 22,646 | 16,983 | 1,045,703 |
| Austin | 361,201 | 335,707 | 931 | 140 | 24,423 | 979 | 1,243 | 336,778 |
| Fremont, California | 87,001 | 76,398 | 459 | 775 | 9,369 | 508 | 992 | 77,632 |
| Rhine, Bonn to Mainz | 2,595,241 | 2,433,343 | 6,815 | 730 | 154,353 | 8,351 | 2,928 | 2,440,888 |

### crc-sdk's reads

Each read ran in a process of its own.

| Area | Read from | Rows | Seconds | Peak memory, MB | Error |
| --- | --- | --- | --- | --- | --- |
| Texas box | the publisher | 11,069,311 | 9080.86 | 5482.9 |  |
| Houston | the publisher | 252,578 | 110.67 | 1070.4 |  |
| Austin | the publisher | 24,423 | 53.37 | 324.0 |  |
| Fremont, California | the publisher | 9,369 | 25.74 | 231.5 |  |
| Rhine, Bonn to Mainz | the publisher | 154,353 | 137.29 | 791.0 |  |

### Outside the coverage

What a read returns for a box the product does not cover.

| Box | Rows | Diagnostics | Reported complete | Error |
| --- | --- | --- | --- | --- |
| Fremont, California (outside EFAS) | 0 | 0 | True |  |

Assessed at crc-sdk 1.0.0 on the default path, where nothing is fitted. The explicit fit, `fit(QuantileFit(...))`, is not assessed yet. The review maps and the comparisons with FEMA zones, USGS gauges and Harvey marks were made from crc-sdk 0.11 output and are shown with the previous version. On 2026-11-24 the publisher's server did not answer, so crc-sdk read the copy of the publisher's files held from 2026-11-17 and 2026-11-23; its own downloads were not exercised.

## What the framework does (transformation statement)

| Step | What crc-sdk does | Code | Outcome |
| --- | --- | --- | --- |
| files | Reads the publisher's README.txt, for GloFAS the tile index `tile_extents.geojson`, and one depth file per return period written in the code (GloFAS 10, 20, 50, 75, 100, 200, 500 years; EFAS also 30 and 40) for every GloFAS tile whose extent meets the box, or for EFAS the one continental file. | crc_sdk/_providers/jrc.py:62-84; crc_sdk/_climate_sources.py:421-453 | **confirmed** |
| transport | Reads each depth file by range requests for the window of the box only, pinned to the file's ETag so that a file changed during the read is refused. | crc_sdk/_climate_io.py:404-420, 423-515, 626-650 | **confirmed**. Not exercised on 2026-11-24: the publisher's server did not answer, so crc-sdk read the copy of the publisher's files held. The values it decoded from those files are compared in the values checks. |
| release | Reads the release from the README (the text after 'Dataset version') and refuses to run when it is not the one written in the code (GloFAS 2.1.2, EFAS 3.1.1). The file addresses hold no version. | crc_sdk/_climate_sources.py:306-330; crc_sdk/_providers/jrc.py:62-80 | **confirmed** |
| area | Takes every pixel of the publisher's grid that the box touches. Since crc-sdk 1.1.0 the report's requested count holds the flooded pixels only; the dry ones are in the `dry_pixels` note. | crc_sdk/_climate_io.py:105-133, 166-170 | **confirmed** |
| nodata | Treats the file's nodata value and non-finite values as no depth. | crc_sdk/_climate_io.py:139-141, 173-178 | **confirmed** |
| selection | Returns a row for every pixel that has a depth at one or more return periods, unless its depths, with the return periods it has no depth for read as 0 m, are lower anywhere than at a shorter return period: those pixels are left out unrepaired. A pixel with no depth at any return period gets no row (crc-sdk 1.1.0; 1.0 also left out pixels with one depth). | crc_sdk/_climate_io.py:201-227; crc_sdk/_climate_sources.py:525-536 | **confirmed** |
| skipped-count | Counts the pixels left out for a decreasing depth in a `source_no_data` warning and in the report's skipped count. The pixels returned with a return period read as 0 m are counted in an `unmapped_depth_as_zero` note, and the dry pixels in a `dry_pixels` note; dry pixels are neither requested nor skipped (crc-sdk 1.1.0; 1.0 put dry pixels in the skipped number). | crc_sdk/_climate_io.py:201-205, 242; crc_sdk/_climate_sources.py:145-185 | **confirmed** |
| knots | Places a depth published for the return period T at the probability 1 - 1/T. A return period with no depth at a returned pixel gives a knot of 0 m, so every row has a knot at every return period of the product. | crc_sdk/_climate_sources.py:445-453; crc_sdk/_climate_io.py:173-178, 191-193 | **confirmed** |
| depths | Returns the publisher's depths unchanged, in metres. | crc_sdk/_climate_io.py:173-178, 191-193; crc_sdk/_climate_sources.py:482-496 | **confirmed** |
| identifier | Names the pixel `jrc:<product>:<tile>:<row>:<column>` by its row and column in the publisher's file (`continental` for EFAS), so that the same pixel has the same name whatever box asked for it. | crc_sdk/_climate_sources.py:457; crc_sdk/_climate_io.py:95-104, 150-153, 198-203 | **confirmed** |
| cell | Gives each row the H3 cell of resolution 9 that holds the centre of the pixel, and the pixel's outline as its geometry. | crc_sdk/_climate_io.py:154-165, 194-197, 208-212 | **confirmed** |
| no-fit | Fits nothing: every row holds a quantile curve made of the published knots, and no fit and no failure. | crc_sdk/_climate_io.py:191-193, 204-214 | **confirmed** |
| labels | Labels every row with the variable `jrc:<product>:flood_depth` and with no scenario and no period. | crc_sdk/_climate_sources.py:482-496; crc_sdk/_climate_io.py:204-207 | **confirmed** |
| licence | Records the Open Database License (`ODbL-1.0`) for every file, with the attribution 'Copernicus Emergency Management Service; European Commission Joint Research Centre'. The licence is written in the code and is not read from the publisher. | crc_sdk/_climate_sources.py:310-318, 431-432, 450-451 | **confirmed** |
| provenance | Records for every file its address, a SHA-256, the licence, the attribution and the retrieval time. For a depth file the checksum is of the window crc-sdk cut from it, not of the publisher's file. | crc_sdk/_climate_io.py:423-515; crc_sdk/_source_io.py:359-397 | **confirmed** |
| coverage | For a box that lies outside a product's coverage, returns no rows and raises no error; since crc-sdk 1.0.1 the report carries an `area_outside_coverage` warning naming the product. | crc_sdk/_climate_sources.py:436-441; crc_sdk/_climate_io.py:105-133 | **confirmed** |

## Checks

### area

The pixels the publisher's grids hold inside the box (every pixel the box touches) against the number crc-sdk reports as requested and the positions of its rows. Steps: area. Tolerance: counts: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| area[glofas-tx] | confirmed | 201,757,502 pixels in the publisher's window, 201,757,502 requested by crc-sdk; 0 rows outside the window |
| area[glofas-houston] | confirmed | 1,298,281 pixels in the publisher's window, 1,298,281 requested by crc-sdk; 0 rows outside the window |
| area[glofas-austin] | confirmed | 361,201 pixels in the publisher's window, 361,201 requested by crc-sdk; 0 rows outside the window |
| area[glofas-fremont] | confirmed | 87,001 pixels in the publisher's window, 87,001 requested by crc-sdk; 0 rows outside the window |
| area[efas-rhine] | confirmed | 2,595,241 pixels in the publisher's window, 2,595,241 requested by crc-sdk; 0 rows outside the window |

### delivered

Which pixels get a row. The reference delivers a pixel that has two or more depths none of which is lower than an earlier one, and skips the rest; crc-sdk's rows and its reported counts are compared with that. Steps: selection, skipped-count. Tolerance: counts: identical; pixels: the same set.

| Check | Outcome | Result |
| --- | --- | --- |
| delivered[glofas-tx] | confirmed | 11,069,311 rows for 11,069,311 deliverable pixels; 0 missing, 0 extra; skipped 190,688,191 against 190,688,191 (190,071,292 dry, 424,212 with one depth, 192,687 with a depth that decreases) |
| delivered[glofas-houston] | confirmed | 252,578 rows for 252,578 deliverable pixels; 0 missing, 0 extra; skipped 1,045,703 against 1,045,703 (1,019,627 dry, 22,086 with one depth, 3,990 with a depth that decreases) |
| delivered[glofas-austin] | confirmed | 24,423 rows for 24,423 deliverable pixels; 0 missing, 0 extra; skipped 336,778 against 336,778 (335,707 dry, 931 with one depth, 140 with a depth that decreases) |
| delivered[glofas-fremont] | confirmed | 9,369 rows for 9,369 deliverable pixels; 0 missing, 0 extra; skipped 77,632 against 77,632 (76,398 dry, 459 with one depth, 775 with a depth that decreases) |
| delivered[efas-rhine] | confirmed | 154,353 rows for 154,353 deliverable pixels; 0 missing, 0 extra; skipped 2,440,888 against 2,440,888 (2,433,343 dry, 6,815 with one depth, 730 with a depth that decreases) |

### values

For every delivered pixel: crc-sdk's knots against the publisher's depths in order of return period, and its probabilities against 1 - 1/T for the same periods. Steps: knots, depths, nodata. Tolerance: depths: identical; probabilities: within 1e-12.

| Check | Outcome | Result |
| --- | --- | --- |
| values[glofas-tx] | confirmed | 72,460,914 depths of 11,069,311 pixels compared; 0 depths and 0 probabilities differ |
| values[glofas-houston] | confirmed | 1,575,372 depths of 252,578 pixels compared; 0 depths and 0 probabilities differ |
| values[glofas-austin] | confirmed | 160,917 depths of 24,423 pixels compared; 0 depths and 0 probabilities differ |
| values[glofas-fremont] | confirmed | 60,290 depths of 9,369 pixels compared; 0 depths and 0 probabilities differ |
| values[efas-rhine] | confirmed | 1,276,907 depths of 154,353 pixels compared; 0 depths and 0 probabilities differ |

### cells

A seeded sample of rows: cell_id against the H3 cell of resolution 9 that holds the centre of the pixel named by the support_id. Steps: identifier, cell. Tolerance: cells: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| cells[glofas-tx] | confirmed | 2,000 rows checked; 0 cells differ; 0 rows repeated |
| cells[glofas-houston] | confirmed | 603 rows checked; 0 cells differ; 0 rows repeated |
| cells[glofas-austin] | confirmed | 646 rows checked; 0 cells differ; 0 rows repeated |
| cells[glofas-fremont] | confirmed | 204 rows checked; 0 cells differ; 0 rows repeated |
| cells[efas-rhine] | confirmed | 603 rows checked; 0 cells differ; 0 rows repeated |

### shape

The shape of crc-sdk's rows: one quantile curve per row and nothing fitted, the product's variable, and no scenario or period. Steps: no-fit, labels. Tolerance: labels: identical text.

| Check | Outcome | Result |
| --- | --- | --- |
| shape[glofas-tx] | confirmed | curve kinds {'quantile_curve': 11069311}; 0 rows with a fit; variable ['jrc:glofas:flood_depth'] |
| shape[glofas-houston] | confirmed | curve kinds {'quantile_curve': 252578}; 0 rows with a fit; variable ['jrc:glofas:flood_depth'] |
| shape[glofas-austin] | confirmed | curve kinds {'quantile_curve': 24423}; 0 rows with a fit; variable ['jrc:glofas:flood_depth'] |
| shape[glofas-fremont] | confirmed | curve kinds {'quantile_curve': 9369}; 0 rows with a fit; variable ['jrc:glofas:flood_depth'] |
| shape[efas-rhine] | confirmed | curve kinds {'quantile_curve': 154353}; 0 rows with a fit; variable ['jrc:efas:flood_depth'] |

### files

The addresses crc-sdk records as read against the publisher's README, tile index and the depth file of every return period for every tile the box meets. Steps: files. Tolerance: addresses: the same set.

| Check | Outcome | Result |
| --- | --- | --- |
| files[glofas-tx] | confirmed | 30 addresses recorded against 30 expected |
| files[glofas-houston] | confirmed | 16 addresses recorded against 16 expected |
| files[glofas-austin] | confirmed | 16 addresses recorded against 16 expected |
| files[glofas-fremont] | confirmed | 9 addresses recorded against 9 expected |
| files[efas-rhine] | confirmed | 10 addresses recorded against 10 expected |

### provenance

Every file crc-sdk records carries a checksum, a licence, an attribution and a retrieval time; for the files it reads whole (README, tile index) the checksum is compared with the reference's. Steps: provenance. Tolerance: checksums: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| provenance[glofas-tx] | confirmed | 31 of 31 recorded files carry all four fields; 0 of 2 whole-file checksums differ; 28 raster checksums are of crc-sdk's crop |
| provenance[glofas-houston] | confirmed | 17 of 17 recorded files carry all four fields; 0 of 2 whole-file checksums differ; 14 raster checksums are of crc-sdk's crop |
| provenance[glofas-austin] | confirmed | 17 of 17 recorded files carry all four fields; 0 of 2 whole-file checksums differ; 14 raster checksums are of crc-sdk's crop |
| provenance[glofas-fremont] | confirmed | 10 of 10 recorded files carry all four fields; 0 of 2 whole-file checksums differ; 7 raster checksums are of crc-sdk's crop |
| provenance[efas-rhine] | confirmed | 11 of 11 recorded files carry all four fields; 0 of 1 whole-file checksums differ; 9 raster checksums are of crc-sdk's crop |

### release

The release crc-sdk records against the version line of the publisher's README. Steps: release. Tolerance: version: identical text.

| Check | Outcome | Result |
| --- | --- | --- |
| release[glofas-tx] | confirmed | README 2.1.2; crc-sdk records 2.1.2, inventory:2.1.2 |
| release[glofas-houston] | confirmed | README 2.1.2; crc-sdk records 2.1.2, inventory:2.1.2 |
| release[glofas-austin] | confirmed | README 2.1.2; crc-sdk records 2.1.2, inventory:2.1.2 |
| release[glofas-fremont] | confirmed | README 2.1.2; crc-sdk records 2.1.2, inventory:2.1.2 |
| release[efas-rhine] | confirmed | README 3.1.1; crc-sdk records 3.1.1, inventory:3.1.1 |

### licence

The licence crc-sdk records against the licence line of the publisher's README; the publisher's copyright.txt is quoted beside it where there is one. Steps: licence. Tolerance: licence: the licence the README names.

| Check | Outcome | Result |
| --- | --- | --- |
| licence[glofas-tx] | confirmed | crc-sdk ODbL-1.0; README: Open Data Commons Open Database License v1.0 |
| licence[glofas-houston] | confirmed | crc-sdk ODbL-1.0; README: Open Data Commons Open Database License v1.0 |
| licence[glofas-austin] | confirmed | crc-sdk ODbL-1.0; README: Open Data Commons Open Database License v1.0 |
| licence[glofas-fremont] | confirmed | crc-sdk ODbL-1.0; README: Open Data Commons Open Database License v1.0 |
| licence[efas-rhine] | confirmed | crc-sdk ODbL-1.0; README: Open Data Commons Open Database License v1.0 |

### overlap

The box is read again as two boxes that overlap by a fifth of its width: pixels in the overlap must carry the same support_id, cell and knots in both, and the two together must give the rows of the whole box. Steps: identifier. Tolerance: rows: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| overlap[glofas-fremont] | confirmed | 2,109 rows in both boxes, 0 differ; the two boxes together against the whole: 0 and 0 rows on one side only |

### coverage

Ask crc-sdk for a box that lies outside the product's coverage and record what comes back: an error, or no rows. Steps: coverage. Tolerance: behaviour: no rows and no error.

| Check | Outcome | Result |
| --- | --- | --- |
| coverage[efas-fremont] | confirmed | 0 rows, 0 diagnostics, reported complete: True |

### transport

crc-sdk read from the publisher's server; the values it returned are compared in the values checks. Steps: transport. Tolerance: values: exact equality.

| Check | Outcome | Result |
| --- | --- | --- |
| transport | confirmed |  |

## Inputs

| Role | File | SHA-256 | Retrieved |
| --- | --- | --- | --- |
| publisher's files | flood_hazard | b22f221866c7cd2f90dee87a46c3765b18eef74c11440e2ae99c792217fa027d | 2026-11-23T18:55:46Z |
| crc-sdk read | flood_hazard |  |  |
| publisher's files | flood_hazard | 0ff55fa48a4650a522f16460dccafc1027952c4a561460a1b97ae34e33ad4c8e | 2026-11-23T19:17:30Z |
| crc-sdk read | flood_hazard |  |  |
| crc-sdk reads | flood_hazard |  |  |
| crc-sdk read | flood_hazard |  |  |

## Findings

| Id | Kind | Finding | Basis | Status |
| --- | --- | --- | --- | --- |
| CRC-003-JRC | doc-code difference | JRC flood and EDO output files do not carry licence, attribution, retrieval time or checksum | reproduced | fixed in 1.0.0 |
| CRC-014-JRC | observation | A pixel the publisher shows flooded gets no curve, and no message, when it has fewer than four depths, equal depths or a decreasing depth | reproduced | superseded by CRC-023-JRC from 1.0.0 |
| CRC-015-JRC | observation | The fitted curve can be positive where the publisher's map is dry, below zero where it is wet, and metres away from the published depth | reproduced | no longer applies from 1.0.0 |
| CRC-016-JRC | observation | A request outside a dataset's coverage ends with an error that does not name the coverage, and the error differs with the cache mode | reproduced | superseded by CRC-024-JRC from 1.0.0 |
| CRC-017-JRC | observation | The release is identified by one line of the publisher's README; the file addresses hold no version and no publisher checksum is taken | reproduced | open |
| CRC-018-JRC | doc-code difference | crc-sdk states CC BY 4.0 for the JRC flood maps; the publisher's README names the Open Database License | reproduced | fixed in 1.0.0 |
| CRC-019-JRC | observation | The publisher's masks of spurious depths and permanent water are not read | reproduced | open |
| CRC-020-JRC | observation | With a cache, a pixel's source_id depends on the box asked for | reproduced | fixed in 1.0.0 |
| CRC-021-JRC | defect | A cache made under a relative path cannot be read offline from another working folder | reproduced | open |
| CRC-022-JRC | observation | A state-sized box is read in one process: 2 h 31 min and 5.5 GB of memory for the Texas box on 1.0.0 (27 minutes and 5.8 GB on 0.11) | reproduced | open |
| CRC-023-JRC | observation | Flooded pixels with one depth, or with a depth lower than one at a shorter return period, are left out; the only trace is one count that also holds every dry pixel | reproduced | fixed in 1.1.0 |
| CRC-024-JRC | observation | A box outside a product's coverage returns no rows, no diagnostic, and a report that says the read is complete and valid | reproduced | fixed in 1.0.1 |

Details are in [the inventory](../inventory.md#findings).

## What this does not cover

- A `confirmed` outcome holds for these files, these options and crc-framework 1.0.0, crc-sdk 1.0.0.
- Verification says nothing about whether the publisher's values are right.
- Validation (fitness for a stated use) is not assessed.
