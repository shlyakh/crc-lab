"""Groundsource: a table of dated places in the lab's two boxes (FS2). Not loaded into CRC.

Transformation statement (the data card repeats it):

1. The publisher's one file (Zenodo record 18647054, ``groundsource_2026.parquet``) is read with
   pyarrow, column by column, after the stage's check has found its md5 equal to the
   publisher's. Its GeoParquet key-value metadata is ignored: only the five documented columns
   are read, and the accidental index column is left.
2. A row is kept for a box when its polygon intersects the box (touching counts). The row's
   bounding box is used only to skip rows that cannot intersect.
3. Kept as written: ``uuid``, ``start_date``, ``end_date``, ``area_km2`` and the polygon (WKB,
   longitude and latitude on WGS84). Added: the box, the polygon's centroid in degrees, and
   whether that centroid is in the box.

``area_km2`` is the area of the named place, not of any flood. A row says that a news report
placed a flood in that place on those days; the publisher's own review found 60% of 400 rows
accurate in both place and dates.

CRC 1.0.0 has no record that holds a date range with a polygon, so this stays a ``flood_lab``
table (D8).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

FILE = "groundsource/groundsource_2026.parquet"
MD5 = "cd1b5de6508f7aad8e1d1d0dd4cecea6"
#: west, south, east, north in degrees
BOXES = {
    "nyc": (-74.26, 40.49, -73.70, 40.92),
    "alameda": (-122.35, 37.45, -121.45, 37.91),
}
READ = ["uuid", "area_km2", "geometry", "start_date", "end_date"]
COLUMNS = [
    "box",
    "uuid",
    "start_date",
    "end_date",
    "area_km2",
    "geometry_wkb",
    "centroid_lon",
    "centroid_lat",
    "centroid_in_box",
]


def md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324  the publisher's checksum is an md5
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def dated_places(
    path: Path, boxes: dict[str, tuple[float, float, float, float]] = BOXES
) -> pd.DataFrame:
    """Statement steps 1 to 3. Reads one row group at a time to stay small in memory."""
    file = pq.ParquetFile(path)
    kept: list[pd.DataFrame] = []
    for index in range(file.metadata.num_row_groups):
        group: pa.Table = file.read_row_group(index, columns=READ)
        shapes = shapely.from_wkb(group["geometry"].to_numpy(zero_copy_only=False))
        bounds = shapely.bounds(shapes)
        for name, (west, south, east, north) in boxes.items():
            maybe = np.flatnonzero(
                (bounds[:, 0] <= east)
                & (bounds[:, 2] >= west)
                & (bounds[:, 1] <= north)
                & (bounds[:, 3] >= south)
            )
            box = shapely.box(west, south, east, north)
            hit = maybe[shapely.intersects(shapes[maybe], box)]
            if hit.size == 0:
                continue
            rows = group.take(pa.array(hit)).to_pandas()
            centroid = shapely.centroid(shapes[hit])
            lon, lat = shapely.get_x(centroid), shapely.get_y(centroid)
            kept.append(
                pd.DataFrame(
                    {
                        "box": name,
                        "uuid": rows["uuid"].astype(str),
                        "start_date": rows["start_date"].astype(str),
                        "end_date": rows["end_date"].astype(str),
                        "area_km2": rows["area_km2"].astype(float),
                        "geometry_wkb": rows["geometry"],
                        "centroid_lon": lon,
                        "centroid_lat": lat,
                        "centroid_in_box": (lon >= west)
                        & (lon <= east)
                        & (lat >= south)
                        & (lat <= north),
                    }
                )
            )
    table = pd.concat(kept, ignore_index=True) if kept else pd.DataFrame(columns=COLUMNS)
    return table.sort_values(["box", "uuid"], kind="stable").reset_index(drop=True)[COLUMNS]


def covering(table: pd.DataFrame, box: str, day: str) -> pd.DataFrame:
    """Rows of a box whose date range holds a day (``YYYY-MM-DD``; text dates sort as dates)."""
    rows = table[table["box"] == box]
    return rows[(rows["start_date"] <= day) & (rows["end_date"] >= day)]
