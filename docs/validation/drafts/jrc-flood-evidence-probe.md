# JRC flood: outside evidence, probe and first fetch

Draft, 2026-11-17. Not reviewed. Written by the agent that built `src/data_source_check/evidence/`.
Every number below was read from a reply received on 2026-11-17 (UTC times in the sidecar files under
`data/cache/validation/jrc-flood/evidence/`). Requests carried `User-Agent: data-source-check/0.1` and
no other identifying information.

Boxes (west, south, east, north, degrees): Houston (-95.9, 29.3, -94.9, 30.2), Austin (-98.0, 30.0,
-97.5, 30.5), Fremont CA (-122.15, 37.42, -121.85, 37.62).

## 1. What answered

| Service | URL | Status | Size | Notes |
| --- | --- | --- | --- | --- |
| FEMA NFHL MapServer | `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer?f=json` | 200 | 9,519 B | currentVersion 11.1, maxRecordCount 2000, query formats JSON, geoJSON, PBF; spatial reference EPSG:4269 (NAD83); `copyrightText` empty |
| FEMA NFHL, second host | `https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer?f=json` | 404 | 1,574 B | not used |
| Flood Hazard Zones layer | `.../MapServer/28?f=json` | 200 | 60,213 B | id 28, name "Flood Hazard Zones", polygons; maxRecordCount 2000; supportsPagination true; no date field; no `editingInfo` (no last-edit date) |
| Layer 28 metadata | `.../MapServer/28/metadata` | 200 | 928 B | only `CreaDate 20191226`; `useLimit` empty |
| FIRM Panels layer | `.../MapServer/3?f=json` | 200 | | has `EFF_DATE` (effective date, epoch ms) and `PRE_DATE` |
| fema.gov NFHL page | `https://www.fema.gov/flood-maps/national-flood-hazard-layer` | 403 | 422 B | terms page not readable by script |
| USGS site service (legacy) | `https://waterservices.usgs.gov/nwis/site/?format=rdb&bBox=...&siteType=ST&hasDataTypeCd=pk&siteOutput=expanded&siteStatus=all` | 200 | 17,574 B (Austin) | still answers; every reply carries "# Warning: A site search criterion has been used for which the data may be unavailable." (also without `hasDataTypeCd`) |
| USGS site root | `https://waterservices.usgs.gov/` | connection reset | 0 | documentation pages under `/docs/` answered 200 |
| USGS OGC API | `https://api.waterdata.usgs.gov/ogcapi/v0/collections` | 200 | 209,895 B | has `monitoring-locations` (bbox, `site_type_code`, drainage_area, altitude, vertical_datum) and `peaks` (one row per parameter 00060/00065, `water_year`, qualifiers as words such as `NOTMAXGH`, `last_modified`). Not used by the fetcher. A search result states a v1 at `/ogcapi/v1`; not probed |
| USGS peak service (legacy) | `https://nwis.waterdata.usgs.gov/nwis/peak?site_no=08074000&agency_cd=USGS&format=rdb` | 200 | 8,279 B | not replaced; `multiple_site_no=a,b` also works (12,442 B for two sites); header warns peaks may be provisional |
| NWS NWPS gauges in a box | `https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-98.0&bbox.ymin=30.0&bbox.xmax=-97.5&bbox.ymax=30.5&srid=EPSG_4326` | 200 | 31,692 B | 31 NWS gauges in the Austin box |
| NWS NWPS one gauge | `https://api.water.noaa.gov/nwps/v1/gauges/08074000` | 200 | 16,416 B | a USGS site number is accepted in place of the NWS id (here BBST2); `flood.categories` action/minor/moderate/major stage and flow, -9999 when none; `datums.vertical` |
| NWS NWPS, gauge not in NWPS | `.../gauges/0810588650` | 404 | 84 B | `{"code": 5, "message": "[0810588650] could not find USGS ID"}` |
| STN, old host | `https://stn.wim.usgs.gov/STNServices/Events.json` | 301 to `https://apps.usgs.gov/stnweb` | 236 B | every path of `stn.wim.usgs.gov` tried redirects there |
| STN, redirect target | `https://apps.usgs.gov/stnweb` | 403 | 2,237 B | "Access forbidden!" (Apache behind Cloudflare); `apps.usgs.gov/STNServices/...` 404 |
| STN services, current | `https://api.waterdata.usgs.gov/stnservices/events/` | 200 | 97,546 B | found in the Flood Event Viewer's JavaScript (`apps.usgs.gov/fev`); answers without a key (the viewer sends an `X-Api-Key`; not used here); `x-ratelimit-limit: 3000` |
| STN marks, one state | `.../stnservices/hwms/filteredhwms/?event=180&states=TX` | 200 | 2,723,003 B | 2,298 marks, no paging; also `&format=csv` (1,108,171 B, same columns) |
| STN marks, whole event | `.../stnservices/hwms/?event=180` | 200 | 1,692,771 B | 2,364 marks (all states), raw fields incl. `survey_date`, `stillwater`, `uncertainty`, `hwm_uncertainty` |
| STN marks, event path | `.../stnservices/events/180/hwms/` | 200 | 2,763,674 B | 2,364 marks, camelCase names, no `elev_ft`; not used |

