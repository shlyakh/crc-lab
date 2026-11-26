"""Second reader of the USGS Hurricane Ida high-water marks for New York City (FS4).

Route, chosen to share nothing with a loader: the standard library's ``csv`` reads the file as
text, ``pyproj`` projects the points, and nothing else is imported from the project but the
square in ``flood_lab.domain``.

A row is one high-water mark (one ``hwm_id``); a site (``site_no``) can hold several. The first
line of the file is a citation and the header is on line 2.

Transformation rules:

1. ``hwm_id`` is read as an integer; the keys ``site_no``, ``verticalDatumName``,
   ``hwmQualityName`` and ``survey_date`` are kept as written (text).
2. ``longitude_dd`` and ``latitude_dd`` are kept as floats exactly as in the file.
3. Easting and northing: EPSG:32618 from the longitude and latitude, rounded to 0.01 m. Every row
   says ``horizontalDatumName`` is ``WGS84 (from Digital Map)``; the metadata says GCS WGS 1984.
   The point is taken as EPSG:4326 and projected with pyproj's default operation. NAD83 and WGS84
   differ by about a metre in this area, which is below the positional accuracy of a phone or
   map position, so no datum shift is applied beyond what pyproj does by default.
4. Elevation: ``elev_ft`` times 0.3048 m per foot (the international foot), rounded to 1e-4 m,
   only when ``verticalDatumName`` is exactly ``NAVD88``; otherwise ``None``. The data dictionary
   says feet; the metadata XML says ``US Survey Feet`` for the vertical system. The two feet
   differ by 2 parts per million (0.00001 m on a 6 m height), so the international foot is
   used and the conflict is reported, not resolved.
5. ``height_above_gnd`` and ``uncertainty`` (feet) times 0.3048, rounded to 1e-4 m; ``None``
   when the field is blank.
6. ``in_square``: ``west <= easting < east`` and ``south <= northing < north`` on
   ``flood_lab.domain.GRID``, using the unrounded projected coordinates.
7. Marks are sorted by ``hwm_id``; a repeated ``hwm_id`` raises ``ValueError``.

Not checked: that the elevation is plausible against terrain or water level, that
``height_above_gnd`` agrees with the notes, that the quality label agrees with ``uncertainty``,
that survey dates are real dates, and anything about the shapefile that accompanies the CSV.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from pyproj import Transformer

from .. import domain

FOOT_M = 0.3048
_TO_UTM = Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True)
DEFAULT_PATH = Path("data/cache/flood/usgs-ida-high-water-marks/FilteredHWMs_NewYork.csv")


def _feet(text: str) -> float | None:
    text = text.strip()
    return round(float(text) * FOOT_M, 4) if text else None


def marks(csv_path: Path | str) -> list[dict[str, Any]]:
    """Every mark in the file, sorted by ``hwm_id``, with the keys listed in the module text."""
    west, south, east, north = (
        domain.GRID.west,
        domain.GRID.south,
        domain.GRID.east,
        domain.GRID.north,
    )
    out: list[dict[str, Any]] = []
    with open(csv_path, encoding="utf-8", newline="") as handle:
        handle.readline()
        for row in csv.DictReader(handle):
            lon = float(row["longitude_dd"])
            lat = float(row["latitude_dd"])
            x, y = _TO_UTM.transform(lon, lat)
            datum = row["verticalDatumName"]
            elev = row["elev_ft"].strip()
            out.append(
                {
                    "hwm_id": int(row["hwm_id"]),
                    "site_no": row["site_no"],
                    "longitude": lon,
                    "latitude": lat,
                    "easting_m": round(x, 2),
                    "northing_m": round(y, 2),
                    "vertical_datum": datum,
                    "elev_navd88_m": _feet(elev) if datum == "NAVD88" and elev else None,
                    "height_above_ground_m": _feet(row["height_above_gnd"]),
                    "uncertainty_m": _feet(row["uncertainty"]),
                    "quality": row["hwmQualityName"],
                    "survey_date": row["survey_date"],
                    "in_square": west <= x < east and south <= y < north,
                }
            )
    out.sort(key=lambda m: m["hwm_id"])
    ids = [m["hwm_id"] for m in out]
    if len(set(ids)) != len(ids):
        raise ValueError("repeated hwm_id")
    return out


def main() -> None:
    path = DEFAULT_PATH
    rows = marks(path)
    inside = [m for m in rows if m["in_square"]]
    print(f"rows: {len(rows)}")
    print(f"distinct sites: {len({m['site_no'] for m in rows})}")
    print(f"rows in square: {len(inside)}")
    print(f"sites in square: {len({m['site_no'] for m in inside})}")
    print(f"vertical datum values: {dict(Counter(m['vertical_datum'] for m in rows))}")
    print(f"blank height_above_gnd: {sum(m['height_above_ground_m'] is None for m in rows)}")
    print(f"blank elev_ft: {sum(m['elev_navd88_m'] is None for m in rows)}")
    print(f"blank uncertainty: {sum(m['uncertainty_m'] is None for m in rows)}")
    for m in inside:
        print(m)


if __name__ == "__main__":
    main()
