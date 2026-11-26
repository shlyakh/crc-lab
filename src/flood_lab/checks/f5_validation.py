"""F5, first part: the model against observations (FV1, FV2), with the second readers (FS4).

    uv run --with matplotlib python -m flood_lab.checks.f5_validation

Offline, from the cache. Nothing is fitted or changed here (FV4): the replays are the frozen F3 runs
at the constant loss rate of 30 mm/h (``hazard/allowance.toml``; the water the sewers and the
ground take away, a lumped loss), ``ida_q30`` and ``sep_q30``.

**Second readers (FS4).** The high-water marks loaded by ``sources.usgs_hwm`` are recomputed by
``reference.usgs_hwm`` and compared row by row; one hour window of radar rainfall (the Ida replay's
MRMS hours, ``f3/mrms/ida_2021.nc``) is decoded again from the raw GRIB files by
``reference.mrms`` and compared cell by cell. Each comparison is run a second time on a copy of
the loaded values with one rule broken on purpose, and must then differ. The two readers are
imported only when the check runs; a reader that is not there gives "not checked".

**FV1 (Ida, the marks in the square).** For each mark: the modelled peak water level of its 5 m
cell (``zsmax``, metres NAVD88, as the model terrain, USGS 3DEP 1 m, and the water-level boundary
at 0 m NAVD88) against the surveyed mark elevation (NAVD88) gives the level error, model less
survey. The modelled inundation depth (water level less ground level) at the mark's 1 m pixel, by
``at_assets``'s rule (ground never below the cell's lowest sub-grid level, CH-21), against the
surveyed height above ground gives the depth error. A cell the model never wets has no modelled
level (its level error is not defined) and a depth of 0. Each mark carries flags: its cell is not
one F3 compares (``calibration.Frame``: outside study-area land, building at the centre, pit,
mapped water, water standing from the start), its pixel is under a footprint, its cell is mostly
roofed (``at_assets``), its quality is "Poor", or its survey uncertainty exceeds
``MAX_UNCERTAINTY_M``. Statistics are given per mark and per site (the mean of the site's marks),
with and without the flagged marks.

**FV2 (both storms).** Every FloodNet sensor in the square in service that day: the measured peak
(or none recorded) against the modelled depth at its pixel, and the deepest modelled depth within
``NEAR_M`` of it on open ground (sensor positions are approximate; read cells and footprints as in
``at_assets``).

Writes ``site/flood/tests/records/f5.json`` and figures under ``docs/flood/figures/f5/``.
"""

from __future__ import annotations

import io
import json
import math
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flood_lab import cache, localtime, paths
from flood_lab.domain import GRID
from flood_lab.hazard import at_assets, calibration
from flood_lab.records import Check, Input, Parameter, Record
from flood_lab.reference import compare
from flood_lab.sources import floodnet, usgs_hwm

RECORD_ID = "f5"
OUT = paths.FIGURES / "f5"
REL = "docs/flood/figures/f5"
FREEZE = Path(__file__).resolve().parents[1] / "hazard" / "allowance.toml"
STUDY_AREA = paths.SITE / "data" / "study_area.geojson"
MRMS_LOADED = "f3/mrms/ida_2021.nc"
MRMS_RAW = "f3/mrms/raw/ida_2021"
#: the storms: freeze key, New York day, label
STORMS = (
    ("ida_2021", "2021-09-01", "Ida, 1 Sep 2021"),
    ("sep29_2023", "2023-09-29", "29 Sep 2023"),
)
#: sensor positions are approximate: the deepest modelled depth this close is also read, m [P]
NEAR_M = 10.0
#: FV4: above this depth RMSE the write-up says substation-level claims are not supported, m [P]
FV4_RMSE_M = 0.5
#: a mark whose survey uncertainty exceeds this is flagged, m [P] (0.1 ft is the common value)
MAX_UNCERTAINTY_M = 0.1
#: Kasaei et al. 2025, HESS 29:2043 [S]; facts table rows FV1 (jamaica-bay-ida-depth-map)
KASAEI = {
    "citation": "Kasaei et al. 2025, Hydrology and Earth System Sciences 29:2043",
    "rmse_calibrated_m": 0.20,
    "rmse_before_calibration_m": 0.40,
    "marks": 8,
    "reading": "The 0.20 m is the error of a model calibrated on those 8 marks: a fitted figure, "
    "not an independent test. 0.40 m is the same model before calibration.",
}
#: colours: categorical slots 1 and 2 of the reference palette (as f3_sites); diverging RdBu
MODEL, OBSERVED, FLAG_GREY = "#2a78d6", "#eb6834", "#9e9e9e"
DPI = 100
#: the zoomed panels keep the observations this close to their median point, m (figure only)
ZOOM_RADIUS_M = 600.0


# --- pure helpers (tested without rasters) -------------------------------------------------------


def error_stats(errors: list[float | None]) -> dict[str, Any]:
    """n, bias (mean), RMSE and MAE of the errors that are not None, metres to 1 mm."""
    e = np.array([x for x in errors if x is not None and not math.isnan(x)], dtype="float64")
    if e.size == 0:
        return {"n": 0, "bias_m": None, "rmse_m": None, "mae_m": None}
    return {
        "n": int(e.size),
        "bias_m": round(float(e.mean()), 3),
        "rmse_m": round(float(np.sqrt((e**2).mean())), 3),
        "mae_m": round(float(np.abs(e).mean()), 3),
    }


