"""F0 toy model for the SFINCS timing test, built with HydroMT-SFINCS (FH2), and its analysis.

Runs only in the builder's own environment (FG4), never in the project's:

    uv run --no-project --python 3.12 --with "hydromt-sfincs==2.0.0" \
        --with "rasterio<1.5.2; sys_platform == 'darwin'" \
        python src/flood_lab/hazard/toy_model.py build --side-km 1 --rain 50 --out <folder>
    ... python src/flood_lab/hazard/toy_model.py analyse <folder> [--compare-to <folder>]

Every value below is a made-up toy value, a placeholder [P]: the toy exists to time the solver
and to check that its water balance closes, not to describe a place.

The terrain: a 1 m GeoTIFF in EPSG:32618 with its south-west corner at (598000, 4500000); a plane
rising to the north, a street grid lowered below the blocks, closed bowls as depressions and a
little noise, all from a fixed seed. The south edge is a water-level boundary held below the
terrain. The model: 5 m cells, sub-grid tables from the 1 m terrain, uniform Manning roughness,
uniform rain as a time series, and SFINCS's spatially uniform constant infiltration ``qinf``
(mm/h) as the stand-in for sewers. A cross-section along the boundary measures what leaves.
"""

from __future__ import annotations

import argparse
import json
import os
from importlib import metadata
from pathlib import Path

import numpy as np

# --- toy values, all placeholders [P] ---------------------------------------------------------
SEED = 20261125
X0, Y0 = 598000.0, 4500000.0
EPSG = 32618
DEM_RES = 1.0  # m
CELL = 5.0  # m
Z_SOUTH = 2.0  # m, terrain at the south edge
SLOPE = 0.004  # m per m, rising to the north
STREET_PITCH = 100.0  # m, block plus street
STREET_WIDTH = 16.0  # m
STREET_DROP = 0.2  # m below the blocks
DEPRESSIONS_PER_KM2 = 3
DEPRESSION_DEPTH = (1.0, 1.5)  # m, range drawn from
DEPRESSION_SIGMA = (25.0, 40.0)  # m, range drawn from
NOISE = 0.01  # m, uniform +-
BOUNDARY_LEVEL = 1.0  # m, constant water level at the south boundary
MANNING = 0.03  # s m^-1/3, uniform
QINF = 10.0  # mm/h, constant infiltration standing in for sewers
RAIN_HOURS = 2.0
DRY_HOURS = 1.0
NR_LEVELS = 10
# HydroMT-SFINCS 2.0.0 requires an even count of sub-grid pixels per cell, so the 5 m cell is
# read as 10 x 10 pixels of 0.5 m sampled from the 1 m terrain (each 1 m pixel gives four).
SUBGRID_PIXELS = 10
DTHISOUT = 10.0  # s, cross-section output step used to integrate the outflow
DTMAPOUT = 3600.0  # s
TREF = "2026-01-01 00:00:00"
WET = 0.05  # m, requirements section 5 [P]


def terrain(side_m: float) -> tuple[np.ndarray, list[dict]]:
    """The 1 m terrain (rows from north to south, as in a GeoTIFF) and the depressions drawn."""
    rng = np.random.default_rng(SEED)
    n = int(round(side_m / DEM_RES))
    centres = (np.arange(n) + 0.5) * DEM_RES
    x = centres[None, :]
    y = centres[::-1][:, None]  # distance north of the south edge
    z = Z_SOUTH + SLOPE * y + np.zeros_like(x)
    street = (np.mod(x, STREET_PITCH) < STREET_WIDTH) | (np.mod(y, STREET_PITCH) < STREET_WIDTH)
    z = z - STREET_DROP * street
    count = int(round(DEPRESSIONS_PER_KM2 * (side_m / 1000.0) ** 2))
    bowls = []
    for _ in range(count):
        cx = rng.uniform(150.0, side_m - 150.0)
        cy = rng.uniform(250.0, side_m - 150.0)
        depth = rng.uniform(*DEPRESSION_DEPTH)
        sigma = rng.uniform(*DEPRESSION_SIGMA)
        z = z - depth * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma**2))
        bowls.append({"x": X0 + cx, "y": Y0 + cy, "depth_m": depth, "sigma_m": sigma})
    z = z + rng.uniform(-NOISE, NOISE, size=z.shape)
    return z.astype("float32"), bowls


