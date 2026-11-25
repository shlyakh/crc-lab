# Inventory: crc-sdk sources

Generated 2026-11-25 by `python -m data_source_check.build` against crc-framework 1.0.0, crc-sdk 1.0.0.
Do not edit: change the files under `src/data_source_check/sources/` and rebuild.

## Sources

| Source | Kind | Tier | Exploration | Verification | Validation | Findings | Signed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CRC Open hosted release (`crc-open`) | pre-fitted release | 1 | not assessed | not assessed | not assessed | 1 | draft |
| ERA5 reanalysis extremes (`era5`) | fitted curves | 1 | in progress | in progress | not assessed | 1 | draft |
| IBTrACS tropical cyclone tracks (`ibtracs`) | pass-through | 1 | assessed | assessed | not assessed | 5 | draft |
| NOAA CO-OPS extreme water levels (`noaa-water-levels`) | pass-through | 1 | in progress | in progress | not assessed | 0 | draft |
| NOAA GHCNh station temperatures (`ghcnh`) | annual samples | 1 | assessed | assessed | not assessed | 3 | draft |
| CMIP6 projections (native grids) (`cmip6`) | fitted curves | 2 | not assessed | not assessed | not assessed | 0 | draft |
| ECCC rainfall intensity-duration-frequency (`eccc-idf`) | fitted curves | 2 | not assessed | not assessed | not assessed | 0 | draft |
| JRC EDO soil moisture index (`jrc-edo`) | fitted curves | 2 | not assessed | not assessed | not assessed | 2 | draft |
| JRC flood hazard maps (GloFAS, EFAS) (`jrc-flood`) | pass-through | 2 | assessed | assessed | not assessed | 12 | draft |
| NASA NEX-GDDP-CMIP6 projections (`nex-gddp-cmip6`) | annual samples | 2 | assessed | assessed | not assessed | 6 | draft |
| NOAA ISD station temperatures (`isd`) | fitted curves | 2 | not assessed | not assessed | not assessed | 0 | draft |
| OS-Climate hazard indicators (`os-climate`) | fitted curves | 2 | not assessed | not assessed | not assessed | 1 | draft |
| CHIRPS v3 monthly rainfall (`chirps`) | pass-through | 3 | not assessed | not assessed | not assessed | 0 | draft |
| ECCC daily climate observations (`eccc-daily`) | pass-through | 3 | not assessed | not assessed | not assessed | 0 | draft |
| ECCC HYDAT daily flow and level (`hydat`) | pass-through | 3 | not assessed | not assessed | not assessed | 0 | draft |
| Fields of The World field boundaries (`ftw-fields`) | pass-through | 3 | not assessed | not assessed | not assessed | 0 | draft |
| NOAA 2022 sea-level scenarios (`noaa-sea-level`) | pass-through | 3 | not assessed | not assessed | not assessed | 0 | draft |
| USDA Cropland Data Layer (`usda-cdl`) | pass-through | 3 | not assessed | not assessed | not assessed | 1 | draft |
| USGS daily streamflow (`usgs-streamflow`) | pass-through | 3 | not assessed | not assessed | not assessed | 0 | draft |
| Your own data (`own-data`) | user data | n/a | not assessed | not assessed | not assessed | 1 | draft |

## What crc-sdk offers that is not assessed

Every entry point found in the installed version has an inventory entry.

Sources with no assessment at any tier: 13 of 19.
Option values (recipes, datasets, versions) not yet assessed: 39.

## Findings

| Id | Source | Kind | Finding | Basis | Status |
| --- | --- | --- | --- | --- | --- |
| CRC-001-NEX | nex-gddp-cmip6 | defect | Temperature recipes (txx, tnn) fail on real NEX files | reproduced | fixed in 0.11.2 |
| CRC-002-FWK | framework | doc-code difference | The 20-year minimum counts the years requested, not the years valid in each cell | code reading | open |
| CRC-003-JRC | jrc-flood | doc-code difference | JRC flood and EDO output files do not carry licence, attribution, retrieval time or checksum | reproduced | fixed in 1.0.0 |
| CRC-004-EDO | jrc-edo | doc-code difference | EDO drought curves are labelled with the last year of the record, not the centre year | code reading | open |
| CRC-005-EDO | jrc-edo | observation | The EDO annual minimum has no completeness rule | code reading | open |
| CRC-006-ERA5 | era5 | observation | ERA5 values are converted without checking the unit the store declares | code reading | open |
| CRC-007-OPEN | crc-open | observation | retrieved_at in a CRC Open file is the time the file was written, not the time the data were downloaded | code reading | open |
| CRC-008-OSC | os-climate | doc-code difference | The OS-Climate licence is documented as read from layer metadata; no code that reads it was found | code reading | open |
| CRC-009-CDL | usda-cdl | observation | The Cropland Data Layer is read from a moving branch and its output records no provenance | code reading | open |
| CRC-010-IBT | ibtracs | defect | The subset "active" is accepted but NOAA has no file under that name | reproduced | fixed in 0.11.2 |
| CRC-011-IBT | ibtracs | observation | The snapshot's manifest has a terms address and a citation but no licence field; the batches carry no provenance | reproduced | fixed in 1.0.0 |
| CRC-012-NEX | nex-gddp-cmip6 | observation | NASA serves files of version 2.0, which cannot be requested | reproduced | superseded by CRC-031-NEX from 1.0.0 |
| CRC-013-FWK | framework | defect | The quantile fit gives up on depths that are flat and then rise, and crc-sdk then drops the pixel without a message | reproduced | superseded by CRC-026-FWK from 1.0.0 |
| CRC-014-JRC | jrc-flood | observation | A pixel the publisher shows flooded gets no curve, and no message, when it has fewer than four depths, equal depths or a decreasing depth | reproduced | superseded by CRC-023-JRC from 1.0.0 |
| CRC-015-JRC | jrc-flood | observation | The fitted curve can be positive where the publisher's map is dry, below zero where it is wet, and metres away from the published depth | reproduced | no longer applies from 1.0.0 |
| CRC-016-JRC | jrc-flood | observation | A request outside a dataset's coverage ends with an error that does not name the coverage, and the error differs with the cache mode | reproduced | superseded by CRC-024-JRC from 1.0.0 |
| CRC-017-JRC | jrc-flood | observation | The release is identified by one line of the publisher's README; the file addresses hold no version and no publisher checksum is taken | reproduced | open |
| CRC-018-JRC | jrc-flood | doc-code difference | crc-sdk states CC BY 4.0 for the JRC flood maps; the publisher's README names the Open Database License | reproduced | fixed in 1.0.0 |
| CRC-019-JRC | jrc-flood | observation | The publisher's masks of spurious depths and permanent water are not read | reproduced | open |
| CRC-020-JRC | jrc-flood | observation | With a cache, a pixel's source_id depends on the box asked for | reproduced | fixed in 1.0.0 |
| CRC-021-JRC | jrc-flood | defect | A cache made under a relative path cannot be read offline from another working folder | reproduced | open |
| CRC-022-JRC | jrc-flood | observation | A state-sized box is read in one process: 2 h 31 min and 5.5 GB of memory for the Texas box on 1.0.0 (27 minutes and 5.8 GB on 0.11) | reproduced | open |
| CRC-023-JRC | jrc-flood | observation | Flooded pixels with one depth, or with a depth lower than one at a shorter return period, are left out; the only trace is one count that also holds every dry pixel | reproduced | open |
| CRC-024-JRC | jrc-flood | observation | A box outside a product's coverage returns no rows, no diagnostic, and a report that says the read is complete and valid | reproduced | open |
| CRC-025-OWN | own-data | observation | `Dataset.from_raster` fails the whole read when one pixel's value decreases as probability rises, with an error that does not name the pixel; the JRC provider skips the same pixel | reproduced | open |
| CRC-026-FWK | framework | defect | Whether the quantile fit of a Gumbel curve converges depends on how the same depths are written: 32-bit values converge, their decimal values do not | reproduced | open |
| CRC-027-FWK | framework | doc-code difference | For a file read by window, the checksum recorded is of crc-sdk's own cut-out, not of the publisher's file | reproduced | open |
| CRC-028-IBT | ibtracs | observation | An agency's wind and pressure are placed at the combined IBTrACS position, not at the position that agency reported | reproduced | open |
| CRC-029-IBT | ibtracs | observation | Every point of the file is returned for every agency, most of them as rows with no value | reproduced | open |
| CRC-030-IBT | ibtracs | doc-code difference | The documentation says an explicit agency; the constructor defaults to the United States agencies | code reading | open |
| CRC-031-NEX | nex-gddp-cmip6 | observation | The file version cannot be chosen: the highest on NASA's listing is read, older revisions NASA still serves cannot be requested, and the version read appears only inside a file name | reproduced | open |
| CRC-032-NEX | nex-gddp-cmip6 | doc-code difference | Models whose calendar is not Gregorian are refused, although inspection lists them | reproduced | open |
| CRC-033-NEX | nex-gddp-cmip6 | doc-code difference | No licence is recorded for NEX files; the model licence written in the file is not read, and a share-alike licence raises no warning | reproduced | open |
| CRC-034-NEX | nex-gddp-cmip6 | observation | A year NASA has no file for is not refused: the nearest year's file is read and every cell comes back with no value | reproduced | open |
| CRC-035-GHC | ghcnh | observation | With the default completeness rule no station-year of forty Texas airport stations carries a value | reproduced | open |
| CRC-036-GHC | ghcnh | observation | One unusable report in one station's file stops the read of every selected station | reproduced | open |
| CRC-037-GHC | ghcnh | observation | GHCNh files are attributed to 'NOAA NCEI and NOAA CO-OPS', with a generic licence text and no dataset version | reproduced | open |
| CRC-038-FWK | framework | observation | A connection the publisher drops ends the read: no download is tried a second time | reproduced | open |

