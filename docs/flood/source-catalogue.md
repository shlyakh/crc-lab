# Source catalogue: the data sources of the flood lab and their alternatives

Change CH-18 (`docs/flood/changes.md`). Written 2026-11-26 at Yuri's request. Terms follow
`docs/flood/terminology.md`.

## 1. Purpose, how to read it, the tags

**Purpose.** Each data source in use is written down with the alternatives it was or could be compared with,
so that a choice can be revisited. For each choice the page says why it was made and what would make us
switch. The first worked case is rainfall: AORC against Stage IV, and 1979 against 2002 (section 4).

**How to read it.**

- Section 2 is the summary: one row per source.
- Section 3 has one part per group of sources. Each has the chosen source, its alternatives, the reason and
  the trigger for a switch.
- Section 4 works through AORC against Stage IV (and MRMS, and Atlas 14), and 1979 against 2002.
- Section 5 lists what was not read and the questions for Yuri.
- "Cost of switching" is **low** (hours, no result changes beyond noise), **medium** (a day or more, one stage
  re-run) or **high** (several stages re-run, or a new fact check and second reader, FS4 and FS6).

**Tags.**

- **[S]** read at a cited source. The URL is given. Date read is 2026-11-26 unless another date is given.
- **[V]** verified in this repo's data or facts files. The file is named (facts files are in
  `src/flood_lab/facts/`, reports in `docs/flood/reports/`).
- **[P]** a placeholder or a judgement of this catalogue.
- "not read" means the page refused access, did not state the field, or was only seen as a search snippet.
  Nothing is filled in from memory.

**Limit of the web reads.** The alternatives' facts were read by fetching pages through a tool that
summarises them. Only the AORC methods quotes come from the extracted PDF text. Before a figure from an
alternative is used in a published number, re-read it on the page (FS6). The facts of the chosen sources were
read for the lab's own data cards on 2026-11-25 (field `checked_on` in each file).

## 2. Summary table

| Source (group) | Feeds | Chosen product | Main alternatives | Why chosen | Cost of switching |
| --- | --- | --- | --- | --- | --- |
| Catalogue rainfall | FH5, FT5 | NOAA AORC v1.1, 2002-2025 | Stage IV; MRMS; ERA5; IMERG; NLDAS-2; PRISM | RainyDay input is documented for AORC; open Zarr bucket; 30 arc-second grid | High: RainyDay input, domain choice, 150 runs and the Atlas 14 comparison all re-run |
| Replay rainfall | FH4, FV1, FV2 | NOAA MRMS multi-sensor hourly, Pass 2 | Stage IV; AORC | 0.01 degree hourly, open bucket, covers both storms (after 2020-10-14) | Low: two storms, one reader and its second reader |
| Frequency reference | FH6, FH5 check | NOAA Atlas 14 Vol. 10 (point) | NOAA Atlas 15 (not yet published) | The current NOAA standard for the Northeast | Low now; medium when Atlas 15 is published (six storms and one table re-run) |
| Terrain | FD2, FH2 | USGS 3DEP 1 m, project NY_CMPG_2013 | NYC 2017 topobathy lidar (1 ft); Copernicus GLO-30; 3DEP 10 m | Flown before both storms; metres; open | High: the whole F3 calibration and every depth depend on it |
| Buildings | FD5 | NYC Building Footprints `5zhs-2jue` with Building Elevation and Subgrade `bsin-59hv` | Microsoft ML footprints; USA Structures; OSM buildings | City-maintained; grade and subgrade measured; joined by building number | Medium: F1 and F6 inputs re-run |
| Building values | FD5, FR3 | USACE National Structure Inventory 2026 | FEMA Hazus default inventory; USA Structures | Public API, structure-level values and occupancy | Medium |
| Substations | FD3 | OpenStreetMap `power=substation` | HIFLD (now restricted); Con Edison hosting-capacity API | Only open source with outlines | Medium: the four-substation case is hand-checked |
| Pluvial flood hazard reference | FS1, FH3 | NYC Stormwater Flood Maps | FEMA NFHL; First Street | Rain-only, citywide, with intensities | High: the loss rate is calibrated on it |
| Surveyed marks | FV1 | USGS Ida high-water marks | none found for rain flooding | Only surveyed depths for Ida | High (no substitute) |
| Street sensors | FV2, FT5 | FloodNet | none found | Only measured peak depths in streets | High (no substitute) |
| Reports of flooding | FV5, FT5 | Groundsource; NOAA Storm Events; NYC 311; NFIP claims | NWS Local Storm Reports (IEM); Copernicus EMS; Sentinel-1; Dartmouth archive | Each tells who saw or paid; none measures depth | Low each (labels, not drivers) |
| Published Ida depth map | FV3 | Kasaei et al. 2025 (Jamaica Bay) | none | Only published model of Ida | Low (comparison only; may not overlap the area) |
| Damage curves, substations | FR2 | Nirandjan et al. 2024 v1.1.0 (Table D2), plus other published curves | Williams et al. 2025; Bor et al. 2026; Karagiannakis et al. 2025; JRC Huizinga 2017 | Open licence (CC BY 4.0), values read from the file | Low to medium: an envelope, curves are interchangeable in `curves.yaml` |
| Damage curves, buildings | FR3 | FEMA Hazus flood functions (FAST tables, Hazus 4.0) | JRC Huizinga 2017; USACE depth-damage | US occupancy classes match the inventory | Medium |
| Outage cost | FM5 | LBNL ICE Calculator 2.2 (online tool and API) | none found | Free public tool, utility-survey based | Medium |
| Substation value | FD4 | Labelled placeholder range from public cost documents | none better | No replacement value of an urban substation is public | n/a (placeholder) |
| Discount rate | FM4 | 7% (FEMA BCA); 3.1% as sensitivity only | OMB A-94 Appendix C rates | FEMA requires 7% | Low |

Also in use and not compared here: NYC 2020 Neighborhood Tabulation Areas (`nyc-nta-2020`, labels only) and
USGS NAIP imagery (`usgs-naip-imagery`, looking only). Software (SFINCS, RainyDay, CRC) is outside this
catalogue except where a source is chosen because of it.

## 3. Sources and alternatives, by group

### 3.1 Rainfall

#### Chosen: NOAA AORC v1.1 (catalogue)

