"""F4 visual test: the storm catalogue, its batch runs and the depth frequency they give (FH5-FH7).

    uv run --with matplotlib python -m flood_lab.checks.f4_catalogue

Offline. Works on whatever catalogue runs have finished (a run folder under
``<cache>/f4/runs/<label>/`` with ``balance.json`` and ``zsmax.tif``) and states the number of
storms ``N`` behind every figure and in the record. While a stratum of the selection is
incomplete its runs carry interim weights (``catalogue.weights``) and the figures say "interim".

* **Per run** (cached in ``<cache>/f4/frequency/per_run/<label>.npz``, so a re-run reads only
  new runs): the 5 m depth grid as F3 calibrated the drainage allowance and tested FH8 on it,
  ``calibration.run_depth`` (peak level less the model terrain at each cell's centre 1 m pixel,
  floored at 0), NaN on the cells ``calibration.Frame`` leaves out: centre pixel in a footprint,
  any pixel in a filled pit, centre pixel on mapped water, lowest level below the start water
  level. The study-area mask is not applied: the grid is the whole square. The lead measure
  of every kept substation site and the wall depth of every building of the study area, both
  exactly as ``at_assets`` defines them.
* **Grid route**: ``crc_load.grid_curves`` -> ``write_rasters`` -> ``load_grid``. The share of
  cells non-decreasing before the clean-up is computed from ``catalogue.depth_at`` output before
  ``make_non_decreasing``.
* **Point route**: the substation sites at the centroid of their outlines and the buildings at
  their footprint centroid -> ``crc_load.points_table`` -> ``load_points``. The first 500
  buildings are timed first; the full set is loaded only if that time extrapolates to under
  ``POINTS_FULL_MAX_S``, otherwise the record says so (no silent subsample).
* **Rainfall**: the catalogue's 3-hour annual maxima at the study box (RainyDay's
  ``*_FreqAnalysis.csv``) at return period ``M / rank`` (RainyDay's own convention), Atlas 14
  AMS 3-hr with its 90% band, AORC observed box maxima at Weibull plotting positions.

Writes ``site/flood/tests/records/f4.json`` and PNG figures under ``docs/flood/figures/f4/``.
Options for a dry run against other folders: ``--runs``, ``--selection``, ``--work``,
``--figures``, ``--records``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from flood_lab import cache, domain, paths
from flood_lab.checks import f3_model
from flood_lab.hazard import at_assets, calibration, catalogue
from flood_lab.records import Check, Input, Parameter, Record
from flood_lab.risk import crc_load

RECORD_ID = "f4"
REL = "docs/flood/figures/f4"
#: bump when the content of a per-run cache file changes
CACHE_VERSION = 4  # 3: CH-21; 4: unreadable wall bands are NaN
RUN_FILES = ("balance.json", "zsmax.tif")
CHOSEN = "f4/rainyday/catalogue_n960/f4_B_d3_n960"
CHOSEN_FREQ = f"{CHOSEN}/f4_B_d3_n960_FreqAnalysis.csv"
CHOSEN_PARAMS = "f4/rainyday/catalogue_n960/params.json"
CATALOGUE_CSV = f"{CHOSEN}/catalogue.csv"
SENSITIVITIES = (
    ("240 storms (10 a year)", "f4/rainyday/catalogue/f4_B_d3/f4_B_d3_FreqAnalysis.csv"),
    (
        "480 storms (20 a year)",
        "f4/rainyday/catalogue_n480/f4_B_d3_n480/f4_B_d3_n480_FreqAnalysis.csv",
    ),
)
DOMAIN_JSON = "f4/domain/domain.json"
DOMAIN_MAPS = "f4/domain/domain_maps.npz"
DOMAIN_SHP = "f4/domain/domain_B_land.shp"
BOX_AMS = "f4/domain/box_ams_observed.json"
QUEUE_DESIGN = "f4/queue_design.json"
QUEUE_CATALOGUE = "f4/queue_catalogue.json"
#: return periods of the plan's rainfall pass rule (2 to 100 years) [P] proposed
BAND_YEARS = (2, 5, 10, 25, 50, 100)
#: return periods of the depth strip and of the substation table
STRIP_YEARS = (10, 100, 500)
DESIGN_YEARS = (2, 5, 10, 25, 100, 500)
DESIGN_HOURS = (1, 3)
#: depth non-decreasing in at least this share of cells before the clean-up [P] proposed (plan F4)
ND_MIN_SHARE = 0.99
#: runs required before the demo of 1 December (requirements §15) and the target (FH5)
RUNS_REQUIRED = 60
RUNS_TARGET = 150
DEMO_DAY = date(2026, 12, 1)
POINTS_TRIAL = 500
#: the full building set goes to CRC only if the 500-building trial extrapolates below this [P]
POINTS_FULL_MAX_S = 900.0
#: categorical slots 1-3 of the reference palette (dataviz skill)
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID_GREY, NOT_READ = "#0b0b0b", "#52514e", "#e5e5e5", "#bdbdbd"
DESIGN_COLOURS = {1: ORANGE, 3: AQUA}


# --- pure helpers (tested without rasters) -------------------------------------------------------


def finished_labels(labels: list[str], runs_dir: Path) -> list[str]:
    """Labels, in the order given, whose run folder holds ``balance.json`` and ``zsmax.tif``."""
    return [x for x in labels if all((runs_dir / x / n).exists() for n in RUN_FILES)]


def stratum_progress(selection: list[dict], done: set[str], m: int) -> list[dict]:
    rows = []
    for s in catalogue.strata(m):
        mine = [x for x in selection if x["stratum"] == s.name]
        fin = sum(x["label"] in done for x in mine)
        rows.append(
            {
                "stratum": s.name,
                "ranks": f"{s.first}-{s.last}",
                "years": s.years,
                "runs": len(mine),
                "finished": fin,
                "complete": fin == len(mine),
            }
        )
    return rows


def is_interim(selection: list[dict], done: set[str], m: int) -> bool:
    """True while some stratum is incomplete (its runs carry interim weights)."""
    return not all(r["complete"] for r in stratum_progress(selection, done, m))


def weibull_positions(values) -> tuple[np.ndarray, np.ndarray]:
    """Values sorted largest first and their return periods ``T = (n + 1) / i`` (Weibull)."""
    v = np.sort(np.asarray(values, float))[::-1]
    n = len(v)
    return v, (n + 1) / np.arange(1, n + 1)


def rank_positions(values) -> tuple[np.ndarray, np.ndarray]:
    """Values sorted largest first and ``T = M / rank`` (RainyDay's convention, M = count)."""
    v = np.sort(np.asarray(values, float))[::-1]
    return v, len(v) / np.arange(1, len(v) + 1)


def value_at(values, years: float) -> float:
    """Annual maximum at return period ``years``: rank ``M / years`` of ``M`` (no interpolation)."""
    v, _ = rank_positions(values)
    rank = int(round(len(v) / years))
    if not 1 <= rank <= len(v):
        raise ValueError(f"{years} years is outside 1 to {len(v)}")
    return float(v[rank - 1])


def band_rows(values, band: dict[float, tuple[float, float, float]], years=BAND_YEARS) -> list:
    """Per return period: the catalogue value, Atlas 14's estimate and band, and whether inside."""
    out = []
    for t in years:
        est, lo, hi = band[float(t)]
        v = value_at(values, t)
        out.append(
            {
                "years": t,
                "catalogue_mm": round(v, 1),
                "atlas14_mm": round(est, 1),
                "lower90_mm": round(lo, 1),
                "upper90_mm": round(hi, 1),
                "inside": bool(lo <= v <= hi),
            }
        )
    return out


def non_decreasing_cells(raw: np.ndarray) -> np.ndarray:
    """``raw`` (aeps, cells) with AEP falling: True where depth never falls as AEP falls."""
    if raw.shape[0] < 2:
        return np.ones(raw.shape[1], bool)
    return np.all(np.diff(raw, axis=0) >= 0, axis=0)


def counts_wet(depths, thresholds=(catalogue.WET_M, at_assets.LEAD_DEPTH_M)) -> dict[str, int]:
    d = np.asarray(depths, float)
    return {f"{t:g}": int((d >= t).sum()) for t in thresholds}


def _where(row: dict) -> str:
    if row["inside"]:
        return "inside"
    return "below" if row["catalogue_mm"] < row["lower90_mm"] else "above"


def years_label(aep: float) -> str:
    return f"{1 / aep:g} y"


# --- inputs --------------------------------------------------------------------------------------


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def read_freq(path: Path) -> np.ndarray:
    """The ``meanrain`` column of a RainyDay frequency file (one realization: min = mean = max)."""
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader)]
        k = header.index("meanrain")
        return np.array([float(r[k]) for r in reader if r])