def pixel_of(x: float, y: float) -> tuple[int, int]:
    """(row, col) of the 1 m pixel of the square holding a point (rows from the north)."""
    col, row = int(math.floor(x - GRID.west)), int(math.floor(GRID.north - y))
    k = int(round(GRID.cell))
    if not (0 <= row < GRID.height * k and 0 <= col < GRID.width * k):
        raise ValueError(f"point ({x}, {y}) is outside the square")
    return row, col


def near_max(values: np.ndarray, x: float, y: float, radius_m: float) -> float | None:
    """Largest finite value of the 1 m pixels whose centre lies within ``radius_m`` of a point."""
    r = int(math.ceil(radius_m)) + 1
    row, col = pixel_of(x, y)
    r0, r1 = max(row - r, 0), min(row + r + 1, values.shape[0])
    c0, c1 = max(col - r, 0), min(col + r + 1, values.shape[1])
    rows, cols = np.mgrid[r0:r1, c0:c1]
    cx, cy = GRID.west + cols + 0.5, GRID.north - rows - 0.5
    inside = (cx - x) ** 2 + (cy - y) ** 2 <= radius_m**2
    window = values[r0:r1, c0:c1][inside]
    window = window[np.isfinite(window)]
    return round(float(window.max()), 3) if window.size else None


def frame_reasons(frame: calibration.Frame, row5: int, col5: int) -> list[str]:
    """Why F3 does not compare a 5 m cell; empty when it does."""
    if frame.compared[row5, col5]:
        return []
    reasons = []
    if not frame.land[row5, col5]:
        reasons.append("outside study-area land")
    if frame.building[row5, col5]:
        reasons.append("building at the cell centre")
    if frame.pit[row5, col5]:
        reasons.append("pit in the cell")
    if frame.standing[row5, col5]:
        reasons.append("water standing from the start")
    if not reasons:
        reasons.append("mapped water")  # the one rule of Frame.compared not kept on the frame
    return reasons


def mark_flags(
    mark: dict[str, Any], reasons: list[str], in_footprint: bool, roofed: bool
) -> list[str]:
    flags = [f"cell not read: {r}" for r in reasons]
    if in_footprint:
        flags.append("pixel inside a building footprint")
    if roofed:
        flags.append("cell mostly under roofs (at_assets)")
    if str(mark.get("quality", "")).startswith("Poor"):
        flags.append(f"quality {mark['quality']}")
    u = mark.get("uncertainty_m")
    if u is not None and u > MAX_UNCERTAINTY_M:
        flags.append(f"survey uncertainty {u} m")
    return flags


def site_means(rows: list[dict[str, Any]], column: str) -> list[float | None]:
    """The mean of ``column`` over each site's marks (marks with None left out), one per site."""
    by_site: dict[str, list[float]] = {}
    for r in rows:
        by_site.setdefault(r["site_no"], [])
        if r[column] is not None:
            by_site[r["site_no"]].append(r[column])
    return [float(np.mean(v)) if v else None for _, v in sorted(by_site.items())]


def fv1_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Level and depth statistics per mark and per site, all marks and unflagged marks."""
    out = {}
    for subset, chosen in (("all", rows), ("unflagged", [r for r in rows if not r["flags"]])):
        out[subset] = {
            "marks": len(chosen),
            "sites": len({r["site_no"] for r in chosen}),
            **{
                f"{what}_per_mark": error_stats([r[f"{what}_error_m"] for r in chosen])
                for what in ("level", "depth")
            },
            **{
                f"{what}_per_site": error_stats(site_means(chosen, f"{what}_error_m"))
                for what in ("level", "depth")
            },
        }
    return out


def fv4_statement(depth_rmse_m: float | None) -> str:
    if depth_rmse_m is None:
        return "No depth error could be computed; FV4 cannot be judged."
    if depth_rmse_m > FV4_RMSE_M:
        return (
            f"The depth error at the marks ({depth_rmse_m:.2f} m RMSE) exceeds {FV4_RMSE_M} m "
            "[P]: the depth layer does not support substation-level depth claims. Proposed: "
            "report depth classes only, or take up F14. No parameter is changed (FV4)."
        )
    return (
        f"The depth error at the marks ({depth_rmse_m:.2f} m RMSE) is within {FV4_RMSE_M} m [P]; "
        "FV4's statement is not required. No parameter is changed (FV4)."
    )


def with_height_in_feet(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deliberate fault: a copy where the first mark with a height keeps it in feet."""
    out = [dict(r) for r in rows]
    for r in out:
        if r["height_above_ground_m"] is not None:
            r["height_above_ground_m"] = round(r["height_above_ground_m"] / usgs_hwm.FT_M, 4)
            break
    return out


def compare_marks(loaded: list[dict], other: list[dict]) -> dict[str, Any]:
    result = compare.compare_tables(
        loaded,
        other,
        key="hwm_id",
        exact=["hwm_id", "site_no", "vertical_datum", "quality", "survey_date", "in_square"],
        close={
            "longitude": 1e-4,
            "latitude": 1e-4,
            "elev_navd88_m": 1e-4,
            "height_above_ground_m": 1e-4,
            "uncertainty_m": 1e-4,
            "easting_m": 0.01,
            "northing_m": 0.01,
        },
    )
    result["outcome"] = compare.outcome(result)
    return result