Facts file: `rainfall-aorc.toml` (checked 2026-11-25) **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | CONUS from 1979, Alaska from 1981. Stored grid 20.0 to 55.0 N, -130.0 to -60.0 W (CH-15) **[V]** |
| Resolution | 30 arc seconds (about 800 m), hourly. Hourly values are the accumulation ending at the top of the hour **[V]** |
| Period | 1979-01-01 to 2025-12-31 23:00 UTC; no 2026 store on 2026-11-25; update frequency "to be determined" **[V]** |
| Licence | NOAA Open Data Dissemination terms: open, attribution requested for unaltered data, no implied endorsement, modified data not presented as original **[V]** |
| Access | Public bucket `s3://noaa-nws-aorc-v1-1-1km`, Zarr v2, one store per year, no account **[V]** |
| Known biases | 0.04% of rows wrongly masked (registry notice 2026-04-02; regeneration under way); 10-day lag so input corrections are included; not independent of Stage IV and NLDAS-2; v1.0 problems fixed in v1.1 **[V]**. Input changes over time: see section 4 |
| Size for the lab | 5.54 GB for the 38-44 N window, 2002-2025 **[V]** (`docs/flood/reports/F3-solver.md`) |

#### Chosen: NOAA MRMS (replays)

Facts file: `rainfall-mrms.toml` **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | CONUS folder in the AWS bucket (siblings for Alaska, Hawaii, Caribbean, Guam) **[V]** |
| Resolution | Hourly accumulation files; the 0.01 degree grid is stated in the F3 report **[V]** (`F3-solver.md`), the grid spacing was not read from a producer page (`rainfall-mrms.toml`, coverage_space "not checked") |
| Period | AWS archive from 2020-10-14 (MRMS v12) **[V]**; earlier products "to be used with caution" **[V]** |
| Licence | NODD terms on AWS; Iowa State "no usage restrictions for this website" **[V]** |
| Access | `s3://noaa-mrms-pds`, GRIB2 gzip, anonymous. Iowa State `mtarchive` as a second copy **[V]** |
| Known biases | Pass 2 has a 1-hour latency (gauge-corrected); the end-of-hour meaning of the time stamp is not confirmed from a primary source **[V]** (`F3-solver.md`, `F5-marks-and-sensors.md`). Producer-stated accuracy limits: not read |

#### Chosen: NOAA Atlas 14, Volume 10 version 3 (frequency reference)

Facts file: `noaa-atlas-14.toml` **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | Point estimates, Northeastern States, here at 40.65 N, -73.85 W (design storms use the study centroid) **[V]** |
| Resolution | Durations 5 min to 60 days; 19 rows; return periods 1 to 1000 years **[V]** |
| Period | Published 2015, revised 2019; statistical, assumes a stationary climate **[V]** |
| Licence | Not found in Volume 10 or the PFDS page; the disclaimer was not read **[V]**. Shown as "licence not stated on the pages read" (requirements section 14) |
| Access | Text/CSV service on `hdsc.nws.noaa.gov` (parameters inferred from working responses) **[V]** |
| Known biases | Point values, not areal (no areal reduction factor applied by the lab); 90% bounds are wide and asymmetric **[V]** |

#### Alternatives

| Product | Coverage and resolution | Period and lag | Licence | Access | Known biases or limits | Source |
| --- | --- | --- | --- | --- | --- | --- |
| **NCEP Stage IV** | CONUS mosaic of the River Forecast Center analyses, 4 km HRAP grid (1121 x 881) **[S]**; the archive record gives 1160 x 880 polar stereographic, 4.76 km at 60 N **[V]** (`rainfall-stage-iv.toml`) | Stage IV from 2002-01-01 (Stage II from 1996-05-01); runs about 35 min after each hour, RFC input arrives 20 min to 12 h late **[S]** | Not read on any producer page. The NCAR archive states CC BY 4.0 (the archive's statement, not NCEP's) **[V]** | NCEP real-time files; `water.noaa.gov` daily NetCDF and GeoTIFF from 2016-06-28 **[S]**; NCAR GDEX GRIB archive **[V]**; no open cloud bucket found (not read: an AWS Marketplace listing seen only in a search snippet) | Manual QC at the RFCs; radar bias removed by the Smith and Krajewski method, which does not remove range-dependent bias; ring artefacts from radar gain; streaks before 2003-11-20; poor multi-sensor data in spring-summer 2000; RFC domain edges averaged **[S]**. AORC's methods say it was biased low in winter 2002 to about 2009 in some areas **[S]** | https://www.emc.ncep.noaa.gov/mmb/SREF/pcpanl/QandA/ ; https://water.noaa.gov/about/precipitation-data-access ; https://gdex.ucar.edu/datasets/d507005/ (read by the lab 2026-11-25 **[V]**) |
| **NOAA MRMS** as the catalogue record | See above: 0.01 degree hourly, but AWS archive only from 2020-10-14 **[V]**; Iowa State says its archive holds products "from October 2014", and announced in 2026 a cut to a rolling 30-day cache for hourly files **[S]** | Four to six years of record: too short for transposition | NODD | As above | v12 change on 2020-10-14 **[V]** | https://mesonet.agron.iastate.edu/archive/mrms.php ; https://registry.opendata.aws/noaa-mrms-pds/ |
| **ERA5** (single levels) | Global, 0.25 degree atmosphere (HRES 31 km) **[S]** | 1940 to present, hourly; about 5 days latency; preliminary ERA5T can differ from the final release **[S]** | CC-BY **[S]** | Copernicus Climate Data Store (account needed; not read) | A general precipitation-bias statement: not read. ECMWF lists "rain bombs": sudden extreme rain in small areas, mostly over Africa and high orography **[S]** | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels ; https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation |
| **ERA5-Land** | 0.1 degree, native 9 km **[S]** | 1950 to present, hourly, "daily" update (lag not read) **[S]** | CC-BY **[S]** | CDS | Precipitation is forced by ERA5 (so it is ERA5's); bias note: not read | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land |
| **GPM IMERG Final** | Global, 0.1 degree (about 10 km), half-hourly **[S]** | 1998-01-01 to 2025-09-30 in the catalogue record; Final lags 2.5, 3.5 or 4 months (the pages disagree) **[S]** | "Openly shared, without restriction" under EOSDIS guidance; cite DOI; Earthdata login to download **[S]** | NASA GES DISC | Biases: not read | https://www.earthdata.nasa.gov/data/catalog/ges-disc-gpm-3imerghh-07 ; https://gpm.nasa.gov/data/imerg |
| **NLDAS-2 forcing A** | North America, 0.125 degree, hourly **[S]** | 1979 to present (latency not read) **[S]** | "Openly shared, without restriction" (no named licence) **[S]** | NASA GES DISC, cloud-enabled | Rain is a gauge-only daily analysis (CPC) disaggregated to hours with radar, CMORPH or NARR and a PRISM orographic adjustment **[S]**. Producer-stated biases: not read | https://earthdata.nasa.gov/data/catalog/ges-disc-nldas-fora0125-h-2.0 |
| **PRISM** (daily) | CONUS, 4 km (800 m also offered) **[S]** | Daily from 1981 **[S]**; update lag and inputs not read | "May be freely reproduced and distributed"; cite group, URL and access date **[S]** | Web service, FTP | Daily, not hourly. The terms page says it is not recommended for very long-term trends **[S]** | https://prism.oregonstate.edu/terms/ |
| **NOAA Atlas 15** | Planned national, spatially continuous, with non-stationary adjustment to 2100 **[S]** | Montana pilot released 2024-09-26; CONUS preliminary estimates "no earlier than September 2026" and published "no earlier than September 2027" on one part of the page, with earlier dates on another **[S]**. Whether CONUS preliminary estimates exist today: not confirmed, probably not published | Not read | Not available | Will supersede Atlas 14 as the national standard once published; Atlas 14 stays standard until then **[S]**. Northeast coverage: not stated on the page | https://water.noaa.gov/about/atlas15 |

Also seen and not catalogued: a Livneh daily data set and CFSR, GDAS, CMORPH, CaPA, which are inputs to AORC
itself (section 4).

#### Why AORC was chosen, and what would trigger a switch

The reasons on record are in CH-17 (reconstructed after the fact) **[V]**: RainyDay's documented input is AORC
daily NetCDF; AORC is an open Zarr bucket that can be read by window; Stage IV had no open bucket and its
producer pages could not be read; AORC's grid is finer. See section 4 for the weighing and for what this
catalogue adds.

**Switch trigger [P].** (a) A reason to doubt AORC's rain over the box (for example its low shortfall at 2 to 10
years, CH-19, were traced to the record); (b) NOAA regenerates the Zarr files and the numbers change; (c)
RainyDay documents Stage IV input; (d) a published bias study of AORC hourly extremes in the Northeast.