def atlas_band(table: dict, duration: str = "3-hr") -> dict[float, tuple[float, float, float]]:
    """Atlas 14 AMS: return period -> (estimate, lower90, upper90) in mm."""
    rows = table["series"]["ams"]["durations"][duration]
    mm = calibration.MM_PER_IN
    return {
        f3_model.return_period(k): (
            float(v["depth"]) * mm,
            float(v["lower90"]) * mm,
            float(v["upper90"]) * mm,
        )
        for k, v in rows.items()
    }


def sites(path: Path):
    """Kept substation sites (as ``at_assets``), one row per LocNumber with its outline centroid."""
    import geopandas as gpd

    gdf = gpd.read_file(path).to_crs(domain.CRS)
    gdf = gdf[gdf["reviewed"].astype(str).str.startswith("kept")]
    out = []
    for loc, group in gdf.groupby("LocNumber", sort=True):
        geoms = [g if g.geom_type == "Polygon" else g.buffer(1.0) for g in group.geometry]
        c = gpd.GeoSeries(geoms, crs=domain.CRS).union_all().centroid
        ll = gpd.GeoSeries([c], crs=domain.CRS).to_crs("EPSG:4326").iloc[0]
        name = next((n for n in group["name"] if isinstance(n, str) and n), "(no name)")
        out.append({"id": loc, "name": name, "longitude": ll.x, "latitude": ll.y})
    return out


def building_points(footprints) -> list[dict]:
    cent = footprints.geometry.centroid.to_crs("EPSG:4326")
    ids = footprints["doitt_id"].astype(str).tolist()
    if len(set(ids)) != len(ids):
        ids = [f"row{i}" for i in range(len(ids))]
    return [
        {"id": f"bldg-{i}", "longitude": p.x, "latitude": p.y}
        for i, p in zip(ids, cent, strict=True)
    ]


# --- per-run extraction, cached ------------------------------------------------------------------


def inputs_key(root: Path, substations: Path) -> str:
    """What a run's extracted depths depend on besides the run: the model's static rasters and
    the site outlines (size and modification time), and the code of the depth rules."""
    from flood_lab.hazard import at_assets as _a
    from flood_lab.hazard import calibration as _c

    model = root / "f3" / "model"
    files = [
        model / n for n in ("dem_model_1m.tif", "buildings_1m.tif", "zb_5m.tif", "pits_1m.tif")
    ] + [root / "terrain" / "water_1m.tif", Path(substations)]
    parts = []
    for f in files:
        st = f.stat()
        parts.append(f"{f.name}:{st.st_size}:{st.st_mtime_ns}")
    for mod in (_a, _c):
        parts.append(_sha_text(Path(mod.__file__).read_text()))
    return _sha_text("\n".join(parts))


def _key(folder: Path, footprint_key: str, site_ids: list[str], inputs: str = "") -> str:
    st = (folder / "zsmax.tif").stat()
    return json.dumps(
        {
            "version": CACHE_VERSION,
            "inputs": inputs,
            "zsmax_size": st.st_size,
            "zsmax_mtime_ns": st.st_mtime_ns,
            "footprints": footprint_key,
            "sites": site_ids,
        },
        sort_keys=True,
    )


#: the grid's depth definition, stated in the record
DEPTH_DEFINITION = (
    "calibration.run_depth (src/flood_lab/hazard/calibration.py): peak water level less the "
    "ground at each 5 m cell's centre 1 m pixel, the ground never below the cell's lowest sub-grid "
    "level (CH-20), floored at 0, the definition the constant loss rate was calibrated and FH8 "
    "tested on; not read (NaN) where calibration.Frame leaves a "
    "cell out: centre pixel in a building footprint, any pixel in a filled pit, centre pixel on "
    "mapped water, lowest level below the start water level (CH-16). Whole square, not only the "
    "study area."
)


@dataclass
class GridFrame:
    """calibration's Frame and the cells the grid does not read."""

    frame: calibration.Frame
    not_read: np.ndarray


def load_frame(root: Path) -> GridFrame:
    """``calibration.Frame`` and its masks, without the study-area mask: building, pit, water
    (the same ``terrain/water_1m.tif`` centre pixel the Frame reads) and standing water."""
    frame = calibration.Frame.load(root, f3_model.STUDY_AREA)
    water = calibration.centre_pixels(calibration._read(root / "terrain" / "water_1m.tif")).astype(
        bool
    )
    mask = frame.building | frame.pit | water | frame.standing
    # the Frame's own comparison set must be the study-area land outside this mask
    if not np.array_equal(frame.compared, frame.land & ~mask):
        raise RuntimeError("calibration.Frame's masks differ from those read here")
    return GridFrame(frame, mask)


def extract(folder: Path, root: Path, grid: GridFrame, footprints, substations: Path) -> dict:
    d1, bld, _ = at_assets.masked_depth(folder, root)
    d5 = calibration.run_depth(folder, grid.frame)
    d5[grid.not_read] = np.nan
    walls = at_assets.building_wall_depths(d1, bld, footprints)
    subs = at_assets.substation_depths(d1, bld, substations)
    return {
        "depth_5m": d5.astype("float32"),
        "walls": walls.astype("float32"),
        "site_ids": np.array([s["LocNumber"] for s in subs]),
        "site_lead": np.array([s["depth_on_25m2_m"] for s in subs], "float32"),
    }


def per_run(
    label: str, runs_dir: Path, store: Path, root: Path, ctx: dict[str, Any]
) -> tuple[dict, bool]:
    """The run's extracted arrays, read from the cache when its key matches; (arrays, fresh)."""
    folder = runs_dir / label
    key = _key(folder, ctx["footprint_key"], ctx["site_ids"], ctx.get("inputs_key", ""))
    path = store / f"{label}.npz"
    if path.exists():
        with np.load(path, allow_pickle=False) as z:
            if str(z["key"]) == key:
                return {n: z[n] for n in z.files if n != "key"}, False
    arrays = extract(folder, root, ctx["frame"], ctx["footprints"], ctx["substations"])
    store.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, key=np.array(key), **arrays)
    part = path.with_name(path.name + ".part")
    part.write_bytes(buffer.getvalue())
    os.replace(part, path)
    return arrays, True