### CRC-001-NEX: Temperature recipes (txx, tnn) fail on real NEX files

- **Documented:** docs/sources/cmip6.md:5 says NEX uses the four recipes txx, tnn, rx1day and rx5day; line 36 says temperatures must be kelvin.
- **Observed:** The files declare kelvin, but h5netcdf returns the one-character unit as bytes (b'K') and the unit check compares its text form with 'K'. The call raises: 'tasmax' is published in "b'K'", but recipe 'txx' converts from 'K'. Precipitation is unaffected.
- **Consequence:** No temperature extremes can be read from NEX-GDDP-CMIP6 at this version.
- **Evidence:** crc_sdk/providers/cmip6.py:952; crc_sdk/workflows/nex.py:39-47; docs/reports/u1-nex-bytes-fix.md (crc-lab): real file headers, failing test, fix; check records nex-gddp-cmip6/units[txx ...] and units[tnn ...] (site/validation/data/records/nex-gddp-cmip6.json), run of 2026-11-12
- **Basis:** reproduced · **Status:** fixed in 0.11.2 (https://github.com/RiskThinking/crc-sdk/pull/42) · found 2026-11-10 at crc-sdk 0.11.1

### CRC-002-FWK: The 20-year minimum counts the years requested, not the years valid in each cell

- **Documented:** docs/sources/jrc.md:58: 'The curated policy fits the lower tail and requires at least 20 complete years.' The policy's own error message says it 'requires at least 20 complete years' (crc_sdk/workflows/blocks.py:126-129).
- **Observed:** validate_years compares the number of years in the request with minimum_years (crc_sdk/workflows/blocks.py:124-125). Each grid cell is then fitted when it has at least 4 valid annual values (MINIMUM_BLOCKS = 4, crc_sdk/connectors/blocks.py:60; minimum_blocks=4 in crc_sdk/providers/era5.py:566 and crc_sdk/providers/cmip6.py:1052). Station sources apply minimum_years per station.
- **Consequence:** A gridded curve can rest on far fewer years than the request suggests where data are missing; the number of years behind each cell's fit should be checked before use.
- **Evidence:** crc_sdk/workflows/blocks.py:124-129; crc_sdk/connectors/blocks.py:60; crc_sdk/providers/era5.py:566; crc_sdk/providers/cmip6.py:1052; docs/sources/jrc.md:58
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-003-JRC: JRC flood and EDO output files do not carry licence, attribution, retrieval time or checksum

- **Documented:** docs/data-licences.md:14-15: 'Every canonical file records source.licence, source.attribution, retrieved_at and checksum (schema 1.3), so outputs self-describe.'
- **Observed:** Those fields are written only when the curve source supplies a CurveSourceInfo (crc_sdk/connectors/adapters.py:309). The JRC and EDO modules define none; the JRC workflow only rewrites the uri (crc_sdk/workflows/jrc.py:521-534). Checksums of the cropped inputs are kept in the cache manifest, not in the output file. Shown on five real JRC flood outputs on 2026-11-17 (GloFAS for the Texas box, Houston, Austin and Fremont; EFAS for the Rhine box): in each, licence, attribution, retrieved_at and checksum are empty. Not yet shown for jrc-edo, where it is still code reading.
- **Consequence:** A JRC flood or EDO file, once moved away from its cache, does not say under which licence or from which bytes it was made.
- **Evidence:** docs/data-licences.md:14-15; crc_sdk/connectors/adapters.py:309; crc_sdk/workflows/jrc.py:521-534; check records jrc-flood/provenance[*] (site/validation/data/records/jrc-flood.json), run of 2026-11-17
- **Basis:** reproduced · **Status:** fixed in 1.0.0 · found 2026-11-11 at crc-sdk 0.11.1

### CRC-004-EDO: EDO drought curves are labelled with the last year of the record, not the centre year

- **Documented:** docs/design-decisions.md:28-30: for a window, 'horizon = centre year (start + end) // 2'. docs/sources/cmip6.md:42: 'horizon is the window centre'.
- **Observed:** The EDO provider sets the year of its record to max(years) (crc_sdk/providers/jrc_edo.py:217).
- **Consequence:** An EDO file and an ERA5 or CMIP6 file built over the same years would carry different horizons and would not join on the row key.
- **Evidence:** crc_sdk/providers/jrc_edo.py:217; docs/design-decisions.md:28-30
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-005-EDO: The EDO annual minimum has no completeness rule

- **Documented:** crc_sdk/connectors/blocks.py:20-30 states the convention for block statistics: a block needs a minimum fraction of valid days.
- **Observed:** The EDO annual value is np.nanmin over whatever ten-day values exist in the year (crc_sdk/providers/jrc_edo.py:255), so one valid value makes a year.
- **Consequence:** A year with most of its record missing still contributes an annual minimum to the fit.
- **Evidence:** crc_sdk/providers/jrc_edo.py:250-255; crc_sdk/connectors/blocks.py:20-30
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-006-ERA5: ERA5 values are converted without checking the unit the store declares

- **Observed:** The CMIP6 and NEX readers refuse a variable whose units attribute differs from the recipe's (crc_sdk/providers/cmip6.py:946-958). The ERA5 provider reads a units attribute only for the time axis (crc_sdk/providers/era5.py:244) and applies the kelvin and metre conversions unconditionally.
- **Consequence:** If a store changed its units, ERA5 values would be converted wrongly without an error.
- **Evidence:** crc_sdk/providers/era5.py:244; crc_sdk/providers/cmip6.py:946-958
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-007-OPEN: retrieved_at in a CRC Open file is the time the file was written, not the time the data were downloaded

- **Documented:** docs/data-licences.md:20-21: 'the retrieval date and checksum are the audit trail.'
- **Observed:** When a selection is materialised, retrieved_at is set to the current time (crc_sdk/workflows/crc_open.py:600), also when the partitions come from a warm cache.
- **Consequence:** The field cannot be used to tell when the release was actually fetched.
- **Evidence:** crc_sdk/workflows/crc_open.py:588-604
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-008-OSC: The OS-Climate licence is documented as read from layer metadata; no code that reads it was found

- **Documented:** docs/data-licences.md:38: 'OS-Climate layers | Read from layer metadata | Per layer'.
- **Observed:** A search of crc_sdk/providers/os_climate.py for licence handling finds none. Only that file was searched.
- **Consequence:** An OS-Climate output file may carry no licence.
- **Evidence:** docs/data-licences.md:38; crc_sdk/providers/os_climate.py (search for 'licen': no match)
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-009-CDL: The Cropland Data Layer is read from a moving branch and its output records no provenance

- **Documented:** docs/development.md:25-26: 'Every adapter records licence, attribution, retrieval time and checksums in canonical metadata or its cache manifest.'
- **Observed:** The request defaults to branch 'main' of the Source Cooperative repository, not a fixed snapshot (crc_sdk/connectors/agriculture.py:100). Rows carry a source path only.
- **Consequence:** Two runs of the same request can return different data with nothing in the output to show it.
- **Evidence:** crc_sdk/connectors/agriculture.py:96-101; docs/development.md:25-26
- **Basis:** code reading · **Status:** open · found 2026-11-11 at crc-sdk 0.11.1

### CRC-010-IBT: The subset "active" is accepted but NOAA has no file under that name

- **Documented:** crc_sdk/workflows/ibtracs.py:28-41 lists "active" among the eleven accepted subsets; the error message for any other spelling names it as valid. docs/sources/observations.md:29 documents basin subsets only.
- **Observed:** crc-sdk requests .../ibtracs.active.list.v04r01.csv and NOAA answers 404. NOAA's directory holds ibtracs.ACTIVE.list.v04r01.csv (capitals). IBTrACSPlan("active", ...).prefetch() raises HTTPError 404; IBTrACSPlan("ACTIVE", ...) is refused as an invalid subset. The other ten names are served.
- **Consequence:** Currently active storms cannot be read through IBTrACSPlan at this version. The other subsets are unaffected.
- **Evidence:** crc_sdk/workflows/ibtracs.py:28-41; crc_sdk/workflows/ibtracs.py:70-71; check record ibtracs/address (site/validation/data/records/ibtracs.json), run of 2026-11-12
- **Basis:** reproduced · **Status:** fixed in 0.11.2 (https://github.com/RiskThinking/crc-sdk/pull/43) · found 2026-11-12 at crc-sdk 0.11.1

### CRC-011-IBT: The snapshot's manifest has a terms address and a citation but no licence field; the batches carry no provenance

- **Documented:** AGENTS.md (crc-sdk) asks contributors to 'record licence, attribution, retrieval time and checksums for every source'. docs/data-licences.md:36 lists IBTrACS as a U.S. government work with attribution requested.
- **Observed:** The manifest written beside the snapshot holds url, version, subset, sha256, retrieved_at, etag, last_modified, units, terms_url and citation (crc_sdk/workflows/ibtracs.py:139-153). It has no licence field. The Arrow batches returned by batches() have no schema metadata, so the provenance travels only in the cache directory.
- **Consequence:** A user who passes the batches on must copy the citation and terms from the manifest or from prefetch(); nothing in the data carries them.
- **Evidence:** crc_sdk/workflows/ibtracs.py:139-153; check records ibtracs/provenance[*] (site/validation/data/records/ibtracs.json), run of 2026-11-12
- **Basis:** reproduced · **Status:** fixed in 1.0.0 · found 2026-11-12 at crc-sdk 0.11.1

### CRC-012-NEX: NASA serves files of version 2.0, which cannot be requested

- **Documented:** docs/sources/cmip6.md:73: 'File revisions 1.0, 1.1 and 1.2 are selected explicitly'. crc_sdk/workflows/nex.py:84-85 refuses any other version.
- **Observed:** For ACCESS-CM2 r1i1p1f1, NASA's archive holds files ending in _v2.0.nc for tasmax, tasmin and pr, in both years checked (historical 2014, ssp585 2050). They were uploaded on 1 July 2025 and carry the attribute version = '2.0'. No version 1.2 file exists for these; version 1.1 exists for pr only. In the Texas box the annual one-day rainfall from 2.0 equals that from 1.1 and differs from 1.0 in 15 of 2,158 cells in 2014 (by at most 0.08 mm) and 42 cells in 2050 (by at most 0.84 mm); the annual maximum temperature from 2.0 equals that from 1.0.
- **Consequence:** A user cannot read NASA's latest revision through crc-sdk, and the default (1.0) is the oldest. The differences seen here are small; other models, variables and regions were not compared. NASA's technical note for version 2.0 (31 May 2025, section 4.3) states that tasmax and tasmin were reprocessed in their entirety with a corrected observational reference (an artifact over central Canada) and that values were swapped in grid cells where the maximum was below the minimum; that anomalously large pr values in cells with an extremely small daily climatology were adjusted; and that bounds were applied to hurs, huss, rlds and sfcWind. These corrections are in version 2.0 only.
- **Evidence:** crc_sdk/workflows/nex.py:84-85; docs/sources/cmip6.md:73-74; NASA technical note for version 2.0, sections 3.2.2.1 and 4.3 (docs/validation/references/nex-gddp-cmip6-v2/README.md); check record nex-gddp-cmip6/versions-served (site/validation/data/records/nex-gddp-cmip6.json), run of 2026-11-12
- **Basis:** reproduced · **Status:** superseded by CRC-031-NEX from 1.0.0 · found 2026-11-12 at crc-sdk 0.11.1

### CRC-013-FWK: The quantile fit gives up on depths that are flat and then rise, and crc-sdk then drops the pixel without a message

- **Documented:** docs/sources/jrc.md:33-39 says the plan 'caches AOI crops, then fits'; no page says that a fit can fail. crc_sdk/connectors/adapters.py:432-433 raises 'quantile optimizer did not converge' when crc-framework's fit_quantiles reports no convergence, and the curated JRC policy sets on_fit_failure = 'skip' (crc_sdk/workflows/jrc.py:53).
- **Observed:** A least-squares line through the same points has an exact solution; the independent reference computes it for every such pixel. crc-framework 0.6.0 does not return one for 2,821 pixels of the Texas box, 82 of the Houston box, 5 of the Fremont box and 49 of the Rhine box (0 of the Austin box); the Houston and Austin boxes lie inside the Texas box. Each has several equal depths followed by larger ones, for example 1, 1, 1, 1, 1, 2.639, 3.768 m. Called directly, fit_quantiles(family='gumbel_r') on that series raises 'gumbel_r fitting did not converge after 374 iterations' when the depths are the 32-bit numbers of the file, and converges after 91 iterations when the same depths are given as decimal numbers. crc-sdk writes no row and no message for these pixels. For every pixel both sides fitted, location and scale agree within 1.2e-6 m (two of 19,702,276 parameters in the Texas box differ by more than the tolerance of 1e-6 m, the larger by 1.1e-6 m).
- **Consequence:** A small share of pixels (about 3 in 10,000 here) that have depths at four or more return periods get no curve although one exists, and nothing in the output says so. Whether a pixel is fitted depends on the last digits of its depths.
- **Evidence:** crc_sdk/connectors/adapters.py:420, 432-433, 702-716; crc_sdk/workflows/jrc.py:53; check records jrc-flood/curves[glofas-tx], curves[glofas-houston], curves[glofas-fremont], curves[efas-rhine] (site/validation/data/records/jrc-flood.json), run of 2026-11-17; optimizer in data/cache/validation/jrc-flood/probes/probes.json (tools/probes/jrc_flood_probes.py), 2026-11-17; tests/validation/test_data_source_check_jrc_flood.py: test_depths_the_optimizer_does_not_converge_on_are_seen
- **Basis:** reproduced · **Status:** superseded by CRC-026-FWK from 1.0.0 · found 2026-11-17 at crc-sdk 0.11.1

### CRC-014-JRC: A pixel the publisher shows flooded gets no curve, and no message, when it has fewer than four depths, equal depths or a decreasing depth

- **Documented:** docs/sources/jrc.md does not mention pixels left out. The rules are in the code: four or more finite depths (crc_sdk/connectors/adapters.py:658-663), a fit failure is skipped (adapters.py:702-716, crc_sdk/workflows/jrc.py:53), and the curated policy writes no diagnostics file (jrc.py:57-81).
- **Observed:** Share of the pixels that have a depth at some return period and get no curve: Texas box 1,832,251 of 11,686,210 (15.7%), Houston 65,705 of 278,654 (23.6%), Austin 3,293 of 25,494 (12.9%), Fremont 2,734 of 10,603 (25.8%), Rhine (EFAS) 18,824 of 161,898 (11.6%). By cause in the Texas box: fewer than four depths 941,251; all depths equal 698,317 (every one of them at exactly 1 m at every return period); a depth lower than at a shorter return period 192,683; the fit not converging 2,821 (CRC-013-FWK). At the 500-year return period 1,832,250 of the 11,686,209 flooded pixels of the Texas box have no curve; at 10 years 890,968 of 9,255,575. The reference applies the same rules and names the same pixels, apart from those of CRC-013-FWK. Set against the publisher's permanent-water layer (GloFAS, four areas): every pixel with all depths equal lies in permanent water (Texas box 698,317 of 698,317; Houston 16,983 of 16,983; Austin 1,243 of 1,243; Fremont 992 of 992), as do nearly all with a decreasing depth (Texas box 192,619 of 192,683); none of the pixels with fewer than four depths does (Texas box 0 of 941,251; Houston 0 of 44,732; Austin 0 of 1,910; Fremont 0 of 967).
- **Consequence:** A place the publisher's map floods only at long return periods (100 years and more), or at a constant 1 m, is absent from the output in the same way as a place that never floods. A user reading the output as 'no row means no flood' undercounts flooded area by the shares above. The pixels left out for equal or decreasing depths are permanent water bodies, where the publisher patched its maps (1 m is the patch value seen); those left out for fewer than four depths are land the publisher's map floods only at the longer return periods, about half of all pixels left out in the Texas box.
- **Evidence:** crc_sdk/connectors/adapters.py:658-663, 702-716; crc_sdk/workflows/jrc.py:53, 57-81; check records jrc-flood/curves[*] and exploration tables 'Wet pixels that get no curve', 'Published wet pixels without a curve, by return period' (site/validation/data/records/jrc-flood.json), run of 2026-11-17; permanent_water in data/cache/validation/jrc-flood/probes/probes.json (tools/probes/jrc_flood_probes.py), 2026-11-17
- **Basis:** reproduced · **Status:** superseded by CRC-023-JRC from 1.0.0 · found 2026-11-17 at crc-sdk 0.11.1

### CRC-015-JRC: The fitted curve can be positive where the publisher's map is dry, below zero where it is wet, and metres away from the published depth

- **Documented:** docs/sources/jrc.md:38-39: 'Fitted values at source return periods are curve evaluations, not bit-for-bit source pixels.' The curated policy sets no limit on the misfit (crc_sdk/workflows/jrc.py:50-56; maximum_normalized_rmse and maximum_absolute_residual are None).
- **Observed:** Largest distance between the curve and a published depth, per fitted pixel: Texas box median 0.039 m, 99th percentile 0.60 m, largest 26.4 m, above 1 m in 31,771 of 9,853,959 pixels; Houston median 0.040 m, largest 3.1 m; Austin median 0.095 m, largest 1.2 m; Fremont median 0.017 m, largest 2.0 m; Rhine median 0.092 m, largest 8.7 m, above 1 m in 654 of 143,074. At the 10-year return period, pixels with no published depth where the curve gives 0.1 m or more: Texas 493,550, Houston 14,678, Austin 782, Fremont 593, Rhine 5,709 (largest value at a dry return period: 53.9 m in the Texas box). Pixels whose curve is below zero at 10 years: Texas 604,768, Houston 21,124, Austin 2,075, Fremont 362, Rhine 15,293. At 100 years and longer neither occurs in any area.
- **Consequence:** Evaluated at 10 to 50 years, the output shows water where the publisher's map has none and negative depths where it has water; the documentation says the values are not bit-for-bit but gives no size. A user who needs the published depth at a published return period cannot get it from the output. Distances computed by the reference from its own fit, which equals crc-sdk's within 1.2e-6 m.
- **Evidence:** docs/sources/jrc.md:38-39; crc_sdk/workflows/jrc.py:50-56; exploration tables 'How far the fitted curve lies from the published depths' and 'Curve where the publisher is dry, and curve below zero' (site/validation/data/records/jrc-flood.json), run of 2026-11-17; check records jrc-flood/values[*] (site/validation/data/records/jrc-flood.json), run of 2026-11-17
- **Basis:** reproduced · **Status:** no longer applies from 1.0.0 · found 2026-11-17 at crc-sdk 0.11.1

### CRC-016-JRC: A request outside a dataset's coverage ends with an error that does not name the coverage, and the error differs with the cache mode

- **Documented:** docs/sources/jrc.md does not say what happens outside the coverage. EFAS's README gives its extent (longitude -24.54 to 67.26, latitude 27.81 to 71.13).
- **Observed:** HazardDataset.efas for the Texas box and for the Fremont box, with a cache: LookupError 'no JRC resources intersect area (-106.645646, 25.837377, -93.508292, 36.500704)' after 1.0 s and 0.7 s; nothing in the message names EFAS's extent or says that the box is outside it. Read in the code, not run: without a cache (stream mode) the same request raises ValueError 'bounds do not intersect the raster' (crc_sdk/connectors/duckdb/geotiff.py:289-292).
- **Consequence:** The user learns that nothing intersects but not why; a caller that catches one error type misses the other.
- **Evidence:** crc_sdk/workflows/jrc.py:156-159, 439-441, 516-517; crc_sdk/connectors/duckdb/geotiff.py:289-292; check records jrc-flood/coverage[efas-tx], coverage[efas-fremont] (site/validation/data/records/jrc-flood.json), run of 2026-11-17
- **Basis:** reproduced · **Status:** superseded by CRC-024-JRC from 1.0.0 · found 2026-11-17 at crc-sdk 0.11.1

### CRC-017-JRC: The release is identified by one line of the publisher's README; the file addresses hold no version and no publisher checksum is taken

- **Documented:** docs/sources/jrc.md:33-34: 'materialize() resolves latest once and pins the version in the cache manifest and canonical provenance'.
- **Observed:** The version is the text after 'Dataset version' in README.txt (crc_sdk/providers/jrc.py:155-176); the depth files are at addresses without a version (.../flood_hazard/RP100/ID38_N30_W100_RP100_depth.tif). The cache manifest holds the SHA-256 of each local crop, not of the publisher's file. On 2026-11-17 the publisher's directory showed, for GloFAS: README 'Dataset version 2.1.2', README last updated 12.01.2026 and modified 2026-10-21, depth files dated 2025-12-17 to 2025-12-18, return-period folders modified 2026-10-30; for EFAS: version 3.1.1, depth files dated 2026-03-03 to 2026-03-05. Read in the code, not run: a later run that finds a manifest does not ask the publisher again (crc_sdk/workflows/jrc.py:362-365).
- **Consequence:** If the publisher replaces a depth file without changing the README line, two runs with the same pinned version read different bytes and nothing records it. The crops in a cache can be checked against the manifest; the publisher's file cannot. No such replacement was observed.
- **Evidence:** crc_sdk/providers/jrc.py:83-110, 155-176; crc_sdk/workflows/jrc.py:109-132, 362-365, 449-465; check records jrc-flood/files[glofas], files[efas], manifest[*] and exploration table 'The publisher's releases' (site/validation/data/records/jrc-flood.json), run of 2026-11-17
- **Basis:** reproduced · **Status:** open · found 2026-11-17 at crc-sdk 0.11.1

### CRC-018-JRC: crc-sdk states CC BY 4.0 for the JRC flood maps; the publisher's README names the Open Database License

- **Documented:** docs/sources/jrc.md:5-6: 'Both sources are CC BY 4.0; cite JRC and the product version.' docs/data-licences.md:31: 'JRC EFAS / GloFAS flood | CC-BY-4.0'.
- **Observed:** README.txt of both datasets, line A02: 'License information, restrictions on use: Open Data Commons Open Database License v1.0'. copyright.txt in the same directories: 'Any copyright and/or sui generis right on the dataset is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence'. The two publisher files name different licences; crc-sdk's documentation agrees with copyright.txt. The licence is written in crc-sdk's documentation only: it is not read from the publisher and not written into the output (CRC-003-JRC).
- **Consequence:** Which licence governs is the publisher's to say; the Open Database License has a share-alike condition that CC BY 4.0 does not. A user relying on crc-sdk's statement has not been told that the publisher's README says otherwise.
- **Evidence:** docs/sources/jrc.md:5-6; docs/data-licences.md:31; publisher files README.txt and copyright.txt of CEMS-GLOFAS/flood_hazard and CEMS-EFAS/flood_hazard, read 2026-11-17 (checksums in the draft records); check records jrc-flood/provenance[*] and exploration table 'The publisher's releases' (site/validation/data/records/jrc-flood.json), run of 2026-11-17
- **Basis:** reproduced · **Status:** fixed in 1.0.0 · found 2026-11-17 at crc-sdk 0.11.1

### CRC-019-JRC: The publisher's masks of spurious depths and permanent water are not read

- **Documented:** docs/sources/jrc.md does not mention them. GloFAS README (F01 and the file description): the release includes, per tile, 'the permanent water bodies used to patch the flood hazard maps' and 'the spurious depth map that identifies areas where depths >10m are predicted in small channels (<3,000km^2) for the 10-year return period, plus a 2km buffer'. EFAS holds Europe_permanent_water_bodies.tif and Europe_spurious_depth_areas.tif.
- **Observed:** crc-sdk requests the depth files only (crc_sdk/providers/jrc.py:186-246). In the GloFAS tiles read here, pixels inside the spurious-depth mask: Texas box 268,433, Austin 1,245, Fremont 5,137, Houston 0. Pixels deeper than 10 m at 100 years, and how many of them lie inside the mask: Fremont 126, all 126 inside; Austin 2,201, 21 inside; Texas box 192,437, 8,393 inside. Largest depth: Texas box 108.2 m, Austin 21.8 m, Fremont 20.5 m, Houston 10.1 m, Rhine 22.9 m. These depths are fitted and delivered like any other. The GloFAS permanent-water layer was read in a probe: of the pixels that get a curve, those inside permanent water are 1,894,754 of 9,853,959 in the Texas box (19%), 16,770 of 212,949 in the Houston box, 6,284 of 22,201 in the Austin box and 1,909 of 7,869 in the Fremont box; their curves are fitted to depths that include the patch value (for example 1, 1, 1, 1, 1, 2.639, 3.768 m). The EFAS masks were not read.
- **Consequence:** Depths the publisher itself marks as doubtful reach the user unmarked; in the Fremont box every depth above 10 m is of that kind. Depths above 10 m outside the mask (most of those in the Texas box) are not explained by it; how many of them are permanent water was not counted. About a fifth of the curves in these areas describe a permanent water body, not flooding of land, and nothing in the output marks them.
- **Evidence:** crc_sdk/providers/jrc.py:186-246; publisher file README.txt of CEMS-GLOFAS/flood_hazard, lines 38-49, read 2026-11-17; exploration table 'Depths above 10 m and the publisher's spurious-depth mask' (site/validation/data/records/jrc-flood.json), run of 2026-11-17; permanent_water in data/cache/validation/jrc-flood/probes/probes.json (tools/probes/jrc_flood_probes.py), 2026-11-17
- **Basis:** reproduced · **Status:** open · found 2026-11-17 at crc-sdk 0.11.1

### CRC-020-JRC: With a cache, a pixel's source_id depends on the box asked for

- **Documented:** docs/concepts.md:43 gives the row key as (hazard_name, horizon, pathway, cell_index, source_id). No page says what source_id is made from.
- **Observed:** source_id is the SHA-256 of the dataset name, the tile and the pixel's row and column (crc_sdk/connectors/adapters.py:299-301, 741-743); with a cache the row and column are those of the local crop (crc_sdk/workflows/jrc.py:502-511). All 22,201 fitted pixels of the Austin box are also in the Texas-box output with the same curve (difference of location 0); of 2,000 of them compared, 0 have the same source_id in the two outputs. Per area, the ids equal the reference's computed from the crop position in every sampled pixel, and equal the position in the publisher's file in 0 of 2,000 (621 of 2,000 in the Texas box, where the crops of two tiles begin at the tile's first row and column). Without a cache the position is the file's (read in the code, not run).
- **Consequence:** Outputs for two boxes cannot be joined, compared or de-duplicated on source_id, and the same request with and without a cache gives different ids for the same pixel.
- **Evidence:** crc_sdk/connectors/adapters.py:299-301, 741-743; crc_sdk/workflows/jrc.py:502-511; check records jrc-flood/source-id[*] (site/validation/data/records/jrc-flood.json), run of 2026-11-17; same_pixel_in_two_areas in data/cache/validation/jrc-flood/probes/probes.json (tools/probes/jrc_flood_probes.py), 2026-11-17
- **Basis:** reproduced · **Status:** fixed in 1.0.0 · found 2026-11-17 at crc-sdk 0.11.1

### CRC-021-JRC: A cache made under a relative path cannot be read offline from another working folder

- **Documented:** No page says a cache is tied to the working folder it was made from. The documentation's example uses a relative path (docs/sources/jrc.md:19).
- **Observed:** The manifest stores each crop's path as the cache path was given (for .cache('cache', ...): 'cache/aoi/rp10-....tif'). A run in offline mode from another working folder, given the absolute path of the same cache, ends with FileNotFoundError 'cems-glofas-river-flood cannot be materialized offline; missing or invalid cached AOI resources: ID18_N40_W130:RP10, ...'; from the working folder the cache was made in, the same run completes. Tried on the Fremont box with four return periods.
- **Consequence:** A cache built with a relative path (as in the documentation's example, .cache('cache/efas', mode='reuse')) stops working offline when it is moved, mounted elsewhere or used by a job started in another folder. The message says the resources are missing or invalid, though the files are present and unchanged.
- **Evidence:** crc_sdk/workflows/jrc.py:109-132, 449-465; docs/sources/jrc.md:19; relative_cache in data/cache/validation/jrc-flood/probes/probes.json (tools/probes/jrc_flood_probes.py), 2026-11-17
- **Basis:** reproduced · **Status:** open · found 2026-11-17 at crc-sdk 0.11.1

### CRC-022-JRC: A state-sized box is read in one process: 2 h 31 min and 5.5 GB of memory for the Texas box on 1.0.0 (27 minutes and 5.8 GB on 0.11)

- **Documented:** docs/sources/jrc.md gives no time or size. Its example is a box of 0.7 by 0.5 degrees.
- **Observed:** GloFAS for the Texas box (201,757,502 pixels in four tiles, 9,851,138 curves, 10,703,386 rows): 1,604 s and a peak of 5,804 MB on an arm64 Mac with 16 GB, the 28 crops (about 0.6 GB at the publisher) fetched in the same run. The smaller boxes took 10 s (Austin, 22,201 curves) to 54 s (Houston, 212,867 curves). The table is validated in a separate worker process (crc_sdk/connectors/parquet.py:232), which fails with BrokenProcessPool when the calling script is read from standard input. Read in the code: the output file is written only at the end of the run. On crc-sdk 1.0.0 (2026-11-25), where nothing is fitted: the same box, read from the publisher by `JRC(...).select(area=...).read()`, took 9,081 s and a peak of 5,483 MB for 11,069,311 rows, on the same machine; Houston took 111 s and the Rhine box 137 s. Four earlier tries of the Texas read ended on a dropped connection and one when the machine slept; nothing of a failed read is kept.
- **Consequence:** On 1.0.0 a user asking for a state should expect hours, not tens of minutes. At 0.11 a user asking for a state or a country should expect tens of minutes and several GB per run, with nothing kept if the run stops before the end; a larger box may not fit in memory. One machine, one run.
- **Evidence:** crc_sdk/connectors/adapters.py:640-803; crc_sdk/connectors/parquet.py:232; exploration table 'crc-sdk's runs' (site/validation/data/records/jrc-flood.json), run of 2026-11-17
- **Basis:** reproduced · **Status:** open · found 2026-11-17 at crc-sdk 0.11.1

### CRC-023-JRC: Flooded pixels with one depth, or with a depth lower than one at a shorter return period, are left out; the only trace is one count that also holds every dry pixel

- **Documented:** docs/sources.md:33 describes the output as 'original pixels and quantile knots' and does not mention pixels left out. The rule is in the code (crc_sdk/_climate_io.py:173-189), and a comment says JRC's maps 'are inconsistent at a few pixels; those are skipped and counted, not repaired' (crc_sdk/_climate_sources.py:463-464). The read reports one number: 'Skipped N source supports whose values are not a quantile curve: fewer than two valid probability values, or values that decrease as probability rises.' (crc_sdk/_climate_sources.py:149-151).
- **Observed:** Counted from the publisher's files by the reference reader, and equal to crc-sdk's own skipped count in every area. Houston: 1,045,703 skipped = 1,019,627 dry + 22,086 with one depth + 3,990 with a decreasing depth. Austin: 336,778 = 335,707 + 931 + 140. Fremont: 77,632 = 76,398 + 459 + 775. Rhine (EFAS): 2,440,888 = 2,433,343 + 6,815 + 730. So of the pixels the publisher shows flooded at some return period, the share left out is 26,076 of 278,654 in Houston (9.4%), 1,071 of 25,494 in Austin (4.2%), 1,234 of 10,603 in Fremont (11.6%) and 7,545 of 161,898 on the Rhine (4.7%). The warning carries no support_id and no split.
- **Consequence:** A pixel that floods only at the longest return period, and a pixel where the publisher's depths are inconsistent, are absent from the output in the same way as a pixel that never floods, and the reported count cannot tell the three apart: in Houston it is 40 times the number of flooded pixels dropped. A user who reads 'no row' as 'no flood' undercounts flooded area by the shares above. 'A few' in the code comment is 775 of 10,603 flooded pixels in the Fremont box.
- **Evidence:** crc_sdk/_climate_io.py:173-189; crc_sdk/_climate_sources.py:149-151, 463-464; docs/sources.md:33; check records jrc-flood/delivered[*] and the table 'Pixels by area' (records of jrc-flood, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-024-JRC: A box outside a product's coverage returns no rows, no diagnostic, and a report that says the read is complete and valid

- **Documented:** docs/sources.md and docs/execution.md do not say what a read outside a product's coverage returns. docs/evaluation.md:58-69 describes failure rows for assets that no support covers, which concerns evaluation, not reading.
- **Observed:** `JRC(product=JRC.Product.EFAS).select(area=Bounds(west=-122.15, south=37.42, east=-121.85, north=37.62)).read()` (Fremont, California, read through the European product) returns 0 rows; report counts requested 0, produced 0, skipped 0; no diagnostics; `complete=True`, `valid=True`; no exception (crc_sdk/_climate_io.py:105-133: a window that misses the raster adds no range).
- **Consequence:** A wrong product, or a box with west and east exchanged, cannot be told from a region the product covers and shows dry: both give an empty, complete, valid result. At 0.11 the same request ended in an error, though one that did not name the coverage (CRC-016-JRC).
- **Evidence:** crc_sdk/_climate_io.py:105-133; check record jrc-flood/coverage[efas-fremont] (records of jrc-flood, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-025-OWN: `Dataset.from_raster` fails the whole read when one pixel's value decreases as probability rises, with an error that does not name the pixel; the JRC provider skips the same pixel

- **Documented:** docs/datasets.md:81-84: 'Each pixel retains its original footprint and quantile knots.' The docstring of crc_sdk/_climate_io.py:55-60 states the difference: with skip_decreasing such a pixel 'is skipped and counted (published maps contain a few); otherwise it is invalid source data, which for user rasters usually means mislabeled probabilities'. docs/datasets.md does not mention it.
- **Observed:** The publisher's own GloFAS files for a 5 by 5 pixel block near Fremont and one near Houston, given to `Dataset.from_raster` with probabilities 1 - 1/T: `ValidationError: quantile evidence requires matching ordered knots, probabilities strictly increasing in [0, 1] and values nondecreasing`; counts requested 13, produced 0 (Fremont) and 4, 0 (Houston); the diagnostic's support_id is None. One pixel in each block has a depth lower at a longer return period (Fremont: 1.0, 1.0 at 10 and 20 years, then 0.256 at 50 years). Through `JRC(...)` the same blocks are read and that pixel is skipped.
- **Consequence:** A user who brings published flood maps in as their own rasters, the documented route for any map crc-sdk has no provider for, gets no output at all for a box that holds one inconsistent pixel, and is not told which pixel. In the Fremont box 775 of 10,603 flooded pixels are of this kind, so most real boxes would fail.
- **Evidence:** crc_sdk/_climate_io.py:55-60, 173-189; docs/datasets.md:81-84; probe jrc-decreasing in docs/reports/v1-probes-1.0.0.md (tools/probes/v1/probes.py), 2026-11-24
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-026-FWK: Whether the quantile fit of a Gumbel curve converges depends on how the same depths are written: 32-bit values converge, their decimal values do not

- **Documented:** crc-framework docs/python.md describes `fit_quantiles` with `QuantileFit`; it states no condition on the representation of the values. A failed fit raises `FitError` with the record of the attempts.
- **Observed:** crc-framework 1.0.0, `QuantileFit` with the Gumbel family, depths that are flat and then rise at the two longest return periods. As 32-bit floats: [..., 2.639, 3.768] converges after 54 iterations and [..., 1.016, 1.13] after 87. The same numbers as decimals do not converge after 362 and 300 iterations ('gumbel_r fitting did not converge'). At crc-framework 0.6.0 it was the reverse: the 32-bit values did not converge (374 and 358 iterations) and the decimals did (91 and 89).
- **Consequence:** The same published depths are fitted or not according to a difference in the eighth significant digit. From 1.0 crc-sdk fits JRC depths only when the user asks, and the failure is then visible; but which pixels fail still follows the number format, not the data.
- **Evidence:** probe crc013-fit in docs/reports/v1-probes-1.0.0.md (tools/probes/v1/probes.py), 2026-11-24; tools/probes/jrc_flood_probes.py (the 0.6.0 case, 2026-11-17)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-027-FWK: For a file read by window, the checksum recorded is of crc-sdk's own cut-out, not of the publisher's file

- **Documented:** docs/data-licences.md:8: 'A `ResourceIdentity` carries its URI and full content SHA-256 identity.'
- **Observed:** For each JRC depth file the recorded resource has an address ending in '#crc-window=<west>,<south>,<east>,<north>' and a SHA-256 of the bundle crc-sdk wrote for that window (crc_sdk/_climate_io.py:423-515). In the four JRC areas 44 of 55 recorded resources are of this kind; the README and the tile index, read whole, carry checksums equal to the reference's. The same holds for NEX files (address ending '#crc-variable=...&window=...').
- **Consequence:** The checksum identifies what crc-sdk extracted, so it changes with the box asked for and cannot be compared with a checksum of the publisher's file, published or computed. It does not show that the publisher's file was the one expected; that rests on the ETag sent with each range request.
- **Evidence:** docs/data-licences.md:8; crc_sdk/_climate_io.py:423-515; check records jrc-flood/provenance[*] (records of jrc-flood, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-028-IBT: An agency's wind and pressure are placed at the combined IBTrACS position, not at the position that agency reported

- **Documented:** docs/sources.md:43: 'Native storm point observations for an explicit `Agency`; event groups and positions remain distinct'. Which position is used is not stated.
- **Observed:** The decoder reads the columns LAT and LON (crc_sdk/_observed_decoders.py:497-499); NOAA's file also holds a position per agency (USA_LAT, USA_LON, TOKYO_LAT, ...), which is not read. The reference reader, built on LAT and LON, agrees with crc-sdk on every row of all ten agencies (checks values[<agency>], 233,822,080 values, 0 differ).
- **Consequence:** For a storm that several agencies tracked, each agency's wind is attached to the same merged position. A user comparing agencies, or wanting the agency's own best track, gets positions that are not that agency's without being told.
- **Evidence:** crc_sdk/_observed_decoders.py:467-478, 497-499; docs/sources.md:43; check records ibtracs/values[*] (records of ibtracs, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-029-IBT: Every point of the file is returned for every agency, most of them as rows with no value

- **Documented:** docs/sources.md:43 and 159 describe the output as the chosen agency's observations. docs/execution.md says expected data failures are kept as rows.
- **Observed:** Each agency returns 1,461,388 rows (two per point of NOAA's file). Rows without a value: USA 884,001; TOKYO 1,275,029; CMA 1,183,352; HKO 1,288,864; NEWDELHI 1,443,316; REUNION 1,393,474; BOM 1,364,033; NADI 1,445,408; WELLINGTON 1,414,631; WMO 1,117,014. For New Delhi 98.8% of the rows are `source_no_data`.
- **Consequence:** The number of rows says nothing about an agency's coverage, and a user must filter on `failure` before any count or statistic. Reading New Delhi costs the same time and memory as reading the United States agencies and returns 18,072 values.
- **Evidence:** crc_sdk/_observed_decoders.py:486-522; table 'What crc-sdk returns for each agency' (records of ibtracs, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-030-IBT: The documentation says an explicit agency; the constructor defaults to the United States agencies

- **Documented:** docs/sources.md:43: 'Native storm point observations for an explicit `Agency`'.
- **Observed:** `IBTrACS()` with no argument reads `Agency.USA` (crc_sdk/_observed_sources.py:2262). The package's own interface declaration, crc_sdk/contracts/api/public-api.json, states this default, so the default is intended and the difference is in the wording of docs/sources.md, where `explicit` may also be meant as `typed`.
- **Consequence:** A user who omits the agency gets one agency's winds, with a 60-second averaging period, without having chosen it; for basins outside the United States agencies' responsibility that is not the WMO-designated centre.
- **Evidence:** docs/sources.md:43; crc_sdk/_observed_sources.py:2262
- **Basis:** code reading · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-031-NEX: The file version cannot be chosen: the highest on NASA's listing is read, older revisions NASA still serves cannot be requested, and the version read appears only inside a file name

- **Documented:** docs/sources.md does not mention NEX file versions. docs/migration-v1.md lists `HazardDataset.nex_gddp_cmip6(...)` as replaced by `NEX(...)` without saying that the `version` argument is gone.
- **Observed:** `NEX(...)` has no version argument (crc_sdk/_climate_sampling.py:269-290). For each year the listing is read and the highest `_v<X.Y>` is taken (crc_sdk/_climate_sampling.py:119, 1627-1641). For ACCESS-CM2 r1i1p1f1, 2014 and 2050, crc-sdk 1.0.0 read version 2.0 of pr, tasmax and tasmin in all eight cases (checks file[*]); crc-sdk 0.11.2 read 1.0 and 1.1 for the same requests. NASA still serves 1.0 of all three variables and 1.1 of pr (check versions-served). The version is not a field of the output: it is in the file name inside the recorded address.
- **Consequence:** The same request gives values from a different revision of NASA's files than it did a version earlier, and will change again when NASA adds a revision, with nothing in the output's fields to show it. A study that must stay on one revision, or reproduce an earlier result, cannot ask for it.
- **Evidence:** crc_sdk/_climate_sampling.py:119, 269-290, 1627-1641; check records nex-gddp-cmip6/file[*] and versions-served (records of nex-gddp-cmip6, run of 2026-11-24 on crc-sdk 1.0.0); records of nex-gddp-cmip6 at 0.11.2 (site/validation/data/records/0.11.2/nex-gddp-cmip6.json)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-032-NEX: Models whose calendar is not Gregorian are refused, although inspection lists them

- **Documented:** docs/sources.md:104-106 and 124: NEX exposes the published combinations of model, scenario and member, and inspection 'reads its calendar'. `NEX().inspect()` lists every model.
- **Observed:** The calendar is read from the first file's header and the read is refused unless it is `standard`, `gregorian` or `proleptic_gregorian` (crc_sdk/_climate_sampling.py:1811-1817). For BCC-CSM2-MR, whose files declare `365_day`: `ValidationError: NEX source does not use its published Gregorian calendar` (check calendar[BCC-CSM2-MR rx1day historical 2014]). A survey of the 2014 historical precipitation headers of 35 models on 2026-11-24, made by the porting agent and not kept as a record, found 14 Gregorian, 16 on `365_day`, 4 on `360_day` and one unread. crc-sdk 0.11 read 365-day models (its records label `365_day` as `noleap`).
- **Consequence:** By that survey 20 of 34 models cannot be read through 1.0, among them UKESM1-0-LL and CanESM5. The error text says 'published Gregorian calendar' of files whose published calendar is not Gregorian, and a user learns that a model is unreadable only after choosing it from the inspection.
- **Evidence:** crc_sdk/_climate_sampling.py:1811-1817; docs/sources.md:104-106, 124; check record nex-gddp-cmip6/calendar[BCC-CSM2-MR rx1day historical 2014] (records of nex-gddp-cmip6, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-033-NEX: No licence is recorded for NEX files; the model licence written in the file is not read, and a share-alike licence raises no warning

- **Documented:** docs/data-licences.md:9-11: licence and attribution are recorded 'when known'; 'there is no invented default license or attribution'. Up to 0.11 crc-sdk kept the file's model licence beside NASA's CC0 and warned when it was not CC0.
- **Observed:** Only a global attribute named `license` or `licence` is copied onto the resource (crc_sdk/_climate_sampling.py:1856-1862). NASA's files carry `cmip6_license`. In all eight cases the recorded licence is null while the file states one: `CC-BY-SA 4.0` in the four temperature files (tasmax, tasmin) and `CC-BY 4.0` in the four precipitation files of the same model, ACCESS-CM2 (checks labels[*]: 'licence on the resource: None; cmip6_license in the file: ...'). NASA's archive-level CC0 statement is not recorded either. No warning is raised.
- **Consequence:** Output derived from a share-alike model carries no licence and no warning, where the previous version recorded the licence and warned. A user cannot see from the output that redistribution has a condition.
- **Evidence:** crc_sdk/_climate_sampling.py:1856-1862; docs/data-licences.md:9-11; check records nex-gddp-cmip6/labels[*] (records of nex-gddp-cmip6, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-034-NEX: A year NASA has no file for is not refused: the nearest year's file is read and every cell comes back with no value

- **Documented:** Not documented.
- **Observed:** Asked for the historical run in 2015, which ends in 2014, crc-sdk reads `pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc` and returns 2,332 rows, each with no value and the failure `incomplete_year` (0 of 365 days) (crc_sdk/_climate_sampling.py:1833-1835, 1911-1912; check year-without-file[rx1day historical 2015]). At 0.11 a file NASA did not have ended in an error.
- **Consequence:** A request for a year outside a scenario's span costs a whole file read (about 250 MB by range requests) and returns rows that look like a year with gaps, not like a year that does not exist.
- **Evidence:** crc_sdk/_climate_sampling.py:1833-1835, 1911-1912; check record nex-gddp-cmip6/year-without-file[rx1day historical 2015] (records of nex-gddp-cmip6, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-035-GHC: With the default completeness rule no station-year of forty Texas airport stations carries a value

- **Documented:** docs/sources.md:93: 'The default is `Coverage.complete()`'; docs/sources.md:259-260: a day needs 24 hourly reports. `Coverage.minimum_fraction` relaxes the year, not the day.
- **Observed:** For the first 40 USW stations in the Texas box, 2000 to 2024, NOAA has a file for 592 of 1,000 station-years. Through `GHCNh(indicator=...).read()` with the default coverage, 0 of 592 rows carry a value, for both indicators; every row has the failure `incomplete_year`. With `Coverage.minimum_fraction(0.9)`, 339 of 592 do. Under the rules of crc-sdk 0.11 (18 of 24 hours a day, 90% of days) the same files give, for example, 13, 16, 17, 15, 16 and 15 complete years for the first six stations, against 0 now. The 24-hour day is fixed in the code (crc_sdk/_station_reduction.py:65-75, 108-117) and cannot be relaxed. The reference recomputation agrees with crc-sdk on every row (checks annual[*], 6,512 values each, 0 differ). A second look on 2026-11-25 at five major airports (Austin, Dallas/Fort Worth, Houston, San Antonio, El Paso), 2019 to 2022: 2 of 20 station-years carry a default value, both with 365 of 365 complete days; the other 18 have 356 to 364 complete days and no value; all 20 have one at a 0.9 fraction (tools/repro/crc_035_ghcnh_default_coverage.py). So the default gives a value only for a year in which every day has all 24 reports.
- **Consequence:** The default read of hourly airport stations returns rows without values only. A user must find and pass a coverage fraction to get anything, and even then a day with 23 reports is discarded. Curves fitted from these stations at 0.11 cannot be reproduced with any setting of 1.0, because the day rule changed and is not adjustable.
- **Evidence:** crc_sdk/_station_reduction.py:65-75, 108-117; crc_sdk/_aggregation.py:95-116, 772-776; docs/sources.md:93, 259-260; check records ghcnh/annual[*] and the tables 'From stations to annual values' and 'Stations' (records of ghcnh, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-036-GHC: One unusable report in one station's file stops the read of every selected station

- **Documented:** docs/execution.md:185-186: terminals raise `ValidationError`. docs/execution.md also says expected data failures are kept as rows.
- **Observed:** On constructed station files: station A alone returns its row. `select(stations=[A, C])`, where C's file holds one report of another station, raises `ValidationError: GHCNh returned an unrequested station` and returns nothing for A. The same holds for an unreadable DATE, a missing coordinate, a non-finite temperature, and two reports at one time and position (crc_sdk/_observed_decoders.py:409-421; crc_sdk/_evidence.py:672-674). At 0.11 such reports were dropped and the read went on. Not met in NOAA's files of the 40 stations assessed.
- **Consequence:** One malformed file among hundreds loses the whole selection, and the user is not left with the stations that were good. The assessment's adapter reads one station at a time for this reason.
- **Evidence:** crc_sdk/_observed_decoders.py:409-421; crc_sdk/_evidence.py:672-674; tests/validation/test_data_source_check_ghcnh.py (the refusal cases on constructed files)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-037-GHC: GHCNh files are attributed to 'NOAA NCEI and NOAA CO-OPS', with a generic licence text and no dataset version

- **Documented:** docs/data-licences.md:9-11: licence and attribution are recorded 'when known' and retain 'the source's actual terms'.
- **Observed:** Every GHCNh resource carries the attribution 'NOAA National Centers for Environmental Information and NOAA CO-OPS; original source records retained.' and the licence 'NOAA open-use terms; originator terms may apply' (crc_sdk/_observed_sources.py:118-122; checks provenance[*], 1,000 files). CO-OPS is NOAA's tides and water-level service and does not publish GHCNh; the constant is shared by the NOAA providers. No GHCNh version or DOI is recorded; 0.11 recorded `ghcnh-v1` and `CC0-1.0`.
- **Consequence:** The attribution a user would reproduce names an office that is not the publisher, and the output no longer says which version of the dataset it came from.
- **Evidence:** crc_sdk/_observed_sources.py:118-122; docs/data-licences.md:9-11; check records ghcnh/provenance[*] (records of ghcnh, run of 2026-11-24 on crc-sdk 1.0.0)
- **Basis:** reproduced · **Status:** open · found 2026-11-24 at crc-sdk 1.0.0

### CRC-038-FWK: A connection the publisher drops ends the read: no download is tried a second time

- **Documented:** docs/execution.md and docs/sources.md describe caches and pinned replays; neither states what happens when a publisher closes a connection during a read.
- **Observed:** A download is one `urllib.request.urlopen(request, timeout=60)` call (crc_sdk/_source_io.py:280); remote rasters are opened through GDAL with `GDAL_DISABLE_READDIR_ON_OPEN` and an optional header file only, without `GDAL_HTTP_MAX_RETRY` or `GDAL_HTTP_RETRY_DELAY` (crc_sdk/_climate_io.py:407-420). The word `retry` occurs in none of the package's 50 Python files. On a local server that closes the first connection and serves the second, `IBTrACS(...).read()` makes one request and raises `RemoteDisconnected`; the same call repeated returns its rows (tools/repro/crc_no_retry.py). Seen with three publishers on 2026-11-24 and 25: JRC (four reads of the Texas box of 28 remote files ended within 90 seconds on `Connection reset by peer`, `RemoteDisconnected`, or a file GDAL could not recognise after a failed request), NOAA (seven resets among 1,000 GHCNh station-years, each ending a read) and NASA (NEX reads completed only with a retry placed around the standard library call). The raster path was read in the code and seen failing on JRC; it was not exercised on a constructed server.
- **Consequence:** A read that needs many requests fails as a whole on one transient failure, and what was read up to then is lost unless a cache was configured. A state-sized JRC box has not been read at all on 1.0.0. Every caller has to add its own retry around `read()`, which repeats the whole read.
- **Evidence:** crc_sdk/_source_io.py:280; crc_sdk/_climate_io.py:407-420; tools/repro/crc_no_retry.py (run of 2026-11-25 on crc-sdk 1.0.0); docs/reports/u3-crc-1.0.0.md (the Texas reads)
- **Basis:** reproduced · **Status:** open · found 2026-11-25 at crc-sdk 1.0.0
