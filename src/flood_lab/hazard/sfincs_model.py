"""F3: the SFINCS model of the study square on the real terrain (FH2), and the folder of each run.

Two parts with different environments (FG4):

* ``base`` needs HydroMT-SFINCS and runs only in the builder's environment::

      uv run --no-project --python 3.12 --with "hydromt-sfincs==2.0.0" \\
          --with "rasterio<1.5.2; sys_platform == 'darwin'" --with scipy \\
          python src/flood_lab/hazard/sfincs_model.py base --cache data/cache/flood

  It writes ``f3/model/dem_model_1m.tif`` (the terrain the solver sees) and the model folder
  ``f3/model/base/`` with grid, mask, boundaries, sub-grid tables and cross-sections, and
  ``f3/model/base/base.json`` (every choice with its tag, counts, versions, timings).

* ``run`` uses the standard library only (and numpy for nothing): it makes one run folder from
  the base by hard links (the 200 MB sub-grid file is not copied) and writes the run's own
  ``sfincs.inp`` and ``sfincs.precip``::

      python src/flood_lab/hazard/sfincs_model.py run --base <base> --out <folder> \\
          --qinf 20 --rain 44.958 --rain-h 1 --after-h 1

Model choices, each a placeholder [P] unless tagged otherwise, recorded in ``base.json``:

* **Terrain**: USGS 3DEP 1 m of F1 (``terrain/dem_1m.tif``). Two edits, both written to
  ``dem_model_1m.tif`` and never to the F1 file:
  - *Pits*: connected land pixels more than ``PIT_BELOW_M`` below datum that are not water are
    filled to the median of a ring around them, with their walls (connected pixels below datum
    within ``PIT_WALL_PX`` of them). F1 found three at the Navy Yard, probably dry
    docks drained when the lidar was flown. Unfilled, they would swallow the rain of their
    surroundings. Their cells are listed so results there can be left out.
  - *Buildings*: city footprints raised by ``BUILDING_RAISE_M`` as obstacles. Rain on a roof
    stays on the roof until the drainage allowance removes it, as roof drains feed the sewer.
* **Water** is what F1's rule says: pixels flattened to the lidar's water level outside every
  neighbourhood outline. In the model it is ordinary terrain, below the boundary level, so it
  fills at the start (``zsini``) and the river is a body of water at the boundary level.
* **Boundaries**: the square's edge is a water-level boundary where it crosses the river (cells
  whose lowest level is below ``WATER_ZB_M``) at ``BOUNDARY_LEVEL_M``, held constant, and an outflow
  boundary on land, where water may leave and none comes in. Water from outside the square
  cannot enter: a limit stated in the report.
* **Roughness**: Manning's n ``MANNING_LAND`` above datum and ``MANNING_SEA`` below, constants;
  roughness from land cover (FH2) is not done here, a proposal in the F3 report.
* **Drainage allowance**: SFINCS's uniform constant infiltration ``qinf`` (mm/h), which takes up
  to that rate from the water standing in a cell while any stands, during and after the rain.
  Cells whose lowest level is below ``WATER_ZB_M`` (the river and the slips) are not drained.
* **Water balance**: four cross-sections one cell inside the square's edges measure every flux
  through the boundary cells; ``storezvolume`` gives storage at each map time.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import time
import traceback
from importlib import metadata
from pathlib import Path

# --- copied from flood_lab.domain (the builder's environment cannot import the project) --------
EPSG = 32618
SQUARE = (585_500.0, 4_504_500.0, 589_500.0, 4_508_500.0)
CELL = 5.0
# --- model choices, placeholders [P] -----------------------------------------------------------
SUBGRID_PIXELS = 10  # 0.5 m pixels per 5 m cell side, even as HydroMT-SFINCS 2.0.0 requires
NR_LEVELS = 10
MANNING_LAND = 0.025  # s m^-1/3
MANNING_SEA = 0.02  # s m^-1/3
PIT_BELOW_M = -5.0  # land pixels below this (and not water) are pits
PIT_RING_PX = (2, 6)  # ring of pixels around a pit whose median is the fill level
PIT_WALL_PX = 15  # pixels beyond the pit that may be filled as its walls
PIT_WALL_BELOW_M = 0.0  # ... and only where they lie below datum, so quays are never raised
BUILDING_RAISE_M = 5.0
BOUNDARY_LEVEL_M = 0.0  # NAVD88, constant
WATER_ZB_M = -1.0  # a cell whose lowest level is below this is water: boundary type, no drainage
DTHISOUT = 10.0  # s, cross-section output step
DTMAPOUT = 1800.0  # s
TREF = "20260101 000000"
BASE_FILES = (
    "sfincs.dep",
    "sfincs.msk",
    "sfincs.ind",
    "sfincs_subgrid.nc",
    "sfincs.bnd",
    "sfincs.bzs",
    "sfincs.crs",
)


def _versions() -> dict[str, str]:
    names = ("hydromt-sfincs", "hydromt", "rasterio", "xarray", "numpy", "scipy", "geopandas")
    found = {"python": sys.version.split()[0]}
    for name in names:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "not installed"
    return found


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --- base model (builder environment) -----------------------------------------------------------


def model_terrain(cache: Path, out: Path) -> dict:
    """Write ``dem_model_1m.tif``: F1's terrain with pits filled and buildings raised."""
    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio import features
    from scipy import ndimage

    src_dem = cache / "terrain" / "dem_1m.tif"
    src_water = cache / "terrain" / "water_1m.tif"
    with rasterio.open(src_dem) as src:
        z = src.read(1).astype("float64")
        profile = src.profile
        transform = src.transform
    with rasterio.open(src_water) as src:
        water = src.read(1) > 0
    bare = z.copy()

    candidates = (~water) & (z < PIT_BELOW_M)
    labels, count = ndimage.label(candidates, structure=np.ones((3, 3)))
    pits = []
    inner, outer = PIT_RING_PX
    for k in range(1, count + 1):
        m = labels == k
        ring = (
            ndimage.binary_dilation(m, iterations=outer)
            & ~ndimage.binary_dilation(m, iterations=inner)
            & ~water
            & ~candidates
        )
        level = float(np.median(bare[ring]))
        # the pit and its walls: pixels below the ring level, connected to the pit and within
        # PIT_WALL_PX of it (a dock's walls are steep, so this stops at the quay and never
        # spreads over low ground nearby)
        near = ndimage.binary_dilation(m, iterations=PIT_WALL_PX)
        grown = ndimage.binary_propagation(
            m, mask=(bare < min(level, PIT_WALL_BELOW_M)) & ~water & near
        )
        rows, cols = np.where(grown)
        xs, ys = rasterio.transform.xy(
            transform, [rows.min(), rows.max()], [cols.min(), cols.max()]
        )
        pits.append(
            {
                "pixels_below_threshold": int(m.sum()),
                "pixels_filled": int(grown.sum()),
                "lowest_m": round(float(bare[m].min()), 3),
                "fill_level_m": round(level, 3),
                "ring_pixels": int(ring.sum()),
                "bbox_utm": [
                    round(min(xs), 1),
                    round(min(ys), 1),
                    round(max(xs), 1),
                    round(max(ys), 1),
                ],
            }
        )
        z[grown] = level
    pit_mask = z != bare

    fp = gpd.read_file(cache / "nyc-building-footprints" / "footprints-box.geojson").to_crs(EPSG)
    fp = fp[fp.geometry.notna() & ~fp.geometry.is_empty]
    bld = features.rasterize(
        ((g, 1) for g in fp.geometry), out_shape=z.shape, transform=transform, dtype="uint8"
    ).astype(bool)
    z[bld] += BUILDING_RAISE_M

    out.mkdir(parents=True, exist_ok=True)
    profile.update(dtype="float32", compress="deflate", tiled=True, predictor=3)
    dst_path = out / "dem_model_1m.tif"
    tmp = out / "dem_model_1m.tmp.tif"
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(z.astype("float32"), 1)
    os.replace(tmp, dst_path)
    for name, arr in (("buildings_1m.tif", bld), ("pits_1m.tif", pit_mask)):
        p = profile.copy()
        p.update(dtype="uint8", nodata=None, predictor=1)
        tmp = out / f"{name}.tmp"
        with rasterio.open(tmp, "w", **p) as dst:
            dst.write(arr.astype("uint8"), 1)
        os.replace(tmp, out / name)
    return {
        "source": str(src_dem.relative_to(cache)),
        "source_sha256": _sha256(src_dem),
        "written": str(dst_path.relative_to(cache)),
        "pits": pits,
        "footprints": int(len(fp)),
        "building_pixels": int(bld.sum()),
        "building_raise_m": BUILDING_RAISE_M,
    }


