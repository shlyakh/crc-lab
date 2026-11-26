"""Jamaica Bay Ida depth map (Kasaei et al. 2025, doi:10.17632/hs2zt6ngwd.1): overlap (FV3).

Transformation statement:

1. The shapefile set ``Ida_flood_map`` (``.shp``, ``.shx``, ``.dbf``, ``.prj``, ``.cpg``; files
   checked against the SHA-256 Mendeley gives, facts ``jamaica-bay-ida-depth-map``) is read with
   geopandas. Its geometries are points, one per map cell, in the ``.prj``'s CRS; they are
   projected to EPSG:32618.
2. **The unit of ``flood_dept``** is not stated in the metadata. It is inferred from the file:
   ``dem_m`` is stated in metres NAVD88; ``flood_dept`` is compared with ``water_elev − dem_m``
   row by row, and with the bounds of the four depth classes the metadata states in metres. The
   numbers behind the inference are returned, not only the conclusion.
3. **Overlap with the square.** Each point stands for a square cell whose side is the median
   distance to its nearest neighbour (the map's own spacing, measured, not assumed). Reported:
   points inside ``domain.SQUARE``, the area of the cells' union inside the square, and the
   shortest distance from any point to the square.

The map is a model product (about 50 m hydrodynamic grid interpolated on a 30 cm DEM), not an
observation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

FOLDER = "jamaica-bay-ida-depth-map"
STEM = "Ida_flood_map"
PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml")
#: depth class bounds stated in the metadata, metres: 0 <0.1, 1 0.1-0.3, 2 0.3-0.91, 3 >=0.91
CLASS_BOUNDS_M = (0.1, 0.3, 0.91)
#: a row agrees with water_elev - dem_m when within this, in the file's unit [P]
AGREE = 0.001


def points(folder: Path) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], str]:
    """Statement step 1: eastings, northings (EPSG:32618), the attributes, and the file's CRS."""
    import geopandas as gpd

    frame = gpd.read_file(folder / f"{STEM}.shp")
    crs = str(frame.crs)
    utm = frame.to_crs("EPSG:32618")
    attributes = {c: frame[c].to_numpy() for c in frame.columns if c != "geometry"}
    return utm.geometry.x.to_numpy(), utm.geometry.y.to_numpy(), attributes, crs


def depth_unit(attributes: dict[str, np.ndarray]) -> dict[str, Any]:
    """Statement step 2: the evidence on the unit of ``flood_dept``."""
    depth = attributes["flood_dept"].astype("float64")
    difference = attributes["water_elev"].astype("float64") - attributes["dem_m"].astype("float64")
    agree = np.abs(depth - difference) <= AGREE
    klass = attributes["class"].astype(int)
    lows = (0.0, *CLASS_BOUNDS_M)
    ranges = {}
    within = 0
    for k in range(4):
        sel = depth[klass == k]
        lo = lows[k]
        hi = CLASS_BOUNDS_M[k] if k < 3 else None
        inside = (sel >= lo - 1e-6) & (sel < hi + 1e-6 if hi is not None else True)
        within += int(np.count_nonzero(inside))
        ranges[str(k)] = {
            "rows": int(sel.size),
            "min": None if sel.size == 0 else round(float(sel.min()), 6),
            "max": None if sel.size == 0 else round(float(sel.max()), 6),
        }
    return {
        "rows": int(depth.size),
        "rows_equal_to_water_elev_minus_dem_m": int(np.count_nonzero(agree)),
        "tolerance": AGREE,
        "rows_off_equal_and_class_3": int(np.count_nonzero(~agree & (klass == 3))),
        "flood_dept_max": round(float(depth.max()), 6),
        "flood_dept_min": round(float(depth.min()), 6),
        "class_ranges": ranges,
        "rows_inside_their_class_bounds_in_m": within,
    }


def spacing(x: np.ndarray, y: np.ndarray) -> float:
    """Median distance from each point to its nearest neighbour, metres."""
    from scipy.spatial import cKDTree

    tree = cKDTree(np.c_[x, y])
    distance, _ = tree.query(np.c_[x, y], k=2)
    return float(np.median(distance[:, 1]))


def overlap(
    x: np.ndarray, y: np.ndarray, cell_m: float, square: tuple[float, float, float, float]
) -> dict[str, Any]:
    """Statement step 3 for points at ``x, y`` with cells of side ``cell_m``."""
    import shapely

    west, south, east, north = square
    inside = (x >= west) & (x < east) & (y >= south) & (y < north)
    dx = np.maximum.reduce([west - x, np.zeros_like(x), x - east])
    dy = np.maximum.reduce([south - y, np.zeros_like(y), y - north])
    distance = np.hypot(dx, dy)
    nearest = int(np.argmin(distance))
    half = cell_m / 2
    near = distance <= cell_m  # only cells this close can reach into the square
    cells = shapely.box(x[near] - half, y[near] - half, x[near] + half, y[near] + half)
    box = shapely.box(west, south, east, north)
    area = float(shapely.union_all(cells).intersection(box).area) if near.any() else 0.0
    return {
        "points": int(x.size),
        "points_inside": int(np.count_nonzero(inside)),
        "cell_m": round(cell_m, 2),
        "overlap_area_m2": round(area, 1),
        "square_area_m2": (east - west) * (north - south),
        "nearest_distance_m": round(float(distance[nearest]), 1),
        "nearest_point_easting_m": round(float(x[nearest]), 1),
        "nearest_point_northing_m": round(float(y[nearest]), 1),
    }
