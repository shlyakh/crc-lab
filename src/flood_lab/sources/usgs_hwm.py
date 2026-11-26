"""USGS high-water marks of Ida in New York City: one row per surveyed mark (FV1).

Source: Capurso and others, 2023, USGS data release doi:10.5066/P9OMBJPQ (ScienceBase item
``618975c8d34ec04fc9c5a049``), file ``FilteredHWMs_NewYork.csv`` and its data dictionary
``STN_FilteredHWMs_data_dictionary.csv``.

Transformation statement (the data card repeats it):

1. The first line of the file is a citation; the header is on line 2. Every one of the 159 rows
   is kept, one per mark (``hwm_id``), sorted by ``hwm_id``.
2. ``longitude`` and ``latitude`` are ``longitude_dd`` and ``latitude_dd`` as written. The file
   names their datum "WGS84 (from Digital Map)" and their method "Phone/Car GPS": a map or phone
   fix, not a survey. They are projected to the project CRS (EPSG:32618) with pyproj and
   rounded to 0.01 m (``easting_m``, ``northing_m``).
3. ``vertical_datum`` is ``verticalDatumName`` as written. ``elev_navd88_m`` is ``elev_ft`` (the
   dictionary: "Surveyed elevation of high-water mark in feet") times 0.3048, rounded to 0.1 mm,
   and only where the datum is NAVD88; under any other datum it is missing, never converted.
4. ``height_above_ground_m`` is ``height_above_gnd`` ("Distance from high-water mark to ground in
   feet") times 0.3048, rounded to 0.1 mm; missing where the file leaves it blank (7 rows).
5. ``uncertainty_m`` is ``uncertainty`` ("Uncertainty of high-water mark survey, in feet") times
   0.3048, rounded to 0.1 mm; missing where blank. ``quality`` is ``hwmQualityName`` as written
   (the flagging uncertainty, e.g. "Good: +/- 0.10 ft"); ``survey_date`` is as written.
6. ``in_square``: the projected point lies in the project square, ``GRID.west <= x < GRID.east``
   and ``GRID.south <= y < GRID.north``.

The foot is taken as the international foot, 0.3048 m; the dictionary does not say which foot.
The US survey foot differs by 2 parts per million, 0.01 mm on a 5 m mark. A mark is where a crew
found debris, mud or a seed line weeks after the storm: no mark is not no flood.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from flood_lab.domain import CRS, GRID

FILE = "usgs-ida-high-water-marks/FilteredHWMs_NewYork.csv"
DICTIONARY = "usgs-ida-high-water-marks/STN_FilteredHWMs_data_dictionary.csv"
FT_M = 0.3048
COLUMNS = [
    "hwm_id",
    "site_no",
    "longitude",
    "latitude",
    "easting_m",
    "northing_m",
    "vertical_datum",
    "elev_navd88_m",
    "height_above_ground_m",
    "uncertainty_m",
    "quality",
    "survey_date",
    "in_square",
]


def _feet_to_m(values: pd.Series) -> pd.Series:
    """Feet to metres rounded to 0.1 mm; blanks stay missing (None in an object column)."""
    metres = (values.astype("float64") * FT_M).round(4)
    return metres.astype(object).where(metres.notna(), None)


def marks(csv: Path) -> pd.DataFrame:
    """Statement steps 1 to 6: one row per mark of the whole file, sorted by ``hwm_id``."""
    from pyproj import Transformer

    raw = pd.read_csv(csv, skiprows=1, dtype={"site_no": str, "survey_date": str})
    lon = raw["longitude_dd"].astype("float64")
    lat = raw["latitude_dd"].astype("float64")
    x, y = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(
        lon.to_numpy(), lat.to_numpy()
    )
    x, y = np.round(np.asarray(x), 2), np.round(np.asarray(y), 2)
    datum = raw["verticalDatumName"].astype(str)
    elev = _feet_to_m(raw["elev_ft"]).where(datum == "NAVD88", None)
    table = pd.DataFrame(
        {
            "hwm_id": raw["hwm_id"].astype(int),
            "site_no": raw["site_no"].astype(str),
            "longitude": lon,
            "latitude": lat,
            "easting_m": x,
            "northing_m": y,
            "vertical_datum": datum,
            "elev_navd88_m": elev,
            "height_above_ground_m": _feet_to_m(raw["height_above_gnd"]),
            "uncertainty_m": _feet_to_m(raw["uncertainty"]),
            "quality": raw["hwmQualityName"].astype(str),
            "survey_date": raw["survey_date"].astype(str),
            "in_square": (x >= GRID.west) & (x < GRID.east) & (y >= GRID.south) & (y < GRID.north),
        }
    )
    return table.sort_values("hwm_id", kind="stable").reset_index(drop=True)[COLUMNS]


def as_rows(table: pd.DataFrame) -> list[dict]:
    """The table as a list of dicts with plain Python values and None for every missing one."""
    rows = []
    for record in table.to_dict(orient="records"):
        row = {}
        for k, v in record.items():
            if v is None or (isinstance(v, float) and np.isnan(v)):
                row[k] = None
            elif isinstance(v, np.bool_ | bool):
                row[k] = bool(v)
            elif isinstance(v, np.integer):
                row[k] = int(v)
            elif isinstance(v, np.floating):
                row[k] = float(v)
            else:
                row[k] = v
        rows.append(row)
    return rows