def _edge_lines():
    """Four cross-sections one cell inside the square, counter-clockwise, left normal inwards."""
    w, s, e, n = SQUARE
    c = CELL
    return {
        "south": [(w + c, s + c), (e - c, s + c)],
        "east": [(e - c, s + c), (e - c, n - c)],
        "north": [(e - c, n - c), (w + c, n - c)],
        "west": [(w + c, n - c), (w + c, s + c)],
    }


def base(cache: Path) -> dict:
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from hydromt_sfincs import SfincsModel
    from shapely.geometry import LineString

    model_dir = cache / "f3" / "model"
    out = model_dir / "base"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    steps = {}
    t = time.perf_counter()
    terrain = model_terrain(cache, model_dir)
    steps["terrain_s"] = round(time.perf_counter() - t, 1)
    dem = str(model_dir / "dem_model_1m.tif")

    west, south, east, north = SQUARE
    n = int(round((north - south) / CELL))
    m = int(round((east - west) / CELL))
    t = time.perf_counter()
    sf = SfincsModel(root=str(out), mode="w+")
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    t1 = t0 + pd.Timedelta(hours=2)
    sf.config.update(
        {
            "tref": t0.to_pydatetime(),
            "tstart": t0.to_pydatetime(),
            "tstop": t1.to_pydatetime(),
            "dtmapout": DTMAPOUT,
            "dtmaxout": (t1 - t0).total_seconds(),
            "dthisout": DTHISOUT,
            "storecumprcp": 1,
            "storezvolume": 1,
            "zsini": BOUNDARY_LEVEL_M,
        }
    )
    sf.grid.create(x0=west, y0=south, dx=CELL, dy=CELL, nmax=n, mmax=m, rotation=0, epsg=EPSG)
    sf.elevation.create(elevation_list=[{"elevation": dem}])
    sf.mask.create(zmin=-100.0)
    sf.mask.create_boundary(btype="waterlevel", zmax=WATER_ZB_M)
    sf.mask.create_boundary(btype="outflow", zmin=WATER_ZB_M)
    steps["grid_mask_s"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    sf.subgrid.create(
        elevation_list=[{"elevation": dem}],
        nr_levels=NR_LEVELS,
        nr_subgrid_pixels=SUBGRID_PIXELS,
        manning_land=MANNING_LAND,
        manning_sea=MANNING_SEA,
        rgh_lev_land=0.0,
    )
    steps["subgrid_s"] = round(time.perf_counter() - t, 1)
    sf.infiltration.create_uniform_constant(qinf=0.0)
    sf.config.set("qinf_zmin", WATER_ZB_M)
    sf.water_level.create_boundary_points_from_mask(bnd_dist=250.0)
    sf.water_level.create_timeseries(shape="constant", offset=BOUNDARY_LEVEL_M)
    lines = _edge_lines()
    sf.cross_sections.set(
        gpd.GeoDataFrame(
            {"name": list(lines)},
            geometry=[LineString(v) for v in lines.values()],
            crs=f"EPSG:{EPSG}",
        )
    )
    rain_csv = out / "rain_placeholder.csv"
    series = pd.Series([0.0, 0.0], index=[t0, t1], name="precip")
    series.index.name = "time"
    series.to_csv(rain_csv)
    sf.precipitation.create_uniform(timeseries=str(rain_csv))
    t = time.perf_counter()
    sf.write()
    steps["write_s"] = round(time.perf_counter() - t, 1)
    rain_csv.unlink()

    msk = sf.grid.data["mask"].values
    counts = {int(k): int(v) for k, v in zip(*np.unique(msk, return_counts=True), strict=True)}
    missing = [f for f in BASE_FILES if not (out / f).exists()]
    return {
        "terrain": terrain,
        "grid": {"x0": west, "y0": south, "dx": CELL, "nmax": n, "mmax": m, "epsg": EPSG},
        "mask_counts": {
            "inactive_0": counts.get(0, 0),
            "active_1": counts.get(1, 0),
            "waterlevel_2": counts.get(2, 0),
            "outflow_3": counts.get(3, 0),
        },
        "cross_sections": {k: [list(p) for p in v] for k, v in lines.items()},
        "steps_s": steps,
        "missing_base_files": missing,
        "inp": (out / "sfincs.inp").read_text(),
    }


# --- one run folder (standard library) ----------------------------------------------------------


def _parse_inp(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            found[k.strip()] = v.strip()
    return found


def _format_inp(values: dict[str, str]) -> str:
    return "".join(f"{k:<20} = {v}\n" for k, v in values.items())


def _hhmmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}{(s % 3600) // 60:02d}{s % 60:02d}"


def make_run(
    base_dir: Path,
    out: Path,
    qinf: float,
    rain_mm_h: float | None,
    rain_h: float,
    after_h: float,
    netampr: Path | None = None,
    level: float | None = None,
    extra: dict[str, str] | None = None,
    tref: str = TREF,
) -> dict:
    """A run folder: base files hard-linked, ``sfincs.inp`` and the rain written for this run.

    Uniform rain: ``rain_mm_h`` for ``rain_h`` hours from the start, then none for ``after_h``.
    Gridded rain: ``netampr`` is a SFINCS ``netamprfile`` already on the model's time axis; its
    length sets ``rain_h``.
    """
    if out.exists():
        raise FileExistsError(f"{out} exists; a run folder is never overwritten")
    out.mkdir(parents=True)
    for name in BASE_FILES:
        os.link(base_dir / name, out / name)
    values = _parse_inp((base_dir / "sfincs.inp").read_text())
    total = (rain_h + after_h) * 3600.0
    values["tref"] = tref
    values["tstart"] = tref
    values["tstop"] = _date_add(total, tref)
    values["dtmaxout"] = f"{total:.1f}"
    values["dtmapout"] = f"{DTMAPOUT:.1f}"
    values["qinf"] = f"{qinf}"
    values["qinf_zmin"] = f"{WATER_ZB_M}"
    if level is not None:
        values["zsini"] = f"{level}"
        lines = (base_dir / "sfincs.bzs").read_text().splitlines()
        npts = len(lines[0].split()) - 1
        (out / "sfincs.bzs").unlink()
        _write_text_atomic(
            out / "sfincs.bzs",
            "".join(
                f"{t:9.1f}" + "".join(f"{level:8.3f}" for _ in range(npts)) + "\n"
                for t in (0.0, total)
            ),
        )
    else:
        lines = (base_dir / "sfincs.bzs").read_text().splitlines()
        # the base time series ends at the base's tstop; rewrite it to cover the run
        npts = len(lines[0].split()) - 1
        lvl = float(lines[0].split()[1])
        (out / "sfincs.bzs").unlink()
        _write_text_atomic(
            out / "sfincs.bzs",
            "".join(
                f"{t:9.1f}" + "".join(f"{lvl:8.3f}" for _ in range(npts)) + "\n"
                for t in (0.0, total)
            ),
        )
    values.pop("prcfile", None)
    values.pop("netamprfile", None)
    if netampr is not None:
        shutil.copy2(netampr, out / "precip_2d.nc")
        values["netamprfile"] = "precip_2d.nc"
        values["dtwnd"] = "3600.0"
    else:
        r = float(rain_mm_h)
        stop = rain_h * 3600.0
        rows = [(0.0, r), (stop, r), (stop + 1.0, 0.0), (total, 0.0)]
        _write_text_atomic(out / "sfincs.precip", "".join(f"{t:9.1f} {v:9.3f}\n" for t, v in rows))
        values["prcfile"] = "sfincs.precip"
    values.update(extra or {})
    _write_text_atomic(out / "sfincs.inp", _format_inp(values))
    spec = {
        "base": str(base_dir),
        "qinf_mm_per_h": qinf,
        "rain": {"kind": "gridded", "file": str(netampr)}
        if netampr
        else {"kind": "uniform", "mm_per_h": rain_mm_h, "hours": rain_h},
        "after_h": after_h,
        "boundary_level_m": level if level is not None else BOUNDARY_LEVEL_M,
        "simulated_s": total,
        "tref": tref,
        "extra_inp": extra or {},
    }
    _write_json(out / "spec.json", spec)
    return spec


def _write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _date_add(seconds: float, tref: str = TREF) -> str:
    from datetime import datetime, timedelta

    t = datetime.strptime(tref, "%Y%m%d %H%M%S") + timedelta(seconds=seconds)
    return t.strftime("%Y%m%d %H%M%S")


def replay_forcing(mrms_nc: Path, out_nc: Path, tref: str, hours: int) -> dict:
    """SFINCS rain for a replay from the hourly radar file: HydroMT reprojects it to the model's
    projection (nearest pixel, the source's own ~1 km cells) and turns each hour's accumulation,
    stamped at the hour's end, into a rate over that hour (``time_label='right'``)."""
    import pandas as pd
    import xarray as xr
    from hydromt_sfincs import SfincsModel

    ds = xr.open_dataset(mrms_nc)
    da = ds["precip"].rename({"lat": "y", "lon": "x"}).sortby("y")
    # each file holds the hour ENDING at its stamp; label it at the hour's start and pass it as
    # time_label="left", so the first hour of the window is kept (HydroMT clips the data to the
    # model window before it shifts a right-labelled series, which drops the first hour)
    stamps = pd.to_datetime(da["time"].values)
    stamps = stamps.tz_localize(None) if stamps.tz is not None else stamps
    da = da.assign_coords(time=stamps - pd.Timedelta(hours=1))
    da = da.rio.write_crs("EPSG:4326") if hasattr(da, "rio") else da
    da.attrs["units"] = "mm"
    src = da.to_dataset(name="precip")
    src.raster.set_crs(4326)
    work = out_nc.parent / "_forcing_tmp"
    if work.exists():
        shutil.rmtree(work)
    sf = SfincsModel(root=str(work), mode="w+")
    t0 = pd.Timestamp(datetime_from(tref))
    t1 = t0 + pd.Timedelta(hours=hours)
    sf.config.update(
        {"tref": t0.to_pydatetime(), "tstart": t0.to_pydatetime(), "tstop": t1.to_pydatetime()}
    )
    west, south, east, north = SQUARE
    sf.grid.create(
        x0=west,
        y0=south,
        dx=CELL,
        dy=CELL,
        nmax=int((north - south) / CELL),
        mmax=int((east - west) / CELL),
        rotation=0,
        epsg=EPSG,
    )
    sf.precipitation.create(precip=src, cumulative_input=True, time_label="left")
    pr = sf.precipitation.data["precip_2d"]
    # an absolute path: HydroMT resolves a relative one against the model root, which is removed
    out_nc = out_nc.resolve()
    sf.precipitation.write(filename=str(out_nc))
    shutil.rmtree(work, ignore_errors=True)
    if not out_nc.exists():
        raise FileNotFoundError(f"HydroMT did not write {out_nc}")
    return {
        "source": str(mrms_nc),
        "source_sha256": _sha256(mrms_nc),
        "tref": tref,
        "hours": hours,
        "shape": list(pr.shape),
        "x_res_m": float(abs(pr["x"].values[1] - pr["x"].values[0])),
        "mean_rate_by_step_mm_h": [round(float(v), 3) for v in pr.mean(("x", "y")).values],
        "max_rate_mm_h": round(float(pr.max()), 3),
        "rule": "hour ending at the file stamp -> rate over [stamp - 1 h, stamp), held constant "
        "(SFINCS's default block rain); the end-of-hour stamp is not confirmed from a primary "
        "source (F3 report)",
    }


def datetime_from(tref: str):
    from datetime import datetime

    return datetime.strptime(tref, "%Y%m%d %H%M%S")


# --- what a finished run leaves (builder environment: xarray and netCDF4) ------------------------


def analyse(folder: Path) -> dict:
    """Write ``zsmax.tif`` (peak water level per 5 m cell, row 0 north, NaN where never wet) and
    ``balance.json`` (the run's water balance) from the solver's output files.

    Balance over the cells that are not boundary cells (mask 1): rain = sum of ``cumprcp``,
    drained = sum of ``cuminf``, stored = change of ``subgrid_volume`` from the first to the last
    map time, out = time integral (trapezoid) of the four edge cross-sections, each counted
    positive inwards. Residual = rain - drained - stored - out.
    """
    import numpy as np
    import rasterio
    import xarray as xr
    from rasterio.transform import from_origin

    area = CELL * CELL
    with xr.open_dataset(folder / "sfincs_map.nc") as ds:
        msk = ds["msk"].values
        interior = msk == 1
        cumprcp = ds["cumprcp"].isel(timemax=-1).values
        cuminf = ds["cuminf"].isel(timemax=-1).values if "cuminf" in ds else np.zeros_like(cumprcp)
        vol = ds["subgrid_volume"].values
        zsmax = ds["zsmax"].max("timemax").values  # rows from south
        zb = ds["zb"].values
        map_times = [str(t) for t in ds["time"].values]
    with xr.open_dataset(folder / "sfincs_his.nc") as his:
        q = his["crosssection_discharge"].values  # (time, sections)
        names = (
            [
                str(n.decode() if isinstance(n, bytes) else n).strip()
                for n in his["crosssection_name"].values
            ]
            if "crosssection_name" in his
            else None
        )
        t = (his["time"].values - his["time"].values[0]) / np.timedelta64(1, "s")
    q = q.reshape(len(t), -1)
    inward = [float(np.trapezoid(q[:, k], t)) for k in range(q.shape[1])]
    rain = float(np.nansum(cumprcp[interior]) * area)
    drained = float(np.nansum(cuminf[interior]) * area)
    stored = float(np.nansum(vol[-1][interior]) - np.nansum(vol[0][interior]))
    out = -float(sum(inward))
    residual = rain - drained - stored - out
    balance = {
        "rain_m3": rain,
        "drained_m3": drained,
        "stored_m3": stored,
        "out_m3": out,
        "inward_by_section_m3": dict(
            zip(names or [str(k) for k in range(len(inward))], inward, strict=True)
        ),
        "residual_m3": residual,
        "residual_share_of_rain": residual / rain if rain else None,
        "map_times": map_times,
        "how": analyse.__doc__.split("\n\n")[1].strip(),
    }
    n = zsmax.shape[0]
    peak = np.where(np.isfinite(zsmax) & (zsmax > zb), zsmax, np.nan)[::-1].astype("float32")
    west, _, _, north = SQUARE
    tmp = folder / "zsmax.tmp.tif"
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=n,
        width=zsmax.shape[1],
        count=1,
        dtype="float32",
        crs=f"EPSG:{EPSG}",
        transform=from_origin(west, north, CELL, CELL),
        nodata=float("nan"),
        compress="deflate",
    ) as dst:
        dst.write(peak, 1)
    os.replace(tmp, folder / "zsmax.tif")
    _write_json(folder / "balance.json", balance)
    return balance


def export_zb(run: Path, out: Path) -> None:
    """The solver's lowest level per cell (``zb`` of the map file), row 0 north, as a GeoTIFF."""
    import rasterio
    import xarray as xr
    from rasterio.transform import from_origin

    with xr.open_dataset(run / "sfincs_map.nc") as ds:
        zb = ds["zb"].values[::-1].astype("float32")
    west, _, _, north = SQUARE
    tmp = out.with_name(out.name + ".tmp")
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=zb.shape[0],
        width=zb.shape[1],
        count=1,
        dtype="float32",
        crs=f"EPSG:{EPSG}",
        transform=from_origin(west, north, CELL, CELL),
        compress="deflate",
    ) as dst:
        dst.write(zb, 1)
    os.replace(tmp, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("base")
    b.add_argument("--cache", type=Path, required=True)
    f = sub.add_parser("replay-forcing")
    f.add_argument("mrms", type=Path)
    f.add_argument("out", type=Path)
    f.add_argument("--tref", required=True, help="YYYYmmdd HHMMSS, UTC")
    f.add_argument("--hours", type=int, required=True)
    z = sub.add_parser("export-zb")
    z.add_argument("run", type=Path, help="any finished run folder of the base")
    z.add_argument("out", type=Path)
    a = sub.add_parser("analyse")
    a.add_argument("folder", type=Path)
    r = sub.add_parser("run")
    r.add_argument("--base", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--qinf", type=float, required=True)
    r.add_argument("--rain", type=float, help="mm/h, uniform")
    r.add_argument("--rain-h", type=float, default=1.0)
    r.add_argument("--after-h", type=float, default=1.0)
    r.add_argument("--netampr", type=Path)
    r.add_argument("--level", type=float)
    r.add_argument("--tref", default=TREF)
    args = parser.parse_args()
    if args.command == "replay-forcing":
        rec = replay_forcing(args.mrms, args.out, args.tref, args.hours)
        _write_json(args.out.with_suffix(".json"), rec)
        print(json.dumps(rec, indent=1))
        return
    if args.command == "export-zb":
        export_zb(args.run, args.out)
        return
    if args.command == "analyse":
        print(json.dumps(analyse(args.folder), indent=1))
        return
    if args.command == "run":
        spec = make_run(
            args.base,
            args.out,
            args.qinf,
            args.rain,
            args.rain_h,
            args.after_h,
            args.netampr,
            args.level,
            tref=args.tref,
        )
        print(json.dumps(spec))
        return
    started = time.perf_counter()
    out = args.cache / "f3" / "model" / "base"
    result: dict = {
        "parameters": {
            "subgrid_pixels_per_cell": SUBGRID_PIXELS,
            "nr_levels": NR_LEVELS,
            "manning_land": MANNING_LAND,
            "manning_sea": MANNING_SEA,
            "pit_below_m": PIT_BELOW_M,
            "pit_ring_px": list(PIT_RING_PX),
            "pit_wall_px": PIT_WALL_PX,
            "pit_wall_below_m": PIT_WALL_BELOW_M,
            "building_raise_m": BUILDING_RAISE_M,
            "boundary_level_m_navd88": BOUNDARY_LEVEL_M,
            "water_zb_m": WATER_ZB_M,
            "dthisout_s": DTHISOUT,
            "dtmapout_s": DTMAPOUT,
            "tags": "all placeholders [P]",
        },
        "builder": _versions(),
    }
    try:
        result |= base(args.cache)
        result["ok"] = not result["missing_base_files"]
    except Exception as error:
        result["ok"] = False
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()
    result["seconds"] = round(time.perf_counter() - started, 1)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["peak_memory_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "base.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("traceback", "inp")}, indent=1))
    if not result["ok"]:
        print(result.get("traceback", ""), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