**MRMS** replaces nothing in the catalogue: its open archive is too short. It stays the replay source because
it is the best-resolved radar-gauge product for 2021-09-01 and 2023-09-29. Switch trigger [P]: a cross-check
of the replays with Stage IV (also hourly) showing a different peak.

**Atlas 14** stays until Atlas 15 preliminary estimates are published and peer-reviewed. Trigger: that
publication, or a request for non-stationary design storms.

### 3.2 Terrain and buildings

#### Chosen: USGS 3DEP 1 m DEM, project NY_CMPG_2013

Facts files: `usgs-3dep-1m.toml`, `lidar-terrain.toml` **[V]**; F1 report line 28 **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | Tile x58y451 covers the whole F1 margin box; project flown 2013-08-06 to 2014-04-21, published 2020-03-30 **[V]** |
| Resolution | 1 m, float32 bare earth, metres, NAVD88, 10 km tiles **[V]** |
| Licence | Public domain; acknowledgement requested **[V]**. USGS's own page says "free of charge and without use restrictions" **[S]** (https://www.usgs.gov/3d-elevation-program/about-3dep-products-services) |
| Access | TNM Access API and the `prd-tnm` S3 bucket **[V]** |
| Known biases | 2013-14 terrain: buildings, grading, drainage and shoreline changes since then are absent; hydro-flattened water at -1.62 m **[V]**. Newer tile B23 (2023-04-13 to 2025-04-09, published 2026-09-17) also covers the box, after Ida **[V]** |

#### Alternatives

| Product | Coverage and resolution | Vintage | Licence | Access | Limits | Source |
| --- | --- | --- | --- | --- | --- | --- |
| **NYC 2017 topobathymetric lidar DEM** (`7sc8-jtbz`) | Five boroughs plus 100 m; 1 ft cells, US survey feet, EPSG:2263, NAVD88 (Geoid 12B) **[V]**, **[S]** | Topographic 2017-05-03 to 05-17, bathymetric July 2017 **[V]**; vertical accuracy 0.074 m at 95% (non-vegetated) **[S]** | No licence on the record; NYC terms page returned 404 on 2026-11-25 **[V]**. NOAA metadata: access constraints "none" **[S]** | Open Data zips; FTP; NOAA Digital Coast and AWS **[V]**, **[S]** | 50% leaf-off; hydro-enforced variants differ from hydro-flattened ones; 2017 is four years before Ida **[V]**, **[S]** | https://data.cityofnewyork.us/api/views/7sc8-jtbz.json ; https://www.fisheries.noaa.gov/inport/item/64732 |
| **Copernicus DEM GLO-30** | Global, 30 m **[S]** | TanDEM-X 2011-2015, released 2019 **[S]** | "Free licence"; cite DOI 10.5270/ESA-c5d3d65; source notice on redistribution **[S]** | Copernicus Browser, API, S3; registration **[S]** | Surface model, buildings and trees included; absolute vertical error under 4 m (90%) **[S]**. Too coarse for a 5 m grid with streets | https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM |
| **USGS 3DEP 1/3 arc-second (about 10 m)** | Conterminous US, about 10 m **[S]** | Vintage, update and format: not stated on the page | "Free of charge and without use restrictions" **[S]** | The National Map | Too coarse for streets and curbs **[P]** | https://www.usgs.gov/3d-elevation-program/about-3dep-products-services |
| Newer NYC lidar | One search found only the 2010 and 2017 captures. Not proven absent. A 2024 NYS Long Island 1 m DEM (CC0) has a western edge at -73.78 and probably does not cover Brooklyn (inference, not confirmed) **[S]** | | | | Not read: https://gis.ny.gov/lidar | https://www.fisheries.noaa.gov/inport/item/80346 |

**Reason for the choice.** The terrain must predate the storms it replays and be in metres at 1 m; the 2013-14
project is the one tile that covers the whole box before Ida and gave 0 nodata pixels **[V]**. F1 also found
units and datum consistent with the city's own grade values at 17,728 footprints **[V]** (`F1-terrain-and-assets.md`).
The 2017 city DEM is newer, but its 1 ft cells in feet and its unread licence made it the second choice.

