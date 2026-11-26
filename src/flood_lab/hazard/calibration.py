"""F3: modelled depth on the project grid, and its comparison with the city's flood maps (FH3).

Reads what ``sfincs_model.py analyse`` leaves in a run folder (``zsmax.tif``, ``balance.json``)
and the model terrain of ``sfincs_model.py base``. Standard project environment; no CRC import.

**Depth at a cell** is the peak water level of the 5 m cell less the model terrain at the 1 m
pixel holding the cell's centre (pixel 2, 2 of its 5 x 5), floored at 0. That is the point the
city's map is read at (F2: a cell takes the class its centre lies in). A centre pixel inside a
building footprint stands on the raised roof, so such cells are left out of the comparison: the
city's maps leave buildings out too (5% of their wet land cells have a centre in a footprint,
against 34% of all land cells; measured in F3).

**Compared cells**: study-area land (Brooklyn in the square), centre not in a footprint, no pixel
in a filled pit, not water by F1's rule, and lowest level (the solver's ``zb``, exported once to
``f3/model/zb_5m.tif`` by ``sfincs_model.py export-zb``) not below the start water level: water
standing from the first second is not flooding. The blind review of F3 found that such cells caused
every monotonicity excess over 1 mm and some false alarms.

**Classes** as the city's maps: 1 for 4 in (0.1016 m) to 1 ft, 2 for 1 ft (0.3048 m) and over.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flood_lab.domain import GRID, TERRAIN_MARGIN_M, WET_M

SHALLOW_M = 0.1016
DEEP_M = 0.3048
#: the city maps of current sea level that the allowance is calibrated on (FH3)
CALIBRATION_MAPS = {"limited": "limited-current", "moderate": "moderate-current"}
#: intensities of the city's scenarios, inches per hour [S] (nyc-stormwater-flood-maps)
INTENSITY_IN_H = {"limited": 1.77, "moderate": 2.13, "extreme": 3.66}
MM_PER_IN = 25.4
#: the city's stated rule: flooded areas "of at least 0.25 contiguous acres" [S]
#: (nyc-stormwater-flood-maps; the dictionary says some smaller areas are present, so it is the
#: publisher's intent, not a property of the map). Applied to the model's wet cells before they
#: are compared, so that like is compared with like [P]
MIN_PATCH_M2 = 0.25 * 4046.8564224
#: cells touching at a corner are one patch [P]
PATCH_CONNECTIVITY = 8


def intensity_mm_h(scenario: str) -> float:
    return round(INTENSITY_IN_H[scenario] * MM_PER_IN, 3)


def classify(depth: np.ndarray) -> np.ndarray:
    out = np.zeros(depth.shape, dtype="uint8")
    out[depth >= SHALLOW_M] = 1
    out[depth >= DEEP_M] = 2
    return out


def min_patch_filter(
    model_class: np.ndarray, min_m2: float = MIN_PATCH_M2, where: np.ndarray | None = None
) -> np.ndarray:
    """Set to 0 every wet patch (class 1 or 2, connected) smaller than ``min_m2``. Only cells in
    ``where`` form patches; the others are set to 0 first, so the river, or water standing from the
    start, can never hold a small patch up by touching it."""
    if where is not None:
        model_class = np.where(where, model_class, 0).astype(model_class.dtype)
    from scipy import ndimage

    wet = model_class >= 1
    structure = np.ones((3, 3)) if PATCH_CONNECTIVITY == 8 else None
    labels, _ = ndimage.label(wet, structure=structure)
    sizes = np.bincount(labels.ravel()) * GRID.cell**2
    keep = sizes >= min_m2
    keep[0] = False
    return np.where(keep[labels], model_class, 0).astype(model_class.dtype)


def _read(path: Path) -> np.ndarray:
    import rasterio

    with rasterio.open(path) as src:
        return src.read(1)


def centre_pixels(raster_1m: np.ndarray) -> np.ndarray:
    """The 1 m pixel at each 5 m cell's centre, from a raster covering the square plus margin."""
    off = int(round(TERRAIN_MARGIN_M))
    k = int(round(GRID.cell))
    rows = off + np.arange(GRID.height) * k + k // 2
    cols = off + np.arange(GRID.width) * k + k // 2
    return raster_1m[np.ix_(rows, cols)]


def any_pixel(raster_1m: np.ndarray) -> np.ndarray:
    """True for a 5 m cell when any of its 1 m pixels is true (square plus margin as input)."""
    off = int(round(TERRAIN_MARGIN_M))
    k = int(round(GRID.cell))
    inner = raster_1m[off : off + GRID.height * k, off : off + GRID.width * k]
    return inner.reshape(GRID.height, k, GRID.width, k).any(axis=(1, 3))


#: the model's start water level (``zsini``), m NAVD88 [P]; a cell whose lowest level lies below it
#: holds water from the first second (slips, the river's edge) and is not compared: such water is
#: not flooding, and its level differs between runs by the rain that fell on it
START_LEVEL_M = 0.0


