"""F4: the catalogue's depth frequency into CRC 1.0.0 by both routes of FH7, and read back.

* **Grid route**, ``Dataset.from_raster``: one GeoTIFF per probability on the project grid
  (EPSG:32618, 5 m). The probabilities are the non-exceedance ``1 - AEP`` of
  ``catalogue.AEPS``, the same set for every cell. Cells that are not read (mostly under roofs,
  or holding water from the start) are nodata; nodata is ``NODATA`` and never 0, so a dry cell
  (0 at every probability) is delivered. Every cell is made non-decreasing first (CRC-025-OWN):
  one decreasing pixel would fail the whole read.
* **Point route**, ``Dataset.from_quantiles``: per asset its own knots, the exact empirical
  distribution of the catalogue: ``(0, 0)``, the dry-year mass ``(p0, 0)``, then for each distinct
  wet depth ``d`` of the runs the knot ``(P(D <= d), d)``. Between knots CRC interpolates linearly
  in probability, so between two storms the depth is interpolated, not stepped (stated).

The read-back compares every delivered knot with what was written; FH7's pass rule asks that
they are equal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flood_lab.hazard import catalogue

NODATA = -9999.0
VARIABLE_ID = "flood-lab:depth-above-ground"


def variable() -> Any:
    from crc_framework import DepthAboveGround, LengthUnit
    from crc_sdk import Variable

    return Variable(VARIABLE_ID, measurement=DepthAboveGround(unit=LengthUnit.METRE))


def annual() -> Any:
    from crc_framework import Tail
    from crc_sdk import Probability

    return Probability.annual(tail=Tail.UPPER)


# --- grid route ---------------------------------------------------------------------------------


def grid_curves(depth: np.ndarray, w: np.ndarray, m: float) -> dict:
    """``depth`` (runs, rows, cols) with NaN where a cell is not read. Returns the curves at
    ``catalogue.AEPS`` (aeps, rows, cols; NaN where not read), the count of cells changed by the
    clean-up, and the count of runs wetting each cell."""
    runs, rows, cols = depth.shape
    flat = depth.reshape(runs, -1)
    read = np.isfinite(flat).all(axis=0)
    curves = np.full((len(catalogue.AEPS), flat.shape[1]), np.nan)
    sub = np.nan_to_num(flat[:, read])
    raw = catalogue.depth_at(sub, w, m)
    cleaned, changed = catalogue.make_non_decreasing(raw)
    curves[:, read] = cleaned
    wet_runs = np.zeros(flat.shape[1], int)
    wet_runs[read] = (sub >= catalogue.WET_M).sum(axis=0)
    return {
        "curves": curves.reshape(len(catalogue.AEPS), rows, cols),
        "cells_read": int(read.sum()),
        "cells_changed_by_clean_up": changed,
        "wet_runs": wet_runs.reshape(rows, cols),
    }


def write_rasters(curves: np.ndarray, folder: Path, west: float, north: float, cell: float):
    """One float32 GeoTIFF per non-exceedance probability; row 0 is north."""
    import rasterio
    from rasterio.transform import from_origin

    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for j, aep in enumerate(catalogue.AEPS):
        band = np.where(np.isfinite(curves[j]), curves[j], NODATA).astype("float32")
        path = folder / f"depth_aep_{aep:g}.tif"
        tmp = path.with_name(path.stem + ".tmp.tif")
        with rasterio.open(
            tmp,
            "w",
            driver="GTiff",
            height=band.shape[0],
            width=band.shape[1],
            count=1,
            dtype="float32",
            crs="EPSG:32618",
            transform=from_origin(west, north, cell, cell),
            nodata=NODATA,
            compress="deflate",
        ) as dst:
            dst.write(band, 1)
        tmp.replace(path)
        files[1.0 - aep] = path
    return files


def load_grid(files: dict[float, Path], curves: np.ndarray, west: float, north: float, cell: float):
    """``Dataset.from_raster`` and the read-back against ``curves`` (aeps, rows, cols)."""
    import pyproj
    import shapely
    from crc_sdk import Dataset

    result = Dataset.from_raster(
        dict(sorted(files.items())), variable=variable(), probability=annual()
    ).read()
    table = result.table
    to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    centres = shapely.centroid(shapely.from_wkb(table["geometry"].to_numpy(zero_copy_only=False)))
    x, y = to_utm.transform(shapely.get_x(centres), shapely.get_y(centres))
    col = ((np.asarray(x) - west) // cell).astype(int)
    row = ((north - np.asarray(y)) // cell).astype(int)
    probs_expected = np.array(sorted(files))
    largest, differ, prob_differ = 0.0, 0, 0
    for i, rec in enumerate(table["curve"].to_pylist()):
        q = rec["quantile_curve"]
        got = np.array(q["values"])
        want = curves[:, row[i], col[i]]  # AEPS fall, so 1 - AEP rises in the same order
        gap = float(np.max(np.abs(got - want)))
        largest = max(largest, gap)
        differ += gap > 1e-6
        prob_differ += not np.allclose(q["probabilities"], probs_expected, rtol=0, atol=1e-12)
    expected_cells = int(np.isfinite(curves[0]).sum())
    return {
        "call": "Dataset.from_raster",
        "cells_written": expected_cells,
        "cells_delivered": table.num_rows,
        "cells_differing": int(differ),
        "cells_with_other_probabilities": int(prob_differ),
        "largest_difference_m": largest,
        "report": str(getattr(result, "report", "")),
        "equal": differ == 0 and prob_differ == 0 and table.num_rows == expected_cells,
    }


# --- point route --------------------------------------------------------------------------------


def asset_knots(depth: np.ndarray, w: np.ndarray, m: float, wet: float = catalogue.WET_M):
    """Exact empirical knots of one asset: ``([0, p0, F(d1), ...], [0, 0, d1, ...])``.

    ``depth`` (runs,) with ``w`` summing to ``m``. Depths below ``wet`` count as 0. ``F(d)`` is the
    weighted share of runs with depth at most ``d``; the last knot is 1."""
    d = np.where(np.asarray(depth, float) >= wet, depth, 0.0)
    w = np.asarray(w, float)
    p0 = float(w[d == 0].sum() / m)
    probs, values = [0.0], [0.0]
    if p0 > 0:
        probs.append(p0)
        values.append(0.0)
    for v in np.unique(d[d > 0]):
        probs.append(float(w[d <= v].sum() / m))
        values.append(float(v))
    if probs[-1] < 1.0 - 1e-9:
        raise ValueError("weights do not sum to m")
    probs[-1] = 1.0
    return probs, values


def points_table(assets: list[dict], depth: np.ndarray, w: np.ndarray, m: float) -> dict:
    """``assets`` [{id, longitude, latitude}], ``depth`` (runs, assets) -> long table for CRC."""
    table: dict[str, list] = {
        k: [] for k in ("support_id", "longitude", "latitude", "probability", "value")
    }
    for j, a in enumerate(assets):
        probs, values = asset_knots(depth[:, j], w, m)
        for p, v in zip(probs, values, strict=True):
            table["support_id"].append(str(a["id"]))
            table["longitude"].append(float(a["longitude"]))
            table["latitude"].append(float(a["latitude"]))
            table["probability"].append(p)
            table["value"].append(v)
    return table


def load_points(table: dict) -> dict:
    """``Dataset.from_quantiles`` and the read-back against the table written."""
    from crc_sdk import Dataset

    rows = Dataset.from_quantiles(table, variable=variable(), probability=annual()).read().table
    want: dict[str, tuple[list, list]] = {}
    for s, p, v in zip(table["support_id"], table["probability"], table["value"], strict=True):
        want.setdefault(s, ([], []))
        want[s][0].append(p)
        want[s][1].append(v)
    largest, differ = 0.0, 0
    for s, rec in zip(rows["support_id"].to_pylist(), rows["curve"].to_pylist(), strict=True):
        q = rec["quantile_curve"]
        wp, wv = want[s]
        same_len = len(q["probabilities"]) == len(wp)
        gap = (
            max(
                float(np.max(np.abs(np.array(q["values"]) - wv))),
                float(np.max(np.abs(np.array(q["probabilities"]) - wp))),
            )
            if same_len
            else float("inf")
        )
        largest = max(largest, gap)
        differ += gap > 1e-9
    return {
        "call": "Dataset.from_quantiles",
        "assets_written": len(want),
        "assets_delivered": rows.num_rows,
        "assets_differing": int(differ),
        "largest_difference": largest,
        "equal": differ == 0 and rows.num_rows == len(want),
    }