**Switch trigger [P].** The 2017 DEM if its licence is read and it is shown to resolve drainage features the 2013
tile misses (for example by the marks' errors at the Wallabout sites). A newer 3DEP tile only if the replayed
storm is later than its flight, which no Tier 1 storm is.

#### Chosen: NYC Building Footprints (`5zhs-2jue`) with Building Elevation and Subgrade (`bsin-59hv`)

Facts files: `nyc-building-footprints.toml`, `nyc-building-elevation-subgrade.toml` **[V]**.

| Field | Footprints | Elevation and subgrade |
| --- | --- | --- |
| Coverage | Five boroughs, 1,082,928 footprints **[V]** | 861,876 building centroids; no small sheds **[V]** |
| Resolution or scale | Polygons; heights and `ground_elevation` (feet, lowest adjacent ground) **[V]** | Grade (feet, NAVD88), subgrade, first-floor data, per building number **[V]** |
| Period | Living layer, edited daily, weekly update; the city as of download (2026-11-23), not as of a storm **[V]** | One-time capture, imagery 2021 or 2022 (the dictionary gives both), never updated **[V]** |
| Licence | No licence field; NYC Open Data terms **[V]** | The same; no attribution requirement found **[V]** |
| Access | SODA endpoint, no token **[V]** | SODA endpoint, no token **[V]** |
| Known biases | Construction year reliable after 2017 only **[V]** | 135,503 rows have estimated grade and 14,039 have no measurement; cellars reachable only from inside are not recorded **[V]** |

#### Chosen: USACE National Structure Inventory, 2026 Base (building values and occupancy)

Facts file: `usace-national-structure-inventory.toml` **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | 50 states and DC, about 134 million structures **[V]** |
| Attributes | Occupancy type (Hazus-style), foundation type and height, values, building years **[V]** |
| Period | Prices August 2025; buildings and population about 2025; not 2021 **[V]** |
| Licence | None stated on the pages read **[V]**; the HEC technical-references site lists versions 2026, 2022 and 2019 but its pages are navigation shells; no licence seen **[S]** (https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/latest) |
| Access | `nsi.sec.usace.army.mil/nsiapi/structures?bbox=...` **[V]** |
| Known biases | Modelled, not surveyed: foundation height, basement and values are typical; the four foundation heights are not used by the lab; stacked structures are several records on one footprint **[V]** |

#### Alternatives

| Product | Coverage and attributes | Vintage | Licence | Access | Limits | Source |
| --- | --- | --- | --- | --- | --- | --- |
| **Microsoft Global ML Building Footprints** | Global; geometry, height (null where not measured), confidence for the footprint **[S]** | Imagery 2014 to 2021 (vintage FAQ) or 2014 to 2024 (intro); latest update 2026-11-12 **[S]** | CDLA Permissive 2.0 on the page **[S]** (not ODbL; an older version may differ, not checked) | Line-delimited GeoJSON, EPSG:4326, index file; Planetary Computer **[S]** | "Not perfect, particularly in dense urban areas"; the page gives both 1.4B and 999M buildings **[S]** | https://github.com/microsoft/GlobalMLBuildingFootprints |
| **ORNL / FEMA USA Structures** | National inventory of structures over 450 sq ft; occupancy fields were seen only in a search snippet **[S]** | Record modified 2025-04-01 **[S]** | Data.gov record: federal government works; rights field empty; a CC BY 4.0 statement on copies is unresolved **[S]** | The hub page returned no content; no file link on data.gov **[S]** | Coverage, update and limits: not read | https://catalog.data.gov/dataset/usa-structures |
| **OpenStreetMap buildings** | Volunteer-mapped | Rolling | ODbL, credit OpenStreetMap, share-alike for distributed derived databases **[S]** | Overpass, extracts | Completeness: not read | https://www.openstreetmap.org/copyright |
| **FEMA Hazus default inventory** | State inventory databases inside Hazus 7.2 **[S]** | Hazus 7.2 released 2026-06-05 **[S]** | Licence or cost: not stated on the page | Download from the Map Service Center; ArcGIS Pro required **[S]** | Comparison with the NSI: not read | https://www.fema.gov/flood-maps/products-tools/hazus |

**Reason for the choice.** City footprints and BES share a building number, give measured grade and subgrade,
and match 95.9% of buildings proper (F1) **[V]**. The NSI is the only free structure-level source with values;
its values are placeholders in the sense of FD4 where the lab shows dollars **[P]**. Micro-level mismatch
between NSI points and footprints is handled by position (F1: 14,455 points inside a footprint, 3,119 within
15 m, 86 unmatched) **[V]**.

**Switch trigger [P].** A licence statement from NYC or USACE that forbids what the page does; NSI replaced by
USA Structures only if its licence and attributes are read and its values are better documented. Microsoft or
OSM buildings only for areas outside New York City.

### 3.3 Assets: substations

#### Chosen: OpenStreetMap `power=substation`

Facts file: `osm-substations.toml` **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | 187 elements in the Brooklyn and Queens box (none are points); 92 without voltage, 139 without location, 51 without operator; 35 are rail traction substations **[V]** |
| Period | Snapshot 2026-11-25; a substation present today may not have existed on 2021-09-01 **[V]** |
| Licence | ODbL, credit "OpenStreetMap" **[V]** |
| Access | Overpass API (one HTTP 502, then 200) **[V]** |
| Known biases | Indoor and basement substations are likely under-mapped **[V]**. The wiki does not address underground substations and gives no completeness figure **[S]** (https://wiki.openstreetmap.org/wiki/Tag:power%3Dsubstation) |

#### Alternatives

| Product | Facts | Source |
| --- | --- | --- |
| **HIFLD electric substations** | No official notice found. Search results say HIFLD Open was shut down around 2025-08-25 and substation data moved to HIFLD Secure (credentials needed). The data.gov listing was seen as "restricted public" in a search result. Archive copies (for example on source.coop, CC BY 4.0) are not official and could not be confirmed to contain substations. Treat as not freely available officially **[S]** (search only; not read: any HIFLD Secure terms) | https://www.napsgfoundation.org/navigating-the-hifld-transition/ (says only that HIFLD Open was sunsetting) |
| **EIA** | EIA states that it and HIFLD do not publish substation locations **[S]** | https://www.eia.gov/tools/faqs/faq.php?id=567&t=3 |
| **Con Edison hosting-capacity map and REST API** | Aggregated distributed generation at substation level and prior-year peak load; "for informational purposes only"; whether the API returns substation geometry: not read; no licence stated **[S]** | https://www.coned.com/en/business-partners/hosting-capacity/about |

**Reason for the choice.** OSM is the only open source with outlines, and F1 hand-checked the four Con Edison
substations at Vinegar Hill against imagery **[V]** (`F1-terrain-and-assets.md`, CH-6). **Switch trigger [P].**
Con Edison publishes substation geometry or flood-ratings under clear terms; or HIFLD is again freely
downloadable. Cost of switching is medium because the case is four hand-checked sites.

### 3.4 Pluvial flood hazard maps (calibration reference)

#### Chosen: NYC Stormwater Flood Maps (NYC DEP, `9i7c-xyvv`)

Facts file: `nyc-stormwater-flood-maps.toml` **[V]**.

| Field | Fact |
| --- | --- |
| Coverage | Citywide; scenario layers: Limited Flood (1.77 in/hr), Moderate (2.13 in/hr) at current sea level, and two with sea-level rise (3.66 in/hr) **[V]** (`requirements.md` section 14) |
| Resolution | Polygons in depth classes; no depth value, date or scenario column (scenario is the layer) **[V]** |
| Period | Design scenarios, no event time; created 2024-07-03; terrain is the 2017 hydro-enforced DEM **[V]** |
| Licence | None attached; NYC Open Data terms; each layer adds a "not for design or floodplain determination" disclaimer **[V]** |
| Known biases | Drainage system assumed fully working, catch basins clear; parks of 100,000 sq ft or more and some lots masked; areas under 0.25 acre dropped; storm surge not modelled; calibrated mostly on events smaller than a 5-year storm **[V]** |

#### Alternatives

| Product | Facts | Source |
| --- | --- | --- |
| **FEMA National Flood Hazard Layer** | Effective flood hazard data and Letters of Map Change for the NFIP; over 90% of the US population; continuous updates; shapefiles by county or state, viewer, web services, KMZ. Preliminary and pending data are not in the NFHL. Licence: none stated. That it excludes rain-only flooding is not stated on the page (not confirmed) **[S]**. The 2013-2015 NYC preliminary maps are known only from search results (not read) | https://www.fema.gov/flood-maps/national-flood-hazard-layer |
| **First Street flood model** | Coverage, resolution, vintage and licence not read (pages returned 403 or 404). A search snippet says it includes pluvial, fluvial and coastal surge, sold to commercial and other users **[S]**, not read | https://help.firststreet.org/hc/en-us/articles/9785701225623-Licensing-First-Street-Data (403) |

**Reason for the choice.** It is the only map of rain-only flooding for the city with stated rain intensities,
so the constant loss rate (30 mm/h) can be fitted to it (FH3, CSI 0.31 against the Limited map and 0.41
against the Moderate map) **[V]** (`changes.md` CH-16). **Switch trigger [P].** DEP republishes with a new model
version or a different drainage assumption; or First Street licence terms are read and allow comparison.
Cost of switching is high: the calibration freeze and everything after it.

### 3.5 Observations for validation

| Source | Chosen for | Facts file **[V]** | Coverage and period | Licence | Known biases |
| --- | --- | --- | --- | --- | --- |
| USGS Ida high-water marks (`618975c8d34ec04fc9c5a049`) | FV1 | `usgs-ida-high-water-marks.toml` | 159 marks at 83 sites in five boroughs, 108 marks at 55 sites in the Brooklyn-Queens box; survey 2021-09-07 to 2021-11-23; published 2023-03-31 | No licence stated; use constraints "none" | Only where crews found debris or mud lines; basements and subways not represented; positions are map or phone fixes |
| USGS Ida depth rasters | picture only | `usgs-ida-depth-rasters.toml` | 250 m discs around 83 sites; 1 ft cells | "None"; acknowledgement requested | Derived from the marks (mark minus lidar, flat water): not independent |
| FloodNet events and sensors (`aq7i-eu5q`, `kb2e-tjy3`) | FV2, FT5 | `floodnet-flood-events.toml`, `floodnet-sensors.toml` | 3,611 events 2020-11-16 to 2026-11-09; 496 sensors in five boroughs; times in GMT | No licence field; NYC terms; attribution and citation requested | Sensors over sidewalks above the local low point; offline periods not recorded; five sensors recorded Ida in Brooklyn and Queens |
| Groundsource (Zenodo 18647054) | FV5, FT5 | `groundsource.toml` | Global, 2000-01-01 to 2026-02-03; published 2026-02-15 | CC BY 4.0 | A row is a place named in news, not a measured flood; recency bias (about 64% of events in 2020-2025); the publisher's own review found 60% of 400 rows accurate |
| NOAA Storm Events | FV5, FT5 | `noaa-storm-events.toml` | US, 1950 on, yearly CSV | Terms not read | What an NWS office chose to enter; damage often 0.00K; times on standard time all year |
| NYC 311 (`erm2-nwe9`) | FV5, FT5 | `nyc-311.toml` | 2020-01-01 to 2026-11-23, daily | No licence field; NYC terms | A call is not a depth; duplicates not flagged; two names for the same complaint type |
| OpenFEMA NFIP redacted claims v3 | FT5 | `nfip-redacted-claims.toml` | US from 1970-08-31; 2,731,064 records | `license: null`; terms page has no licence wording | Insured losses only; coordinates rounded to 0.1 degree |
| Jamaica Bay Ida depth map (Mendeley `hs2zt6ngwd`) | FV3 | `jamaica-bay-ida-depth-map.toml` | Jamaica Bay watershed only; about 50 m model, peak elevation only | CC BY 4.0 | A model, no buildings, one lumped drain rate; its 0.20 m error is in-sample (0.40 m before calibration); marks not independent of the USGS set |

#### Alternatives

| Product | Facts | Source |
| --- | --- | --- |
| **NWS Local Storm Reports via Iowa Environmental Mesonet** | Point reports; yearly selector 2003 to 2026, no formal start stated; public domain "for any lawful purpose", attribution appreciated; "certainly not complete or official"; update frequency of the archive not stated **[S]** | https://mesonet.agron.iastate.edu/request/gis/lsrs.phtml ; https://mesonet.agron.iastate.edu/disclaimer.php |
| **Copernicus EMS rapid mapping** | The public list of 271 activations (2003 to 2026) has no United States entry, nothing named Ida or New York, no 2021 event. The Risk and Recovery module list was not read, and the licence was not read **[S]** (summary of the raw JSON, not the raw JSON) | https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/?limit=300&offset=0 |
| **Sentinel-1 SAR flood mapping** | NASA ARSET says urban SAR flood mapping "is still an area of research" because of side-looking geometry, 10 m resolution and double-bounce; X-band sensors "should be better". No ESA page was found **[S]** | https://www.earthdata.nasa.gov/s3fs-public/2025-07/ARSET-SARFloods2023-part3-qa.pdf |
| **Dartmouth Flood Observatory archive** | Official pages returned 404; the archive is large events, global, from 1985 per a search snippet only. Not read | https://floodobservatory.colorado.edu/ (home page, no archive description) |
| **NYC after-action lists of flooded places** | No NYC list was found. Not read: the CDBG-DR Ida action plan, the DEP 2024 stormwater analysis report, the state after-action report (all seen as search results only) | e.g. https://www.nyc.gov/assets/dep/downloads/pdf/water/stormwater/2024-stormwater-analysis-report.pdf |

**Reason for the choices.** The marks are the only surveyed depths for Ida; FloodNet is the only measured
street depth. The report sources (Groundsource, Storm Events, 311, claims) say who saw or paid, and are used
as labels with their biases stated (FS6, FV5). None gives depth. **Switch trigger [P].** A new survey of
depths for another storm; Local Storm Reports as one more label (cost low) if the IEM page's update rule is
read. Radar-based SAR is not a replacement in dense urban areas.

### 3.6 Damage curves, costs and the discount rate

#### Chosen: damage curves for substations

Facts files: `substation-curves-nirandjan.toml`, `substation-curves-other.toml` **[V]**.

| Field | Fact |
| --- | --- |
| Nirandjan et al. 2024, Table D2 v1.1.0 | Zenodo 13889558, CC BY 4.0; substation curves F2.1 to F2.3 identical for three voltage classes; stop at 3.05 m depth with damage factor 0.16; 0.0694 at 1.2 m, 0.1569 at 3.0 m (read from the file) **[V]** |
| Williams et al. 2025 | CC BY-NC-ND 4.0; New Zealand expert elicitation; values not read (publisher refuses automated access) **[V]** |
| Bor et al. 2026 | arXiv preprint, CC BY 4.0, high-voltage substations only (above 345 kV) **[V]** |
| Karagiannakis et al. 2025 | CC BY 4.0, read from the arXiv copy **[V]** |

#### Chosen: damage curves for buildings: FEMA Hazus flood functions

Facts file: `hazus-flood-functions.toml` **[V]**. The machine-readable tables used are in FEMA's FAST repository
(GPL-3.0, last push 2022-03-30, Hazus 4.0 data, archived in effect). FEMA's own pages and the Inventory Technical
Manual (Table 10-12, the 4 ft functional depth) were not readable on 2026-11-25 **[V]**.

#### Alternatives

| Product | Facts | Source |
| --- | --- | --- |
| **FEMA Hazus 7.2** | Current version, released 2026-06-05 per the release notes; page last updated 2026-09-14; built on Esri ArcGIS Pro 3.4 to 3.6; Hazus 6.1 downloads ended 2026-03-03; supports earthquake, hurricane and flood. Licence or cost: not stated. Flood-specific limits and the flood model's resolution: not read. The technical manual on the site is the legacy Hazus-MH 2.1 (not read) **[S]**. FEMA did not block this page **[S]**; it did block the Inventory Manual earlier **[V]** | https://www.fema.gov/flood-maps/products-tools/hazus |
| **JRC global flood depth-damage functions (Huizinga et al. 2017)** | JRC105688, EUR 28552 EN, 2017-04-12; per-continent curves, maximum damage per country; residential, commerce, industry, infrastructure (roads), agriculture; infrastructure curves are generic; reuse authorised with acknowledgement; the catalogue record carries a contradictory line and the JRC data page returned "request rejected". Uncertainty chapter numbers not extracted **[S]** | https://publications.jrc.ec.europa.eu/repository/handle/JRC105688 |
| **USACE depth-damage (EGM 04-01, HEC-FDA)** | EGM 04-01 is "generic depth-damage relationships for residential structures with basements" (2003), found in a search snippet and a HEC-FDA certification report. No official page was read | https://www.hec.usace.army.mil/software/hec-fda/documentation/HEC-FDA_CertificationReport.pdf (not read in detail) |

**Reasons.** Nirandjan is the only substation set with an open licence whose values were read from the file;
the others stay as envelope members, shown with their tags (FR2). Hazus is chosen for buildings because its
occupancy classes match the NSI. **Switch trigger [P].** Williams values read by a person with access
(question 7 of the requirements); Hazus functions read from FEMA's own 7.2 files; a US-specific substation
curve published.

#### Outage cost: LBNL ICE Calculator 2.x

Facts file: `ice-calculator.toml` **[V]**: free online tool and API, public domain per its FAQ; spreadsheets
licensed; interruptions up to 24 hours only; survey-based; 2.2.0 released 2026-02-19; estimates changed between
2.0 and 2.2 **[V]**. A re-read of the tool pages on 2026-11-26 returned only the page title (the app needs
JavaScript), and the LBNL project pages returned 403 **[S]**, so no new fact was added. No alternative was
found: no official DOE, NREL or EPRI value-of-lost-load page was read (search leads only: LBNL-55718 on
energy.gov, an EPRI survey review, OSTI copies). Cost of switching: medium (inputs and responses are stored).

#### Substation value (placeholder)

Facts file: `substation-cost-sources.toml` **[V]**: MISO MTEP24 and MTEP26 (2026-06-10) guides; Black & Veatch for
WECC (2012); CAISO owners' 2025 unit-cost guides; Con Edison Idlewild petition (2023). None is a replacement
value of an existing urban substation. No PJM, SPP or NYISO unit-cost document by voltage class was found.
The range stays a labelled placeholder **[P]** (CH-6).

#### Discount rate

Facts file: `fema-bca.toml` **[V]**: FEMA's BCA pages could be read only through Internet Archive copies;
7% confirmed; 3.1% revoked, kept only as a sensitivity "not a FEMA rate" (requirements section 14).

| Product | Facts | Source |
| --- | --- | --- |
| **OMB Circular A-94, Appendix C (revised 2026-03-06)** | Valid for calendar year 2026. Real Treasury rates: 3-year 1.1%, 5-year 1.3%, 7-year 1.4%, 10-year 1.6%, 20-year 2.0%, 30-year 2.0%. Memo M-26-09 says these rates "do not apply to regulatory analysis or benefit-cost analysis of public investment". The main text (Transmittal Memo No. 64) says constant-dollar benefit-cost analyses should use a real rate of 7 percent **[S]** | https://www.whitehouse.gov/wp-content/uploads/2026/03/CircularA-94Appendix-C.pdf ; https://www.whitehouse.gov/wp-content/uploads/2026/03/M-26-09-2026-Discount-Rates-for-OMB-Circular-No.-A-94.pdf ; https://www.whitehouse.gov/wp-content/uploads/2025/12/a094.pdf |
| FEMA page 2026 | The BCA page says the Toolkit follows A-94; it did not state 7% or 3.1% in the text read; last updated 2026-10-29 **[S]**. The FEMA discount-rate policy aid was not read; the Internet Archive could not be fetched in this session | https://fema.gov/node/366486 |

The 7% rate rests on the FEMA statement already in `fema-bca.toml` **[V]** and on A-94's main text **[S]**; a
sentence in search snippets that OMB rescinded and then reinstated the 2023 revisions is not verified.
**Switch trigger [P].** FEMA changes its mandated rate (low cost: one number).

## 4. First worked case: rainfall

### 4.1 AORC v1.1 against NCEP Stage IV, MRMS and Atlas 14

**What the choice does.** The catalogue record feeds RainyDay, which turns 24 years of hourly rain into 1,000
synthetic years of storms (`docs/flood/simulated-events.md`). The record must therefore be (a) hourly, (b)
gridded over a transposition domain of 81,585 cells, (c) accepted by RainyDay, (d) long enough to hold rare
storms, and (e) readable without a manual archive request.

| Test | AORC v1.1 | Stage IV | MRMS | Atlas 14 |
| --- | --- | --- | --- | --- |
| Hourly gridded record | Yes **[V]** | Yes, 4 km **[S]** | Yes, archive too short **[V]** | No (a table) |
| Documented RainyDay input | Yes, `aorcprecip_urls.txt` and file naming **[V]** (`rainyday.toml`) | Not documented in the pages read **[V]** | Not documented **[V]** | n/a |
| Open cloud copy, read by window | Yes, Zarr, 5.54 GB for the window **[V]** | None found (NCAR GRIB archive; NOAA `water.noaa.gov` daily files from 2016-06-28) **[V]**, **[S]** | Yes, from 2020-10-14 **[V]** | Point service |
| Period | 1979-2025 | 2002 on **[S]** | 2020-10-14 on (AWS) **[V]** | Statistical |
| Resolution | 30 arc seconds **[V]** | 4 km **[S]** | 0.01 degree **[V]** | Point |
| Producer-stated biases read | Yes (section 4.2) **[S]** | Partly: producer's Q&A page read; main pages 404 **[S]** | Not read | Stated: stationary, point |
| Independence | Built from Stage IV (2002 on) and NLDAS-2 **[S]** | n/a | Different radar mosaic | Gauge-based frequency analysis |

**What this catalogue adds.**

1. **The Stage IV risk was assessed from AORC's own methods, not unknown.** AORC says Stage IV "was
   consistently biased low during the winter months from 2002 to approximately 2009" in some areas, until
   dual-polarimetric radar and the Multisensor Precipitation Estimator improved it **[S]** (AORC methods
   section 4.1.1). Since AORC daily totals use Stage IV from 2002, the same low bias is inside the lab's
   catalogue years 2002 to about 2009 in winter. A 3-hour rain catalogue is dominated by summer storms **[P]**,
   so the effect on the top 960 storms is probably small. *Counted 2026-11-26 from the catalogue's tables
   (`data/cache/flood/f4/rainyday/catalogue_n960/`):* 32 of the 960 storms start in December to February
   2002–2009; they are the parent storm of 40 of the 1,000 synthetic years, none of the 30 wettest, and of 1
   of the 150 years selected for the solver **[V]**.
2. **AORC is not an independent check of Stage IV.** Using AORC and then comparing with Stage IV would
   compare a product with its main input **[S]**.
3. **A fall 2016 to 2017 gap in Stage IV use in the Northeast.** The methods say NLDAS-2 daily rain replaced
   Stage IV "in the Northeastern United States (Connecticut, Maine, Massachusetts, New Hampshire, New York,
   Pennsylvania, Rhode Island and Vermont) from the beginning of 2016 through the fall of 2017" **[S]**. That
   lies inside 2002-2025 and covers New York. *Counted 2026-11-26:* 66 of the 960 storms start between
   January 2016 and November 2017; they are the parent storm of 50 synthetic years, none of the 30 wettest,
   and of 4 of the 150 selected years **[V]**. Whether AORC's values in those months are lower was not tested.
4. **The methods text contradicts itself on bias correction after 2010.** One passage says 1979-2015 daily rain
   was corrected with Livneh monthly data and Stage IV was used directly after 2015; another says that from 2010
   Stage IV is bias-corrected by month **[S]**. Not resolved.
5. **Which hours get shaped by what.** Hourly shape comes from Stage IV hourly data in recent years, and from
   coarser or weaker sources before **[S]** (section 4.2).

**Where MRMS and Stage IV could be used beside AORC without changing the catalogue.** The replays already use
MRMS (FH4). A cross-check of AORC and MRMS hourly maxima over the study box for 2021-09-01 and 2023-09-29 would
test AORC where it matters most. It has not been done here **[P]**; it costs about an hour with data already
cached. Stage IV for the same two days could be added if an open copy is found; its lack of an open bucket
(not found; AWS Marketplace listing unopened) is the practical barrier.

**Atlas 14 as the frequency reference.** The catalogue is 31.3, 43.2 and 53.1 mm at 2, 5 and 10 years against
Atlas 14 lower bounds 35.8, 46.7 and 54.9 mm; inside the 90% band at 25, 50 and 100 years (CH-19) **[V]**
(`changes.md`, `simulated-events.md`). AORC observed at the box has a median annual maximum of 38.1 mm
(inside the band), so the shortfall is the catalogue's, not the record's **[V]**. Atlas 14 is a point value
and its band is wide; the areal-reduction factor is not applied, which would lower the point estimate for a
box of 16 km² by an amount not computed here **[P]**. Atlas 15 would replace the reference once published
(section 3.1).

### 4.2 AORC 1979-2025 against 2002-2025

Read from the AORC methods PDF (https://www.weather.gov/media/owp/operations/aorc_v1_1_methods.pdf; section 3
and section 4.1.1 with Table 4.1) on 2026-11-26. Quotes are from the extracted PDF text.

| Item | 1979 to 2001 | 2002 on |
| --- | --- | --- |
| Daily rain reference | NLDAS-2 24-hour totals ending 1200 UTC (a gauge-only CPC analysis, see NLDAS-2 above) | "Stage IV daily precipitation, with interactive, manual quality control and the introduction of radar data, has been used since 2002" |
| Hourly shape | Manually Digitized Radar (47 km in Table 4.1) 1979-1994; WSI NOWrad (4 km) 1996-2001; Stage II 1996-2002; CFSR and GDAS where no radar or satellite | Stage IV hourly (4 km) |
| Bias correction | Livneh monthly data, 1979-2015 | See the contradiction in 4.1 |

Statements on homogeneity **[S]**:

- "temporal inconsistencies are also observed for some or all eight elements", caused by switching input
  datasets between periods or changing bias-correction procedures.
- "The artifacts of the input forcing datasets are more pronounced for the precipitation element for the
  period before 2000 or pre-NEXRAD period."
- The coarse (about 40 km) MDR hourly shapes are much poorer than 4 km NEXRAD for intense events (Figure 4.3
  and its text).
- Stage IV "radar blockage issues in areas with high topographic variability (e.g. Appalachians and
  Shenandoah) are carried into the final AORC output".

