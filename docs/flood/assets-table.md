# The asset table: what it is and how far to trust it

Data card for `site/flood/data/assets_oed.csv`, the one table of assets every engine reads
(requirement FD6). It is a product of this project, built by `just flood-f1-assets` from four sources,
each with its own data card under `docs/flood/data-cards/`. Counts, match rates and checks are in the
record `site/flood/tests/records/f1-assets.json` and on the gallery; none is repeated here.

| | |
| --- | --- |
| Rows | One per asset: substations (`LocNumber` S- and the smallest OpenStreetMap id of its outlines) and buildings (B- and the city's building identification number) |
| Area | Assets whose centre lies on the study area: Brooklyn land in the square of `src/flood_lab/domain.py` |
| Columns | Sixteen in Oasis Open Exposure Data 5.0.0 names, then the lab's own (`lab_`); listed with their rules in `src/flood_lab/assets/schema.py` |
| Coordinates | WGS84 longitude and latitude, and project metres (EPSG:32618) |
| Heights | Metres above NAVD88 |
| Money | US dollars as the source states them, in the source's price year, not adjusted; each with a tag S, I or P |
| Licence of the parts | OpenStreetMap: ODbL, credit "© OpenStreetMap contributors". City tables: NYC Open Data terms. Structure inventory and terrain: see their cards; the inventory's terms were not found stated |

## Where each column comes from

| What | Source | Note |
| --- | --- | --- |
| Substation outlines, names, voltage, kind | OpenStreetMap (`osm-substations`) | Volunteers' mapping; a named substation is one asset; rail traction substations are left out |
| Whether a substation is kept, and indoor or outdoor | `src/flood_lab/assets/substation_review.toml` | A look at aerial imagery by the coordinating model, recorded with what was seen; Yuri may change any line |
| Substation value, low, mid, high | `src/flood_lab/assets/values.toml` (`substation-cost-sources`) | **Placeholder.** Bracketed by two published figures for other substations; the mid figure is their geometric mean |
| Building outline, identification number, year built | City footprints (`nyc-building-footprints`) | |
| Ground and first-floor elevation, subgrade flag | City Building Elevation and Subgrade table (`nyc-building-elevation-subgrade`) | A one-time survey; about a third of grades are marked as estimated; a zero means not measured and is left empty |
| Occupancy, foundation type, building value | USACE National Structure Inventory (`usace-national-structure-inventory`) | Joined by position, not by a shared number; modelled, depreciated values; where a footprint holds several inventory points only the largest is taken |
| Terrain elevation at the asset | USGS 1 m terrain (`usgs-3dep-1m`) | Flown 2013 to 2014; carries about a metre of horizontal datum offset |

## Limits

- A building with no row in the elevation table has its ground elevation from the terrain and no
  first-floor height. Garages are almost never in that table.
- A building with no inventory point has no value and no occupancy in this table. Since CH-31
  (2026-11-28) the exposures table `site/flood/data/exposures.csv` gives it a substitute class (PLUTO)
  and value (Hazus cost per ft²), flagged as such; this table is unchanged.
- Customers served per substation (FD7) is empty: no public figure exists and no placeholder was made.
- Substation values are placeholders spanning a factor of about forty.
- Building occupancy and construction codes in OED terms are empty.
