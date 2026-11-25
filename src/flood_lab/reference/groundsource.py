"""Second reader of the Groundsource Parquet file (requirements FS2, FS4).

The publisher's file (Zenodo record 18647054, ``groundsource_2026.parquet``) has the columns
``uuid``, ``area_km2``, ``geometry`` (WKB, WGS84), ``start_date``, ``end_date`` and an accidental
``__index_level_0__``. Its GeoParquet key-value metadata (``geo``) names the geometry column but
gives no geometry types, and DuckDB refuses the file as GeoParquet ("Geoparquet column 'geometry'
does not have geometry types").

Route, chosen to share nothing with a loader built on pyarrow: DuckDB reads the file with its
GeoParquet interpretation switched off (``SET enable_geoparquet_conversion = false``), so the
geometry column arrives as plain bytes. The publisher's file is not altered or copied, and no
DuckDB extension is needed (none is installed or loaded; autoloading is off). Rows are fetched in
batches as Python values; shapely parses the WKB, a bounding-box overlap is the cheap prefilter,
and shapely's exact ``intersects`` with the box decides.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import shapely

from .. import cache

FILE_NAME = "groundsource_2026.parquet"
MD5 = "cd1b5de6508f7aad8e1d1d0dd4cecea6"
#: west, south, east, north, degrees
BOXES: dict[str, tuple[float, float, float, float]] = {
    "nyc": (-74.26, 40.49, -73.70, 40.92),
    "alameda": (-122.35, 37.45, -121.45, 37.91),
}
COLUMNS = ("uuid", "area_km2", "geometry", "start_date", "end_date")
BATCH_ROWS = 200_000


def checksum(path: str | Path) -> str:
    """The md5 of the file, read in blocks of 1 MiB."""
    digest = hashlib.md5()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(
        config={"autoinstall_known_extensions": False, "autoload_known_extensions": False}
    )
    con.execute("SET enable_geoparquet_conversion = false")
    return con


def _batches(path: str | Path):
    """The file's rows in batches of tuples (``COLUMNS`` order), through DuckDB."""
    con = _connect()
    try:
        cursor = con.execute(f"SELECT {', '.join(COLUMNS)} FROM read_parquet(?)", [str(Path(path))])
        while batch := cursor.fetchmany(BATCH_ROWS):
            yield batch
    finally:
        con.close()


def dated_places(
    path: str | Path, boxes: dict[str, tuple[float, float, float, float]] = BOXES
) -> list[dict[str, Any]]:
    """One row per (box, uuid) for every row of the file whose polygon intersects the box.

    Rules: the test is the exact geometric intersection of the polygon with the rectangle,
    boundary touching included (shapely ``intersects``), not a bounding-box test; the bounding
    box only discards rows that cannot intersect. ``start_date``, ``end_date``, ``area_km2`` and
    ``geometry_wkb`` are kept as in the file; ``centroid_lon`` and ``centroid_lat`` are the planar
    centroid in degrees; ``centroid_in_box`` is True when the centroid is in the box, edges
    included. Rows are sorted by (``box``, ``uuid``).
    """
    rectangles = {name: shapely.box(*bounds) for name, bounds in boxes.items()}
    found: list[dict[str, Any]] = []
    for batch in _batches(path):
        wkb = np.array([row[2] for row in batch], dtype=object)
        geoms = shapely.from_wkb(wkb)
        bounds = shapely.bounds(geoms)
        for name, (west, south, east, north) in boxes.items():
            near = (
                (bounds[:, 0] <= east)
                & (bounds[:, 2] >= west)
                & (bounds[:, 1] <= north)
                & (bounds[:, 3] >= south)
            )
            index = np.flatnonzero(near)
            if index.size == 0:
                continue
            hit = index[shapely.intersects(geoms[index], rectangles[name])]
            centroids = shapely.centroid(geoms[hit])
            for i, centre in zip(hit, centroids, strict=True):
                uuid, area, blob, start, end = batch[i]
                lon, lat = float(centre.x), float(centre.y)
                found.append(
                    {
                        "box": name,
                        "uuid": uuid,
                        "start_date": start,
                        "end_date": end,
                        "area_km2": area,
                        "geometry_wkb": bytes(blob),
                        "centroid_lon": lon,
                        "centroid_lat": lat,
                        "centroid_in_box": bool(west <= lon <= east and south <= lat <= north),
                    }
                )
    found.sort(key=lambda r: (r["box"], r["uuid"]))
    return found


def covering(rows: list[dict[str, Any]], box: str, day: str) -> int:
    """Rows of ``box`` whose date range holds ``day``: ``start_date <= day <= end_date``."""
    return sum(1 for r in rows if r["box"] == box and r["start_date"] <= day <= r["end_date"])


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write the table as Parquet through DuckDB, atomically."""
    from . import write_atomic

    def _write(tmp: Path) -> None:
        con = duckdb.connect()
        try:
            con.execute(
                "CREATE TABLE t (box VARCHAR, uuid VARCHAR, start_date VARCHAR, end_date VARCHAR,"
                " area_km2 DOUBLE, geometry_wkb BLOB, centroid_lon DOUBLE, centroid_lat DOUBLE,"
                " centroid_in_box BOOLEAN)"
            )
            con.executemany(
                "INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r["box"],
                        r["uuid"],
                        r["start_date"],
                        r["end_date"],
                        r["area_km2"],
                        r["geometry_wkb"],
                        r["centroid_lon"],
                        r["centroid_lat"],
                        r["centroid_in_box"],
                    )
                    for r in rows
                ],
            )
            tmp.unlink(missing_ok=True)
            con.execute(f"COPY t TO '{tmp}' (FORMAT parquet)")
        finally:
            con.close()

    write_atomic(path, _write)


def main() -> None:  # pragma: no cover - run on the real file by hand
    from . import peak_memory_bytes, scratch_dir, write_json

    path = cache.root() / "groundsource" / FILE_NAME
    out = scratch_dir() / "groundsource"
    start = time.perf_counter()
    md5 = checksum(path)
    md5_seconds = time.perf_counter() - start
    if md5 != MD5:
        raise SystemExit(f"{path}: md5 {md5}, expected {MD5}; stopping")
    rows = dated_places(path)
    seconds = time.perf_counter() - start
    con = _connect()
    total = con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    con.close()
    per_box = {name: sum(1 for r in rows if r["box"] == name) for name in BOXES}
    keys = [(r["box"], r["uuid"]) for r in rows]
    summary = {
        "input": str(path),
        "md5": md5,
        "md5_expected": MD5,
        "file_rows": total,
        "rows_per_box": per_box,
        "repeated_box_uuid": len(keys) - len(set(keys)),
        "centroid_outside_box": {
            name: sum(1 for r in rows if r["box"] == name and not r["centroid_in_box"])
            for name in BOXES
        },
        "nyc_covering_2021-09-01": covering(rows, "nyc", "2021-09-01"),
        "seconds_md5": round(md5_seconds, 2),
        "seconds_total": round(seconds, 2),
        "peak_memory_bytes": peak_memory_bytes(),
    }
    _write_parquet(out / "dated-places.parquet", rows)
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
