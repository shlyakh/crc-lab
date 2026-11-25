"""Second reader of the NYC Stormwater Flood Maps (requirements FS1, FS4).

The publisher's zip holds four ESRI file geodatabases, one per scenario, each with one feature
class of MultiPolygon Z in EPSG:2263 (US feet) and the coded field ``Flooding_Category``:

* 1: nuisance flooding, 4 in to under 1 ft;
* 2: deep and contiguous flooding, 1 ft and greater;
* 3: future high tides (tidal inundation from sea-level rise), only in the 2050 and 2080 layers.
  Code 3 is not a rainfall depth class and never enters ``depth_class``.

Route, chosen to share nothing with a loader that rasterises with GDAL: polygons are read with
pyogrio's raw reader (WKB, no geopandas), their Z dropped, their vertices moved from EPSG:2263 to
EPSG:26918 (NAD83 / UTM 18N) with pyproj, and those eastings and northings used as project-grid
coordinates unchanged, as the terrain was (``flood_lab.terrain``: no NAD83-to-WGS84 shift). Each
cell is then classed by an explicit point-in-polygon test of its centre with shapely; no
rasterise function is called.

Reading a path in a zip works through GDAL's virtual file system:
``/vsizip//abs/path/NYCFloodStormwaterFloodMaps.zip/<folder>/<name>.gdb``.
"""

from __future__ import annotations

import time
import warnings
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import pyproj
import shapely
from shapely.geometry.base import BaseGeometry

from .. import cache, domain

SCENARIOS = ("limited-current", "moderate-current", "moderate-2050", "extreme-2080")
#: the scenario's folder inside the publisher's zip ends with this text; it holds one ``.gdb``
SCENARIO_FOLDERS = {
    "limited-current": "Limited Flood (1.77 inches per hr) with Current Sea Levels",
    "moderate-current": "Moderate Flood (2.13 inches per hr) with Current Sea Levels",
    "moderate-2050": "Moderate Flood (2.13 inches per hr) with 2050 Sea Level Rise",
    "extreme-2080": "Extreme Flood (3.66 inches per hr) with 2080 Sea Level Rise",
}
ZIP_NAME = "NYCFloodStormwaterFloodMaps.zip"
ZIP_SHA256 = "5effe9bcca896660f44a5e50c348ab4ebf7550ff3c764ef77f06d775f0c010f5"
FIELD = "Flooding_Category"
SOURCE_CRS = "EPSG:2263"
GRID_CRS = "EPSG:26918"
DEPTH_CODES = (1, 2)
TIDAL_CODE = 3
CODES = (*DEPTH_CODES, TIDAL_CODE)


class UnreadableMap(RuntimeError):
    """A flood-map source that cannot be read; never turned into an empty map."""


def _open_error(path: str, detail: str) -> UnreadableMap:
    return UnreadableMap(
        f"cannot read the flood map at {path}: {detail}. (The Limited Flood geodatabase is stored "
        "in ESRI's Compressed Data Format, which GDAL's open driver cannot read: pass an "
        "exported copy, for example a GeoPackage, instead.)"
    )