def run_info(folder: Path) -> dict:
    out: dict[str, Any] = {"label": folder.name}
    for name in ("spec.json", "run_run.json"):
        out[f"has_{name.split('.')[0]}"] = (folder / name).exists()
    bal = json.loads((folder / "balance.json").read_text())
    out["residual_share_of_rain"] = bal.get("residual_share_of_rain")
    if out["has_run_run"]:
        rr = json.loads((folder / "run_run.json").read_text())
        out["wall_time_s"] = rr.get("wall_time_s")
        out["solver_finished"] = rr.get("parsed", {}).get("finished")
    return out


# --- figures -------------------------------------------------------------------------------------


def _png(figure, name: str, out: Path) -> str:
    plt = f3_model._plt()
    buffer = io.BytesIO()
    figure.savefig(
        buffer, format="png", dpi=f3_model.DPI, metadata={"Software": None}, facecolor="white"
    )
    path = out / name
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".png.part")
    part.write_bytes(buffer.getvalue())
    part.replace(path)
    plt.close(figure)
    return f"{REL}/{name}"


def _n_text(n: int, interim: bool) -> str:
    return f"N = {n} catalogue storms" + (" (interim weights)" if interim and n else "")


def figure_domain(maps, shp, box, storms, out: Path) -> str:
    import geopandas as gpd
    from matplotlib.patches import Rectangle

    plt = f3_model._plt()
    lat, lon, ratio = maps["lat"], maps["lon"], maps["ratio_max3"]
    if lat[0] < lat[-1]:
        ratio, lat = ratio[::-1], lat[::-1]
    figure, axis = plt.subplots(figsize=(10.5, 7.6))
    image = axis.imshow(
        ratio,
        extent=(lon.min(), lon.max(), lat.min(), lat.max()),
        cmap="RdBu_r",
        vmin=0.7,
        vmax=1.3,
        interpolation="nearest",
        aspect=1 / np.cos(np.deg2rad(41.0)),
    )
    bar = figure.colorbar(image, ax=axis, shrink=0.8, extend="both")
    bar.set_label(
        "3-hour ratio: smoothed mean annual maximum / the study area's (2002-2025)", fontsize=8
    )
    f3_model._outline(
        axis, gpd.read_file(shp).to_crs("EPSG:4326").geometry.union_all(), color=INK, lw=1.6
    )
    (y0, y1), (x0, x1) = box["lat"], box["lon"]
    axis.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec=ORANGE, lw=2.0))
    axis.annotate(
        "study box",
        (x1, y1),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=8,
        color=INK,
    )
    axis.scatter(
        storms[:, 0], storms[:, 1], s=4, color=INK, alpha=0.55, linewidths=0, label="storm"
    )
    axis.set_xlim(lon.min(), lon.max())
    axis.set_ylim(lat.min(), lat.max())
    axis.set_xlabel("Longitude", fontsize=8)
    axis.set_ylabel("Latitude", fontsize=8)
    axis.tick_params(labelsize=7)
    axis.legend(
        handles=[
            plt.Line2D([], [], color=INK, lw=1.6, label="domain B (land with AORC data)"),
            plt.Line2D([], [], color=ORANGE, lw=2.0, label="study box"),
            plt.Line2D(
                [],
                [],
                marker="o",
                ls="",
                color=INK,
                alpha=0.55,
                markersize=3,
                label=f"{len(storms)} catalogue storms: centre of the box-sized window of "
                "each storm's largest 3-hour rain",
            ),
        ],
        fontsize=7.5,
        loc="lower right",
        framealpha=0.9,
    )
    axis.set_title(
        "Transposition domain B over the AORC download window (38-44 N, 78.5-69.5 W), "
        "with the 960 storms of the chosen catalogue",
        fontsize=9.5,
    )
    figure.tight_layout()
    return _png(figure, "domain.png", out)