Harvey: event id 180, name "2017 Harvey", 2017-08-24 to 2017-09-24, description "Hurricane Harvey
Texas Coast August 2017", last updated 2022-09-09.

Licence and terms found:

- FEMA: no licence or use statement in the service, layer or metadata replies; the fema.gov page answered
  403. (FEMA data are a US federal government work; that is general knowledge, not a statement read here.)
- USGS: "USGS-authored or produced data and information are considered to be in the U.S. Public Domain"
  (`https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits`). The peak file
  header says some data "may not have received Director's approval ... provisional and are subject to
  revision". The repository rule asks for attribution of USGS and NOAA data.
- NWPS: no licence field; each gauge lists `dataAttribution` (e.g. "Observations courtesy of U.S.
  Geological Survey", "... U.S. Army Corps of Engineers").
- STN: no licence statement in the replies; the USGS public-domain statement above applies to USGS data.
  The STN replies name the people who flagged, surveyed and approved each mark; the parser drops these
  fields and the test fixtures have them replaced by "(removed)".

## 2. Rules applied

FEMA zone class (`fema_nfhl.zone_class`; zone and subtype trimmed and in capitals), first match wins:

1. `FLD_ZONE` starts with "V" (V, VE, V1-30): `1pct-coastal`;
2. `SFHA_TF` is "T" and `FLD_ZONE` starts with "A" (A, AE, AH, AO, AR, A99, A1-30): `1pct-riverine`;
3. `FLD_ZONE` is "X" and `ZONE_SUBTY` contains "0.2 PCT": `0.2pct`;
4. anything else: `other` (X minimal, X levee, X "1 PCT DEPTH LESS THAN 1 FOOT", D, OPEN WATER, an A zone
   whose `SFHA_TF` is not "T").

`floodway` is true when `ZONE_SUBTY` contains "FLOODWAY", whatever the class (so VE "RIVERINE FLOODWAY
SHOWN IN COASTAL ZONE" is coastal with floodway true). "riverine" is only a name for A zones: A and AE
zones near the coast can be mapped from storm surge, and the layer does not say which.

FEMA query: bounding-box intersects, `outSR=4326` (no datum transformation requested; service is NAD83),
`geometryPrecision=6`, `maxAllowableOffset=0.00001` degrees (about 1 m), `orderByFields=OBJECTID`, pages of
`maxRecordCount` with `resultOffset`, each tile's `returnCountOnly` compared with the features returned;
a tile that errors, times out or comes back short is cut in four (at most four times over). Polygons
crossing a tile edge are kept once by OBJECTID. FIRM panels (layer 3, no geometry) are paged the same way
for their effective dates.

USGS water year: from `peak_dt`, month 10 to 12 gives year + 1, otherwise the year; a month written 00
gives no water year (the date is kept as written).

## 3. First fetch (2026-11-17)

Into `data/cache/validation/jrc-flood/evidence/` (git-ignored), with `live=True`, once each.

FEMA NFHL, layer 28, no failures, no tile split:

| Box | Features | Pages | Zone bytes | Time | 1pct-riverine | 1pct-coastal | 0.2pct | other | floodway | Panels |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Houston | 21,289 | 11 | 92,263,870 | 65.2 s | 6,806 | 214 | 9,924 | 4,345 | 711 | 370 |
| Austin | 7,071 | 4 | 41,023,807 | 41.0 s | 1,894 | 0 | 4,518 | 659 | 125 | 126 |
| Fremont | 718 | 1 | 2,905,714 | 2.6 s | 329 | 15 | 192 | 182 | 16 | 65 |

Zone values met: Houston AE, AE FLOODWAY, A, AO, VE, VE "RIVERINE FLOODWAY SHOWN IN COASTAL ZONE",
X 0.2 PCT, X minimal (4,180), X levee (164), OPEN WATER (1). Austin AE, AE FLOODWAY, A, AO, X 0.2 PCT,
X minimal (657), X levee (2). Fremont also AH (41), D (17), OPEN WATER (4), A/AE "1 PCT ANNUAL CHANCE
FLOOD HAZARD CONTAINED IN CHANNEL" (7). No X "1 PCT DEPTH LESS THAN 1 FOOT" in any box.

Effective dates of the FIRM panels (per DFIRM_ID):

- Houston: 48201C (Harris) 2007-06-18, 2013-10-16, 2014-06-09, 2017-01-06, 2019-05-02, 2019-11-15;
  48039C 2020-12-30; 48071C 2015-05-04, 2018-01-19; 48157C 2014-04-02, 2017-12-21, 2021-01-29; 48167C
  2019-08-15; 48185C 2012-04-03; 48291C 2008-05-02, 2018-01-19; 48339C 2014-08-18; 48473C 2009-02-18,
  2019-05-16; 48481C 2017-12-21.
- Austin: 48021C 2006-01-19, 2016-01-06, 2023-05-09; 48055C 2012-06-19, 2026-06-10; 48209C 2005-09-02,
  2025-01-17; 48453C 2008-09-26, 2014-08-18, 2016-01-06, 2020-01-22; 48491C 2008-09-26, 2019-12-20.
- Fremont: 06001C 2009-08-03; 06081C 2012-10-16, 2019-04-05; 06085C 2009-05-18, 2014-02-19.

USGS gauges and peaks (site type ST with peak data, active and inactive), no failures:

| Box | Gauges | Peak rows | Water years | Peaks Aug-Sep 2017 | NWPS found / 404 | NWPS with minor stage | Bytes | Time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Houston | 107 | 3,690 | 1884-2026 | 63 (62 with gage height) | 31 / 76 | 31 | 1,157,226 | 85.3 s |
| Austin | 58 | 1,274 | 1869-2026 | 16 (16 with gage height) | 28 / 30 | 9 | 505,578 | 45.5 s |

Rows with discharge: Houston 3,234, Austin 1,252; with gage height: 3,623, 1,246. Peaks with month 00
(no water year): Houston 5, Austin 4. Gauge datum (`alt_datum_cd`): Houston NAVD88 76, NGVD29 31;
Austin NAVD88 33, NGVD29 25. One Houston gauge has no drainage area.

STN, Harvey (event 180), Texas: 2,298 marks, 4,513,320 bytes in three replies, 6.3 s.

- Environment: Riverine 1,967, Coastal 331. With height above ground: 2,093 (riverine 1,789).
- Vertical datum: NAVD88 2,224, "local control point" 55, NGVD29 18, empty 1 (id 23484).
- Horizontal datum: NAD83 2,292, "WGS84 (from Digital Map)" 6.
- Quality: Excellent (+/- 0.05 ft) 401, Good (+/- 0.10 ft) 622, Fair (+/- 0.20 ft) 661, Poor
  (+/- 0.40 ft) 419, VP (> 0.40 ft) 192, Unknown/Historical 3.
- `stillwater` (from the whole-event reply): true 2,039, false 259; every Texas mark had survey details.
- In the Houston box: 829 marks, 694 with height above ground, 715 riverine (114 coastal); datum NAVD88
  828, NGVD29 1.

## 4. What to know before use

- FEMA polygons are generalised by the server at about 1 m. On 100 Austin polygons fetched at full
  detail as a check, 0 were invalid at full detail and 5 invalid after generalisation; areas differed by
  a median of 0.14 % and at most 73 % (one small polygon). In the stored boxes 431 (Houston), 606 (Austin)
  and 1 (Fremont) polygons are invalid as sent; `zones()` flags them (`valid`) and does not repair them.
  Full detail is heavy: 100 Austin polygons were 19,298,076 bytes, and a page of 400 at full detail
  failed with "Error: Error performing query operation, Code: 500".
- FEMA zones are regulatory maps of different dates; much of Harris County (48201C) is on panels
  effective 2007, before Harvey and before NOAA Atlas 14 rainfall. `STATIC_BFE` is in feet on `V_DATUM`
  (NAVD88 where given; most rows have neither).
- USGS gage heights are feet above each gauge's own datum, not elevations; `alt_va` gives that datum's
  altitude in NAVD88 or NGVD29 (both occur). Discharge is in cfs. `peak_cd` and `gage_ht_cd` are kept
  verbatim (e.g. 5/6 regulation, 7 historic, 9 hurricane, C urbanisation, 2 estimate).
- NWPS flood stages are on the NWS gauge's reading scale; whether it equals the USGS gage height datum is
  not checked. 76 Houston and 30 Austin gauges have no NWPS entry (404).
- STN elevations are feet on the stated vertical datum; 55 Texas marks are on a "local control point"
  and one has no datum, so they are not comparable with NAVD88 without more work. Height above ground
  is missing for 205 marks. The STN host moved; the address in use is the one the viewer reads, found in
  its code, not a documented address.
- Both legacy NWIS services answered; USGS is moving to `api.waterdata.usgs.gov` (OGC API, with a
  `peaks` collection), which the fetcher does not use.