def read_polygons(path: str | Path, layer: str | None = None) -> list[tuple[int, BaseGeometry]]:
    """The (code, polygon) rows of one scenario, in EPSG:2263, Z dropped, in file order.

    Rule: ``path`` is anything pyogrio opens (a ``.gdb`` folder, a GeoPackage, a ``/vsizip/``
    path). With no ``layer`` the source must hold exactly one. The layer must be in EPSG:2263
    and carry ``Flooding_Category`` with codes 1, 2 or 3 only. A source that does not open, lists
    no layer, or warns that a table is in a format the driver cannot handle raises
    ``UnreadableMap``; a wrong CRS, a missing field, an empty or unknown code raises ``ValueError``.
    """
    path = str(path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            layers = pyogrio.list_layers(path)
        except Exception as error:  # pyogrio raises DataSourceError and others
            raise _open_error(path, f"{type(error).__name__}: {error}") from error
        unhandled = [str(w.message) for w in caught if "unhandled" in str(w.message)]
        if unhandled:
            raise _open_error(path, unhandled[0])
        if len(layers) == 0:
            raise _open_error(path, "the source lists no layer")
        names = [str(name) for name, _ in layers]
        if layer is None:
            if len(names) != 1:
                raise ValueError(f"{path} holds {len(names)} layers, name one of {names}")
            layer = names[0]
        elif layer not in names:
            raise ValueError(f"{path} has no layer {layer!r}; it has {names}")
        try:
            meta, _, geometry, fields = pyogrio.raw.read(path, layer=layer, columns=[FIELD])
        except Exception as error:
            raise _open_error(path, f"{type(error).__name__}: {error}") from error
        unhandled = [str(w.message) for w in caught if "unhandled" in str(w.message)]
        if unhandled:
            raise _open_error(path, unhandled[0])
    if meta["crs"] != SOURCE_CRS:
        raise ValueError(f"{path} layer {layer!r} is in {meta['crs']}, expected {SOURCE_CRS}")
    if FIELD not in list(meta["fields"]):
        raise ValueError(f"{path} layer {layer!r} has no field {FIELD}: {list(meta['fields'])}")
    codes = fields[list(meta["fields"]).index(FIELD)]
    rows: list[tuple[int, BaseGeometry]] = []
    for code, wkb in zip(codes, geometry, strict=True):
        if code is None or (isinstance(code, float) and np.isnan(code)):
            raise ValueError(f"{path}: a row has no {FIELD}")
        if int(code) not in CODES:
            raise ValueError(f"{path}: unknown {FIELD} {code}, expected one of {CODES}")
        if wkb is None:
            raise ValueError(f"{path}: a row with {FIELD} {code} has no geometry")
        rows.append((int(code), shapely.force_2d(shapely.from_wkb(wkb))))
    return rows


def to_grid(geom: BaseGeometry) -> BaseGeometry:
    """A geometry moved from EPSG:2263 to EPSG:26918, whose metres are the project grid's."""
    transformer = pyproj.Transformer.from_crs(SOURCE_CRS, GRID_CRS, always_xy=True)

    def _move(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, _move)


def transformation() -> str:
    """The operation PROJ uses for EPSG:2263 to EPSG:26918 (both NAD83: no datum shift)."""
    transformer = pyproj.Transformer.from_crs(SOURCE_CRS, GRID_CRS, always_xy=True)
    return f"{transformer.description} | {transformer.definition}"


def cell_centres(grid: domain.Grid) -> tuple[np.ndarray, np.ndarray]:
    """Centres, arrays of shape (height, width).

    x = west + (col + 0.5) cell, y = north - (row + 0.5) cell.
    """
    x = grid.west + (np.arange(grid.width) + 0.5) * grid.cell
    y = grid.north - (np.arange(grid.height) + 0.5) * grid.cell
    return np.meshgrid(x, y)


def classes_on_grid(
    path: str | Path, grid: domain.Grid = domain.GRID, layer: str | None = None
) -> dict[str, Any]:
    """Depth classes, the tidal mask and the area per code of one scenario on ``grid``.

    Rules:

    * a cell is 2 where its centre is inside a code-2 polygon, else 1 where it is inside a code-1
      polygon, else 0 (``depth_class``, uint8, row 0 at the north);
    * ``tidal`` is True where the centre is inside a code-3 polygon; a cell may be tidal and in a
      depth class at once, and ``tidal_and_depth_cells`` counts those;
    * "inside" is shapely's ``contains``: a centre exactly on a polygon's edge is outside;
    * ``area_m2`` is, for each code present in the layer, the area of its polygons cut to the
      grid's extent, in square metres on the project grid (overlapping rows of one code are
      united first, so no area is counted twice).
    """
    rows = read_polygons(path, layer)
    square = shapely.box(grid.west, grid.south, grid.east, grid.north)
    xs, ys = cell_centres(grid)
    inside: dict[int, np.ndarray] = {}
    area: dict[int, float] = {}
    for code in sorted({code for code, _ in rows}):
        # each row is cut to the square before rows of one code are united: a row is citywide
        parts = [shapely.intersection(to_grid(geom), square) for c, geom in rows if c == code]
        clipped = parts[0] if len(parts) == 1 else shapely.union_all(parts)
        area[code] = float(clipped.area)
        shapely.prepare(clipped)
        inside[code] = shapely.contains_xy(clipped, xs, ys)
    none = np.zeros((grid.height, grid.width), dtype=bool)
    in1, in2, tidal = (inside.get(code, none) for code in CODES)
    depth = np.zeros((grid.height, grid.width), dtype=np.uint8)
    depth[in1] = 1
    depth[in2] = 2
    return {
        "depth_class": depth,
        "tidal": tidal.copy(),
        "area_m2": area,
        "codes": sorted(area),
        "polygons": len(rows),
        "cells": {
            "class_1": int((depth == 1).sum()),
            "class_2": int((depth == 2).sum()),
            "tidal": int(tidal.sum()),
            "tidal_and_depth_cells": int((tidal & (depth > 0)).sum()),
            "code_1_and_code_2": int((in1 & in2).sum()),
        },
        "tidal_and_depth_cells": int((tidal & (depth > 0)).sum()),
    }


def zip_path(zip_file: Path, scenario: str) -> str:
    """The ``/vsizip/`` path of a scenario's geodatabase inside the publisher's zip.

    The folder is found by the scenario's name and must hold exactly one ``.gdb``: the inner
    names are not uniform (the 2050 one lacks the word "inches").
    """
    folder = f"NYC Stormwater Flood Map - {SCENARIO_FOLDERS[scenario]}/"
    with zipfile.ZipFile(zip_file) as archive:
        found = sorted(
            {
                name.split(".gdb/")[0] + ".gdb"
                for name in archive.namelist()
                if folder in name and ".gdb/" in name
            }
        )
    if len(found) != 1:
        raise UnreadableMap(f"{zip_file}: {len(found)} geodatabases for {scenario}: {found}")
    return f"/vsizip/{zip_file}/{found[0]}"


def main() -> None:  # pragma: no cover - run on the real files by hand
    from . import peak_memory_bytes, scratch_dir, write_atomic, write_json

    root = cache.root()
    zip_file = root / "nyc-stormwater-flood-maps" / ZIP_NAME
    out = scratch_dir() / "nyc-flood-maps"
    summary: dict[str, Any] = {
        "input": str(zip_file),
        "grid": [domain.GRID.west, domain.GRID.south, domain.GRID.east, domain.GRID.north],
        "cell": domain.GRID.cell,
        "transformation": transformation(),
        "scenarios": {},
    }
    for scenario in SCENARIOS:
        start = time.perf_counter()
        try:
            result = classes_on_grid(zip_path(zip_file, scenario))
        except UnreadableMap as error:
            summary["scenarios"][scenario] = {"unreadable": str(error)}
            print(f"{scenario}: unreadable: {error}")
            continue
        seconds = time.perf_counter() - start

        def _save(tmp: Path, result: dict[str, Any] = result) -> None:
            with tmp.open("wb") as handle:
                np.savez_compressed(
                    handle, depth_class=result["depth_class"], tidal=result["tidal"]
                )

        write_atomic(out / f"{scenario}.npz", _save)
        summary["scenarios"][scenario] = {
            "codes": result["codes"],
            "polygons": result["polygons"],
            "cells": result["cells"],
            "area_m2": {str(k): v for k, v in result["area_m2"].items()},
            "seconds": round(seconds, 2),
        }
        print(scenario, summary["scenarios"][scenario])
    summary["peak_memory_bytes"] = peak_memory_bytes()
    write_json(out / "summary.json", summary)


if __name__ == "__main__":  # pragma: no cover
    main()