def figure_rainfall(chosen, sens, band, observed, rows, out: Path) -> str:
    plt = f3_model._plt()
    figure, (axis, tab) = plt.subplots(
        1, 2, figsize=(12.5, 6), gridspec_kw={"width_ratios": [2.1, 1]}
    )
    ts = sorted(band)
    axis.fill_between(
        ts,
        [band[t][1] for t in ts],
        [band[t][2] for t in ts],
        color=GRID_GREY,
        label="Atlas 14 AMS 3-hr, 90% band",
        zorder=1,
    )
    axis.plot(ts, [band[t][0] for t in ts], "-", color=INK2, lw=1.5, label="Atlas 14 AMS 3-hr")
    for label, values in sens:
        v, t = rank_positions(values)
        axis.plot(t, v, color=BLUE, lw=0.8, alpha=0.45, ls="--", label=f"sensitivity, {label}")
    v, t = rank_positions(chosen)
    axis.plot(t, v, color=BLUE, lw=2.0, label="catalogue, 960 storms (40 a year), M = 1000")
    ov, ot = weibull_positions(observed)
    axis.scatter(
        ot,
        ov,
        s=40,
        color=ORANGE,
        edgecolors="white",
        linewidths=1.5,
        zorder=4,
        label=f"AORC observed at the box, {len(ov)} years, T = (n + 1) / i (Weibull)",
    )
    axis.axvspan(min(BAND_YEARS), max(BAND_YEARS), color=BLUE, alpha=0.05, zorder=0)
    axis.text(
        np.sqrt(min(BAND_YEARS) * max(BAND_YEARS)),
        0.98,
        "pass-rule range, 2-100 y",
        transform=axis.get_xaxis_transform(),
        ha="center",
        va="top",
        fontsize=8,
        color=INK2,
    )
    axis.set_xscale("log")
    axis.set_xlim(1, 1000)
    axis.set_xticks([1, 2, 5, 10, 25, 50, 100, 200, 500, 1000])
    axis.set_xticklabels(["1", "2", "5", "10", "25", "50", "100", "200", "500", "1000"])
    axis.set_xlabel("Return period, years (catalogue: T = M / rank)", fontsize=9)
    axis.set_ylabel("3-hour annual maximum rainfall at the study box, mm", fontsize=9)
    axis.grid(color=GRID_GREY, lw=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.tick_params(labelsize=8)
    axis.legend(fontsize=7.5, loc="upper left", frameon=False)
    tab.axis("off")
    cells = [
        [
            f"{r['years']}",
            f"{r['catalogue_mm']:.1f}",
            f"{r['lower90_mm']:.1f}-{r['upper90_mm']:.1f}",
            _where(r),
        ]
        for r in rows
    ]
    table = tab.table(
        cellText=cells,
        colLabels=["T, y", "catalogue\nmm", "Atlas 14\n90% band, mm", "catalogue\nis"],
        loc="upper center",
        cellLoc="center",
        colWidths=[0.14, 0.24, 0.38, 0.24],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.9)
    outside = [r["years"] for r in rows if not r["inside"]]
    tab.text(
        0.5,
        0.42,
        "Proposed pass rule: catalogue inside the band at 2-100 y.\n"
        f"Outcome: FAIL at {', '.join(map(str, outside)) or 'none'} y;\n"
        "accepted by Yuri as CH-19 (2026-11-26).\n"
        "Depth below about 10 years rests on a\ncatalogue that is too dry there.",
        ha="center",
        va="top",
        fontsize=8.5,
        color=INK,
        transform=tab.transAxes,
    )
    figure.suptitle(
        "3-hour rainfall frequency at the study box: catalogue against Atlas 14 and AORC",
        fontsize=10,
    )
    figure.tight_layout()
    return _png(figure, "rainfall_frequency.png", out)


def _depth_panel(axis, depth, title: str) -> None:
    from matplotlib.colors import BoundaryNorm, ListedColormap

    g = domain.GRID
    extent = (g.west, g.east, g.south, g.north)
    if depth is None:
        axis.text(0.5, 0.5, "no catalogue curve\n(N = 0)", ha="center", va="center", fontsize=9)
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_title(title, fontsize=8.5)
        return
    axis.imshow(
        np.where(np.isnan(depth), 1.0, np.nan),
        extent=extent,
        cmap=ListedColormap([NOT_READ]),
        vmin=0,
        vmax=1,
        interpolation="nearest",
    )
    cmap = ListedColormap(list(f3_model.DEPTH_COLOURS))
    norm = BoundaryNorm([*f3_model.DEPTH_BREAKS, 99.0], cmap.N)
    shown = np.where(depth >= f3_model.DEPTH_BREAKS[0], depth, np.nan)
    axis.imshow(shown, extent=extent, cmap=cmap, norm=norm, interpolation="nearest")
    wet = int(np.nansum(depth >= catalogue.WET_M))
    axis.set_title(f"{title}\n{wet:,} cells wet (0.05 m)", fontsize=8.5)
    axis.set_xticks([])
    axis.set_yticks([])
    axis.set_aspect("equal")


def figure_strip(cat_maps, design_maps, n: int, interim: bool, out: Path) -> str:
    from matplotlib.patches import Patch

    plt = f3_model._plt()
    figure, axes = plt.subplots(len(STRIP_YEARS), 3, figsize=(11, 11.6))
    for i, t in enumerate(STRIP_YEARS):
        _depth_panel(axes[i][0], cat_maps.get(t), f"catalogue, {t} y ({_n_text(n, interim)})")
        for j, h in enumerate(DESIGN_HOURS, 1):
            _depth_panel(axes[i][j], design_maps.get((h, t)), f"Atlas 14 design storm {h} h, {t} y")
    handles = [
        Patch(color=f3_model.DEPTH_COLOURS[0], label="0.05 to 0.1016 m"),
        Patch(color=f3_model.DEPTH_COLOURS[1], label="0.1016 to 0.3048 m"),
        Patch(color=f3_model.DEPTH_COLOURS[2], label="0.3048 m and over"),
        Patch(color=NOT_READ, label="not read (building, pit, water, below the start level)"),
    ]
    figure.legend(handles=handles, loc="lower center", ncol=4, fontsize=8, frameon=False)
    figure.suptitle(
        "Peak depth on the 4 km square (5 m cells): the catalogue's per-cell depth at 10, 100 and "
        "500 years beside the uniform design storms",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0.03, 1, 0.97))
    return _png(figure, "depth_strip.png", out)


def net_rain(folder: Path) -> dict:
    """The design storm's rain rate and drainage allowance, from its spec.json."""
    spec = json.loads((folder / "spec.json").read_text())
    return {
        "rain_mm_per_h": spec.get("rain", {}).get("mm_per_h"),
        "allowance_mm_per_h": spec.get("qinf_mm_per_h"),
    }


def no_flood(row: dict) -> bool:
    """A design storm that wets no 5 m cell, or whose rain does not exceed the allowance."""
    rain, allowance = row.get("rain_mm_per_h"), row.get("allowance_mm_per_h")
    no_net = rain is not None and allowance is not None and rain <= allowance
    return row["wet_cells_005"] == 0 or no_net


def _bar_pair(axis, labels: list[str], values: list[dict | None]) -> None:
    x = np.arange(len(labels))
    width = 0.38
    for k, (thr, colour, name) in enumerate(
        (("0.05", BLUE, "wall depth 0.05 m or more"), ("0.3", ORANGE, "wall depth 0.3 m or more"))
    ):
        ys = [v[thr] if v else 0 for v in values]
        bars = axis.bar(x + (k - 0.5) * width, ys, width * 0.94, color=colour, label=name)
        for bar, v, y in zip(bars, values, ys, strict=True):
            axis.annotate(
                f"{y:,}" if v else "n/a",
                (bar.get_x() + bar.get_width() / 2, y),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color=INK,
            )
    axis.set_xticks(x, labels, fontsize=7.5)
    axis.grid(axis="y", color=GRID_GREY, lw=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)


def figure_buildings(groups, design_rows: list[dict], total: int, out: Path) -> str:
    """Left: 100 years by method. Right: every design storm, with the 5 m cells it wets; a
    storm shaded as without net rain (no wet cell, or rain not above the constant loss rate)
    should wet nothing (CH-20, CH-21)."""
    plt = f3_model._plt()
    figure, (left, right) = plt.subplots(
        1, 2, figsize=(14.5, 5.6), gridspec_kw={"width_ratios": [1, 2.4]}
    )
    _bar_pair(left, [g[0] for g in groups], [g[1] for g in groups])
    left.set_ylabel(f"Buildings of the study area (of {total:,})", fontsize=9)
    left.legend(fontsize=8, frameon=False, loc="upper right")
    left.set_title(
        "Buildings wet at 100 years: the catalogue (each building's\nown curve at AEP 0.01) "
        "against the 1-hour and 3-hour design storms",
        fontsize=9,
    )
    labels = [
        f"{r['run'][3:].replace('_', ' ')}\n{r['wet_cells_005']:,} cells"
        + ("\nno net rain" if no_flood(r) else "")
        for r in design_rows
    ]
    _bar_pair(right, labels, [r["buildings_wet"] for r in design_rows])
    for i, r in enumerate(design_rows):
        if no_flood(r):
            right.axvspan(i - 0.5, i + 0.5, color=GRID_GREY, alpha=0.6, zorder=0)
    right.set_title(
        "Every design storm: buildings 'wet at the wall' and the 5 m cells it wets (0.05 m). "
        "Shaded: storms that wet no 5 m cell or whose rain\ndoes not exceed the "
        "30 mm/h constant loss rate; they should wet no building (a floor here would come "
        "from the terrain, CH-20 and CH-21)",
        fontsize=9,
    )
    figure.tight_layout()
    return _png(figure, "buildings_wet.png", out)


