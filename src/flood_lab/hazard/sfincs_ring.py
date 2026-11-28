"""F4 sensitivity: F3's SFINCS model on the study square plus a 500 m ring, to measure run-on.

F3's model (``sfincs_model.py``) covers the 4 km square only. Its edge on land is an outflow
boundary: water may leave and none comes in, so run-on from the contributing area outside the
square is left out. This model is F3's in every choice (cell, sub-grid pixels and levels, Manning's
n, pit filling, buildings raised, water rule, boundary level, ``WATER_ZB_M``, output steps; all
taken from ``sfincs_model``, never retyped) on the 5 km extent of F1's terrain (``RING``: the
square plus ``domain.TERRAIN_MARGIN_M`` on every side). The outer edge carries F3's boundaries:
water level at ``BOUNDARY_LEVEL_M`` where it crosses the river, outflow on land. The flux across
the square's edges, now inside the model, is the run-on (inward) and the runoff leaving the square
(outward).

Builder's environment (as ``sfincs_model.py``)::

    B='uv run --no-project --python 3.12 --with hydromt-sfincs==2.0.0
       --with rasterio<1.5.2;sys_platform=="darwin" --with scipy python'
    $B src/flood_lab/hazard/sfincs_ring.py base --cache data/cache/flood
    $B src/flood_lab/hazard/sfincs_ring.py replay-forcing <mrms.nc> <out.nc> --tref .. --hours ..
    $B src/flood_lab/hazard/sfincs_ring.py rebuild-scenario <scenario.nc> <out.nc> --run-dir <rd>
    $B src/flood_lab/hazard/sfincs_ring.py scenario-forcing <rebuilt.nc> <out.nc>
    $B src/flood_lab/hazard/sfincs_ring.py analyse <run folder>

and, standard library only, ``queue`` (writes ``f4/ring/queue_ring.json``).

* **Cross-sections.** Outer: four lines one cell inside the outer edge, on the faces between the
  boundary cells and the first interior cells, as F3's (``outer_lines``); they give the water
  balance (continuity) of the whole model. Inner: lines ON the square's edges, which lie on cell
  faces of this grid (the square starts 100 cells in), so they measure the flux into the 800 x 800
  cells of F3's square exactly (``inner_lines``). Each inner edge is cut into ``SECTION_M`` pieces
  so that inflow on one part of an edge and outflow on another are not netted against each other:
  per piece, the positive part of the discharge series is integrated as inflow and the negative
  part as outflow. Netting inside a piece and inside a 10 s output step is not resolved, so the
  inflow and outflow are lower bounds of the gross fluxes; their difference is exact. Lines run
  counter-clockwise, as F3's, so discharge is positive into the enclosed area.
* **Analysis.** ``tools/flood/f3_batch.py`` runs ``sfincs_model.py analyse`` after the solver,
  which assumes the square's grid: it writes ``zsmax.tif`` with the square's origin and sums every
  cross-section into one outflow. ``analyse`` here must be run after it on each ring run; it
  rewrites ``zsmax.tif`` (1000 x 1000, the ring's origin) and ``balance.json`` (outer water
  balance, the square's water balance, inner-edge fluxes; ``"analysed_by": "sfincs_ring"``).
* **Rain.** Gridded rain is reprojected by HydroMT exactly as ``sfincs_model.replay_forcing``
  does, on the ring's grid. A RainyDay scenario file holds only the AORC cells that bound the
  square; ``rebuild_scenario`` cuts the parent storm of RainyDay's catalogue over the ring with the
  scenario's transposition shift and proves it equals the scenario file on the scenario's cells.
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
from contextlib import contextmanager
from pathlib import Path

try:  # the project's environment
    from flood_lab.hazard import sfincs_model as sm
except ImportError:  # the builder's environment cannot import the project
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sfincs_model as sm  # type: ignore[no-redef]

SQUARE = sm.SQUARE
CELL = sm.CELL
EPSG = sm.EPSG
MARGIN_M = 500.0  # = flood_lab.domain.TERRAIN_MARGIN_M (checked in the tests)
RING = (SQUARE[0] - MARGIN_M, SQUARE[1] - MARGIN_M, SQUARE[2] + MARGIN_M, SQUARE[3] + MARGIN_M)
#: length of one inner cross-section piece, m [P]
SECTION_M = 50.0
EDGES = ("south", "east", "north", "west")
RING_DIR = ("f4", "ring")
ANALYSED_BY = "sfincs_ring"
#: F3's mask (1 interior, 2 water level, 3 outflow), north-up on the square
F3_MASK = Path(__file__).resolve().parents[3] / "data/cache/flood/f3/model/base/gis/mask.tif"


# --- geometry (pure) -----------------------------------------------------------------------------


def grid_shape(bounds=RING, cell: float = CELL) -> tuple[int, int]:
    """(rows, columns) of a grid of ``cell`` over ``bounds`` (west, south, east, north)."""
    w, s, e, n = bounds
    return int(round((n - s) / cell)), int(round((e - w) / cell))


def square_window(outer=RING, inner=SQUARE, cell: float = CELL) -> tuple[slice, slice]:
    """Rows and columns of ``inner`` in a north-up raster of ``outer``; refuses a misaligned cut."""
    w, s, e, n = outer
    iw, i_s, ie, i_n = inner
    offs = [(n - i_n) / cell, (iw - w) / cell, (n - i_s) / cell, (ie - w) / cell]
    if any(abs(v - round(v)) > 1e-9 for v in offs):
        raise ValueError(f"{inner} does not lie on the {cell} m cells of {outer}")
    r0, c0, r1, c1 = (int(round(v)) for v in offs)
    rows, cols = grid_shape(outer, cell)
    if not (0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= cols):
        raise ValueError(f"{inner} is not inside {outer}")
    return slice(r0, r1), slice(c0, c1)


def _box_lines(w: float, s: float, e: float, n: float) -> dict[str, list[tuple[float, float]]]:
    """The four sides of a box, counter-clockwise (left normal inwards)."""
    return {
        "south": [(w, s), (e, s)],
        "east": [(e, s), (e, n)],
        "north": [(e, n), (w, n)],
        "west": [(w, n), (w, s)],
    }


def outer_lines(bounds=RING, cell: float = CELL) -> dict[str, list[tuple[float, float]]]:
    """F3's rule on the ring: one cell inside the model's edge, named ``out_<edge>``."""
    w, s, e, n = bounds
    lines = _box_lines(w + cell, s + cell, e - cell, n - cell)
    return {f"out_{k}": v for k, v in lines.items()}


def inner_lines(square=SQUARE, piece_m: float = SECTION_M) -> dict[str, list[tuple[float, float]]]:
    """The square's edges cut into ``piece_m`` pieces, counter-clockwise, ``in_<edge>_<k>``."""
    out = {}
    for edge, ((x0, y0), (x1, y1)) in _box_lines(*square).items():
        length = abs(x1 - x0) + abs(y1 - y0)
        k = length / piece_m
        if abs(k - round(k)) > 1e-9:
            raise ValueError(f"edge length {length} is not a multiple of {piece_m}")
        k = int(round(k))
        for i in range(k):
            a, b = i / k, (i + 1) / k
            out[f"in_{edge}_{i:03d}"] = [
                (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b),
            ]
    return out