def compare_rain(a: np.ndarray, b: np.ndarray, tolerance_mm: float) -> dict[str, Any]:
    """Cell by cell: cells with |a - b| > tolerance, and cells where only one is NaN."""
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    if a.shape != b.shape:
        return {
            "shape_a": list(a.shape),
            "shape_b": list(b.shape),
            "differences": max(a.size, b.size, 1),
            "outcome": "differs",
        }
    nan_a, nan_b = np.isnan(a), np.isnan(b)
    one_nan = int((nan_a ^ nan_b).sum())
    both = ~nan_a & ~nan_b
    over = int((np.abs(a - b)[both] > tolerance_mm).sum())
    result = {
        "shape": list(a.shape),
        "cells": int(a.size),
        "tolerance_mm": tolerance_mm,
        "cells_over_tolerance": over,
        "nan_mismatch": one_nan,
        "nan_both": int((nan_a & nan_b).sum()),
        "max_abs_difference_mm": round(float(np.abs(a - b)[both].max()), 6) if both.any() else None,
        "differences": over + one_nan,
    }
    result["outcome"] = compare.outcome(result)
    return result


def rain_faults(loaded: np.ndarray) -> dict[str, np.ndarray]:
    """Deliberate faults on a copy of the loaded rain: hours shifted by one; one cell + 1 mm."""
    shifted = np.roll(np.asarray(loaded, dtype="float64"), 1, axis=0)
    perturbed = np.asarray(loaded, dtype="float64").copy()
    t, i, j = np.argwhere(np.isfinite(perturbed))[0]
    perturbed[t, i, j] += 1.0
    return {"hours shifted by one": shifted, "one cell plus 1 mm": perturbed}


# --- second readers ------------------------------------------------------------------------------


def second_reader_marks(csv: Path, loaded: list[dict]) -> dict[str, Any]:
    try:
        from flood_lab.reference import usgs_hwm as reader
    except ImportError as error:
        return {"outcome": "not checked", "why": f"reference.usgs_hwm not importable: {error}"}
    other = reader.marks(csv)
    result = compare_marks(loaded, other)
    fault = compare_marks(with_height_in_feet(loaded), other)
    result["deliberate_fault"] = {
        "rule broken": "one height above ground left in feet",
        "outcome": fault["outcome"],
        "differences": fault["differences"],
    }
    return result


def second_reader_rain(root: Path) -> dict[str, Any]:
    try:
        from flood_lab.reference import mrms as reader
    except ImportError as error:
        return {"outcome": "not checked", "why": f"reference.mrms not importable: {error}"}
    import xarray as xr

    with xr.open_dataset(root / MRMS_LOADED, engine="h5netcdf") as ds:
        loaded = ds["precip"].values.astype("float64")
        times = pd.to_datetime(ds["time"].values).to_pydatetime()
        lats, lons = ds["lat"].values.astype("float64"), ds["lon"].values.astype("float64")
    end_times = [t.replace(tzinfo=UTC) for t in times]
    other = np.asarray(reader.read_window(root / MRMS_RAW, end_times, lats, lons))
    tolerance = float(reader.TOLERANCE_MM)
    result = compare_rain(loaded, other, tolerance)
    result["window"] = [end_times[0].isoformat(), end_times[-1].isoformat()]
    result["deliberate_faults"] = {
        name: compare_rain(broken, other, tolerance)["outcome"]
        for name, broken in rain_faults(loaded).items()
    }
    return result


# --- reading the runs ----------------------------------------------------------------------------


def _read(path: Path) -> np.ndarray:
    import rasterio

    with rasterio.open(path) as src:
        return src.read(1)


def run_rasters(run: Path, root: Path) -> dict[str, np.ndarray]:
    """Peak level (5 m), raw and masked depth, ground and footprints (1 m) of one run."""
    masked, bld, ground = at_assets.masked_depth(run, root)
    zsmax = _read(run / "zsmax.tif").astype("float64")
    k = int(round(GRID.cell))
    level = np.repeat(np.repeat(zsmax, k, axis=0), k, axis=1)
    d = level - ground
    raw = np.where(np.isfinite(d), np.maximum(d, 0.0), 0.0)
    open_ground = np.where(bld, np.nan, masked)
    return {
        "zsmax": zsmax,
        "depth": raw,
        "masked": masked,
        "open": open_ground,
        "ground": ground,
        "bld": bld,
    }


def mark_rows(marks: list[dict], r: dict[str, np.ndarray], frame) -> list[dict[str, Any]]:
    k = int(round(GRID.cell))
    rows = []
    for m in marks:
        x, y = m["easting_m"], m["northing_m"]
        pr, pc = pixel_of(x, y)
        r5, c5 = pr // k, pc // k
        zs = r["zsmax"][r5, c5]
        level = None if not np.isfinite(zs) else round(float(zs), 3)
        depth = round(float(r["depth"][pr, pc]), 3)
        ground = round(float(r["ground"][pr, pc]), 3)
        h, elev = m["height_above_ground_m"], m["elev_navd88_m"]
        surveyed_ground = round(elev - h, 4) if h is not None and elev is not None else None
        flags = mark_flags(
            m,
            frame_reasons(frame, r5, c5),
            bool(r["bld"][pr, pc]),
            bool(np.isnan(r["masked"][pr, pc])) and not frame.standing[r5, c5],
        )
        rows.append(
            {
                "hwm_id": m["hwm_id"],
                "site_no": m["site_no"],
                "easting_m": x,
                "northing_m": y,
                "quality": m["quality"],
                "uncertainty_m": m["uncertainty_m"],
                "surveyed_level_navd88_m": elev,
                "surveyed_height_m": h,
                "surveyed_ground_navd88_m": surveyed_ground,
                "model_level_navd88_m": level,
                "model_ground_navd88_m": ground,
                "model_depth_m": depth,
                "model_depth_max_within_10m_m": near_max(r["open"], x, y, NEAR_M),
                "level_error_m": None if level is None or elev is None else round(level - elev, 3),
                "depth_error_m": None if h is None else round(depth - h, 3),
                "ground_error_m": None
                if surveyed_ground is None
                else round(ground - surveyed_ground, 3),
                "cell_dry": level is None,
                "flags": flags,
            }
        )
    return rows