def write_geotiff(z: np.ndarray, path: Path) -> None:
    import rasterio
    from rasterio.transform import from_origin

    n = z.shape[0]
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=n,
        width=z.shape[1],
        count=1,
        dtype="float32",
        crs=f"EPSG:{EPSG}",
        transform=from_origin(X0, Y0 + n * DEM_RES, DEM_RES, DEM_RES),
        nodata=-9999.0,
        compress="deflate",
        tiled=True,
    ) as dst:
        dst.write(z, 1)
    os.replace(tmp, path)


def build(side_km: float, rain: float, out: Path) -> None:
    import geopandas as gpd
    import pandas as pd
    from hydromt_sfincs import SfincsModel
    from shapely.geometry import LineString, box

    side_m = side_km * 1000.0
    out.mkdir(parents=True, exist_ok=True)
    dem_path = out / "terrain_1m.tif"
    z, bowls = terrain(side_m)
    write_geotiff(z, dem_path)

    sf = SfincsModel(root=str(out), mode="w+")
    t0 = pd.Timestamp(TREF)
    t1 = t0 + pd.Timedelta(hours=RAIN_HOURS + DRY_HOURS)
    sf.config.update(
        {
            "tref": t0.to_pydatetime(),
            "tstart": t0.to_pydatetime(),
            "tstop": t1.to_pydatetime(),
            "dtmapout": DTMAPOUT,
            "dtmaxout": (t1 - t0).total_seconds(),
            "dthisout": DTHISOUT,
            "storecumprcp": 1,
            "storezvolume": 1,  # writes subgrid_volume per map time
            "zsini": 0.0,
        }
    )
    ncell = int(round(side_m / CELL))
    sf.grid.create(x0=X0, y0=Y0, dx=CELL, dy=CELL, nmax=ncell, mmax=ncell, rotation=0, epsg=EPSG)
    sf.elevation.create(elevation_list=[{"elevation": str(dem_path)}])
    sf.mask.create(zmin=-100.0)
    south = gpd.GeoDataFrame(
        geometry=[box(X0 - 1, Y0 - 1, X0 + side_m + 1, Y0 + CELL - 1)], crs=f"EPSG:{EPSG}"
    )
    sf.mask.create_boundary(btype="waterlevel", include_polygon=south)
    sf.subgrid.create(
        elevation_list=[{"elevation": str(dem_path)}],
        nr_levels=NR_LEVELS,
        nr_subgrid_pixels=SUBGRID_PIXELS,
        manning_land=MANNING,
        manning_sea=MANNING,
    )
    sf.infiltration.create_uniform_constant(qinf=QINF)
    sf.config.set("qinf_zmin", -100.0)
    sf.water_level.create_boundary_points_from_mask(bnd_dist=min(500.0, side_m / 2))
    sf.water_level.create_timeseries(shape="constant", offset=BOUNDARY_LEVEL)
    rain_csv = out / "rain.csv"
    stop_rain = t0 + pd.Timedelta(hours=RAIN_HOURS)
    series = pd.Series(
        [rain, rain, 0.0, 0.0],
        index=[t0, stop_rain, stop_rain + pd.Timedelta(seconds=1), t1],
        name="precip",
    )
    series.index.name = "time"
    series.to_csv(rain_csv)
    sf.precipitation.create_uniform(timeseries=str(rain_csv))
    line = LineString([(X0, Y0 + CELL), (X0 + side_m, Y0 + CELL)])
    sf.cross_sections.set(
        gpd.GeoDataFrame({"name": ["south_boundary"]}, geometry=[line], crs=f"EPSG:{EPSG}")
    )
    sf.write()
    meta = {
        "side_km": side_km,
        "cells": ncell * ncell,
        "rain_mm_per_h": rain,
        "depressions": bowls,
        "parameters": {
            "seed": SEED,
            "x0": X0,
            "y0": Y0,
            "epsg": EPSG,
            "dem_res_m": DEM_RES,
            "cell_m": CELL,
            "z_south_m": Z_SOUTH,
            "slope": SLOPE,
            "street_pitch_m": STREET_PITCH,
            "street_width_m": STREET_WIDTH,
            "street_drop_m": STREET_DROP,
            "depressions_per_km2": DEPRESSIONS_PER_KM2,
            "depression_depth_m": list(DEPRESSION_DEPTH),
            "depression_sigma_m": list(DEPRESSION_SIGMA),
            "noise_m": NOISE,
            "boundary_level_m": BOUNDARY_LEVEL,
            "manning": MANNING,
            "qinf_mm_per_h": QINF,
            "rain_hours": RAIN_HOURS,
            "dry_hours": DRY_HOURS,
            "subgrid_levels": NR_LEVELS,
            "subgrid_pixels_per_cell": SUBGRID_PIXELS,
            "dthisout_s": DTHISOUT,
        },
        "builder": _versions(),
    }
    _write_json(out / "toy_model.json", meta)