def all_lines() -> dict[str, list[tuple[float, float]]]:
    return outer_lines() | inner_lines()


# --- fluxes (pure numpy) -------------------------------------------------------------------------


def split_integrals(q, t) -> tuple[list[float], list[float]]:
    """Per column of ``q`` (time, sections; m3/s, positive inwards): the trapezoid integrals of
    its positive part and of its negative part (as a positive number), m3. The parts are taken at
    the output times, so a sign change inside a step is split at the step's ends."""
    import numpy as np

    q = np.asarray(q, dtype="float64").reshape(len(t), -1)
    pos = np.trapezoid(np.maximum(q, 0.0), t, axis=0)
    neg = np.trapezoid(np.maximum(-q, 0.0), t, axis=0)
    return [float(v) for v in pos], [float(v) for v in neg]


def edge_fluxes(names: list[str], q, t) -> dict:
    """Inflow, outflow and net (m3) per inner edge and per outer section, from the cross-section
    series ``q`` (time, sections) named ``names``."""
    import numpy as np

    q = np.asarray(q, dtype="float64").reshape(len(t), -1)
    if q.shape[1] != len(names):
        raise ValueError(f"{q.shape[1]} series for {len(names)} names")
    pos, neg = split_integrals(q, t)
    net = [float(v) for v in np.trapezoid(q, t, axis=0)]
    inner: dict[str, dict] = {
        e: {"inflow_m3": 0.0, "outflow_m3": 0.0, "net_inward_m3": 0.0, "pieces": 0} for e in EDGES
    }
    outer: dict[str, float] = {}
    for k, name in enumerate(names):
        if name.startswith("in_"):
            row = inner[name.split("_")[1]]
            row["inflow_m3"] += pos[k]
            row["outflow_m3"] += neg[k]
            row["net_inward_m3"] += net[k]
            row["pieces"] += 1
        elif name.startswith("out_"):
            outer[name[4:]] = net[k]
        else:
            raise ValueError(f"cross-section {name!r} is neither inner nor outer")
    return {"inner": inner, "outer_inward_m3": outer}


# --- rain over the ring from RainyDay's catalogue (pure numpy) ----------------------------------


def index_range(coords, lo: float, hi: float, pad: int = 1) -> tuple[int, int]:
    """[i0, i1) of the cells of an ascending axis whose centres span [lo, hi], with ``pad``
    more cells on each side (so the reprojection has a source cell at every model cell)."""
    import numpy as np

    c = np.asarray(coords, dtype="float64")
    if not np.all(np.diff(c) > 0):
        raise ValueError("coordinates must ascend")
    i0 = int(np.searchsorted(c, lo, side="right")) - 1 - pad
    i1 = int(np.searchsorted(c, hi, side="left")) + 1 + pad
    if i0 < 0 or i1 > len(c):
        raise ValueError(f"[{lo}, {hi}] with {pad} cells of padding is outside the axis")
    return i0, i1


def cut_transposed(
    parent, shift_y: int, shift_x: int, rows: tuple[int, int], cols: tuple[int, int]
):
    """The parent storm's field (time, lat, lon) moved by RainyDay's transposition: the value at
    domain cell (r, c) is the parent's at (r - shift_y, c - shift_x). Returns the block
    ``rows`` x ``cols`` of the moved field; refuses a block whose source leaves the domain."""
    r0, r1 = rows[0] - shift_y, rows[1] - shift_y
    c0, c1 = cols[0] - shift_x, cols[1] - shift_x
    ny, nx = parent.shape[-2:]
    if r0 < 0 or c0 < 0 or r1 > ny or c1 > nx:
        raise ValueError("the transposed block reaches outside the parent storm's domain")
    return parent[..., r0:r1, c0:c1]