def profiles(events_csv: Path, sensor_id: str, local_day: str) -> list[dict[str, Any]]:
    """The publisher's depth profile of each event of a sensor on a day (GMT start + seconds)."""
    raw = pd.read_csv(events_csv, dtype={"sensor_id": "string"})
    raw = raw[raw["sensor_id"] == sensor_id]
    if raw.empty:
        return []
    raw = raw[localtime.local_day(raw["flood_start_time"]).to_numpy() == local_day]
    out = []
    for _, e in raw.iterrows():
        depth = json.loads(e["flood_profile_depth_inches"])
        secs = json.loads(e["flood_profile_time_secs"])
        out.append(
            {
                "start_utc": pd.Timestamp(e["flood_start_time"], tz="UTC"),
                "seconds": secs,
                "depth_m": [v * floodnet.INCH_M for v in depth],
            }
        )
    return out


def sensor_rows(
    sensors: pd.DataFrame, r: dict[str, np.ndarray], frame, storm: str
) -> list[dict[str, Any]]:
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    k = int(round(GRID.cell))
    out = []
    for _, s in sensors.iterrows():
        x, y = to_utm.transform(float(s["longitude"]), float(s["latitude"]))
        pr, pc = pixel_of(x, y)
        r5, c5 = pr // k, pc // k
        measured = None if pd.isna(s["peak_depth_m"]) else round(float(s["peak_depth_m"]), 3)
        model = round(float(r["depth"][pr, pc]), 3)
        near = near_max(r["open"], x, y, NEAR_M)
        out.append(
            {
                "storm": storm,
                "sensor_id": s["sensor_id"],
                "easting_m": round(x, 2),
                "northing_m": round(y, 2),
                "recorded": bool(s["recorded"]),
                "measured_peak_m": measured,
                "model_depth_m": model,
                "model_depth_max_within_10m_m": near,
                "error_m": None if measured is None else round(model - measured, 3),
                "error_near_m": None
                if measured is None or near is None
                else round(near - measured, 3),
                "flags": mark_flags(
                    {},
                    frame_reasons(frame, r5, c5),
                    bool(r["bld"][pr, pc]),
                    bool(np.isnan(r["masked"][pr, pc])) and not frame.standing[r5, c5],
                ),
            }
        )
    return out


# --- figures -------------------------------------------------------------------------------------


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _png(figure, name: str) -> str:
    plt = _plt()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=DPI, metadata={"Software": None}, facecolor="white")
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".png.part")
    part.write_bytes(buffer.getvalue())
    part.replace(path)
    plt.close(figure)
    return f"{REL}/{name}"


def figure_scatter(rows: list[dict], summary: dict) -> str:
    plt = _plt()
    figure, axes = plt.subplots(1, 2, figsize=(11, 5.4))
    panels = (
        ("depth", "surveyed_height_m", "model_depth_m", "Inundation depth at the mark, m"),
        ("level", "surveyed_level_navd88_m", "model_level_navd88_m", "Water level, m NAVD88"),
    )
    for axis, (what, obs, mod, label) in zip(axes, panels, strict=True):
        pts = [(r[obs], r[mod], bool(r["flags"])) for r in rows if r[obs] is not None]
        shown = [(o, m, f) for o, m, f in pts if m is not None]
        values = [v for o, m, _ in shown for v in (o, m)]
        lo, hi = (min(values), max(values)) if values else (0.0, 1.0)
        pad = 0.1 * (hi - lo or 1.0)
        lo, hi = (-0.05 if what == "depth" else lo - pad), hi + pad
        axis.plot([lo, hi], [lo, hi], color="#333333", linewidth=1, zorder=1, label="1:1")
        band = KASAEI["rmse_calibrated_m"]
        axis.fill_between(
            [lo, hi],
            [lo - band, hi - band],
            [lo + band, hi + band],
            color="#e0e0e0",
            zorder=0,
            label="±0.20 m (Kasaei et al. 2025, calibrated, fitted)",
        )
        for flagged, colour, name in ((False, MODEL, "mark"), (True, FLAG_GREY, "flagged mark")):
            sel = [(o, m) for o, m, f in shown if f == flagged]
            if sel:
                axis.scatter(
                    *zip(*sel, strict=True),
                    s=64,
                    color=colour,
                    edgecolors="white",
                    linewidths=2,
                    zorder=3,
                    label=name,
                )
        dry = [o for o, m, _ in pts if m is None]
        if dry:
            axis.text(
                0.02,
                0.02,
                f"{len(dry)} mark(s) in cells the model never wets: no level",
                transform=axis.transAxes,
                fontsize=8,
                color="#555555",
            )
        a = summary["all"][f"{what}_per_mark"]
        u = summary["unflagged"][f"{what}_per_mark"]
        text = (
            f"all marks: n={a['n']}, bias {a['bias_m']:+.2f} m, RMSE {a['rmse_m']:.2f} m"
            if a["n"]
            else "all marks: none"
        )
        text += (
            f"\nunflagged: n={u['n']}, bias {u['bias_m']:+.2f} m, RMSE {u['rmse_m']:.2f} m"
            if u["n"]
            else "\nunflagged: none"
        )
        axis.text(
            0.02,
            0.97,
            text,
            transform=axis.transAxes,
            va="top",
            fontsize=8.5,
            bbox={"fc": "white", "ec": "#cccccc", "pad": 3},
        )
        axis.set_xlim(lo, hi)
        axis.set_ylim(lo, hi)
        axis.set_aspect("equal")
        axis.set_xlabel(f"Surveyed (USGS high-water mark): {label}", fontsize=9)
        axis.set_ylabel(f"Modelled (Ida replay, 30 mm/h loss): {label}", fontsize=9)
        axis.grid(color="#eeeeee", linewidth=0.8, zorder=0)
        axis.tick_params(labelsize=8)
        axis.legend(fontsize=7.5, frameon=True, loc="upper left", bbox_to_anchor=(0.0, 0.86))
    figure.suptitle(
        "Ida, 1 Sep 2021: modelled against surveyed at the high-water marks in the square",
        fontsize=10,
    )
    figure.tight_layout()
    return _png(figure, "marks_scatter.png")