def _versions() -> dict[str, str]:
    names = ("hydromt-sfincs", "hydromt", "rasterio", "xarray", "numpy", "netCDF4", "xugrid")
    found = {}
    for name in names:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "not installed"
    return found


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    os.replace(tmp, path)


def _cell_depth(folder: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """zsmax and depth on the 5 m grid (zsmax minus the cell's lowest sub-grid level), mask.

    With sub-grid tables the map file's ``zb`` is the cell's lowest sub-grid level; ``analyse``
    checks that against ``z_zmin`` of the sub-grid file.
    """
    import xarray as xr

    ds = xr.open_dataset(folder / "sfincs_map.nc")
    zsmax = ds["zsmax"].max("timemax").values  # (n, m), rows from south
    zb = ds["zb"].values
    depth = np.where(np.isfinite(zsmax), np.maximum(zsmax - zb, 0.0), 0.0)
    return zsmax, depth, ds["msk"].values


def analyse(folder: Path, compare_to: Path | None) -> None:
    import rasterio
    import xarray as xr

    meta = json.loads((folder / "toy_model.json").read_text())
    ds = xr.open_dataset(folder / "sfincs_map.nc")
    area = CELL * CELL
    msk = ds["msk"].values
    interior = msk == 1
    cumprcp = ds["cumprcp"].isel(timemax=-1).values
    cuminf = ds["cuminf"].isel(timemax=-1).values
    vol = ds["subgrid_volume"].values
    rain_m3 = float(np.nansum(cumprcp[interior]) * area)
    inf_m3 = float(np.nansum(cuminf[interior]) * area)
    stored_m3 = float(np.nansum(vol[-1][interior]) - np.nansum(vol[0][interior]))
    his = xr.open_dataset(folder / "sfincs_his.nc")
    q = his["crosssection_discharge"].values.reshape(len(his["time"]), -1)[:, 0]
    t = (his["time"].values - his["time"].values[0]) / np.timedelta64(1, "s")
    # discharge is positive in the direction of the line's left normal: to the north here
    out_m3 = float(-np.trapezoid(q, t))
    # the residual and its share are computed by flood_lab.checks.f0_solver_timing
    balance = {
        "rain_m3": rain_m3,
        "infiltrated_m3": inf_m3,
        "stored_m3": stored_m3,
        "out_m3": out_m3,
        "how": "interior cells (mask 1): rain = sum of cumprcp, infiltrated = sum of cuminf, "
        "stored = change of subgrid_volume from the first to the last map time; out = time "
        "integral (trapezoid, 10 s) of crosssection_discharge on the line between the boundary "
        "row and the first interior row",
    }

    zsmax, depth5, _ = _cell_depth(folder)
    z_zmin = xr.open_dataset(folder / "sfincs_subgrid.nc")["z_zmin"].values
    zb_is_zmin = bool(np.allclose(np.sort(ds["zb"].values[interior | (msk == 2)]), np.sort(z_zmin)))
    with rasterio.open(folder / "terrain_1m.tif") as src:
        dem = src.read(1)[::-1]  # rows from south, as in the map file
    k = int(round(CELL / DEM_RES))
    zs1 = np.repeat(np.repeat(np.nan_to_num(zsmax, nan=-1e9), k, axis=0), k, axis=1)
    depth1 = np.maximum(zs1 - dem, 0.0)
    n = dem.shape[0]
    centres = (np.arange(n) + 0.5) * DEM_RES
    xx, yy = np.meshgrid(centres, centres)
    near = np.zeros(dem.shape, bool)
    far = np.ones(dem.shape, bool)
    for bowl in meta["depressions"]:
        r2 = (xx - (bowl["x"] - X0)) ** 2 + (yy - (bowl["y"] - Y0)) ** 2
        near |= r2 < (0.5 * bowl["sigma_m"]) ** 2
        far &= r2 > (3 * bowl["sigma_m"]) ** 2
    far[: int(100 / DEM_RES)] = False  # leave out the strip by the boundary
    result = {
        "folder": folder.name,
        "side_km": meta["side_km"],
        "cells": meta["cells"],
        "rain_mm_per_h": meta["rain_mm_per_h"],
        "water_balance": balance,
        "depth": {
            "subgrid_1m_max_m": float(depth1.max()),
            "subgrid_1m_depressions_mean_m": float(depth1[near].mean()),
            "subgrid_1m_slope_mean_m": float(depth1[far].mean()),
            "subgrid_1m_slope_p95_m": float(np.percentile(depth1[far], 95)),
            "cell_5m_max_m": float(depth5[interior].max()),
            "zb_equals_subgrid_z_zmin": zb_is_zmin,
            "how": "1 m: zsmax of the 5 m cell minus the 1 m terrain, floored at 0; "
            "5 m: zsmax minus zb, the cell's lowest sub-grid level",
        },
        "map_vars": sorted(ds.data_vars),
        "his_vars": sorted(his.data_vars),
    }
    if meta["side_km"] <= 1.0:
        result["depth_5m_grid"] = {
            "x0": X0,
            "y0": Y0,
            "cell_m": CELL,
            "rows_from": "south",
            "values_mm": np.round(depth5 * 1000).astype(int).tolist(),
        }
    if compare_to is not None:
        _, other5, _ = _cell_depth(compare_to)
        diff = depth5 - other5
        result["compare_to"] = {
            "folder": compare_to.name,
            "rain_mm_per_h": json.loads((compare_to / "toy_model.json").read_text())[
                "rain_mm_per_h"
            ],
            "max_depth_minus_other_m": float(diff[interior].max()),
            "cells_deeper_than_other": int((diff[interior] > 0).sum()),
            "deeper_cells": [
                {
                    "row_from_south": int(i),
                    "col": int(j),
                    "depth_m": float(depth5[i, j]),
                    "other_depth_m": float(other5[i, j]),
                }
                for i, j in np.argwhere((diff > 0) & interior)
            ],
            "max_depth_minus_other_where_either_wet_m": float(
                diff[interior & ((depth5 >= WET) | (other5 >= WET))].max()
            ),
            "cells": int(interior.sum()),
        }
    result["builder"] = _versions()
    _write_json(folder / "analysis.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "depth_5m_grid"}, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--side-km", type=float, required=True)
    b.add_argument("--rain", type=float, required=True, help="mm/h for the first two hours")
    b.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("analyse")
    a.add_argument("folder", type=Path)
    a.add_argument("--compare-to", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(args.side_km, args.rain, args.out)
    else:
        analyse(args.folder, args.compare_to)


if __name__ == "__main__":
    main()
