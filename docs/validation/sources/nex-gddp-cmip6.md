# NASA NEX-GDDP-CMIP6 projections: assessment

Generated from the records of the run of 2026-11-24T23:57:52Z against crc-framework 1.0.0, crc-sdk 1.0.0. **Draft: not yet reviewed.**
Do not edit: change the source file or re-run the assessment and rebuild.

- **What the framework adds:** From NASA's daily files crc-sdk makes one row per grid cell of a box and year: the largest one-day or five-day rainfall, or the hottest or the coldest day, after converting units. It reads the newest file version NASA lists for each year, keeps a cell's value only when every day (every five-day window) of the year is present, and gives a cell without a value a row with the reason. Nothing is fitted. What it acquired is kept in its own cache when one is given.
- **How it is compared:** For one model and member in the Texas box, two years and the four indicators, the reference reader lists NASA's bucket itself, downloads the whole file crc-sdk read, and recomputes every grid cell's annual value, coverage, edges and H3 cell, compared value by value with crc-sdk's rows. Which file version each side read, the file's own identity attributes, the labels and provenance, a year without a file, a model with a 365-day calendar, and the file versions NASA serves are checked separately.
- **Purpose (the framework's documentation):** Annual extremes from bias-adjusted, downscaled daily model output at 0.25 degree, one model and member at a time.
- **Publisher:** NASA NCCS · https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com/NEX-GDDP-CMIP6
- **Entry points:** `NEX`
- **Status:** exploration assessed, verification assessed, validation not assessed
- **Options, indicator:** assessed annual_maximum_daily_maximum_temperature, annual_maximum_daily_precipitation, annual_maximum_five_day_precipitation, annual_minimum_daily_minimum_temperature; not assessed none

## Exploration

### What was read

Model ACCESS-CM2, member r1i1p1f1, the Texas box, the file crc-sdk read. Counted from NASA's files by the reference reader.

| Case | File | File version | Licence in the file | Calendar | Days | Cells in box | Cells with a value | Lowest | Highest | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rx1day historical 2014 | pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | 2.0 | CC-BY 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | 12.74 | 78.99 | mm |
| rx5day historical 2014 | pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | 2.0 | CC-BY 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | 32.48 | 178.75 | mm |
| txx historical 2014 | tasmax_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | 2.0 | CC-BY-SA 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | 27.32 | 46.68 | degC |
| tnn historical 2014 | tasmin_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | 2.0 | CC-BY-SA 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | -34.46 | 1.78 | degC |
| rx1day ssp585 2050 | pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | 2.0 | CC-BY 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | 11.96 | 101.60 | mm |
| rx5day ssp585 2050 | pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | 2.0 | CC-BY 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | 25.90 | 261.77 | mm |
| txx ssp585 2050 | tasmax_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | 2.0 | CC-BY-SA 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | 30.23 | 51.23 | degC |
| tnn ssp585 2050 | tasmin_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | 2.0 | CC-BY-SA 4.0 | proleptic_gregorian | 365 | 2,332 | 2,158 | -32.21 | 8.82 | degC |

### File versions NASA serves

Versions in NASA's listing for each variable and year. crc-sdk 1.0 reads the highest and offers no way to ask for another.

| Variable | Scenario | Year | Versions listed | Read by crc-sdk 1.0 |
| --- | --- | --- | --- | --- |
| tasmax | historical | 2014 | 1.0, 2.0 | 2.0 |
| tasmin | historical | 2014 | 1.0, 2.0 | 2.0 |
| pr | historical | 2014 | 1.0, 1.1, 2.0 | 2.0 |
| tasmax | ssp585 | 2050 | 1.0, 2.0 | 2.0 |
| tasmin | ssp585 | 2050 | 1.0, 2.0 | 2.0 |
| pr | ssp585 | 2050 | 1.0, 1.1, 2.0 | 2.0 |

### Do the file versions give different annual values?

Annual values from each other version already downloaded against the version crc-sdk 1.0 reads, in the box (reference reader only; crc-sdk is not involved). crc-sdk 0.11 read version 1.0 by default.

| Recipe | Scenario | Year | Version | Against | Cells | Cells that differ | Largest difference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rx1day | historical | 2014 | 1.0 | 2.0 | 2,158 | 15 | 0.081 |
| rx1day | historical | 2014 | 1.1 | 2.0 | 2,158 | 0 | 0 |
| txx | historical | 2014 | 1.0 | 2.0 | 2,158 | 0 | 0 |
| rx1day | ssp585 | 2050 | 1.0 | 2.0 | 2,158 | 42 | 0.843 |
| rx1day | ssp585 | 2050 | 1.1 | 2.0 | 2,158 | 0 | 0 |
| txx | ssp585 | 2050 | 1.0 | 2.0 | 2,158 | 0 | 0 |

Assessed on one model and member (ACCESS-CM2, r1i1p1f1), the Texas box, 2014 of the historical run and 2050 of ssp585: the sample of the run on crc-sdk 0.11.2 (2,332 grid cells, 2,158 on land), whose records are kept under records/0.11.2/. crc-sdk 1.0 reads NASA's version 2.0 files for this sample where 0.11 read version 1.0 by default, so the values differ between the two runs by what NASA changed between the versions (the exploration tables show by how much). crc-sdk 1.0 takes no file version, no grid label and, by default, requires every day of the year; `Coverage.minimum_fraction` and `observations()` were not assessed. Scenario, model and member are free text in 1.0 and are not read by the detector. Each result is one model and one member, not an ensemble. Ocean cells carry no value. The licence written in the files (`cmip6_license`) differs by file while NASA states the archive is CC0.

## What the framework does (transformation statement)

| Step | What crc-sdk does | Code | Outcome |
| --- | --- | --- | --- |
| files | Lists NASA's bucket (S3 ListObjectsV2, page by page) under `<model>/<scenario>/<member>/<variable>/`, then reads one NetCDF file per year by HTTP range requests of 1 MiB with `If-Match` on the ETag, checking size and validator before and after. NASA's whole file is neither downloaded nor checksummed; crc-sdk caches and checksums the window it cuts from it. | crc_sdk/_climate_sampling.py:107-108, 1588-1625, 1785-1807, 1836-1845; crc_sdk/_climate_io.py:551-571, 602-674, 677-822 | **confirmed**. NASA's files are stored in chunks of one day by the whole globe, so a box of any size reads every chunk of the file (about 240 requests for a 247 MB file). |
| versions | For each year, reads the file with the highest version in NASA's listing, the version being taken from the file name (no suffix is 1.0, `_v<version>` otherwise). | crc_sdk/_climate_sampling.py:119, 1627-1641, 1797-1803 | **confirmed** |
| versions-offered | Takes no file version: an older revision NASA still serves cannot be requested. | crc_sdk/_climate_sampling.py:269-290, 1627-1641 | **differs** |
| identity | Takes the model, scenario and member from the request and the listing address, and labels the result with them; the file's own identity attributes are not compared with the request. | crc_sdk/_climate_sampling.py:1788-1794, 1818-1828 | **confirmed**. That no comparison is made is shown in the offline tests, on a file that names another member. |
| calendar | Reads the calendar from the header of the earliest year's file and reads the series in that calendar when it is one CF names (Gregorian, `noleap`/`365_day`, `all_leap`/`366_day`, `360_day`, `julian`; crc-sdk 1.1.0, where 1.0 refused all but the Gregorian ones); each year's file must declare the same calendar. | crc_sdk/_climate_sampling.py:1837-1850; crc_sdk/_climate_grid.py:83-99 | **confirmed**. Asked for one model with a 365-day calendar (BCC-CSM2-MR, its header only); models with a 360-day calendar were not asked for. |
| time | Decodes `days since <date>` to whole days (the stamp is floored), requires them to be unique and increasing, and keeps a day of the year only when exactly one time step falls in it. | crc_sdk/_climate_sampling.py:1863-1870; crc_sdk/_providers/cmip6.py:74-94; crc_sdk/_climate_grid.py:404-424 | **confirmed**. The files read have 365 days and no gap. A day absent from the time axis and a leap year were exercised only in the offline tests. |
| licence | Copies a global `license` attribute, else `licence`, else `cmip6_license` (the model licence NASA writes in its files; read since crc-sdk 1.0.1), onto the file's resource as its licence. NASA's statement that the archive is CC0 is not recorded. | crc_sdk/_climate_sampling.py:1879-1883 | **confirmed** |
| units-rain | Requires precipitation to declare exactly `kg m-2 s-1` and multiplies it by 86,400 to give millimetres per day. | crc_sdk/_climate_sampling.py:1851-1855, 1910; crc_sdk/_providers/cmip6.py:137-142; crc_sdk/_climate_io.py:836-855 | **confirmed** |
| units-temperature | Requires temperature to declare exactly `K` (bytes are decoded to text first) and subtracts 273.15 to give degrees Celsius. | crc_sdk/_climate_sampling.py:1851-1855, 1910; crc_sdk/_providers/cmip6.py:137-142; crc_sdk/_climate_io.py:836-855 | **confirmed** |
| area | Selects every grid cell whose rectangle (edges halfway between neighbouring centres) intersects or touches the box; longitudes are brought to -180..180. Rows follow the file's latitude order and, within a row, its column order. | crc_sdk/_climate_sampling.py:1872-1878; crc_sdk/_climate_grid.py:115-226; crc_sdk/_climate_io.py:717-728 | **confirmed**. A box across the 180 degree meridian was not run. |
| missing | Treats values equal to the file's `_FillValue` or `missing_value`, and non-finite values, as missing (after `scale_factor` and `add_offset`, when present). | crc_sdk/_climate_grid.py:229-253, 417, 424 | **confirmed** |
| completeness | By default (`Coverage.complete()`) gives a cell a value only when every day of the year is present; for rx5day, every five-day window that lies within the year (365 days give 361 windows). | crc_sdk/_climate_sampling.py:143-146, 278-286, 1925; crc_sdk/_climate_grid.py:425-442; docs/sources.md:87-96 | **confirmed**. In NASA's files a cell has every day or none (ocean), so a partly complete cell was exercised only in the offline tests. |
| statistic-rain | `rx1day` is the largest daily value of the year. `rx5day` is the largest sum of five consecutive days within the year; windows do not reach into the neighbouring years. A negative precipitation value makes the whole read fail. | crc_sdk/_climate_grid.py:401-403, 418-419, 427-440 | **confirmed** |
| statistic-temperature | `txx` is the highest daily maximum of the year and `tnn` the lowest daily minimum. | crc_sdk/_climate_grid.py:420-423, 437-440 | **confirmed** |
| output | Returns one row per selected grid cell and year, with or without a value: the cell's rectangle as geometry, its H3 cell (resolution 9) at the centre, `support_id` `nex:0p25:<row>:<column>` (its place in NASA's file), the time as the year, the value, the coverage (valid and expected days or windows, the minimum fraction) and, for a cell without a value, the failure `incomplete_year`. No distribution is fitted. | crc_sdk/_climate_sampling.py:837-892, 1913-1928; crc_sdk/_climate_grid.py:443-471 | **confirmed** |
| year-without-file | A year NASA has no file for is not refused: crc-sdk reads the nearest year's file to place the cells and returns every cell without a value (failure `incomplete_year`, 0 days present). Since crc-sdk 1.0.1 the report carries a `source_year_unavailable` warning naming the year and the published years. | crc_sdk/_climate_sampling.py:778-800 | **confirmed**. Asked for one year after the end of the historical run (2015); a year before the first file was not asked for. |
| labels | Labels every row with the variable `nex:<indicator>`, the scenario and a period; the metadata names the unit (degC or mm), the calendar, the model, the member and the release `<model>/<scenario>/<member>/<variable>`. | crc_sdk/_climate_sampling.py:397-420, 930-1008, 1818-1828 | **confirmed** |
| provenance | Records the unit conversion and the annual reduction (with its coverage rule) as provenance, and as resources: the listing page, the release (a checksum of every year's file name and ETag), the header read and the window cut from each file, each with its address and retrieval time and the attribution 'NASA Earth Exchange NEX-GDDP-CMIP6' on the release and the window. | crc_sdk/_climate_sampling.py:1011-1117, 1644-1652, 1806-1814, 1937-1940; crc_sdk/_climate_io.py:788-799 | **confirmed**. The release checksum and the checksum of each window are crc-sdk's own encodings and were not recomputed. |

## Checks

### file

The file crc-sdk read (from its provenance) against the highest version NASA lists for the year (the reference's own listing of the bucket); and the ETag NASA lists for that file against the ETag of the reference's download. Steps: files, versions. Tolerance: etag: identical text; file: identical address.

| Check | Outcome | Result |
| --- | --- | --- |
| file[rx1day historical 2014] | confirmed | crc-sdk read version 2.0 (pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc); highest listed 2.0 of 1.0, 1.1, 2.0 |
| file[rx5day historical 2014] | confirmed | crc-sdk read version 2.0 (pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc); highest listed 2.0 of 1.0, 1.1, 2.0 |
| file[txx historical 2014] | confirmed | crc-sdk read version 2.0 (tasmax_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc); highest listed 2.0 of 1.0, 2.0 |
| file[tnn historical 2014] | confirmed | crc-sdk read version 2.0 (tasmin_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc); highest listed 2.0 of 1.0, 2.0 |
| file[rx1day ssp585 2050] | confirmed | crc-sdk read version 2.0 (pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc); highest listed 2.0 of 1.0, 1.1, 2.0 |
| file[rx5day ssp585 2050] | confirmed | crc-sdk read version 2.0 (pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc); highest listed 2.0 of 1.0, 1.1, 2.0 |
| file[txx ssp585 2050] | confirmed | crc-sdk read version 2.0 (tasmax_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc); highest listed 2.0 of 1.0, 2.0 |
| file[tnn ssp585 2050] | confirmed | crc-sdk read version 2.0 (tasmin_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc); highest listed 2.0 of 1.0, 2.0 |

### annual

Every grid cell of the box: the annual value, its coverage (days or five-day windows present, of those expected), the cell's edges, its H3 cell and its place in the file, recomputed in Python from the whole NASA file crc-sdk read, against crc-sdk's rows, in order. A cell with no value must carry the failure incomplete_year. Steps: time, area, missing, completeness, output, units-rain, statistic-rain. Tolerance: labels: identical text; numbers: within 1e-09; order: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| annual[rx1day historical 2014] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[rx5day historical 2014] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[txx historical 2014] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[tnn historical 2014] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[rx1day ssp585 2050] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[rx5day ssp585 2050] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[txx ssp585 2050] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |
| annual[tnn ssp585 2050] | confirmed | 2,158 cells with a value of 2,332 in the box; 2,332 rows against 2,332; 0 values differ; largest difference 0.0e+00 |

### labels

The labels crc-sdk puts on its result against the request and the file's own attributes: variable, unit, scenario, model, member, release, calendar, the unit conversion and the annual reduction recorded in the provenance (with its coverage rule), the licence on the file's resource against the file's global `license` attribute, the attribution, and a retrieval time. Steps: labels, provenance, licence. Tolerance: labels: identical text; numbers: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| labels[rx1day historical 2014] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY 4.0 |
| labels[rx5day historical 2014] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY 4.0 |
| labels[txx historical 2014] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY-SA 4.0 |
| labels[tnn historical 2014] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY-SA 4.0 |
| labels[rx1day ssp585 2050] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY 4.0 |
| labels[rx5day ssp585 2050] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY 4.0 |
| labels[txx ssp585 2050] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY-SA 4.0 |
| labels[tnn ssp585 2050] | confirmed | 0 labels wrong; licence on the resource: None; `license` in the file: None; cmip6_license in the file: CC-BY-SA 4.0 |

### identity

The identity the file states in its own attributes (cmip6_source_id, variant_label, scenario, version) against the model, member and scenario crc-sdk labels its result with and the version in the name of the file it read. Steps: identity. Tolerance: identity: identical text.

| Check | Outcome | Result |
| --- | --- | --- |
| identity[rx1day historical 2014] | confirmed | 0 of 4 identity attributes differ |
| identity[rx5day historical 2014] | confirmed | 0 of 4 identity attributes differ |
| identity[txx historical 2014] | confirmed | 0 of 4 identity attributes differ |
| identity[tnn historical 2014] | confirmed | 0 of 4 identity attributes differ |
| identity[rx1day ssp585 2050] | confirmed | 0 of 4 identity attributes differ |
| identity[rx5day ssp585 2050] | confirmed | 0 of 4 identity attributes differ |
| identity[txx ssp585 2050] | confirmed | 0 of 4 identity attributes differ |
| identity[tnn ssp585 2050] | confirmed | 0 of 4 identity attributes differ |

### year-without-file

Ask crc-sdk for rx1day historical 2015, a year NASA has no file for: crc-sdk must return one row per grid cell of the box (the cells of the nearest year's file) with no value, 0 days present and the failure incomplete_year. Steps: year-without-file. Tolerance: numbers: within 1e-09; order: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| year-without-file[rx1day historical 2015] | confirmed | 2,332 rows against 2,332; 25,652 values compared, 0 differ; crc-sdk read pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc |

### calendar

Ask crc-sdk for BCC-CSM2-MR rx1day historical 2014. The reference reads the calendar of that model's first file (its header only, by range requests). crc-sdk must refuse exactly when the calendar is not Gregorian (standard, gregorian, proleptic_gregorian). Steps: calendar. Tolerance: behaviour: refused if and only if not Gregorian.

| Check | Outcome | Result |
| --- | --- | --- |
| calendar[BCC-CSM2-MR rx1day historical 2014] | confirmed | calendar 365_day; crc-sdk refuses: ValidationError: NEX source does not use its published Gregorian calendar |

### versions-served

For each variable and year assessed, the file versions NASA lists (the reference's own listing) against the versions a crc-sdk user can request: crc-sdk 1.0 takes no version and reads only the highest one. Steps: versions-offered. Tolerance: versions: every version served can be requested.

| Check | Outcome | Result |
| --- | --- | --- |
| versions-served | differs | served by NASA but not requestable through crc-sdk: tasmax historical 2014: 1.0; tasmin historical 2014: 1.0; pr historical 2014: 1.0, 1.1; tasmax ssp585 2050: 1.0; tasmin ssp585 2050: 1.0; pr ssp585 2050: 1.0, 1.1 |

## Inputs

| Role | File | SHA-256 | Retrieved |
| --- | --- | --- | --- |
| reference download | pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | f25615bd38744b10c669004367c14a7e0d9eb25abbf02481878d3f302018a8e9 | 2026-11-24T23:38:52Z |
| crc-sdk answer (range requests) | pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc |  |  |
| publisher listing |  |  |  |
| reference download | tasmax_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | 52d22c87cb4e5f8f801b5a646e9c8f355c2aeb460ac2afd8dc285d6a036baaf4 | 2026-11-24T23:38:52Z |
| crc-sdk answer (range requests) | tasmax_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc |  |  |
| publisher listing |  |  |  |
| reference download | tasmin_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc | e82705ee34cb7870c3a24ef7bf179bfbd5c1d944aacdb3a682048e78c8ee23ad | 2026-11-24T23:38:52Z |
| crc-sdk answer (range requests) | tasmin_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc |  |  |
| publisher listing |  |  |  |
| reference download | pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | d9d43693f8bd53238792bc05f9c2ee4b529d675a457cf311fbe269d9697adb11 | 2026-11-24T23:38:52Z |
| crc-sdk answer (range requests) | pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc |  |  |
| publisher listing |  |  |  |
| reference download | tasmax_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | a2e3361bbe6ff70ce20ff01563e1e0a921243bdca23d77fdc39eba424c06f1d6 | 2026-11-24T23:39:37Z |
| crc-sdk answer (range requests) | tasmax_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc |  |  |
| publisher listing |  |  |  |
| reference download | tasmin_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc | 94f997bf63ecca03aa758ea7c7893fa662f3eb822c0696d858c2622037c73719 | 2026-11-24T23:39:56Z |
| crc-sdk answer (range requests) | tasmin_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2050_v2.0.nc |  |  |
| publisher listing |  |  |  |
| crc-sdk answer | pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014_v2.0.nc |  |  |
| reference header | pr_day_BCC-CSM2-MR_historical_r1i1p1f1_gn_1950_v2.0.nc |  |  |
| publisher listing | nex-gddp-cmip6.s3.us-west-2.amazonaws.com |  |  |

## Findings

| Id | Kind | Finding | Basis | Status |
| --- | --- | --- | --- | --- |
| CRC-001-NEX | defect | Temperature recipes (txx, tnn) fail on real NEX files | reproduced | fixed in 0.11.2 |
| CRC-012-NEX | observation | NASA serves files of version 2.0, which cannot be requested | reproduced | superseded by CRC-031-NEX from 1.0.0 |
| CRC-031-NEX | observation | The file version cannot be chosen: the highest on NASA's listing is read, older revisions NASA still serves cannot be requested, and the version read appears only inside a file name | reproduced | open |
| CRC-032-NEX | doc-code difference | Models whose calendar is not Gregorian are refused, although inspection lists them | reproduced | fixed in 1.1.0 |
| CRC-033-NEX | doc-code difference | No licence is recorded for NEX files; the model licence written in the file is not read, and a share-alike licence raises no warning | reproduced | fixed in 1.0.1 |
| CRC-034-NEX | observation | A year NASA has no file for is not refused: the nearest year's file is read and every cell comes back with no value | reproduced | fixed in 1.0.1 |

Details are in [the inventory](../inventory.md#findings).

## What this does not cover

- A `confirmed` outcome holds for these files, these options and crc-framework 1.0.0, crc-sdk 1.0.0.
- Verification says nothing about whether the publisher's values are right.
- Validation (fitness for a stated use) is not assessed.