**What this means for 1979 against 2002 [P].**

| Consideration | 2002-2025 | 1979-2025 |
| --- | --- | --- |
| Years | 24 | 47 |
| Storm sample | 960 storms (40 a year) | About twice the sample, more rare storms |
| Hourly rain quality | Radar-based, 4 km | 1979-2001 hourly shapes from MDR, NOWrad, GDAS; the daily total is gauge-only. 3-hour storms are the product's weakest feature there |
| Homogeneity | Stage IV changes (winter low bias to about 2009) | Plus the 2002 switch of daily reference |
| Download | 5.54 GB, done | About 10.9 GB at 0.23 GB a year, over the 10 GB budget of F0; 3 to 4 more hours **[V]** (CH-17) |
| Cross-check with Stage IV | Possible (same years) | Only for 2002 on |

The catalogue shortfall at 2 to 10 years is not an argument for 1979: more years would add rare storms
but most of the shortfall is at frequent storms, and the added storms come from the product's least reliable
period for short bursts. This is a judgement, not a test **[P]**. A test that would settle it: build the
catalogue with 1979-2001 and 2002-2025 separately for storms of 3 hours, compare their ranks and tails with
each other and with Atlas 14. It uses the same download and RainyDay run. Not done.

**Reason on record for 2002** (CH-17): the budget and Stage IV's start year; "either reason is a
reconstruction" **[V]**. This catalogue adds a third, more substantive one: the input is radar-based and
homogeneous in kind from 2002 **[S]**, but this was not argued when the choice was made.