def figure_wet_runs(wet_runs, read, n: int, interim: bool, out: Path) -> str:
    from matplotlib.colors import LinearSegmentedColormap, ListedColormap

    plt = f3_model._plt()
    g = domain.GRID
    extent = (g.west, g.east, g.south, g.north)
    figure, axis = plt.subplots(figsize=(8.6, 7.6))
    if wet_runs is None:
        axis.text(0.5, 0.5, "no catalogue run finished (N = 0)", ha="center", va="center")
        axis.set_xticks([])
        axis.set_yticks([])
    else:
        axis.imshow(
            np.where(read, np.nan, 1.0),
            extent=extent,
            cmap=ListedColormap([NOT_READ]),
            vmin=0,
            vmax=1,
            interpolation="nearest",
        )
        shown = np.where(read & (wet_runs > 0), wet_runs, np.nan).astype(float)
        image = axis.imshow(
            shown,
            extent=extent,
            cmap=LinearSegmentedColormap.from_list(
                "blues_from_light", plt.get_cmap("Blues")(np.linspace(0.25, 1.0, 64))
            ),
            vmin=1,
            vmax=max(n, 1),
            interpolation="nearest",
        )
        bar = figure.colorbar(image, ax=axis, shrink=0.8)
        bar.set_label(f"catalogue runs wetting the cell (>= 0.05 m), of {n}", fontsize=8)
        f3_model._map_axis(axis, (g.west, g.east, g.south, g.north), "")
    axis.set_title(
        f"Catalogue runs wetting each 5 m cell (FH7); {_n_text(n, interim)}\n"
        "grey: not read; white: dry in every run",
        fontsize=9,
    )
    figure.tight_layout()
    return _png(figure, "wet_runs.png", out)


def figure_progress(progress, cat_runs, design_runs, out: Path) -> str:
    plt = f3_model._plt()
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.4))
    a = axes[0]
    names = [p["stratum"] for p in progress]
    x = np.arange(len(names))
    a.bar(x, [p["runs"] for p in progress], 0.6, color=GRID_GREY, label="selected")
    a.bar(x, [p["finished"] for p in progress], 0.6, color=BLUE, label="finished")
    for i, p in enumerate(progress):
        a.annotate(
            f"{p['finished']} / {p['runs']}",
            (i, p["runs"]),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )
    a.set_xticks(x, [f"{p['stratum']}\nranks {p['ranks']}" for p in progress], fontsize=8)
    a.set_title("Catalogue runs finished per stratum", fontsize=9)
    a.legend(fontsize=7.5, frameon=False)
    for axis, key, title in (
        (axes[1], "wall_time_s", "Solver wall time per run, s"),
        (axes[2], "residual_share_of_rain", "Water-balance residual, share of rain"),
    ):
        for runs, colour, name in ((cat_runs, BLUE, "catalogue"), (design_runs, ORANGE, "design")):
            pts = [(i, r[key]) for i, r in enumerate(runs, 1) if r.get(key) is not None]
            if pts:
                axis.scatter(*zip(*pts, strict=True), s=22, color=colour, label=name)
        axis.set_title(title, fontsize=9)
        axis.set_xlabel("run, in order finished (each set counted apart)", fontsize=8)
        axis.legend(fontsize=7.5, frameon=False)
    axes[2].axhline(f3_model.BALANCE_MAX_SHARE, color=INK2, ls="--", lw=1)
    axes[2].axhline(-f3_model.BALANCE_MAX_SHARE, color=INK2, ls="--", lw=1)
    axes[2].set_ylim(-0.012, 0.012)
    for axis in axes:
        axis.tick_params(labelsize=8)
        axis.grid(axis="y", color=GRID_GREY, lw=0.8)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle(
        f"Batch progress: {sum(p['finished'] for p in progress)} of "
        f"{sum(p['runs'] for p in progress)} catalogue runs, {len(design_runs)} design runs "
        "(dashed: the 1% water-balance limit)",
        fontsize=10,
    )
    figure.tight_layout()
    return _png(figure, "progress.png", out)


# --- the check -----------------------------------------------------------------------------------


def _input(path: Path, root: Path) -> Input:
    """An input named from the cache root when it lies there, else from its own folder."""
    try:
        return Input.of(path, root=root)
    except ValueError:
        return Input.of(path, root=path.parents[2])


def _today() -> date:
    return datetime.now(ZoneInfo(domain.TIMEZONE)).date()


