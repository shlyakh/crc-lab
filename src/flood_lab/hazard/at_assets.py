"""F3: modelled depth at the assets, from a run's peak water level (lead-asset rule, demo plan §4).

Depth at a 1 m pixel is the peak water level of the 5 m cell that holds it less the model terrain
at that pixel (``f3/model/dem_model_1m.tif``: buildings raised as obstacles), floored at 0. A pixel
on a roof therefore reads 0 unless water stands above the roof; the depth reported for an outline
is that of the ground inside it that is not under a footprint.

* **Cells mostly under roofs are not read.** In a 5 m cell that is mostly footprint, the rain of
  the whole cell lands on its sliver of ground and the cell's level can rise far above what stands
  in the street (F3 found up to 4 m at the 99th percentile in cells over three quarters roofed).
  Pixels in cells at least ``MAX_ROOF_SHARE`` under footprints are left out of every figure here.
* **Substation site**: every outline of one asset (``LocNumber``) of ``substations.geojson`` that
  was kept at the F1 review; an outline drawn as an open line is read as a 1 m band around it.
  Reported: the depth exceeded on ``LEAD_AREA_M2`` of the site's open ground (the measure of the
  lead-asset rule; one deepest pixel is too easily a lidar artefact or a pit), the deepest pixel,
  the 95th percentile, and the area wet to 0.05 m and to 0.3 m.
* **Building**: the deepest pixel in a band ``BAND_M`` wide around its footprint, outside it; the
  water at its walls. Standard F3 output for the count of buildings wet in a storm; F6 reads
  depth at each building against its own first-floor height.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flood_lab.domain import GRID, TERRAIN_MARGIN_M

#: threshold of the lead-asset rule, metres [P] (demo-concerns §2, not yet confirmed by Yuri)
LEAD_DEPTH_M = 0.3
#: the lead-asset rule reads the depth exceeded on this much open ground, m2 [P] (one cell)
LEAD_AREA_M2 = 25
WET_M = 0.05
BAND_M = 2.0
#: pixels in cells at least this share under footprints are not read [P]
MAX_ROOF_SHARE = 0.5


def _read(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        return src.read(1), src.transform


def pixel_depth(zsmax_5m: np.ndarray, dem_1m: np.ndarray) -> np.ndarray:
    """Depth on the 1 m pixels of the square (rows from the north), floored at 0."""
    off = int(round(TERRAIN_MARGIN_M))
    k = int(round(GRID.cell))
    z = dem_1m[off : off + GRID.height * k, off : off + GRID.width * k].astype("float64")
    level = np.repeat(np.repeat(zsmax_5m.astype("float64"), k, axis=0), k, axis=1)
    d = level - z
    return np.where(np.isfinite(d), np.maximum(d, 0.0), 0.0)


def _square_transform():
    from rasterio.transform import from_origin

    return from_origin(GRID.west, GRID.north, 1.0, 1.0)


def _rasterize(geoms, shape) -> np.ndarray:
    from rasterio import features

    return features.rasterize(
        ((g, 1) for g in geoms), out_shape=shape, transform=_square_transform(), dtype="uint8"
    ).astype(bool)


def substation_depths(
    depth_1m: np.ndarray, buildings_1m: np.ndarray, substations: Path
) -> list[dict]:
    import geopandas as gpd

    gdf = gpd.read_file(substations).to_crs("EPSG:32618")
    gdf = gdf[gdf["reviewed"].astype(str).str.startswith("kept")]
    out = []
    for loc, group in gdf.groupby("LocNumber", sort=True):
        geoms = [g if g.geom_type == "Polygon" else g.buffer(1.0) for g in group.geometry]
        inside = _rasterize(geoms, depth_1m.shape)
        ground = inside & ~buildings_1m & np.isfinite(depth_1m)
        d = np.sort(depth_1m[ground])[::-1] if ground.any() else np.array([0.0])
        lead = float(d[min(LEAD_AREA_M2, len(d)) - 1])
        out.append(
            {
                "LocNumber": loc,
                "name": next((n for n in group["name"] if isinstance(n, str) and n), "(no name)"),
                "pixels": int(inside.sum()),
                "open_ground_pixels_read": int(ground.sum()),
                "depth_on_25m2_m": round(lead, 3),
                "max_depth_m": round(float(d.max()), 3),
                "p95_depth_m": round(float(np.percentile(d, 95)), 3),
                "area_wet_005_m2": int((d >= WET_M).sum()),
                "area_wet_030_m2": int((d >= LEAD_DEPTH_M).sum()),
                "meets_lead_rule": bool(lead >= LEAD_DEPTH_M),
            }
        )
    return out


def building_wall_depths(depth_1m: np.ndarray, buildings_1m: np.ndarray, footprints) -> np.ndarray:
    """Deepest pixel in a band around each footprint, outside every footprint (one per row)."""
    from rasterio import features

    shape = depth_1m.shape
    bands = [g.buffer(BAND_M).difference(g) for g in footprints.geometry]
    labels = features.rasterize(
        ((b, i + 1) for i, b in enumerate(bands) if not b.is_empty),
        out_shape=shape,
        transform=_square_transform(),
        dtype="int32",
    )
    # rasterize keeps the last band where bands overlap; a shared band takes one owner, which
    # undercounts a little for touching buildings (rows share the street in front of them)
    labels = np.where(buildings_1m | ~np.isfinite(depth_1m), 0, labels)
    best = np.zeros(len(bands) + 1)
    np.maximum.at(best, labels.ravel(), np.nan_to_num(depth_1m, nan=0.0).ravel())
    return best[1:]


def run_assets(run: Path, cache: Path, site: Path, footprints=None) -> dict:
    zsmax, _ = _read(run / "zsmax.tif")
    dem, _ = _read(cache / "f3" / "model" / "dem_model_1m.tif")
    bld, _ = _read(cache / "f3" / "model" / "buildings_1m.tif")
    off = int(round(TERRAIN_MARGIN_M))
    k = int(round(GRID.cell))
    bld = bld[off : off + GRID.height * k, off : off + GRID.width * k].astype(bool)
    depth = pixel_depth(zsmax, dem)
    roofed = bld.reshape(GRID.height, k, GRID.width, k).mean(axis=(1, 3)) >= MAX_ROOF_SHARE
    depth[np.repeat(np.repeat(roofed, k, axis=0), k, axis=1)] = np.nan
    result = {"substations": substation_depths(depth, bld, site / "data" / "substations.geojson")}
    if footprints is not None:
        walls = building_wall_depths(depth, bld, footprints)
        result["buildings"] = {
            "count": int(len(walls)),
            "wet_005": int((walls >= WET_M).sum()),
            "wet_030": int((walls >= LEAD_DEPTH_M).sum()),
            "max_m": round(float(walls.max()), 3) if len(walls) else None,
        }
        result["_wall_depths"] = walls
    return result