**Switch trigger [P].** A decision that rare-storm sampling matters more than hourly quality; the test above
showing 1979-2001 storms agree in tail and shape; or a reason to go beyond the 1,000 synthetic years in FH5.

## 5. What was not read, and questions for Yuri

### 5.1 Not read

- **Stage IV:** the producer's main pages (EMC and NCO product pages: HTTP 404; EMC index: 403) and the NCAR
  archive page in this session (certificate rejected; read earlier by the lab, `rainfall-stage-iv.toml`);
  period end date; licence on any producer page; an open cloud bucket; a producer statement on mountains and
  snow.
- **MRMS:** the grid size on a producer page (NSSL page says "1-km"); the exact archive start on a producer
  page; Pass 1 and Pass 2 definitions beyond the lab's notes; accuracy limits.
- **ERA5:** a general precipitation-bias statement; **ERA5-Land:** update lag and bias note; **IMERG:** biases
  and one consistent Final latency; **NLDAS-2:** latency, biases, a named licence; **PRISM:** update lag,
  inputs, explicit daily-only statement; **Atlas 14:** licence, publication date on the page, climate
  statement; **Atlas 15:** status after June 2026, Northeast coverage, licence.
- **AORC:** sub-heading names under methods section 4.1.1; whether corrected Zarr files are posted.
- **Terrain and buildings:** NYC lidar licence; a newer NYC lidar (none found, not proven absent); the 3DEP
  Known Issues page and 1 m access details; Copernicus Product Handbook; USA Structures attributes, coverage,
  update and limits; all NSI fields on the current official pages and the NSI-Hazus comparison; OSM building
  completeness; NYC Open Data human pages (navigation text only).