def figure_sensors(rows: list[dict], traces: dict[tuple[str, str], list[dict]]) -> str:
    plt = _plt()
    n = len(rows)
    cols = 4
    nrows = max(1, math.ceil(n / cols))
    figure, axes = plt.subplots(nrows, cols, figsize=(13, 3.0 * nrows), squeeze=False)
    for axis, r in zip(axes.ravel(), rows, strict=False):
        events = traces.get((r["storm"], r["sensor_id"]), [])
        for e in events:
            t = [e["start_utc"] + pd.Timedelta(seconds=s) for s in e["seconds"]]
            axis.plot(t, e["depth_m"], color=OBSERVED, linewidth=2, label="measured (FloodNet)")
        axis.axhline(r["model_depth_m"], color=MODEL, linewidth=2, label="modelled peak at pixel")
        if r["model_depth_max_within_10m_m"] is not None:
            axis.axhline(
                r["model_depth_max_within_10m_m"],
                color=MODEL,
                linewidth=1.2,
                linestyle="--",
                label="modelled, deepest within 10 m",
            )
        if not events:
            axis.text(
                0.5,
                0.6,
                "none recorded",
                transform=axis.transAxes,
                ha="center",
                fontsize=9,
                color="#555555",
            )
            axis.set_xticks([])
        else:
            axis.tick_params(axis="x", labelsize=7, rotation=30)
        top = max(
            [r["model_depth_m"], r["model_depth_max_within_10m_m"] or 0]
            + [max(e["depth_m"]) for e in events]
            + [0.1]
        )
        axis.set_ylim(0, top * 1.2)
        axis.set_title(f"{r['storm']}\n{r['sensor_id']}", fontsize=7.5)
        axis.set_ylabel("depth, m", fontsize=8)
        axis.tick_params(axis="y", labelsize=7)
        axis.grid(axis="y", color="#eeeeee")
    for axis in axes.ravel()[n:]:
        axis.set_axis_off()
    handles, labels = [], []
    for axis in axes.ravel():
        for h, lab in zip(*axis.get_legend_handles_labels(), strict=True):
            if lab not in labels:
                handles.append(h)
                labels.append(lab)
    figure.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False)
    figure.suptitle(
        "FloodNet sensors in the square in service on the day: measured depth through "
        "the event (times UTC) and the modelled peak",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.96))
    return _png(figure, "sensors.png")