def main(argv: list[str] | None = None) -> int:
    import geopandas as gpd

    root = cache.root()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, default=root / "f4" / "runs")
    ap.add_argument("--selection", type=Path, default=root / "f4" / "selection.json")
    ap.add_argument("--work", type=Path, default=root / "f4" / "frequency")
    ap.add_argument("--figures", type=Path, default=paths.FIGURES / "f4")
    ap.add_argument("--records", type=Path, default=paths.RECORDS)
    args = ap.parse_args(argv)
    started = time.perf_counter()
    timing: dict[str, float] = {}

    def lap(name: str, t0: float) -> float:
        timing[name] = round(time.perf_counter() - t0, 1)
        return time.perf_counter()

    t0 = time.perf_counter()
    needed = [
        args.selection,
        root / CHOSEN_FREQ,
        root / CHOSEN_PARAMS,
        root / CATALOGUE_CSV,
        root / DOMAIN_JSON,
        root / DOMAIN_MAPS,
        root / DOMAIN_SHP,
        root / BOX_AMS,
        root / f3_model.ATLAS14,
        root / QUEUE_DESIGN,
        *[root / p for _, p in SENSITIVITIES],
    ]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        print("f4_catalogue: missing inputs, nothing written:\n  " + "\n  ".join(missing))
        return 1
    selection = json.loads(args.selection.read_text())
    ms = {int(x["synthetic_years"]) for x in selection}
    if len(ms) != 1:
        print(f"f4_catalogue: selection names several M: {sorted(ms)}", file=sys.stderr)
        return 1
    m = ms.pop()
    labels = [x["label"] for x in sorted(selection, key=lambda x: x["order"])]
    done_list = finished_labels(labels, args.runs)
    done = set(done_list)
    n = len(done)
    progress = stratum_progress(selection, done, m)
    interim = is_interim(selection, done, m)
    w_of = catalogue.weights(selection, done, m)
    covered = catalogue.covered_years(selection, done, m) if n else 0
    design_labels = [f"ds_{h}h_{t}y" for h in DESIGN_HOURS for t in DESIGN_YEARS]
    design_done = finished_labels(design_labels, args.runs)
    others = sorted(
        p.name
        for p in args.runs.iterdir()
        if p.is_dir() and p.name not in done and p.name not in design_labels
    )

    # assets and the per-run cache
    study = gpd.read_file(f3_model.STUDY_AREA).to_crs(domain.CRS).geometry.union_all()
    footprints = f3_model.study_footprints(root, study)
    site_rows = sites(f3_model.SUBSTATIONS)
    site_ids = [s["id"] for s in site_rows]
    bpoints = building_points(footprints)
    ctx = {
        "footprints": footprints,
        "footprint_key": _sha_text("\n".join(p["id"] for p in bpoints)),
        "site_ids": site_ids,
        "substations": f3_model.SUBSTATIONS,
        "frame": load_frame(root),
        "inputs_key": inputs_key(root, f3_model.SUBSTATIONS),
    }
    store = args.work / "per_run"
    t0 = lap("inputs_s", t0)
    arrays: dict[str, dict] = {}
    fresh = 0
    for label in done_list + design_done:
        a, new = per_run(label, args.runs, store, root, ctx)
        if list(a["site_ids"]) != site_ids:
            raise RuntimeError(f"{label}: substation sites differ from the outlines read")
        arrays[label] = a
        fresh += new
    t0 = lap("per_run_extraction_s", t0)

    cat_info = [run_info(args.runs / x) for x in done_list]
    design_info = [run_info(args.runs / x) for x in design_done]
    numbers: dict[str, Any] = {
        "M_synthetic_years": m,
        "N_catalogue_runs_finished": n,
        "catalogue_runs_selected": len(selection),
        "interim_weights": interim,
        "covered_years": covered,
        "design_runs_finished": len(design_done),
        "runs_extracted_this_time": fresh,
        "buildings_in_study_area": len(footprints),
        "substation_sites": len(site_ids),
    }
    tables: dict[str, Any] = {
        "progress": progress,
        "catalogue_runs": [
            info
            | {
                k: x[k]
                for x in selection
                if x["label"] == info["label"]
                for k in ("rank", "stratum", "order", "box_total_mm", "return_period_y")
            }
            | {"weight_used": w_of.get(info["label"])}
            for info in cat_info
        ],
        "design_runs": design_info,
    }
    notes_extra: list[str] = []
    if others:
        notes_extra.append(f"Other folders in the runs folder, not read: {', '.join(others)}.")
    if not (root / QUEUE_CATALOGUE).exists():
        notes_extra.append("queue_catalogue.json was not yet written when this check ran.")

    # design storms: depth maps, buildings, sites
    design_maps = {}
    design_buildings = {}
    design_sites = {}
    for label in design_done:
        h, t = int(label.split("_")[1][:-1]), int(label.split("_")[2][:-1])
        a = arrays[label]
        design_maps[(h, t)] = a["depth_5m"].astype("float64")
        design_buildings[(h, t)] = counts_wet(a["walls"])
        design_sites[(h, t)] = dict(zip(site_ids, a["site_lead"].round(3).tolist(), strict=True))
    tables["design_storms"] = [
        {
            "run": f"ds_{h}h_{t}y",
            "wet_cells_005": int(np.nansum(design_maps[(h, t)] >= catalogue.WET_M)),
            "buildings_wet": design_buildings[(h, t)],
            "substation_depth_on_25m2_m": design_sites[(h, t)],
            **net_rain(args.runs / f"ds_{h}h_{t}y"),
        }
        for (h, t) in sorted(design_maps)
    ]
    floor = [r for r in tables["design_storms"] if no_flood(r)]
    tables["floor_storms_wetting_no_cell_or_without_net_rain"] = {
        r["run"]: {
            "wet_cells_005": r["wet_cells_005"],
            "rain_mm_per_h": r["rain_mm_per_h"],
            "allowance_mm_per_h": r["allowance_mm_per_h"],
            "buildings_wet_at_wall": r["buildings_wet"],
        }
        for r in floor
    }
    if floor and any(r["buildings_wet"]["0.05"] or r["wet_cells_005"] for r in floor):
        notes_extra.append(
            "Floor: design storms that wet no 5 m cell or whose rain does not exceed the drainage "
            f"allowance ({', '.join(r['run'] for r in floor)}) still show "
            f"{min(r['buildings_wet']['0.05'] for r in floor):,} to "
            f"{max(r['buildings_wet']['0.05'] for r in floor):,} buildings 'wet at the wall' "
            f"(0.05 m) and {min(r['wet_cells_005'] for r in floor):,} to "
            f"{max(r['wet_cells_005'] for r in floor):,} wet 5 m cells: a floor from the "
            "terrain, not flooding by the storm."
        )

    # catalogue frequency
    checks: list[Check] = []
    frequency_ok = n > 0 and covered == m
    if n and not frequency_ok:
        notes_extra.append(
            f"The finished runs cover {covered} of {m} years (a stratum has no finished run); "
            "no frequency is computed until every stratum has one."
        )
    cat_maps: dict[int, np.ndarray] = {}
    wet_runs = read = None
    grid_back = points_back = None
    nd_share = changed = None
    cat_buildings = None
    site_curves: dict[str, dict] = {}
    if frequency_ok:
        w = np.array([w_of[x] for x in done_list])
        depth = np.stack([arrays[x]["depth_5m"] for x in done_list])
        g = catalogue.AEPS
        res = crc_load.grid_curves(depth, w, m)
        t0 = lap("grid_curves_s", t0)
        flat = depth.reshape(n, -1)
        read_flat = np.isfinite(flat).all(axis=0)
        sub = np.nan_to_num(flat[:, read_flat])
        ever = (sub >= catalogue.WET_M).any(axis=0)
        raw = catalogue.depth_at(sub[:, ever], w, m)
        nd = non_decreasing_cells(raw)
        cells_read = int(read_flat.sum())
        nd_count = int(nd.sum()) + int((~ever).sum())
        nd_share = nd_count / cells_read
        changed = res["cells_changed_by_clean_up"]
        curves = res["curves"]
        after_ok = bool(np.all(np.diff(curves.reshape(len(g), -1)[:, read_flat], axis=0) >= 0))
        del raw, sub, flat
        t0 = lap("non_decreasing_share_s", t0)
        numbers |= {
            "cells_read": cells_read,
            "cells_wet_in_some_run": int(ever.sum()),
            "cells_non_decreasing_before_clean_up": nd_count,
            "share_non_decreasing_before_clean_up": round(nd_share, 6),
            "cells_changed_by_clean_up": changed,
            "non_decreasing_after_clean_up": after_ok,
        }
        wet_runs, read = res["wet_runs"], read_flat.reshape(domain.GRID.height, domain.GRID.width)
        numbers["max_runs_wetting_a_cell"] = int(wet_runs.max())
        numbers["cells_read_in_study_area"] = int((read & ctx["frame"].frame.land).sum())
        for t in STRIP_YEARS:
            cat_maps[t] = curves[int(np.argmin(np.abs(np.array(g) - 1 / t)))]
        tables["catalogue_wet_cells_005"] = {
            years_label(p): int(np.nansum(curves[j] >= catalogue.WET_M)) for j, p in enumerate(g)
        }
        files = crc_load.write_rasters(
            curves, args.work / "grid", domain.GRID.west, domain.GRID.north, domain.GRID.cell
        )
        t0 = lap("write_rasters_s", t0)
        grid_back = crc_load.load_grid(
            files, curves, domain.GRID.west, domain.GRID.north, domain.GRID.cell
        )
        t0 = lap("crc_grid_route_s", t0)
        numbers["grid_read_back_equal"] = grid_back["equal"]

        # assets
        lead = np.stack([arrays[x]["site_lead"] for x in done_list]).astype("float64")
        walls = np.stack([arrays[x]["walls"] for x in done_list]).astype("float64")
        # buildings whose wall band has no readable pixel carry no curve (not a dry 0)
        readable = np.isfinite(walls).all(axis=0)
        walls = walls[:, readable]
        bpoints = [b for b, k in zip(bpoints, readable, strict=True) if k]
        numbers["buildings_not_read"] = int((~readable).sum())
        at = catalogue.depth_at(lead, w, m, aeps=tuple(1 / t for t in STRIP_YEARS))
        for j, s in enumerate(site_rows):
            site_curves[s["id"]] = {
                "name": s["name"],
                **{f"{t} y": round(float(at[k, j]), 3) for k, t in enumerate(STRIP_YEARS)},
                "wet_probability": round(float(catalogue.wet_probability(lead, w, m)[j]), 4),
            }
        tables["substation_depth_on_25m2_m"] = site_curves
        b100 = catalogue.depth_at(walls, w, m, aeps=(0.01,))[0]
        cat_buildings = counts_wet(b100)
        numbers["buildings_wet_100y_catalogue"] = cat_buildings
        t0 = lap("asset_curves_s", t0)
        trial_n = min(POINTS_TRIAL, len(bpoints))
        trial = site_rows + bpoints[:trial_n]
        tt = time.perf_counter()
        trial_back = crc_load.load_points(
            crc_load.points_table(trial, np.hstack([lead, walls[:, :trial_n]]), w, m)
        )
        trial_s = time.perf_counter() - tt
        estimate = trial_s * (len(site_rows) + len(bpoints)) / len(trial)
        points: dict[str, Any] = {
            "trial_assets": len(trial),
            "trial_s": round(trial_s, 1),
            "trial_equal": trial_back["equal"],
            "estimated_full_s": round(estimate, 1),
        }
        if estimate <= POINTS_FULL_MAX_S:
            tt = time.perf_counter()
            points_back = crc_load.load_points(
                crc_load.points_table(site_rows + bpoints, np.hstack([lead, walls]), w, m)
            )
            points["full_s"] = round(time.perf_counter() - tt, 1)
            points["full"] = points_back
        else:
            points_back = trial_back
            points["full"] = (
                f"not loaded: the {trial_n}-building trial extrapolates to {estimate:.0f} s, "
                f"over {POINTS_FULL_MAX_S:.0f} s"
            )
            notes_extra.append(f"Point route: {points['full']}; the trial's read-back is used.")
        points["trial"] = trial_back
        tables["point_route"] = points
        tables["grid_route"] = grid_back
        numbers["points_read_back_equal"] = points_back["equal"]
        numbers["points_assets_loaded"] = points_back["assets_written"]
        t0 = lap("crc_point_route_s", t0)

    # rainfall frequency (independent of the runs)
    chosen = read_freq(root / CHOSEN_FREQ)
    sens = [(name, read_freq(root / p)) for name, p in SENSITIVITIES]
    atlas = json.loads((root / f3_model.ATLAS14).read_text())
    band = atlas_band(atlas)
    box_obs = json.loads((root / BOX_AMS).read_text())
    observed = np.array(list(box_obs["max3"].values()), float)
    rain_rows = band_rows(chosen, band)
    tables["rainfall_band"] = rain_rows
    tables["rainfall_sensitivities"] = {
        name: {f"{t} y": round(value_at(v, t), 1) for t in BAND_YEARS} for name, v in sens
    }
    numbers["observed_box_median_3h_mm"] = round(float(np.median(observed)), 2)
    if len(chosen) != m:
        notes_extra.append(f"The frequency file has {len(chosen)} rows, not M = {m}.")

    # figures
    dom = json.loads((root / DOMAIN_JSON).read_text())
    with np.load(root / DOMAIN_MAPS) as z:
        maps = {k: z[k] for k in ("lat", "lon", "ratio_max3")}
    with (root / CATALOGUE_CSV).open(newline="") as fh:
        storms = np.array(
            [
                (float(r["window_lon_center"]), float(r["window_lat_center"]))
                for r in csv.DictReader(fh)
            ]
        )
    numbers["catalogue_storms_plotted"] = len(storms)
    building_groups = [
        (f"catalogue\n{_n_text(n, interim)}", cat_buildings),
        *[(f"design {h} h, 100 y", design_buildings.get((h, 100))) for h in DESIGN_HOURS],
    ]
    numbers["buildings_wet_100y_design"] = {
        f"{h} h": design_buildings.get((h, 100)) for h in DESIGN_HOURS
    }
    figures = [
        figure_domain(maps, root / DOMAIN_SHP, dom["box"], storms, args.figures),
        figure_rainfall(chosen, sens, band, observed, rain_rows, args.figures),
        figure_strip(cat_maps, design_maps, n, interim, args.figures),
        figure_buildings(building_groups, tables["design_storms"], len(footprints), args.figures),
        figure_wet_runs(wet_runs, read, n, interim, args.figures),
        figure_progress(progress, cat_info, design_info, args.figures),
    ]
    t0 = lap("figures_s", t0)

    # checks
    outside = [r["years"] for r in rain_rows if not r["inside"]]
    checks.append(
        Check(
            "catalogue rainfall inside the Atlas 14 band, 2-100 y",
            "3-hour annual maximum at the study box (rank M / T of M) within Atlas 14 AMS 3-hr "
            "90% band at 2, 5, 10, 25, 50 and 100 years (plan F4)",
            not outside,
            value={r["years"]: r["catalogue_mm"] for r in rain_rows},
            threshold={r["years"]: [r["lower90_mm"], r["upper90_mm"]] for r in rain_rows},
            proposed=True,
            note=(
                f"fail, accepted: below the band at {', '.join(map(str, outside))} y; accepted "
                "by Yuri as CH-19 ('Accept, start batch', 2026-11-26); recorded as a finding"
                if outside
                else ""
            ),
        )
    )
    all_runs = cat_info + design_info
    bad_record = [r["label"] for r in all_runs if not (r["has_spec"] and r["has_run_run"])]
    bad_balance = [
        r["label"]
        for r in all_runs
        if r["residual_share_of_rain"] is None
        or abs(r["residual_share_of_rain"]) > f3_model.BALANCE_MAX_SHARE
    ]
    worst = max((abs(r["residual_share_of_rain"] or 0) for r in all_runs), default=None)
    checks.append(
        Check(
            "every finished batch run has a record and a water balance within 1%",
            "spec.json, run_run.json and balance.json present, |residual| <= 1% of the rain "
            "(FH8), for every finished catalogue and design run",
            (not bad_record and not bad_balance) if all_runs else None,
            value={
                "runs": len(all_runs),
                "catalogue": n,
                "design": len(design_info),
                "largest_abs_residual_share": worst,
                "without_record": bad_record,
                "outside_balance": bad_balance,
            },
            threshold=f3_model.BALANCE_MAX_SHARE,
        )
    )
    na = "not judged: no frequency yet (N = 0 or a stratum has no finished run)"
    checks.append(
        Check(
            "depth non-decreasing with return period before the clean-up",
            f"share of read cells whose depth_at curve never falls as AEP falls >= {ND_MIN_SHARE}",
            None if nd_share is None else bool(nd_share >= ND_MIN_SHARE),
            value=None if nd_share is None else round(nd_share, 6),
            threshold=ND_MIN_SHARE,
            proposed=True,
            note=na if nd_share is None else f"{changed} cells changed by the clean-up",
        )
    )
    checks.append(
        Check(
            "depth non-decreasing in every cell after the clean-up",
            "every read cell non-decreasing after make_non_decreasing; cells changed reported",
            None if nd_share is None else numbers["non_decreasing_after_clean_up"],
            value=None if nd_share is None else {"cells_changed": changed},
            note=na if nd_share is None else "",
        )
    )
    checks.append(
        Check(
            "grid route read back equal (Dataset.from_raster)",
            "every delivered cell's knots equal what was written (1e-6 m), same probabilities, "
            "same cell count (FH7)",
            None if grid_back is None else grid_back["equal"],
            value=None
            if grid_back is None
            else {k: v for k, v in grid_back.items() if k != "report"},
            note=na if grid_back is None else "",
        )
    )
    points_note = na
    if points_back is not None:
        points_note = (
            "full asset set"
            if isinstance(tables["point_route"]["full"], dict)
            else f"trial of {POINTS_TRIAL} buildings and the sites only; full set not loaded"
        )
    checks.append(
        Check(
            "point route read back equal (Dataset.from_quantiles)",
            "every asset's knots delivered equal to those written (1e-9) (FH7)",
            None if points_back is None else points_back["equal"],
            value=points_back,
            note=points_note,
        )
    )
    today = _today()
    checks.append(
        Check(
            f"at least {RUNS_REQUIRED} catalogue runs before 1 December",
            f"finished catalogue runs >= {RUNS_REQUIRED} by {DEMO_DAY} (requirements §15)",
            True if n >= RUNS_REQUIRED else (False if today >= DEMO_DAY else None),
            value=n,
            threshold=RUNS_REQUIRED,
            note="" if n >= RUNS_REQUIRED else f"batch running; checked on {today}",
        )
    )
    checks.append(
        Check(
            f"all {RUNS_TARGET} catalogue runs finished",
            f"finished catalogue runs = {RUNS_TARGET} (FH5 target)",
            True if n >= RUNS_TARGET else None,
            value=n,
            threshold=RUNS_TARGET,
            note="" if n >= RUNS_TARGET else "batch running; figures are rebuilt when it ends",
        )
    )

    numbers["check_wall_time_s"] = round(time.perf_counter() - started, 1)
    tables["timing_s"] = timing
    state = _n_text(n, interim) + (f", {covered} of {m} years covered" if n else "")
    captions = {
        "domain.png": "3-hour ratio map (smoothed mean annual maximum over the study area's, "
        "AORC 2002-2025) over the download window, domain B, the study box and the 960 storms "
        "of the chosen catalogue, each at the centre of the box-sized window of its largest "
        "3-hour rain (RainyDay's storm location).",
        "rainfall_frequency.png": "3-hour annual maximum rainfall at the study box: the chosen "
        "catalogue (960 storms, M = 1000, T = M / rank), the 240- and 480-storm sensitivities, "
        "Atlas 14 AMS 3-hr with its 90% band, and AORC observed box maxima at Weibull plotting "
        "positions T = (n + 1) / i. Below the band at 2-10 y: fail, accepted (CH-19).",
        "depth_strip.png": f"Per-cell depth at 10, 100 and 500 years from the catalogue ({state})"
        " beside the 1-hour and 3-hour Atlas 14 design storms of the same return periods.",
        "buildings_wet.png": "Buildings of the study area wet at the wall (0.05 m, 0.3 m) at 100"
        f" years: the catalogue ({state}; each building's own curve at AEP 0.01) against each "
        "design storm; beside it every design storm with the 5 m cells it wets. Shaded: storms "
        "that wet no 5 m cell or whose rain does not exceed the 30 mm/h constant loss rate; "
        "since CH-20 and CH-21 (ground never below a cell's lowest sub-grid level) they wet "
        "no cell and no building, where before they showed about 2,900 buildings.",
        "wet_runs.png": f"Number of catalogue runs wetting each read 5 m cell ({state}).",
        "progress.png": "Catalogue runs finished per stratum; solver wall time and water-balance"
        " residual per finished run (catalogue and design).",
    }
    first = (
        f"F4 storm catalogue and batch: {state}. Depth frequency is empirical (catalogue."
        "depth_at, RainyDay's rank convention), one storm per synthetic year; the largest-rain "
        "storm of a year is taken as its worst flood. Grid depth: " + DEPTH_DEFINITION + " "
        "Asset depths: at_assets (1 m pixels; substation lead measure, building wall band). "
        "Figures made before the batch completes are rebuilt afterwards (requirements §15)."
    )
    inputs = [
        _input(args.selection, root),
        *[
            Input.of(root / p, root=root)
            for p in (
                CHOSEN_FREQ,
                CHOSEN_PARAMS,
                f"{CHOSEN}/run_record.json",
                CATALOGUE_CSV,
                DOMAIN_SHP,
                DOMAIN_JSON,
                DOMAIN_MAPS,
                BOX_AMS,
                f3_model.ATLAS14,
                QUEUE_DESIGN,
                *[p for _, p in SENSITIVITIES],
            )
        ],
        *(
            [Input.of(root / QUEUE_CATALOGUE, root=root)]
            if (root / QUEUE_CATALOGUE).exists()
            else []
        ),
        Input.of(root / "terrain" / "water_1m.tif", root=root),
        Input.of(f3_model.SUBSTATIONS, root=paths.ROOT),
        Input.of(f3_model.STUDY_AREA, root=paths.ROOT),
        Input.of(root / f3_model.FOOTPRINTS, root=root),
        *[
            Input.of(root / "f3" / "model" / x, root=root)
            for x in ("dem_model_1m.tif", "buildings_1m.tif", "zb_5m.tif", "pits_1m.tif")
        ],
        *[_input(args.runs / x / "zsmax.tif", root) for x in done_list + design_done],
    ]
    record = Record(
        id=RECORD_ID,
        stage="F4",
        title="Storm catalogue, batch runs and depth frequency into CRC by both routes",
        inputs=inputs,
        parameters=[
            Parameter("synthetic_years_M", m, "P", "RainyDay NYEARS, CH-19"),
            Parameter("grid_depth_definition", DEPTH_DEFINITION, "I", "calibration.py"),
            Parameter("wet_m", catalogue.WET_M, "P", "catalogue.WET_M"),
            Parameter("aeps", list(catalogue.AEPS), "P", "catalogue.AEPS"),
            Parameter("band_years", list(BAND_YEARS), "P", "plan F4 pass rule"),
            Parameter("non_decreasing_min_share", ND_MIN_SHARE, "P", "plan F4 pass rule"),
            Parameter("balance_max_share", f3_model.BALANCE_MAX_SHARE, "P", "FH8"),
            Parameter("lead_depth_m", at_assets.LEAD_DEPTH_M, "P", "demo-concerns §2"),
            Parameter("max_roof_share", at_assets.MAX_ROOF_SHARE, "P", "at_assets"),
            Parameter("points_trial", POINTS_TRIAL, "P", "brief: time 500 first"),
            Parameter("points_full_max_s", POINTS_FULL_MAX_S, "P"),
            Parameter("depth_colours", list(f3_model.DEPTH_COLOURS), "P", "as F3; FP7 has none"),
        ],
        numbers=numbers,
        tables=tables | {"captions": captions},
        checks=checks,
        figures=figures,
        notes=[first, *(f"{k}: {v}" for k, v in captions.items()), *notes_extra],
    )
    record.software = record.software | {
        k: f3_model._version(k) for k in ("numpy", "rasterio", "geopandas", "matplotlib")
    }
    path = record.write(args.records)
    print(
        json.dumps(
            {
                "record": str(path),
                "passed": record.passed,
                "numbers": numbers,
                "checks": [(c.name, c.passed, c.value) for c in checks],
                "rainfall": rain_rows,
                "substations": site_curves,
                "design_buildings_100y": numbers["buildings_wet_100y_design"],
                "timing_s": timing,
                "figures": figures,
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