- **Assets and hazard:** HIFLD official notice and HIFLD Secure terms; Con Edison API geometry; First Street
  licence, resolution and vintage; FEMA NFHL licence and the exclusion of rain flooding; NYC preliminary FIRM
  pages.
- **Observations:** IEM LSR update frequency; Copernicus EMS licence and the Risk and Recovery list; ESA
  statement on urban SAR limits; Dartmouth archive resolution, update and licence; any NYC list of flooded
  places for Ida; NOAA Storm Events terms.
- **Damage and cost:** USACE EGM 04-01 official text and its coverage beyond residential; Hazus licence and
  flood-model limits; Hazus functional depth (Table 10-12); Williams values; ICE free-access and API terms
  (re-read returned only the title); DOE, NREL and EPRI value-of-lost-load pages; the FEMA page stating 7%
  in 2026.

### 5.2 Places where the catalogue suggests a choice may need revisiting (questions, not decisions)

1. **Q1. Winter bias of Stage IV inside AORC (2002 to about 2009).** Should F4 test whether any of the 960
   catalogue storms fall in winter in those years? The check is cheap (storm dates are in the RainyDay output).
2. **Q2. The 2016-2017 NLDAS-2 substitution for Northeast Stage IV in AORC.** Same test: are catalogue storms
   in that window, and do they differ from MRMS-era storms?
