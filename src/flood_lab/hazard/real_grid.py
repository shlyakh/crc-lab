"""F1: the SFINCS grid and sub-grid tables on the real terrain, built with HydroMT-SFINCS (FH2).

Runs only in the builder's own environment (FG4), never in the project's, and no test imports it:

    uv run --no-project --python 3.12 --with "hydromt-sfincs==2.0.0" \
        --with "rasterio<1.5.2; sys_platform == 'darwin'" \
        python src/flood_lab/hazard/real_grid.py --cache <data/cache/flood>

Builds the model grid for the square (``domain.SQUARE``, copied below because this environment
cannot import the project) at ``domain.CELL_M``, its elevation and mask, and the sub-grid tables
from ``terrain/dem_1m.tif``, into ``terrain/sfincs_grid/``. No forcing, no boundary, no run.
Writes ``terrain/sfincs_grid/real_grid.json``: time taken (``seconds`` from the start of the
script, so it includes importing HydroMT; ``steps_s`` per step), peak memory of the process, files
with sizes, active cell count, versions, and a comparison of the tables' cell minimum and maximum
with ``terrain/dem_5m.tif``. If the build fails, the JSON says where and why.

As in the toy model (``toy_model.py``): HydroMT-SFINCS 2.0.0 requires an even count of sub-grid
pixels per cell, so the 5 m cell is read as 10 x 10 pixels of 0.5 m sampled from the 1 m terrain
(each 1 m pixel gives four). Roughness is uniform here, a placeholder [P]: roughness from land
cover is F3's work, and the sub-grid tables are built again then.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
import traceback
from importlib import metadata
from pathlib import Path

# --- copied from flood_lab.domain (the builder's environment cannot import the project) --------
EPSG = 32618
SQUARE = (585_500.0, 4_504_500.0, 589_500.0, 4_508_500.0)
CELL = 5.0
# --- placeholders [P] ---------------------------------------------------------------------------
SUBGRID_PIXELS = 10  # 0.5 m pixels per 5 m cell side, even as HydroMT-SFINCS 2.0.0 requires
NR_LEVELS = 10
MANNING = 0.03  # s m^-1/3, uniform, until F3 maps roughness from land cover
MASK_ZMIN = -50.0  # m: below the lowest terrain value, so every cell of the square is active


def _versions() -> dict[str, str]:
    names = ("hydromt-sfincs", "hydromt", "rasterio", "xarray", "numpy", "netCDF4", "xugrid")
    found = {"python": sys.version.split()[0]}
    for name in names:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "not installed"
    return found


def _peak_memory_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)  # macOS bytes, Linux KiB


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def build(cache: Path) -> dict:
    from hydromt_sfincs import SfincsModel

    dem = cache / "terrain" / "dem_1m.tif"
    out = cache / "terrain" / "sfincs_grid"
    out.mkdir(parents=True, exist_ok=True)
    west, south, east, north = SQUARE
    n = int(round((north - south) / CELL))
    m = int(round((east - west) / CELL))
    steps = {}
    t0 = time.perf_counter()
    sf = SfincsModel(root=str(out), mode="w+")
    sf.grid.create(x0=west, y0=south, dx=CELL, dy=CELL, nmax=n, mmax=m, rotation=0, epsg=EPSG)
    sf.elevation.create(elevation_list=[{"elevation": str(dem)}])
    sf.mask.create(zmin=MASK_ZMIN)
    steps["grid_elevation_mask_s"] = round(time.perf_counter() - t0, 1)
    t1 = time.perf_counter()
    sf.subgrid.create(
        elevation_list=[{"elevation": str(dem)}],
        nr_levels=NR_LEVELS,
        nr_subgrid_pixels=SUBGRID_PIXELS,
        manning_land=MANNING,
        manning_sea=MANNING,
    )
    steps["subgrid_s"] = round(time.perf_counter() - t1, 1)
    t2 = time.perf_counter()
    sf.write()
    steps["write_s"] = round(time.perf_counter() - t2, 1)
    mask = sf.grid.data["mask"].values if "mask" in sf.grid.data else None
    active = int((mask > 0).sum()) if mask is not None else None
    return {
        "cells": n * m,
        "active_cells": active,
        "grid": {"x0": west, "y0": south, "dx": CELL, "nmax": n, "mmax": m, "epsg": EPSG},
        "steps_s": steps,
    }


def compare(cache: Path) -> dict:
    """Sub-grid z_zmin and z_zmax against the minimum and maximum bands of terrain/dem_5m.tif.

    Both describe the same 5 m cells: ``dem_5m.tif`` from the 25 pixels of 1 m directly (row 0
    north), the sub-grid tables from HydroMT's 0.5 m resampling of the same terrain (one value per
    active cell, in the order of ``sfincs.ind``). All cells are active here, so the order is
    checked both ways and the one that fits is reported.
    """
    import numpy as np
    import rasterio
    import xarray as xr

    out = cache / "terrain" / "sfincs_grid"
    with xr.open_dataset(out / "sfincs_subgrid.nc") as ds:
        zmin = ds["z_zmin"].values
        zmax = ds["z_zmax"].values
    with rasterio.open(cache / "terrain" / "dem_5m.tif") as src:
        low, high = src.read(2)[::-1], src.read(3)[::-1]  # row 0 south, as SFINCS counts
    if zmin.size != low.size:
        return {"compared": False, "why": f"{zmin.size} sub-grid cells, {low.size} 5 m cells"}
    fits = {order: float(np.median(np.abs(zmin - low.ravel(order=order)))) for order in ("C", "F")}
    order = min(fits, key=fits.get)

    def summary(a, b) -> dict:
        d = a - b.ravel(order=order)
        p = np.percentile(d, [0, 1, 5, 50, 95, 99, 100])
        return {
            "percentiles_0_1_5_50_95_99_100_m": [round(float(v), 4) for v in p],
            "share_within_0.01_m": round(float(np.mean(np.abs(d) <= 0.01)), 4),
            "share_within_0.1_m": round(float(np.mean(np.abs(d) <= 0.1)), 4),
        }

    return {
        "compared": True,
        "order_that_fits": "column-major, row 0 south"
        if order == "F"
        else "row-major, row 0 south",
        "median_abs_difference_by_order_m": {k: round(v, 4) for k, v in fits.items()},
        "z_zmin_minus_dem5m_min": summary(zmin, low),
        "z_zmax_minus_dem5m_max": summary(zmax, high),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    out = args.cache / "terrain" / "sfincs_grid"
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result: dict = {
        "parameters": {
            "subgrid_pixels_per_cell": SUBGRID_PIXELS,
            "subgrid_pixel_m": CELL / SUBGRID_PIXELS,
            "nr_levels": NR_LEVELS,
            "manning_uniform": MANNING,
            "mask_zmin_m": MASK_ZMIN,
            "tags": "all placeholders [P]",
        },
        "builder": _versions(),
    }
    try:
        result |= build(args.cache)
        result["ok"] = True
    except Exception as error:  # the record must say exactly why
        result["ok"] = False
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()
    result["seconds"] = round(time.perf_counter() - started, 1)
    if result["ok"]:
        try:
            result["compare_with_dem_5m"] = compare(args.cache)
        except Exception as error:
            result["compare_with_dem_5m"] = {"compared": False, "why": f"{error!r}"}
    result["peak_memory_bytes"] = _peak_memory_bytes()
    result["files"] = {
        str(p.relative_to(out)): p.stat().st_size
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "real_grid.json"
    }
    result["total_bytes"] = sum(result["files"].values())
    _write_json(out / "real_grid.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "traceback"}, indent=1))
    if not result["ok"]:
        print(result["traceback"], file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