@dataclass
class Frame:
    """What every comparison needs, read once."""

    ground: np.ndarray  # model terrain at the cell centre pixel, m
    compared: np.ndarray  # bool, cells in the comparison
    land: np.ndarray  # bool, study-area land
    building: np.ndarray  # bool, centre pixel in a footprint
    pit: np.ndarray  # bool, any pixel of the cell in a filled pit
    standing: np.ndarray  # bool, the cell's lowest level is below the start water level

    @classmethod
    def load(cls, cache: Path, study_area: Path) -> Frame:
        import geopandas as gpd
        from rasterio import features
        from rasterio.transform import Affine

        model = cache / "f3" / "model"
        ground = centre_pixels(_read(model / "dem_model_1m.tif")).astype("float64")
        building = centre_pixels(_read(model / "buildings_1m.tif")).astype(bool)
        pit = any_pixel(_read(model / "pits_1m.tif").astype(bool))
        standing = _read(model / "zb_5m.tif") < START_LEVEL_M
        water = centre_pixels(_read(cache / "terrain" / "water_1m.tif")).astype(bool)
        sa = gpd.read_file(study_area).to_crs(GRID_CRS)
        land = features.rasterize(
            sa.geometry, out_shape=(GRID.height, GRID.width), transform=Affine(*GRID.transform)
        ).astype(bool)
        compared = land & ~building & ~pit & ~water & ~standing
        return cls(ground, compared, land, building, pit, standing)


GRID_CRS = "EPSG:32618"


def depth_at_centres(zsmax: np.ndarray, ground: np.ndarray) -> np.ndarray:
    d = zsmax - ground
    return np.where(np.isfinite(d), np.maximum(d, 0.0), 0.0)


def run_depth(run: Path, frame: Frame) -> np.ndarray:
    return depth_at_centres(_read(run / "zsmax.tif").astype("float64"), frame.ground)


def compare(model_class: np.ndarray, city_class: np.ndarray, where: np.ndarray) -> dict:
    """Areas per class and the critical success index, for 'wet' (class 1 or 2) and per class."""
    cell_ha = GRID.cell**2 / 1e4
    m, c = model_class[where], city_class[where]
    out: dict = {"cells_compared": int(where.sum())}
    for k, name in ((1, "shallow"), (2, "deep")):
        out[f"model_{name}_ha"] = round(float((m == k).sum()) * cell_ha, 3)
        out[f"city_{name}_ha"] = round(float((c == k).sum()) * cell_ha, 3)
    mw, cw = m >= 1, c >= 1
    hits, misses, false = int((mw & cw).sum()), int((~mw & cw).sum()), int((mw & ~cw).sum())
    out |= {
        "wet_hits": hits,
        "wet_misses": misses,
        "wet_false_alarms": false,
        "csi_wet": round(hits / (hits + misses + false), 4) if hits + misses + false else None,
        "same_class_share_of_city_wet": round(float((m[cw] == c[cw]).mean()), 4)
        if cw.any()
        else None,
    }
    for k, name in ((2, "deep"),):
        mk, ck = m == k, c == k
        h, mi, fa = int((mk & ck).sum()), int((~mk & ck).sum()), int((mk & ~ck).sum())
        out[f"csi_{name}"] = round(h / (h + mi + fa), 4) if h + mi + fa else None
    return out


def area_error(result: dict) -> float:
    """Calibration objective of FH3: squared log ratio of modelled to city area, both classes."""
    total = 0.0
    for name in ("shallow", "deep"):
        mod, city = result[f"model_{name}_ha"], result[f"city_{name}_ha"]
        total += float(np.log((mod + 0.01) / (city + 0.01)) ** 2)
    return total


def city_class(name: str) -> np.ndarray:
    from flood_lab.paths import SITE

    raw = _read(SITE / "data" / "city_flood_maps" / f"{name}.tif")
    return np.where((raw == 1) | (raw == 2), raw, 0).astype("uint8")


def summarise_run(
    run: Path, frame: Frame, scenario: str, extra_masks: dict[str, np.ndarray] | None = None
) -> dict:
    """Comparison of one run with the city map of its scenario: ``filtered`` (the model's wet
    patches under a quarter acre removed; what the calibration uses) and ``raw``; plus any
    sensitivity in ``extra_masks`` (cells to leave out), on the filtered classes."""
    depth = run_depth(run, frame)
    city = city_class(CALIBRATION_MAPS.get(scenario, scenario))
    raw = classify(depth)
    filtered = min_patch_filter(raw, where=frame.compared)
    result = {
        "filtered": compare(filtered, city, frame.compared),
        "raw": compare(raw, city, frame.compared),
    }
    for v in result.values():
        v["area_error"] = round(area_error(v), 4)
    for name, mask in (extra_masks or {}).items():
        r = compare(filtered, city, frame.compared & ~mask)
        r["area_error"] = round(area_error(r), 4)
        result[f"filtered_without_{name}"] = r
    result["balance"] = json.loads((run / "balance.json").read_text())
    return result


#: FH8 tolerance, set at the F0 stop: at lower rainfall no cell is deeper by more than this
MONOTONE_TOL_M = 0.001


def monotonicity(depth_low: np.ndarray, depth_high: np.ndarray, where: np.ndarray) -> dict:
    """FH8 on two runs that differ only in rainfall (``low`` has less): no cell deeper at the lower
    rainfall by more than 1 mm, and no cell wet to 0.05 m in either run deeper at all. Depth is the
    cell-centre depth of this module, on the cells in ``where``."""
    diff = depth_low - depth_high
    d, lo, hi = diff[where], depth_low[where], depth_high[where]
    wet = (lo >= WET_M) | (hi >= WET_M)
    over_tol = int((d > MONOTONE_TOL_M).sum())
    wet_deeper = int((d[wet] > 0).sum())
    return {
        "cells": int(where.sum()),
        "cells_deeper_at_lower_rain_by_over_1mm": over_tol,
        "wet_cells_deeper_at_lower_rain": wet_deeper,
        "max_excess_m": round(float(d.max()), 6) if d.size else None,
        "passed": over_tol == 0 and wet_deeper == 0,
    }