3. **Q3. 1979 against 2002.** The homogeneity statements suggest 1979-2001 gives weaker hourly shapes, which
   the 3-hour storms depend on. Do you want the split test of section 4.2 before deciding on the 11 GB
   download (CH-17 left 1979 as a later option)?
4. **Q4. AORC against MRMS at the box for the two storm days.** An hour's work; not done. Do you want it
   written as a change row?
5. **Q5. Terrain.** The 2013-14 lidar was chosen on date; the city's 2017 DEM is closer to the Ida surface and
   was not ruled out on quality. Should F3's marks error (RMSE 0.21 m) be repeated on it before the licence
   is read? This is a "high" cost switch, so the answer matters only if the marks' error is judged too large.
6. **Q6. HIFLD substations.** Appear to be no longer freely available officially; OSM is now the only open
   source with outlines. Worth saying on the page. No action proposed.
7. **Q7. Atlas 15.** CONUS preliminary estimates are due "no earlier than September 2026" and may soon be
   published. When they are, the frequency reference changes. Add a trigger to the requirements?
8. **Q8. Licences recorded as "not stated".** Several chosen sources (Atlas 14, NSI, NYC terrain and footprints,
   USGS marks, Storm Events, NFIP claims) have no licence statement on the pages read. The page already says so
   (requirements section 14); this catalogue repeats it and adds no new reading.

## Models and tokens

| Task | Model | Tokens |
| --- | --- | --- |
| Catalogue: reading the facts files and reports, writing | Sonnet | 160,176 |
| Web lookups of the alternatives (three agents started by the writer) | Sonnet | about 75,700, 71,500 and 78,500 (as reported by the writer) |
| Scope, the counts in §4.1, review | Opus 5.5 (main session) | not available to the session |
