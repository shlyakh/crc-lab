"""The one asset table, ``site/flood/data/assets_oed.csv`` (requirement FD6).

Every engine reads this file or an export of it. Columns in Oasis Open Exposure Data (OED) names
come first; the lab's own columns start with ``lab_``. The sixteen OED names were checked in F1
against the OED specification, version 5.0.0 (``OasisLMF/ODS_OpenExposureData``, tag 5.0.0): all
exist. Codes used, from the same version: ``CountryCode`` US; ``LocCurrency`` USD;
``LocPerilsCovered`` OSF (flash, surface or pluvial flood); ``FirstFloorHeightUnit`` 2 (metres;
the specification's default, 1, is feet); ``OccupancyCode`` 1300 (utilities, electrical) for a
substation. ``OccupancyCode`` of a building and ``ConstructionCode`` are left empty: no mapping
from the structure inventory's occupancy classes to OED codes was read, and no source gives a
construction class. ``LocName`` is at most 20 characters in the specification.

Rules the table must keep (``validate`` checks them):

* one row per asset; ``LocNumber`` is unique and stable (``S-`` plus a number for a substation
  site, ``B-`` plus the city's building identification number for a building);
* ``Latitude`` and ``Longitude`` are WGS84 (CRC's ``Assets`` accepts nothing else) and agree with
  ``lab_x_m`` and ``lab_y_m`` in the project CRS to within a metre;
* every asset has a ground elevation in metres above NAVD88, with where it came from;
* every money value carries its tag: S (stated by a source), I (inferred), P (placeholder);
* a value that is not known is empty, never zero.
"""

from __future__ import annotations

from typing import Any

#: OED columns (names checked against OED 5.0.0), in file order
OED = (
    "PortNumber",
    "AccNumber",
    "LocNumber",
    "LocName",
    "CountryCode",
    "Latitude",
    "Longitude",
    "OccupancyCode",
    "ConstructionCode",
    "NumberOfStoreys",
    "YearBuilt",
    "BuildingTIV",
    "LocCurrency",
    "LocPerilsCovered",
    "FirstFloorHeight",
    "FirstFloorHeightUnit",
)
#: the lab's own columns
LAB = (
    "lab_asset_type",  # "substation" or "building"
    "lab_x_m",  # project CRS (EPSG:32618)
    "lab_y_m",
    "lab_in_study_area",  # true when on the borough land inside the square
    "lab_ground_elev_m",  # NAVD88
    "lab_ground_elev_source",  # "terrain" or the name of a table field
    "lab_terrain_elev_m",  # the 1 m terrain at the asset, always filled, for comparison
    "lab_first_floor_elev_m",  # NAVD88, buildings where known
    "lab_first_floor_height_m",  # above ground; may be negative
    "lab_subgrade",  # buildings: "Y", "N" or empty
    "lab_bin",  # buildings: the city's building identification number
    "lab_match",  # buildings: how footprint, elevation table and inventory were joined
    "lab_occupancy_hazus",  # buildings: occupancy class of the structure inventory
    "lab_foundation_type",
    "lab_nsi_id",
    "lab_osm_ids",  # substations: the OpenStreetMap elements of the site, "way/1;way/2"
    "lab_outlines",  # substations: number of mapped outlines merged into the site
    "lab_voltage_kv",  # substations: highest tagged voltage, empty when untagged
    "lab_substation_kind",  # substations: transmission, distribution, ...
    "lab_indoor",  # substations: "yes", "no" or "unknown", from tags and the imagery review
    "lab_reviewed",  # substations: "kept", or "removed: <reason>" (removed rows stay in the table)
    "lab_value_low_usd",
    "lab_value_mid_usd",
    "lab_value_high_usd",
    "lab_value_tag",  # S, I or P
    "lab_value_source",
    "lab_customers_served",  # substations; requirement FD7
    "lab_customers_tag",
)
COLUMNS = OED + LAB
ASSET_TYPES = ("substation", "building")
TAGS = ("S", "I", "P")
#: New York City in round numbers, to catch swapped or projected coordinates
LAT_RANGE = (40.4, 41.0)
LON_RANGE = (-74.3, -73.6)


def validate(rows: list[dict[str, Any]]) -> list[str]:
    """Faults of the table as plain sentences; an empty list means the rules hold."""
    faults: list[str] = []
    if not rows:
        return ["the table has no rows"]
    if tuple(rows[0]) != COLUMNS:
        missing = [c for c in COLUMNS if c not in rows[0]]
        extra = [c for c in rows[0] if c not in COLUMNS]
        faults.append(f"columns differ from the schema: missing {missing}, unexpected {extra}")
        return faults
    seen: set[str] = set()
    for number, row in enumerate(rows, start=2):  # line 1 is the header
        key = str(row["LocNumber"])
        where = f"line {number} ({key})"
        if not key or key in seen:
            faults.append(f"{where}: LocNumber is empty or repeated")
        seen.add(key)
        kind = row["lab_asset_type"]
        if kind not in ASSET_TYPES:
            faults.append(f"{where}: lab_asset_type is {kind!r}")
        elif not key.startswith("S-" if kind == "substation" else "B-"):
            faults.append(f"{where}: LocNumber does not start with the letter of its asset type")
        try:
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
                faults.append(f"{where}: latitude and longitude are not in New York City")
        except (TypeError, ValueError):
            faults.append(f"{where}: latitude or longitude is not a number")
        if row["lab_ground_elev_m"] in ("", None) or not row["lab_ground_elev_source"]:
            faults.append(f"{where}: no ground elevation, or no source for it")
        if row["lab_terrain_elev_m"] in ("", None):
            faults.append(f"{where}: no terrain elevation")
        values = [row[f"lab_value_{level}_usd"] for level in ("low", "mid", "high")]
        given = [v for v in values if v not in ("", None)]
        if given:
            if row["lab_value_tag"] not in TAGS:
                faults.append(f"{where}: a value without a tag S, I or P")
            if len(given) == 3 and not float(values[0]) <= float(values[1]) <= float(values[2]):
                faults.append(f"{where}: low, mid and high values are not in order")
            if any(float(v) == 0 for v in given):
                faults.append(f"{where}: a value of zero; an unknown value is left empty")
    return faults
