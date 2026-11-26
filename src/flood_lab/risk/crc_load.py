"""F4: the catalogue's depth frequency into CRC 1.0.0 by both routes of FH7, and read back.

* **Grid route**, ``Dataset.from_raster``: one GeoTIFF per probability on the project grid
  (EPSG:32618, 5 m). The probabilities are the non-exceedance ``1 - AEP`` of
  ``catalogue.AEPS``, the same set for every cell. Cells that are not read (mostly under roofs,
  or holding water from the start) are nodata; nodata is ``NODATA`` and never 0, so a dry cell
  (0 at every probability) is delivered. Every cell is made non-decreasing first (CRC-025-OWN):
  one decreasing pixel would fail the whole read.
* **Point route**, ``Dataset.from_quantiles``: per asset its own knots, the exact empirical
  distribution of the catalogue as a step function (CH-23). CRC's ``QuantileCurve`` interpolates
  linearly in probability between knots, so each step is given as two knots with the same depth,
  at its two ends: depth ``d_k`` holds for non-exceedance ``u`` in ``[F(d_{k-1}), F(d_k))``, with
  ``F(d_0) = 0`` and the dry-year mass as the step at depth 0. The jump sits between
  ``F(d_k) - STEP_GAP`` and ``F(d_k)``, so at every probability more than ``STEP_GAP`` from a
  jump CRC reads exactly the catalogue's ``depth_at`` (ties included: at ``u = F(d_k)`` both give
  the next depth up).

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
STEP_GAP = 1e-9  # width of a jump between two steps of the point route (CH-23)


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
    """Empirical step function of one asset as knots for CRC (CH-23).

    ``depth`` (runs,) with ``w`` summing to ``m``. Depths below ``wet`` count as 0. The levels are
    0 (if any run is dry) and each distinct wet depth; ``F`` is the weighted share of runs at or
    below a level. Level ``k`` gives the knots ``(F_{k-1}, d_k)`` and ``(F_k - STEP_GAP, d_k)``
    (the last ends at ``(1, d_last)``), so CRC's linear interpolation reproduces the step."""
    d = np.where(np.asarray(depth, float) >= wet, depth, 0.0)
    w = np.asarray(w, float)
    levels = np.unique(d)
    cum = [float(w[d <= v].sum() / m) for v in levels]
    if cum[-1] < 1.0 - 1e-9:
        raise ValueError("weights do not sum to m")
    cum[-1] = 1.0
    probs, values, lo = [], [], 0.0
    for k, (v, hi) in enumerate(zip(levels, cum, strict=True)):
        end = hi if k == len(levels) - 1 else hi - STEP_GAP
        if end - lo <= STEP_GAP:
            raise ValueError("a step is not wider than STEP_GAP")
        probs += [lo, end]
        values += [float(v), float(v)]
        lo = hi
    return probs, values


def point_route_at(depth: np.ndarray, w: np.ndarray, m: float, aeps=catalogue.AEPS) -> np.ndarray:
    """What CRC reads from the point route at each AEP: ``QuantileCurve`` (the class
    ``from_quantiles`` delivers) on each asset's knots, at non-exceedance ``1 - aep``.
    ``depth`` (runs, assets) -> (len(aeps), assets), comparable with ``catalogue.depth_at``."""
    from crc_framework import QuantileCurve

    u = [1.0 - a for a in aeps]
    out = np.zeros((len(aeps), depth.shape[1]))
    for j in range(depth.shape[1]):
        curve = QuantileCurve(*asset_knots(depth[:, j], w, m))
        out[:, j] = [float(curve.quantile(x)) for x in u]
    return out


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