def figure_map(runs: dict[str, dict], marks: list[dict], sensors: list[dict], study) -> str:
    from matplotlib.colors import ListedColormap, TwoSlopeNorm

    plt = _plt()
    figure, axes = plt.subplots(1, 3, figsize=(17, 6.0), layout="constrained")
    first_of_site: dict[str, int] = {}
    errors_of_site: dict[str, list[float]] = {}
    for m in marks:
        first_of_site[m["site_no"]] = min(first_of_site.get(m["site_no"], m["hwm_id"]), m["hwm_id"])
        errors_of_site.setdefault(m["site_no"], []).append(m["depth_error_m"])
    site_text = {
        k: " / ".join("–" if e is None else f"{e:+.2f}" for e in v)
        for k, v in errors_of_site.items()
    }
    pts = [(m["easting_m"], m["northing_m"]) for m in marks] + [
        (s["easting_m"], s["northing_m"]) for s in sensors
    ]
    mx, my = float(np.median([p[0] for p in pts])), float(np.median([p[1] for p in pts]))
    near = [p for p in pts if math.hypot(p[0] - mx, p[1] - my) <= ZOOM_RADIUS_M]
    xs, ys = zip(*near, strict=True)
    zoom = (min(xs) - 120, max(xs) + 120, min(ys) - 120, max(ys) + 120)
    norm = TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0)
    cmap = plt.get_cmap("RdBu_r")
    blues = ListedColormap(("#c6dbef", "#6baed6", "#2171b5", "#08306b"))
    from matplotlib.colors import BoundaryNorm

    dnorm = BoundaryNorm([0.05, 0.1016, 0.3048, 0.6096, 99.0], blues.N)
    full = (GRID.west, GRID.east, GRID.south, GRID.north)
    panels = (
        ("ida_2021", full, "Ida: depth error at marks and sensors, whole square"),
        ("ida_2021", zoom, "Ida: Wallabout area"),
        ("sep29_2023", zoom, "29 Sep 2023: Wallabout area (sensors only)"),
    )
    scale = None
    for axis, (storm, bounds, title) in zip(axes, panels, strict=True):
        r = runs[storm]
        step = 5 if bounds == full else 1
        c0, c1 = int(bounds[0] - GRID.west), int(bounds[1] - GRID.west)
        r0, r1 = int(GRID.north - bounds[3]), int(GRID.north - bounds[2])
        c0, r0 = max(c0, 0), max(r0, 0)
        win = (slice(r0, r1, step), slice(c0, c1, step))
        extent = (GRID.west + c0, GRID.west + c1, GRID.north - r1, GRID.north - r0)
        axis.imshow(
            np.where(r["bld"][win], 1.0, np.nan),
            extent=extent,
            cmap=ListedColormap(["#d9d9d9"]),
            vmin=0,
            vmax=1,
            interpolation="nearest",
        )
        d = r["masked"][win]
        axis.imshow(
            np.where(d >= 0.05, d, np.nan),
            extent=extent,
            cmap=blues,
            norm=dnorm,
            interpolation="nearest",
        )
        for g in study.geometry:
            for poly in getattr(g, "geoms", [g]):
                axis.plot(*poly.exterior.xy, color="black", linewidth=0.6)
        if storm == "ida_2021":
            for m in marks:
                e = m["depth_error_m"]
                scale = axis.scatter(
                    m["easting_m"],
                    m["northing_m"],
                    c=[0.0 if e is None else e],
                    cmap=cmap,
                    norm=norm,
                    s=80,
                    marker="o",
                    edgecolors="black",
                    linewidths=0.8,
                    zorder=4,
                )
                if bounds != full and m["hwm_id"] == first_of_site[m["site_no"]]:
                    axis.annotate(
                        f"{m['site_no'][-5:]}: {site_text[m['site_no']]}",
                        (m["easting_m"], m["northing_m"]),
                        xytext=(-8, 9),
                        textcoords="offset points",
                        fontsize=7,
                        ha="right",
                        bbox={"fc": "white", "ec": "none", "alpha": 0.8, "pad": 1},
                    )
        for s in sensors:
            if s["storm"] != storm:
                continue
            e = s["error_m"]
            axis.scatter(
                s["easting_m"],
                s["northing_m"],
                c=[0.0 if e is None else e],
                cmap=cmap,
                norm=norm,
                s=90,
                marker="s",
                edgecolors="black",
                linewidths=0.8 if e is not None else 2.0,
                zorder=4,
            )
            if bounds != full:
                label = f"{e:+.2f}" if e is not None else "none recorded"
                axis.annotate(
                    label,
                    (s["easting_m"], s["northing_m"]),
                    xytext=(5, -10),
                    textcoords="offset points",
                    fontsize=7,
                )
        if bounds == full:
            axis.add_patch(
                plt.Rectangle(
                    (zoom[0], zoom[2]),
                    zoom[1] - zoom[0],
                    zoom[3] - zoom[2],
                    fill=False,
                    edgecolor="#333333",
                    linestyle="--",
                )
            )
        axis.set_xlim(bounds[0], bounds[1])
        axis.set_ylim(bounds[2], bounds[3])
        axis.set_aspect("equal")
        axis.set_title(title, fontsize=9.5)
        axis.tick_params(labelsize=7)
        axis.ticklabel_format(style="plain", useOffset=False)
        axis.set_xlabel("Easting, m (UTM 18N)", fontsize=8)
    axes[0].set_ylabel("Northing, m", fontsize=8)
    if scale is not None:
        bar = figure.colorbar(scale, ax=list(axes), shrink=0.8)
        bar.set_label(
            "depth error, model less observed, m (circle: mark; square: sensor; "
            "thick square: none recorded)",
            fontsize=8,
        )
    figure.suptitle(
        "Modelled maximum inundation depth (blues: 0.05 m, 4 in, 1 ft, 2 ft; grey: "
        "buildings) with the errors at the observations",
        fontsize=10,
    )
    return _png(figure, "error_map.png")


# --- main ----------------------------------------------------------------------------------------