# --- base model (builder environment) -----------------------------------------------------------


def _write_raster(path: Path, arr, bounds, cell: float, dtype: str, nodata=None) -> None:
    import rasterio
    from rasterio.transform import from_origin

    tmp = path.with_name(path.name + ".tmp")
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype=dtype,
        crs=f"EPSG:{EPSG}",
        transform=from_origin(bounds[0], bounds[3], cell, cell),
        nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(arr.astype(dtype), 1)
    os.replace(tmp, path)


def _north_up(da):
    """A 2-D (y, x) DataArray as a numpy array with row 0 at the north."""
    import numpy as np

    v = da.values
    y = da[da.dims[0]].values
    return v[::-1] if len(y) > 1 and y[1] > y[0] else np.asarray(v)


def base(cache: Path) -> dict:
    """The ring's base model, F3's ``sfincs_model.base`` step by step on ``RING``."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import rasterio
    from hydromt_sfincs import SfincsModel
    from shapely.geometry import LineString

    model_dir = cache.joinpath(*RING_DIR, "model")
    out = model_dir / "base"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    steps = {}
    t = time.perf_counter()
    # F3's terrain function: it reads the whole of F1's 5 km terrain, so its output is the same
    terrain = sm.model_terrain(cache, model_dir)
    steps["terrain_s"] = round(time.perf_counter() - t, 1)
    dem = str(model_dir / "dem_model_1m.tif")
    with rasterio.open(dem) as a, rasterio.open(cache / "f3" / "model" / "dem_model_1m.tif") as b:
        same = a.shape == b.shape and a.transform == b.transform
        if same:
            same = bool(np.array_equal(a.read(1), b.read(1), equal_nan=True))
        terrain["bounds"] = list(a.bounds)
    terrain["identical_to_f3_dem_model_1m"] = same

    west, south, east, north = RING
    n, m = grid_shape(RING)
    t = time.perf_counter()
    sf = SfincsModel(root=str(out), mode="w+")
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    t1 = t0 + pd.Timedelta(hours=2)
    sf.config.update(
        {
            "tref": t0.to_pydatetime(),
            "tstart": t0.to_pydatetime(),
            "tstop": t1.to_pydatetime(),
            "dtmapout": sm.DTMAPOUT,
            "dtmaxout": (t1 - t0).total_seconds(),
            "dthisout": sm.DTHISOUT,
            "storecumprcp": 1,
            "storezvolume": 1,
            "zsini": sm.BOUNDARY_LEVEL_M,
        }
    )
    sf.grid.create(x0=west, y0=south, dx=CELL, dy=CELL, nmax=n, mmax=m, rotation=0, epsg=EPSG)
    sf.elevation.create(elevation_list=[{"elevation": dem}])
    sf.mask.create(zmin=-100.0)
    sf.mask.create_boundary(btype="waterlevel", zmax=sm.WATER_ZB_M)
    sf.mask.create_boundary(btype="outflow", zmin=sm.WATER_ZB_M)
    steps["grid_mask_s"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    sf.subgrid.create(
        elevation_list=[{"elevation": dem}],
        nr_levels=sm.NR_LEVELS,
        nr_subgrid_pixels=sm.SUBGRID_PIXELS,
        manning_land=sm.MANNING_LAND,
        manning_sea=sm.MANNING_SEA,
        rgh_lev_land=0.0,
    )
    steps["subgrid_s"] = round(time.perf_counter() - t, 1)
    sf.infiltration.create_uniform_constant(qinf=0.0)
    sf.config.set("qinf_zmin", sm.WATER_ZB_M)
    sf.water_level.create_boundary_points_from_mask(bnd_dist=250.0)
    sf.water_level.create_timeseries(shape="constant", offset=sm.BOUNDARY_LEVEL_M)
    lines = all_lines()
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

    msk = _north_up(sf.grid.data["mask"])
    zb = _north_up(sf.subgrid.data["z_zmin"]).astype("float32")
    _write_raster(model_dir / "zb_5m.tif", zb, RING, CELL, "float32")
    _write_raster(model_dir / "mask_5m.tif", msk, RING, CELL, "uint8")
    counts = {int(k): int(v) for k, v in zip(*np.unique(msk, return_counts=True), strict=True)}
    missing = [f for f in sm.BASE_FILES if not (out / f).exists()]
    rows, cols = square_window()
    inner_mask = msk[rows, cols]
    bnd = boundary_cells(msk, zb)
    return {
        "terrain": terrain,
        "grid": {"x0": west, "y0": south, "dx": CELL, "nmax": n, "mmax": m, "epsg": EPSG},
        "mask_counts": {
            "inactive_0": counts.get(0, 0),
            "active_1": counts.get(1, 0),
            "waterlevel_2": counts.get(2, 0),
            "outflow_3": counts.get(3, 0),
        },
        "boundary_cells_by_edge": bnd,
        "square_cells_in_model": {
            "rows_cols": [rows.start, rows.stop, cols.start, cols.stop],
            "all_interior": bool((inner_mask == 1).all()),
            "counts": {
                int(k): int(v)
                for k, v in zip(*np.unique(inner_mask, return_counts=True), strict=True)
            },
        },
        "cross_sections": {
            "outer": {k: [list(p) for p in v] for k, v in outer_lines().items()},
            "inner_piece_m": SECTION_M,
            "inner_pieces": len(inner_lines()),
            "inner_edges": {k: [list(p) for p in v] for k, v in sm_box_lines().items()},
        },
        "steps_s": steps,
        "missing_base_files": missing,
        "inp": (out / "sfincs.inp").read_text(),
    }


def sm_box_lines() -> dict[str, list[tuple[float, float]]]:
    return _box_lines(*SQUARE)


def boundary_cells(msk, zb) -> dict:
    """Boundary cells (mask 2 water level, 3 outflow) on each outer edge of a north-up mask; a
    corner cell is counted on both its edges. Also the lowest ``zb`` of the water-level cells."""

    sides = {"north": (0, slice(None)), "south": (-1, slice(None))}
    out = {}
    for name, (r, c) in sides.items():
        v = msk[r, c]
        out[name] = {"waterlevel_2": int((v == 2).sum()), "outflow_3": int((v == 3).sum())}
    for name, c in (("west", 0), ("east", -1)):
        v = msk[:, c]
        out[name] = {"waterlevel_2": int((v == 2).sum()), "outflow_3": int((v == 3).sum())}
    inner = msk[1:-1, 1:-1]
    out["not_on_edge"] = {
        "waterlevel_2": int((inner == 2).sum()),
        "outflow_3": int((inner == 3).sum()),
    }
    wl = msk == 2
    out["waterlevel_zb_m"] = (
        [round(float(zb[wl].min()), 3), round(float(zb[wl].max()), 3)] if wl.any() else None
    )
    out["rule"] = f"water level where zb < {sm.WATER_ZB_M} m, outflow elsewhere on the edge"
    return out


# --- rain (builder environment) -----------------------------------------------------------------


@contextmanager
def _extent(bounds):
    """``sfincs_model``'s rain functions read the module's ``SQUARE`` at call time: point it at
    ``bounds`` for the call (this process only; the file is not changed)."""
    old = sm.SQUARE
    sm.SQUARE = tuple(bounds)
    try:
        yield
    finally:
        sm.SQUARE = old


def replay_forcing(mrms_nc: Path, out_nc: Path, tref: str, hours: int) -> dict:
    with _extent(RING):
        rec = sm.replay_forcing(mrms_nc, out_nc, tref, hours)
    rec["extent"] = list(RING)
    return rec


def scenario_forcing(src_nc: Path, out_nc: Path, tref=None, hours=None) -> dict:
    """``sfincs_model.scenario_forcing`` on the ring (its check then reads the ring's bounds)."""
    with _extent(RING):
        rec = sm.scenario_forcing(src_nc, out_nc, tref, hours)
    rec["extent"] = list(RING)
    return rec


def extend_axis(centres, lo: float, hi: float, pad: int = 1):
    """A regular axis of pixel centres (ascending or descending) extended by whole pixels until
    the pixels cover [lo, hi] with ``pad`` pixels to spare on each side; returns (axis, before),
    where ``before`` is the number of pixels added in front."""
    import math

    import numpy as np

    c = np.asarray(centres, dtype="float64")
    d = np.diff(c)
    if len(c) < 2 or not np.allclose(d, d[0], rtol=0, atol=1e-6 * abs(d[0])):
        raise ValueError("the axis is not regular")
    step = float(d[0])
    a, b = (c[0], c[-1]) if step > 0 else (c[-1], c[0])
    h = abs(step)
    add_low = max(0, math.ceil((a - h / 2 - lo) / h)) + pad
    add_high = max(0, math.ceil((hi - (b + h / 2)) / h)) + pad
    before, after = (add_low, add_high) if step > 0 else (add_high, add_low)
    axis = c[0] + step * np.arange(-before, len(c) + after)
    return axis, before


def aligned_forcing(
    template_nc: Path,
    source_nc: Path,
    out_nc: Path,
    var: str,
    lat: str,
    lon: str,
    bounds=RING,
) -> dict:
    """The square run's own forcing file extended to cover the ring, on its own pixels.

    HydroMT's reprojection over a larger model chooses a different pixel grid (origin and size),
    so the rain on a square cell would differ between the two runs and mix with the run-on. Here
    every pixel of ``template_nc`` (the square run's ``netamprfile``) is kept as it is, and the
    pixels added around it take the source cell whose centre is nearest to theirs, at the same
    hour (``source_nc``: hourly rain stamped at the end of its hour, ``var`` on ``lat``/``lon``).
    The record checks the rule on the template's own pixels: how many the nearest-cell rule gives
    differently from HydroMT."""
    import numpy as np
    import pandas as pd
    import xarray as xr
    from pyproj import Transformer

    with xr.open_dataset(template_nc, decode_times=False) as tp:
        tp = tp.load()
    with xr.open_dataset(source_nc) as src:
        src = src.load()
    name = list(tp.data_vars)[0]
    tvals = tp[name].values.astype("float64")
    tx, ty = tp["x"].values, tp["y"].values
    units = tp["time"].attrs.get("units", "")
    if not units.startswith("minutes since"):
        raise ValueError(f"{template_nc}: time units {units!r}")
    t0 = pd.Timestamp(units.split("since", 1)[1].strip())
    starts = [t0 + pd.Timedelta(minutes=float(m)) for m in tp["time"].values]
    stamps = pd.to_datetime(src["time"].values)
    stamps = stamps.tz_localize(None) if stamps.tz is not None else stamps
    hour_of = {s - pd.Timedelta(hours=1): i for i, s in enumerate(stamps)}
    js = [hour_of.get(s) for s in starts]
    w, s, e, n = bounds
    nx, bx = extend_axis(tx, w, e)
    ny, by = extend_axis(ty, s, n)
    gx, gy = np.meshgrid(nx, ny)
    glo, gla = Transformer.from_crs(EPSG, 4326, always_xy=True).transform(gx, gy)
    sla = src[lat].values.astype("float64")
    slo = src[lon].values.astype("float64")
    iy = np.abs(gla[..., None] - sla[None, None, :]).argmin(axis=-1)
    ix = np.abs(glo[..., None] - slo[None, None, :]).argmin(axis=-1)
    rain = src[var].transpose("time", lat, lon).values.astype("float64")
    out = np.zeros((len(starts), len(ny), len(nx)), dtype="float64")
    for k, j in enumerate(js):
        if j is not None:
            out[k] = rain[j][iy, ix]
    if not (np.isfinite(out).all() and (out >= 0).all()):
        raise ValueError("the added pixels hold missing or negative rain")
    inner = (slice(by, by + len(ty)), slice(bx, bx + len(tx)))
    mine = out[:, inner[0], inner[1]]
    differ = np.abs(mine - tvals)
    out[:, inner[0], inner[1]] = tvals
    ds = xr.Dataset(
        {name: (("time", "y", "x"), out.astype("float32"), tp[name].attrs)},
        coords={
            "time": ("time", tp["time"].values, tp["time"].attrs),
            "y": ("y", ny, tp["y"].attrs),
            "x": ("x", nx, tp["x"].attrs),
        },
        attrs=tp.attrs,
    )
    if "spatial_ref" in tp:
        ds = ds.assign_coords(spatial_ref=tp["spatial_ref"])
    out_nc.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_nc.with_name(out_nc.name + ".tmp")
    ds.to_netcdf(tmp, encoding={name: {"_FillValue": np.float32("nan")}})
    os.replace(tmp, out_nc)
    pix = abs(float(tx[1] - tx[0]))
    return {
        "template": str(template_nc),
        "template_sha256": sm._sha256(template_nc),
        "source": str(source_nc),
        "source_sha256": sm._sha256(source_nc),
        "rule": aligned_forcing.__doc__.split("\n\n")[1].strip(),
        "template_shape": list(tvals.shape),
        "shape": list(out.shape),
        "pixels_added": {"west_or_first_x": bx, "north_or_first_y": by},
        "pixel_m": pix,
        "hours_without_source_stamp": [k for k, j in enumerate(js) if j is None],
        "covers_ring": bool(
            nx.min() - pix / 2 <= w
            and nx.max() + pix / 2 >= e
            and ny.min() - pix / 2 <= s
            and ny.max() + pix / 2 >= n
        ),
        "check_on_template_pixels": {
            "pixel_hours": int(differ.size),
            "differ_from_hydromt": int((differ > 1e-4).sum()),
            "largest_abs_difference_mm_h": float(differ.max()),
        },
        "mean_rate_by_step_mm_h": [round(float(v), 3) for v in out.mean(axis=(1, 2))],
        "written": str(out_nc),
    }


def _scenario_row(scenarios_csv: Path, scenario_nc: Path) -> dict:
    import csv

    with scenarios_csv.open() as f:
        for row in csv.DictReader(f):
            if Path(row["path"]).name == scenario_nc.name:
                return row
    raise KeyError(f"{scenario_nc.name} is not in {scenarios_csv}")


def rebuild_scenario(scenario_nc: Path, out_nc: Path, run_dir: Path, bounds=RING) -> dict:
    """A scenario file over ``bounds`` (the ring by default): the parent storm's ``rain`` from
    RainyDay's catalogue moved by the scenario's shift (``scenarios.csv``), on the scenario's own
    time axis (stamps not in the parent are RainyDay's padding: zero, checked on the scenario's
    cells). Over the square (CH-26) it gives the square runs pixels beyond the square's edges:
    RainyDay's own scenario holds only the pixels whose centres lie in the study box, and SFINCS
    puts no rain on cells outside the outermost pixel centres of a ``netamprfile``."""
    import glob

    import numpy as np
    import xarray as xr
    from pyproj import Transformer

    row = _scenario_row(run_dir / "scenarios.csv", scenario_nc)
    parent = int(row["parent_storm"])
    sy, sx = int(row["source_y_index"]), int(row["source_x_index"])
    dy, dx = int(row["shift_y_cells"]), int(row["shift_x_cells"])
    files = glob.glob(str(run_dir / "StormCatalog" / f"*_storm_{parent}_*.nc"))
    if len(files) != 1:
        raise FileNotFoundError(f"parent storm {parent}: {len(files)} catalogue files")
    with xr.open_dataset(files[0]) as cat:
        lat = cat["latitude"].values.astype("float64")
        lon = cat["longitude"].values.astype("float64")
        prain = cat["rain"].values.astype("float64")
        ptime = cat["time"].values
        cx = int(cat["xlocation"].values[parent - 1])
        cy = int(cat["ylocation"].values[parent - 1])
    with xr.open_dataset(scenario_nc) as sc:
        srain = sc["rain"].values.astype("float64")
        stime = sc["time"].values
        slat = sc["latitude"].values.astype("float64")
        slon = sc["longitude"].values.astype("float64")
        attrs = dict(sc.attrs)
    if not (np.all(np.diff(lat) > 0) and np.all(np.diff(lon) > 0)):
        raise ValueError("the catalogue's axes do not ascend")
    # the box's lat/lon bounds, from points along its edges
    w, s, e, n = bounds
    k = 81
    xs = np.r_[np.linspace(w, e, k), np.full(k, e), np.linspace(e, w, k), np.full(k, w)]
    ys = np.r_[np.full(k, s), np.linspace(s, n, k), np.full(k, n), np.linspace(n, s, k)]
    lo, la = Transformer.from_crs(EPSG, 4326, always_xy=True).transform(xs, ys)
    rows = index_range(lat, float(la.min()), float(la.max()))
    cols = index_range(lon, float(lo.min()), float(lo.max()))
    block = cut_transposed(prain, dy, dx, rows, cols)
    blat, blon = lat[rows[0] : rows[1]], lon[cols[0] : cols[1]]
    # the scenario's time axis: the parent's stamps, then padding
    pos = {np.datetime64(t, "ns"): i for i, t in enumerate(ptime)}
    out = np.zeros((len(stime), *block.shape[1:]), dtype="float64")
    padded = []
    for i, t in enumerate(stime):
        j = pos.get(np.datetime64(t, "ns"))
        if j is None:
            padded.append(i)
        else:
            out[i] = block[j]
    # proof on the scenario's own cells
    iy = [int(np.argmin(np.abs(blat - v))) for v in slat]
    ix = [int(np.argmin(np.abs(blon - v))) for v in slon]
    coord_err = max(float(np.abs(blat[iy] - slat).max()), float(np.abs(blon[ix] - slon).max()))
    sub = out[:, iy][:, :, ix]
    diff = np.abs(sub - srain)
    if (out < 0).any() or not np.isfinite(out).all():
        raise ValueError("the rebuilt rain holds missing or negative values")
    ds = xr.Dataset(
        {"rain": (("time", "latitude", "longitude"), out.astype("float32"))},
        coords={"time": stime, "latitude": blat, "longitude": blon},
        attrs={
            "source": f"rebuilt over {tuple(bounds)} (EPSG:{EPSG}) from {Path(files[0]).name}, "
            f"shift x {dx} y {dy} cells, as {scenario_nc.name}",
            "rainrate_units": attrs.get("rainrate_units", "mm hr^-1"),
        },
    )
    out_nc.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_nc.with_name(out_nc.name + ".tmp")
    ds.to_netcdf(tmp)
    os.replace(tmp, out_nc)
    return {
        "scenario": str(scenario_nc),
        "scenario_sha256": sm._sha256(scenario_nc),
        "parent_file": files[0],
        "parent_storm": parent,
        "parent_location_xy": [cx, cy],
        "source_index_xy": [sx, sy],
        "shift_cells_xy": [dx, dy],
        "domain_rows": list(rows),
        "domain_cols": list(cols),
        "shape": list(out.shape),
        "bounds": list(bounds),
        "ring_lonlat_bounds": [float(la.min()), float(la.max()), float(lo.min()), float(lo.max())],
        "padded_steps": padded,
        "proof": {
            "scenario_cells": [len(slat), len(slon)],
            "largest_coordinate_mismatch_deg": coord_err,
            "largest_abs_difference_mm_h": float(diff.max()),
            "scenario_total_mm_mean_of_cells": float(srain.mean(axis=(1, 2)).sum()),
            "rebuilt_total_mm_same_cells": float(sub.mean(axis=(1, 2)).sum()),
            "equal": bool(diff.max() == 0.0 and coord_err < 1e-6),
        },
        "written": str(out_nc),
    }


# --- what a finished ring run leaves (builder environment) ---------------------------------------


def analyse(folder: Path) -> dict:
    """Rewrite ``zsmax.tif`` (ring grid, row 0 north, NaN where never wet) and ``balance.json``.

    Outer water balance (continuity) over the cells that are not boundary cells (mask 1): rain =
    sum of ``cumprcp``, drained = sum of ``cuminf`` (the loss rate ``qinf``), stored = change of
    ``subgrid_volume`` from the first to the last map time, out = time integral (trapezoid) of the
    four outer cross-sections, positive outwards. Residual = rain - drained - stored - out.
    Square: the same over its 800 x 800 cells with the inner cross-sections; run-on per edge is
    the inflow integral of its pieces, runoff leaving the square the outflow integral.
    """
    import numpy as np
    import xarray as xr

    area = CELL * CELL
    with xr.open_dataset(folder / "sfincs_map.nc") as ds:
        msk = ds["msk"].values  # rows from the south
        cumprcp = ds["cumprcp"].isel(timemax=-1).values
        cuminf = ds["cuminf"].isel(timemax=-1).values if "cuminf" in ds else np.zeros_like(cumprcp)
        vol = ds["subgrid_volume"].values
        zsmax = ds["zsmax"].max("timemax").values
        zb = ds["zb"].values
        map_times = [str(t) for t in ds["time"].values]
    with xr.open_dataset(folder / "sfincs_his.nc") as his:
        q = his["crosssection_discharge"].values
        if "crosssection_name" not in his:
            raise KeyError("sfincs_his.nc names no cross-sections")
        names = [
            str(v.decode() if isinstance(v, bytes) else v).strip()
            for v in his["crosssection_name"].values
        ]
        t = (his["time"].values - his["time"].values[0]) / np.timedelta64(1, "s")
    if msk.shape != grid_shape(RING):
        raise ValueError(f"{folder}: map grid {msk.shape} is not the ring's {grid_shape(RING)}")
    fl = edge_fluxes(names, q, t)
    interior = msk == 1
    rain = float(np.nansum(cumprcp[interior]) * area)
    drained = float(np.nansum(cuminf[interior]) * area)
    stored = float(np.nansum(vol[-1][interior]) - np.nansum(vol[0][interior]))
    out = -float(sum(fl["outer_inward_m3"].values()))
    residual = rain - drained - stored - out
    # the square: rows from the south in the map file
    rows_n, cols = square_window()
    nrow = msk.shape[0]
    rows_s = slice(nrow - rows_n.stop, nrow - rows_n.start)
    sq = np.zeros_like(interior)
    sq[rows_s, cols] = True
    sq_rain = float(np.nansum(cumprcp[sq]) * area)
    sq_drained = float(np.nansum(cuminf[sq]) * area)
    sq_stored = float(np.nansum(vol[-1][sq]) - np.nansum(vol[0][sq]))
    inner = fl["inner"]
    sq_in = sum(v["net_inward_m3"] for v in inner.values())
    sq_res = sq_rain + sq_in - sq_drained - sq_stored
    for v in inner.values():
        v["inflow_share_of_square_rain"] = v["inflow_m3"] / sq_rain if sq_rain else None
    # rain and loss on the cells F3's water balance sums (its mask 1), to set against the square
    # run's own balance.json: equal rain shows both runs had the same rain on the square
    f3_cells = {}
    if F3_MASK.exists():
        import rasterio

        with rasterio.open(F3_MASK) as src:
            f3m = src.read(1)[::-1] == 1  # rows from the south, as the map file
        sel = np.zeros_like(interior)
        sel[rows_s, cols] = f3m
        f3_cells = {
            "cells": int(sel.sum()),
            "rain_m3": float(np.nansum(cumprcp[sel]) * area),
            "drained_m3": float(np.nansum(cuminf[sel]) * area),
            "mask": str(F3_MASK),
        }
    balance = {
        "analysed_by": ANALYSED_BY,
        "extent": list(RING),
        "rain_m3": rain,
        "drained_m3": drained,
        "stored_m3": stored,
        "out_m3": out,
        "inward_by_section_m3": fl["outer_inward_m3"],
        "residual_m3": residual,
        "residual_share_of_rain": residual / rain if rain else None,
        "square": {
            "rain_m3": sq_rain,
            "drained_m3": sq_drained,
            "stored_m3": sq_stored,
            "net_inward_m3": sq_in,
            "inflow_m3": sum(v["inflow_m3"] for v in inner.values()),
            "outflow_m3": sum(v["outflow_m3"] for v in inner.values()),
            "by_edge": inner,
            "residual_m3": sq_res,
            "residual_share_of_rain": sq_res / sq_rain if sq_rain else None,
            "f3_interior_cells": f3_cells,
        },
        "his_steps": int(len(t)),
        "map_times": map_times,
        "how": analyse.__doc__.split("\n\n")[1].strip(),
    }
    peak = np.where(np.isfinite(zsmax) & (zsmax > zb), zsmax, np.nan)[::-1].astype("float32")
    _write_raster(folder / "zsmax.tif", peak, RING, CELL, "float32", nodata=float("nan"))
    sm._write_json(folder / "balance.json", balance)
    return balance


# --- the queue (standard library) ---------------------------------------------------------------


def lowest_ranks(selection: list[dict], finished: set[str], n: int = 2) -> list[dict]:
    """The ``n`` selection items of lowest rank (largest storms) among the finished runs."""
    done = [x for x in selection if x["label"] in finished]
    return sorted(done, key=lambda x: int(x["rank"]))[:n]


def chosen_storms(cache: Path) -> dict:
    """The two catalogue storms of the ring runs, chosen once and kept in ``f4/ring/chosen.json``
    (the batch keeps adding runs, so a later choice would differ)."""
    path = cache.joinpath(*RING_DIR, "chosen.json")
    if path.exists():
        return json.loads(path.read_text())
    selection = json.loads((cache / "f4" / "selection.json").read_text())
    runs = cache / "f4" / "runs"
    finished = {x["label"] for x in selection if (runs / x["label"] / "balance.json").exists()}
    picked = lowest_ranks(selection, finished)
    rec = {
        "rule": "the two lowest-rank (largest) items of f4/selection.json whose square run has "
        "a balance.json in f4/runs/ when the ring forcing was built",
        "chosen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_then": len(finished),
        "lower_ranks_not_finished_then": sorted(
            int(x["rank"])
            for x in selection
            if picked and int(x["rank"]) < int(picked[-1]["rank"]) and x["label"] not in finished
        ),
        "labels": [x["label"] for x in picked],
        "items": picked,
    }
    sm._write_json(path, rec)
    return rec


def queue_items(root: Path) -> list[dict]:
    """The four ring runs. Each mirrors its square run's ``spec.json`` (loss rate, times) and only
    changes the base and the rain file."""
    cache = root / "data" / "cache" / "flood"
    ring = cache.joinpath(*RING_DIR)
    pairs = (
        ("ring_ida", cache / "f3" / "runs" / "ida_q30", ring / "forcing" / "ring_ida.nc"),
        ("ring_ds_1h_100y", cache / "f4" / "runs" / "ds_1h_100y", None),
    )
    chosen = chosen_storms(cache)
    # the catalogue's square runs with rain on the whole square (CH-26)
    pairs += tuple(
        (f"ring_{c}", cache / "f4" / "runs_cover" / c, ring / "forcing" / f"ring_{c}.nc")
        for c in chosen["labels"]
    )
    items = []
    for label, square_run, forcing in pairs:
        spec = json.loads((square_run / "spec.json").read_text())
        item = {
            "label": label,
            "base": str(ring / "model" / "base"),
            "qinf": spec["qinf_mm_per_h"],
            "tref": spec["tref"],
            "after_h": spec["after_h"],
            "square_run": str(square_run),
        }
        if spec["rain"]["kind"] == "uniform":
            item["rain"] = spec["rain"]["mm_per_h"]
            item["rain_h"] = spec["rain"]["hours"]
        else:
            if forcing is None or not forcing.exists():
                raise FileNotFoundError(f"{label}: forcing {forcing} is missing")
            item["netampr"] = str(forcing)
            item["rain_h"] = round(spec["simulated_s"] / 3600.0 - spec["after_h"], 6)
        items.append(item)
    return items


def _base_main(cache: Path) -> None:
    started = time.perf_counter()
    out = cache.joinpath(*RING_DIR, "model", "base")
    result: dict = {
        "parameters": {
            "extent": list(RING),
            "inner_square": list(SQUARE),
            "inner_piece_m": SECTION_M,
            "subgrid_pixels_per_cell": sm.SUBGRID_PIXELS,
            "nr_levels": sm.NR_LEVELS,
            "manning_land": sm.MANNING_LAND,
            "manning_sea": sm.MANNING_SEA,
            "pit_below_m": sm.PIT_BELOW_M,
            "pit_ring_px": list(sm.PIT_RING_PX),
            "pit_wall_px": sm.PIT_WALL_PX,
            "pit_wall_below_m": sm.PIT_WALL_BELOW_M,
            "building_raise_m": sm.BUILDING_RAISE_M,
            "boundary_level_m_navd88": sm.BOUNDARY_LEVEL_M,
            "water_zb_m": sm.WATER_ZB_M,
            "dthisout_s": sm.DTHISOUT,
            "dtmapout_s": sm.DTMAPOUT,
            "tags": "all placeholders [P], F3's values read from sfincs_model.py",
        },
        "builder": sm._versions(),
    }
    try:
        result |= base(cache)
        result["ok"] = not result["missing_base_files"]
    except Exception as error:
        result["ok"] = False
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()
    result["seconds"] = round(time.perf_counter() - started, 1)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["peak_memory_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    out.mkdir(parents=True, exist_ok=True)
    sm._write_json(out / "base.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("traceback", "inp")}, indent=1))
    if not result["ok"]:
        print(result.get("traceback", ""), file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("base")
    b.add_argument("--cache", type=Path, required=True)
    f = sub.add_parser("replay-forcing")
    f.add_argument("mrms", type=Path)
    f.add_argument("out", type=Path)
    f.add_argument("--tref", required=True)
    f.add_argument("--hours", type=int, required=True)
    r = sub.add_parser("rebuild-scenario")
    r.add_argument("scenario", type=Path)
    r.add_argument("out", type=Path)
    r.add_argument("--run-dir", type=Path, required=True, help="RainyDay output folder")
    r.add_argument("--box", choices=("ring", "square"), default="ring")
    sc = sub.add_parser("scenario-forcing")
    sc.add_argument("scenario", type=Path, help="a rebuilt scenario file")
    sc.add_argument("out", type=Path)
    sc.add_argument("--tref")
    sc.add_argument("--hours", type=int)
    al = sub.add_parser("aligned-forcing")
    al.add_argument("template", type=Path, help="the square run's netamprfile")
    al.add_argument("source", type=Path, help="hourly rain, end-of-hour stamps")
    al.add_argument("out", type=Path)
    al.add_argument("--var", default="rain")
    al.add_argument("--lat", default="latitude")
    al.add_argument("--lon", default="longitude")
    al.add_argument("--box", choices=("ring", "square"), default="ring")
    a = sub.add_parser("analyse")
    a.add_argument("folder", type=Path)
    q = sub.add_parser("queue")
    q.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.command == "base":
        _base_main(args.cache)
        return
    if args.command in (
        "replay-forcing",
        "rebuild-scenario",
        "scenario-forcing",
        "aligned-forcing",
    ):
        if args.command == "aligned-forcing":
            box = SQUARE if args.box == "square" else RING
            rec = aligned_forcing(
                args.template, args.source, args.out, args.var, args.lat, args.lon, box
            )
        elif args.command == "replay-forcing":
            rec = replay_forcing(args.mrms, args.out, args.tref, args.hours)
        elif args.command == "rebuild-scenario":
            box = SQUARE if args.box == "square" else RING
            rec = rebuild_scenario(args.scenario, args.out, args.run_dir, box)
        else:
            rec = scenario_forcing(args.scenario, args.out, args.tref, args.hours)
        sm._write_json(args.out.with_suffix(".json"), rec)
        print(json.dumps(rec, indent=1))
        return
    if args.command == "analyse":
        bal = analyse(args.folder)
        print(json.dumps({k: v for k, v in bal.items() if k != "map_times"}, indent=1))
        return
    if args.command == "queue":
        root = Path(__file__).resolve().parents[3]
        items = queue_items(root)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        sm._write_json(args.out, items)  # type: ignore[arg-type]
        print(json.dumps(items, indent=1))


if __name__ == "__main__":
    main()