def _version(name: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def main() -> int:
    import geopandas as gpd

    root = cache.root()
    freeze = tomllib.loads(FREEZE.read_text())
    replays = freeze["runs"]["replays"]
    csv = root / usgs_hwm.FILE
    for need in (csv, root / floodnet.EVENTS, root / floodnet.SENSORS, root / MRMS_LOADED):
        if not need.exists():
            print(f"missing input {need}; nothing written", file=sys.stderr)
            return 1
    for storm, *_ in STORMS:
        if not (root / "f3" / "runs" / replays[storm] / "zsmax.tif").exists():
            print(f"run {replays[storm]} has no zsmax.tif; nothing written", file=sys.stderr)
            return 1

    table = usgs_hwm.marks(csv)
    loaded = usgs_hwm.as_rows(table)
    marks_check = second_reader_marks(csv, loaded)
    rain_check = second_reader_rain(root)

    frame = calibration.Frame.load(root, STUDY_AREA)
    runs = {s: run_rasters(root / "f3" / "runs" / replays[s], root) for s, *_ in STORMS}
    in_square = [m for m in loaded if m["in_square"]]
    marks = mark_rows(in_square, runs["ida_2021"], frame)
    summary = fv1_summary(marks)
    rmse = summary["all"]["depth_per_mark"]["rmse_m"]
    statement = fv4_statement(rmse)

    events = floodnet.events(root / floodnet.EVENTS, root / floodnet.SENSORS)
    sensors, traces, served = [], {}, {}
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    for storm, day, _label in STORMS:
        s = floodnet.storm_sensors(events, root / floodnet.SENSORS, day)
        x, y = to_utm.transform(s["longitude"].to_numpy(float), s["latitude"].to_numpy(float))
        x, y = np.asarray(x), np.asarray(y)
        inside = (x >= GRID.west) & (x < GRID.east) & (y >= GRID.south) & (y < GRID.north)
        s = s[inside]
        served[storm] = {"in_service": int(len(s)), "recorded": int(s["recorded"].sum())}
        rows = sensor_rows(s, runs[storm], frame, storm)
        sensors += rows
        for r in rows:
            traces[(storm, r["sensor_id"])] = profiles(root / floodnet.EVENTS, r["sensor_id"], day)
    recorded = [r for r in sensors if r["recorded"]]
    fv2 = {
        storm: {
            **served[storm],
            "at_pixel": error_stats([r["error_m"] for r in recorded if r["storm"] == storm]),
            "deepest_within_10m": error_stats(
                [r["error_near_m"] for r in recorded if r["storm"] == storm]
            ),
        }
        for storm, *_ in STORMS
    }
    profile_note = (
        "The cached FloodNet events table carries each event's depth profile "
        "(flood_profile_depth_inches, flood_profile_time_secs); the panels draw it as published. "
        "Its peak is the loader's max_depth_inches."
    )

    study = gpd.read_file(STUDY_AREA).to_crs("EPSG:32618")
    figures = [
        figure_scatter(marks, summary),
        figure_sensors(sensors, traces),
        figure_map(runs, marks, sensors, study),
    ]

    def judged(result: dict) -> bool | None:
        return {"confirmed": True, "differs": False}.get(result["outcome"])

    faults = []
    if "deliberate_fault" in marks_check:
        faults.append(
            (
                "marks: " + marks_check["deliberate_fault"]["rule broken"],
                marks_check["deliberate_fault"]["outcome"],
            )
        )
    for name, outcome in rain_check.get("deliberate_faults", {}).items():
        faults.append((f"MRMS: {name}", outcome))
    checks = [
        Check(
            name="second reader: USGS high-water marks",
            rule="reference.usgs_hwm recomputes every loaded mark: identifiers, datum, quality, "
            "date and in_square equal; metres within 1e-4, eastings and northings within 0.01 m",
            passed=judged(marks_check),
            value={k: marks_check.get(k) for k in ("outcome", "differences", "rows_a", "rows_b")},
            note=marks_check.get("why", ""),
        ),
        Check(
            name="second reader: MRMS rain of the Ida replay window",
            rule="reference.mrms decodes the raw hours again; no cell differs by more than its "
            "TOLERANCE_MM and NaN matches NaN",
            passed=judged(rain_check),
            value={
                k: rain_check.get(k)
                for k in ("outcome", "differences", "cells", "tolerance_mm", "window")
            },
            note=rain_check.get("why", ""),
        ),
        Check(
            name="deliberate faults are caught",
            rule="each broken copy of the loaded values differs from the second reader (FS4); "
            "also in tests/flood/test_f5_validation.py",
            passed=None
            if not faults or len(faults) < 3
            else all(o == "differs" for _, o in faults),
            value=dict(faults),
            note="" if len(faults) == 3 else "not every second reader was available",
        ),
        Check(
            name="FV1: model against the high-water marks (reported, not judged)",
            rule="level and depth error per mark and per site, with and without flagged marks",
            passed=None,
            value={
                "depth_rmse_m": rmse,
                "level_rmse_m": summary["all"]["level_per_mark"]["rmse_m"],
            },
        ),
        Check(
            name="FV4: depth RMSE at the marks against 0.5 m",
            rule="if depth RMSE > 0.5 m the record states that substation-level depth claims are "
            "not supported; no parameter is changed",
            passed=None,
            value=rmse,
            threshold=FV4_RMSE_M,
            proposed=True,
            note=statement,
        ),
        Check(
            name="FV2: model against the FloodNet sensors (reported, not judged)",
            rule="every sensor in the square in service on the day; modelled depth at the pixel "
            "and the deepest within 10 m against the measured peak",
            passed=None,
            value=fv2,
        ),
    ]
    captions = {
        "marks_scatter.png": (
            "Ida replay (frozen F3 model, constant loss rate 30 mm/h) against the 11 USGS "
            "high-water marks in the square (6 sites). Left: inundation depth at the mark's 1 m "
            "pixel (modelled water level less ground level, ground never below the cell's "
            "lowest sub-grid level) against the surveyed height above ground. Right: modelled "
            "peak water level of the 5 m cell against the surveyed mark elevation, NAVD88. "
            "Grey band: ±0.20 m, the error Kasaei et al. 2025 report after calibrating on 8 marks "
            "(a fitted figure, not an independent test; 0.40 m before calibration). Limit: "
            "marks are phone fixes (positions to a few metres) and were surveyed weeks later."
        ),
        "sensors.png": (
            "FloodNet sensors in the square in service on each storm day: measured depth "
            "through each event as published (times UTC), the modelled peak at the sensor's "
            "pixel (solid) and the deepest modelled depth on open ground within 10 m (dashed; "
            "sensor positions are approximate). Limit: the model gives a peak, not a time "
            "series, here."
        ),
        "error_map.png": (
            "Modelled maximum inundation depth on read open ground with the depth error, model "
            "less observed, at each mark (circles, Ida) and sensor (squares; thick edge: in "
            "service, none recorded)."
        ),
    }
    root_inputs = [
        Input.of(csv, root=root),
        Input.of(root / usgs_hwm.DICTIONARY, root=root),
        Input.of(root / floodnet.EVENTS, root=root),
        Input.of(root / floodnet.SENSORS, root=root),
        Input.of(root / MRMS_LOADED, root=root),
        *[
            Input.of(root / "f3" / "model" / n, root=root)
            for n in ("dem_model_1m.tif", "buildings_1m.tif", "zb_5m.tif", "pits_1m.tif")
        ],
        Input.of(root / "terrain" / "water_1m.tif", root=root),
        *[
            Input.of(root / "f3" / "runs" / replays[s] / n, root=root)
            for s, *_ in STORMS
            for n in ("spec.json", "zsmax.tif")
        ],
    ]
    record = Record(
        id=RECORD_ID,
        stage="F5",
        title="Validation against observations: Ida high-water marks and FloodNet sensors",
        inputs=[
            Input.of(FREEZE, root=paths.ROOT),
            Input.of(STUDY_AREA, root=paths.ROOT),
            *root_inputs,
        ],
        parameters=[
            Parameter(
                "constant_loss_rate_mm_per_h",
                freeze["allowance_mm_per_h"],
                freeze["tag"],
                "frozen F3 value; not changed (FV4)",
            ),
            Parameter("near_m", NEAR_M, "P", "sensor positions are approximate"),
            Parameter("fv4_rmse_m", FV4_RMSE_M, "P", "requirements FV4"),
            Parameter("max_uncertainty_m", MAX_UNCERTAINTY_M, "P", "flag above"),
            Parameter("max_roof_share", at_assets.MAX_ROOF_SHARE, "P", "at_assets"),
            Parameter(
                "kasaei_rmse_calibrated_m", KASAEI["rmse_calibrated_m"], "S", KASAEI["citation"]
            ),
            Parameter(
                "kasaei_rmse_before_calibration_m",
                KASAEI["rmse_before_calibration_m"],
                "S",
                KASAEI["citation"],
            ),
            Parameter("foot_m", usgs_hwm.FT_M, "S", "international foot; the dictionary says feet"),
        ],
        numbers={
            "marks_in_file": len(loaded),
            "sites_in_file": len({m["site_no"] for m in loaded}),
            "marks_in_square": len(in_square),
            "sites_in_square": len({m["site_no"] for m in in_square}),
            "marks_flagged": sum(1 for m in marks if m["flags"]),
            "depth_rmse_m": rmse,
            "fv4_exceeded": None if rmse is None else rmse > FV4_RMSE_M,
        },
        tables={
            "fv1_summary": summary,
            "fv1_marks": marks,
            "fv2_summary": fv2,
            "fv2_sensors": sensors,
            "second_reader_marks": marks_check,
            "second_reader_mrms": rain_check,
            "published_comparison": KASAEI,
            "captions": captions,
        },
        checks=checks,
        figures=figures,
        notes=[
            "F5 first part (FV1, FV2, FV4; FV3 and FV5 later). Model against observations is "
            "reported, not judged. " + statement,
            "Published comparison: " + KASAEI["reading"] + f" ({KASAEI['citation']}).",
            "Vertical datum: zsmax is the solver's water level in metres NAVD88, the datum of the "
            "model terrain (USGS 3DEP 1 m, NAVD88) and of the water-level boundary (0 m NAVD88); "
            "the marks are surveyed in NAVD88 (feet, converted with 0.3048).",
            "Marks: horizontal positions are phone or map fixes (WGS84 from digital map), so a "
            "mark's 1 m pixel may be a few metres off; the deepest modelled depth within 10 m is "
            "given beside the pixel's for that reason, not used in the statistics.",
            profile_note,
            *(f"{k}: {v}" for k, v in captions.items()),
        ],
    )
    record.software = record.software | {
        n: _version(n) for n in ("numpy", "rasterio", "geopandas", "matplotlib", "pyproj")
    }
    path = record.write(paths.RECORDS)
    print(
        json.dumps(
            {
                "record": str(path),
                "fv1": summary,
                "fv2": fv2,
                "fv4": statement,
                "marks_reader": marks_check.get("outcome"),
                "mrms_reader": rain_check.get("outcome"),
                "faults": dict(faults),
                "written": datetime.now(UTC).isoformat(),
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
