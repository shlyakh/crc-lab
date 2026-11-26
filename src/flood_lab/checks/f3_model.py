"""F3 visual test: the solver model, the drainage allowance and the two replays (FH2 to FH4, FH8).

    uv run --with matplotlib python -m flood_lab.checks.f3_model

Offline. Reads the frozen allowance and the names of the runs from
``src/flood_lab/hazard/allowance.toml`` (written when the allowance is frozen) and every run folder
it names under ``<cache>/f3/runs/`` (``spec.json``, ``run_run.json``, ``balance.json``,
``zsmax.tif``). A run's scenario is read from its ``spec.json`` (the rain rate, or gridded rain
for a replay), never from its label. A run that is named but has no ``balance.json`` and
``zsmax.tif`` yet is recorded as "not run"; no value is put in its place.

Writes the record ``site/flood/tests/records/f3-model.json`` and PNG figures under
``docs/flood/figures/f3/``, without timestamps. Without the freeze file it writes nothing and exits
with code 1. matplotlib is supplied on the command line (FG4) and imported only to draw, so the
helpers here can be tested without it.
"""

from __future__ import annotations

import io
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import numpy as np

from flood_lab import cache, domain, paths
from flood_lab.hazard import at_assets, calibration
from flood_lab.records import Check, Input, Parameter, Record

FREEZE = Path(__file__).resolve().parents[1] / "hazard" / "allowance.toml"
OUT = paths.FIGURES / "f3"
REL = "docs/flood/figures/f3"
RECORD_ID = "f3-model"
STUDY_AREA = paths.SITE / "data" / "study_area.geojson"
SUBSTATIONS = paths.SITE / "data" / "substations.geojson"
NTA = "nyc-nta-2020/nta2020.geojson"
FOOTPRINTS = "nyc-building-footprints/footprints-box.geojson"
ATLAS14 = "f3/atlas14/table.json"
MRMS_SUMMARY = "f3/mrms/summary.json"
FORCING = "f3/forcing"
#: NTA 2020 code of the Brooklyn Navy Yard, left out in a sensitivity of the calibration
NAVY_YARD = "BK0261"
#: FH8: the water balance closes within this share of the rain [P] (requirements FH8)
BALANCE_MAX_SHARE = 0.01
#: critical success index the calibration should reach at each map [P] proposed (plan F3)
CSI_MIN = 0.5
#: the extreme scenario is checked against this city map (2080 sea level)
EXTREME_MAP = "extreme-2080"
#: depth classes of the figures, metres: wet, the city's 4 in and 1 ft
DEPTH_BREAKS = (domain.WET_M, calibration.SHALLOW_M, calibration.DEEP_M)
#: FP7 defines no colours yet; three steps of matplotlib's sequential "Blues" [P]
DEPTH_COLOURS = ("#c6dbef", "#6baed6", "#08519c")
HIT, MISS, FALSE_ALARM, DRY = "#2563eb", "#f59e0b", "#dc2626", "#d9d9d9"
DPI = 100
#: Atlas 14 rows read, and the hours each stands for
ATLAS_DURATIONS = (("30-min", 0.5), ("60-min", 1.0), ("2-hr", 2.0))
FIGURE_NAMES = (
    "calibration_curve.png",
    "hit_miss.png",
    "water_balance.png",
    "replays.png",
    "atlas14.png",
    "sensitivity.png",
)


# --- the freeze file and the run folders ---------------------------------------------------------


class FreezeError(Exception):
    """The freeze file is missing or lacks what the check needs."""


#: "frozen" once Yuri has frozen the value; "proposed" while ``frozen_on`` says "not frozen"
STATE = "frozen"


def state_of(freeze: dict[str, Any]) -> str:
    return "proposed" if str(freeze.get("frozen_on", "")).startswith("not frozen") else "frozen"


def load_freeze(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FreezeError(
            f"{path} does not exist: the allowance is not frozen yet, so there is nothing to "
            "check. Nothing was written."
        )
    freeze = tomllib.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in ("allowance_mm_per_h", "tag", "runs") if k not in freeze]
    runs = freeze.get("runs", {})
    missing += [f"runs.{k}" for k in ("calibration", "frozen") if k not in runs]
    if missing:
        raise FreezeError(f"{path} lacks {', '.join(missing)}. Nothing was written.")
    return freeze


def referenced_labels(runs: dict[str, Any]) -> list[str]:
    """Every run label the freeze file names, in the order it names them, each once."""
    found: list[str] = list(runs.get("calibration", []))
    found += list(runs.get("frozen", {}).values())
    if runs.get("extreme_check"):
        found.append(runs["extreme_check"])
    for table in ("duration", "boundary_level", "replays"):
        found += list(runs.get(table, {}).values())
    for pair in runs.get("monotonicity", []):
        found += list(pair)
    return list(dict.fromkeys(found))


def scenario_of(spec: dict[str, Any]) -> str:
    """limited, moderate or extreme by the uniform rain rate; replay for gridded rain."""
    rain = spec.get("rain", {})
    if rain.get("kind") == "gridded":
        return "replay"
    rate = rain.get("mm_per_h")
    if rate is None:
        return "unknown"
    for name in calibration.INTENSITY_IN_H:
        if abs(float(rate) - calibration.intensity_mm_h(name)) < 5e-4:
            return name
    return "other"


def city_map_of(scenario: str) -> str | None:
    if scenario in calibration.CALIBRATION_MAPS:
        return calibration.CALIBRATION_MAPS[scenario]
    return EXTREME_MAP if scenario == "extreme" else None


def load_run(runs_dir: Path, label: str) -> dict[str, Any] | None:
    """A finished run's files, or None when the folder or one of its outputs is missing."""
    folder = runs_dir / label
    needed = [folder / n for n in ("spec.json", "balance.json", "zsmax.tif")]
    if not all(p.exists() for p in needed):
        return None
    spec = json.loads((folder / "spec.json").read_text())
    solver_path = folder / "run_run.json"
    solver = json.loads(solver_path.read_text()) if solver_path.exists() else {}
    return {
        "label": label,
        "folder": folder,
        "spec": spec,
        "balance": json.loads((folder / "balance.json").read_text()),
        "solver": solver,
        "scenario": scenario_of(spec),
    }


def run_row(run: dict[str, Any]) -> dict[str, Any]:
    """One row of the runs table, every value read from the run's files."""
    spec, balance, solver = run["spec"], run["balance"], run["solver"]
    rain = spec.get("rain", {})
    parsed = solver.get("parsed", {})
    simulated_h = spec["simulated_s"] / 3600.0
    return {
        "label": run["label"],
        "scenario": run["scenario"],
        "allowance_mm_per_h": spec["qinf_mm_per_h"],
        "rain_mm_per_h": rain.get("mm_per_h"),
        "rain_file": Path(rain["file"]).name if rain.get("file") else None,
        "rain_h": rain["hours"] if "hours" in rain else round(simulated_h - spec["after_h"], 3),
        "after_h": spec["after_h"],
        "boundary_level_m": spec.get("boundary_level_m"),
        "simulated_h": round(simulated_h, 3),
        "wall_time_s": solver.get("wall_time_s"),
        "average_time_step_s": parsed.get("average_time_step_s"),
        "solver_finished": parsed.get("finished"),
        "sfincs_revision": parsed.get("sfincs_revision"),
        "rain_m3": round(balance["rain_m3"], 1),
        "drained_m3": round(balance["drained_m3"], 1),
        "stored_m3": round(balance["stored_m3"], 1),
        "out_m3": round(balance["out_m3"], 1),
        "residual_m3": round(balance["residual_m3"], 1),
        "residual_share_of_rain": balance["residual_share_of_rain"],
    }


def not_run(name: str, rule: str, label: str | None, what: str = "run") -> Check:
    named = f"'{label}'" if label else "none named"
    return Check(
        name, rule, None, note=f"not run: {what} {named} has no finished output in f3/runs"
    )


# --- Atlas 14 ------------------------------------------------------------------------------------


def return_period(label: str) -> float:
    """Years from a column label as printed: '10' (ARI) or "'1/10" (AEP)."""
    text = label.strip().lstrip("'")
    if "/" in text:
        num, den = text.split("/")
        return float(den) / float(num)
    return float(text)


def bracket(value: float, labels: list[str], depths: list[str]) -> dict[str, Any]:
    """Between which two tabulated columns a depth falls; no interpolation."""
    numbers = [float(d) for d in depths]
    if any(b < a for a, b in zip(numbers, numbers[1:], strict=False)):
        return {"placement": "not placed: tabulated depths decrease along the row"}
    if value < numbers[0]:
        return {"placement": f"below {labels[0]}", "next_depth": depths[0]}
    for i in range(len(numbers) - 1):
        if numbers[i] <= value < numbers[i + 1]:
            return {
                "placement": f"between {labels[i]} and {labels[i + 1]}",
                "between": [labels[i], labels[i + 1]],
                "depths": [depths[i], depths[i + 1]],
            }
    return {"placement": f"above {labels[-1]}", "last_depth": depths[-1]}


def atlas14_placement(table: dict[str, Any]) -> dict[str, Any]:
    """Each scenario's intensity, held for 30 min, 60 min and 2 h, placed on both series."""
    out: dict[str, Any] = {"units": table.get("units"), "series": {}}
    for series_name, series in table["series"].items():
        labels = list(series["return_periods"])
        header = series.get("csv_header", [])
        version = next((h for h in header if "Version" in h), None)
        rows = []
        for duration, hours in ATLAS_DURATIONS:
            row = series["durations"].get(duration)
            if row is None:
                rows.append({"duration": duration, "placement": "row not in the table"})
                continue
            cols = [c for c in labels if c in row]
            for scenario, inches in calibration.INTENSITY_IN_H.items():
                depth = round(inches * hours, 4)
                rows.append(
                    {
                        "duration": duration,
                        "scenario": scenario,
                        "intensity_in_h": inches,
                        "depth_in": depth,
                        **bracket(depth, cols, [row[c]["depth"] for c in cols]),
                    }
                )
        out["series"][series_name] = {
            "return_period_label": series.get("return_period_label"),
            "version": version,
            "volume": series.get("volume"),
            "version_number": series.get("version"),
            "region": series.get("region"),
            "service_point": series.get("service_point"),
            "rows": rows,
        }
    return out


# --- areas ---------------------------------------------------------------------------------------


def wet_areas(depth: np.ndarray, where: np.ndarray) -> dict[str, float]:
    cell_ha = domain.GRID.cell**2 / 1e4
    return {
        f"ge_{t}_m_ha": round(float(((depth >= t) & where).sum()) * cell_ha, 4)
        for t in DEPTH_BREAKS
    }


def depth_class_map(depth: np.ndarray) -> np.ndarray:
    """0 dry, 1 wet to under 4 in, 2 to under 1 ft, 3 at 1 ft and over."""
    out = np.zeros(depth.shape, dtype="uint8")
    for k, t in enumerate(DEPTH_BREAKS, start=1):
        out[depth >= t] = k
    return out


def model_wet_ha(result: dict[str, Any]) -> float:
    return round(result["model_shallow_ha"] + result["model_deep_ha"], 3)


def radar_totals(forcing: dict[str, Any] | None, summary: dict[str, Any] | None) -> dict:
    out: dict[str, Any] = {}
    if forcing is not None:
        rates = forcing["mean_rate_by_step_mm_h"]
        step_h = forcing["hours"] / len(rates) if rates else None
        out["forcing"] = {
            "tref_utc": forcing.get("tref"),
            "hours": forcing.get("hours"),
            "step_h": step_h,
            "square_mean_total_mm": round(sum(rates) * step_h, 3) if rates else None,
            "square_mean_peak_rate_mm_h": max(rates) if rates else None,
            "max_rate_mm_h": forcing.get("max_rate_mm_h"),
            "x_res_m": forcing.get("x_res_m"),
            "rule": forcing.get("rule"),
        }
    if summary is not None:
        hours = summary.get("hours", [])
        out["radar_box"] = {
            "unit": summary.get("unit"),
            "hours": len(hours),
            "first_end_utc": hours[0]["end_utc"] if hours else None,
            "last_end_utc": hours[-1]["end_utc"] if hours else None,
            "box_mean_total_mm": round(sum(h["box_mean_mm"] for h in hours), 3),
            "box_max_hour_mm": round(max((h["box_max_mm"] for h in hours), default=0.0), 3),
            "storm_total_mm": {
                k: round(v["value"], 2) for k, v in summary.get("storm_total_mm", {}).items()
            },
        }
    return out


def forcing_summary(
    spec: dict[str, Any], storm: str, root: Path
) -> tuple[dict | None, Path | None]:
    """The forcing summary JSON written beside the replay's rain file."""
    candidates = []
    if spec.get("rain", {}).get("file"):
        candidates.append(root / FORCING / f"{Path(spec['rain']['file']).stem}.json")
    candidates.append(root / FORCING / f"{storm}.json")
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text()), path
    return None, None


# --- figures -------------------------------------------------------------------------------------


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _png(figure, name: str) -> str:
    """Write a figure atomically, without the timestamp matplotlib would put in the file."""
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


def _study_bounds(land: np.ndarray, pad: int = 10) -> tuple[float, float, float, float]:
    rows, cols = np.nonzero(land)
    g = domain.GRID
    r0, r1 = max(rows.min() - pad, 0), min(rows.max() + 1 + pad, g.height)
    c0, c1 = max(cols.min() - pad, 0), min(cols.max() + 1 + pad, g.width)
    return g.west + c0 * g.cell, g.west + c1 * g.cell, g.north - r1 * g.cell, g.north - r0 * g.cell


def _map_axis(axis, bounds, title: str) -> None:
    axis.set_xlim(bounds[0], bounds[1])
    axis.set_ylim(bounds[2], bounds[3])
    axis.set_aspect("equal")
    axis.set_title(title, fontsize=9.5)
    axis.set_xlabel("Easting, m (UTM 18N)", fontsize=8)
    axis.set_ylabel("Northing, m", fontsize=8)
    axis.tick_params(labelsize=7)
    axis.ticklabel_format(style="plain", useOffset=False)
    axis.annotate(
        "N",
        xy=(0.96, 0.95),
        xytext=(0.96, 0.85),
        xycoords="axes fraction",
        ha="center",
        fontsize=9,
        arrowprops={"arrowstyle": "-|>", "color": "black"},
    )


def _outline(axis, geometry, **style) -> None:
    for poly in getattr(geometry, "geoms", [geometry]):
        if poly.geom_type == "Polygon":
            x, y = poly.exterior.xy
            axis.plot(x, y, **style)
        elif poly.geom_type in ("LineString", "LinearRing"):
            x, y = poly.xy
            axis.plot(x, y, **style)
        else:
            _outline(axis, poly, **style)


def figure_calibration(rows: list[dict], allowance: float) -> str:
    plt = _plt()
    figure, axes = plt.subplots(2, 2, figsize=(10.5, 7.4), sharex=True)
    for col, scenario in enumerate(calibration.CALIBRATION_MAPS):
        sel = sorted((r for r in rows if r["scenario"] == scenario), key=lambda r: r["allowance"])
        top, bottom = axes[0, col], axes[1, col]
        title = (
            f"{scenario.capitalize()} ({calibration.INTENSITY_IN_H[scenario]} in/h, "
            f"map {calibration.CALIBRATION_MAPS[scenario]})"
        )
        top.set_title(title, fontsize=9.5)
        if not sel:
            top.text(0.5, 0.5, "no calibration run", ha="center", transform=top.transAxes)
            bottom.text(0.5, 0.5, "no calibration run", ha="center", transform=bottom.transAxes)
            continue
        x = [r["allowance"] for r in sel]
        f = [r["filtered"] for r in sel]
        for key, colour, name in (
            ("shallow", DEPTH_COLOURS[1], "4 in to 1 ft"),
            ("deep", DEPTH_COLOURS[2], "1 ft and over"),
        ):
            top.plot(
                x, [v[f"model_{key}_ha"] for v in f], "o-", color=colour, label=f"model {name}"
            )
            top.axhline(f[0][f"city_{key}_ha"], color=colour, ls="--", lw=1.2, label=f"city {name}")
        top.set_ylim(bottom=0)
        top.set_ylabel("area on compared cells, ha", fontsize=8)
        top.legend(fontsize=7, loc="lower left")
        bottom.plot(x, [v["csi_wet"] for v in f], "o-", color="black", label="CSI wet, filtered")
        bottom.plot(
            x, [r["raw"]["csi_wet"] for r in sel], "s--", color="grey", label="CSI wet, raw"
        )
        bottom.plot(
            x, [v["csi_deep"] for v in f], "^:", color=DEPTH_COLOURS[2], label="CSI deep, filtered"
        )
        bottom.axhline(CSI_MIN, color="#dc2626", lw=0.8, ls=":", label=f"{CSI_MIN} (proposed)")
        bottom.set_ylim(0, 1)
        bottom.set_ylabel("critical success index", fontsize=8)
        bottom.set_xlabel("drainage allowance, mm/h", fontsize=8)
        bottom.legend(fontsize=7, loc="upper right")
        for axis in (top, bottom):
            axis.axvline(allowance, color="#16a34a", lw=1.5, alpha=0.7)
            axis.tick_params(labelsize=7)
        top.text(
            allowance,
            top.get_ylim()[1] * 0.98,
            f" {STATE} {allowance:g} mm/h",
            color="#16a34a",
            fontsize=7,
            va="top",
            ha="left",
        )
    figure.suptitle(
        "Calibration curve: modelled area per class against the drainage allowance", fontsize=10.5
    )
    figure.tight_layout()
    return _png(figure, "calibration_curve.png")


def figure_hit_miss(panels: list[dict], frame, study, bounds) -> str:
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    plt = _plt()
    g = domain.GRID
    figure, axes = plt.subplots(1, len(panels), figsize=(6.2 * len(panels), 6.6), squeeze=False)
    for axis, p in zip(axes[0], panels, strict=True):
        if p.get("classes") is None:
            axis.text(0.5, 0.5, f"{p['title']}\nnot run", ha="center", transform=axis.transAxes)
            axis.set_axis_off()
            continue
        m, c = p["classes"]["model"] >= 1, p["classes"]["city"] >= 1
        where = frame.compared
        shown = np.full(where.shape, np.nan)
        shown[where] = 0
        shown[where & m & c] = 1
        shown[where & ~m & c] = 2
        shown[where & m & ~c] = 3
        axis.imshow(
            shown,
            extent=(g.west, g.east, g.south, g.north),
            cmap=ListedColormap([DRY, HIT, MISS, FALSE_ALARM]),
            vmin=-0.5,
            vmax=3.5,
            interpolation="nearest",
        )
        _outline(axis, study, color="black", lw=0.6)
        _map_axis(axis, bounds, p["title"])
        r = p["result"]
        axis.legend(
            handles=[
                Patch(color=HIT, label=f"hit: {r['wet_hits']} cells"),
                Patch(color=MISS, label=f"miss (city wet only): {r['wet_misses']}"),
                Patch(
                    color=FALSE_ALARM, label=f"false alarm (model only): {r['wet_false_alarms']}"
                ),
                Patch(color=DRY, label="compared, dry in both"),
            ],
            loc="lower left",
            fontsize=7,
            framealpha=0.9,
        )
    figure.suptitle(
        f"Hit, miss and false alarm at the {STATE} allowance (wet = 4 in or more; model patches "
        "under a quarter acre removed)",
        fontsize=10,
    )
    figure.tight_layout()
    return _png(figure, "hit_miss.png")


def figure_balance(rows: list[dict]) -> str:
    plt = _plt()
    figure, axis = plt.subplots(figsize=(max(7.0, 1.0 + 0.9 * len(rows)), 4.8))
    keys = (
        ("rain_m3", "rain", "#1f77b4"),
        ("drained_m3", "drained", "#2ca02c"),
        ("stored_m3", "stored", "#ff7f0e"),
        ("out_m3", "out", "#9467bd"),
    )
    x = np.arange(len(rows))
    width = 0.2
    for k, (key, name, colour) in enumerate(keys):
        axis.bar(
            x + (k - 1.5) * width, [r[key] / 1e3 for r in rows], width, color=colour, label=name
        )
    top = max(r["rain_m3"] for r in rows) / 1e3
    for i, r in enumerate(rows):
        share = r["residual_share_of_rain"]
        text = "residual\nn/a" if share is None else f"residual\n{100 * share:+.4f}%"
        axis.text(i, top * 1.04, text, ha="center", fontsize=7)
    axis.set_ylim(
        min(0.0, min(min(r[k] for k, _, _ in keys) for r in rows) / 1e3 * 1.1), top * 1.22
    )
    axis.axhline(0, color="black", lw=0.6)
    axis.set_xticks(x, [r["label"] for r in rows], rotation=30, ha="right", fontsize=8)
    axis.set_ylabel("thousand m³ over the run", fontsize=8)
    axis.legend(fontsize=8, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.22))
    axis.set_title("Water balance per run (cells inside the boundary cells)", fontsize=10)
    figure.tight_layout()
    return _png(figure, "water_balance.png")


def figure_replays(panels: list[dict], frame, study, bounds, stations) -> str:
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    plt = _plt()
    g = domain.GRID
    n = len(panels)
    figure, axes = plt.subplots(
        n, 2, figsize=(12.0, 6.4 * n), squeeze=False, gridspec_kw={"width_ratios": [1.5, 1.0]}
    )
    for (left, right), p in zip(axes, panels, strict=True):
        if p.get("depth") is None:
            for axis in (left, right):
                axis.text(0.5, 0.5, f"{p['storm']}: not run", ha="center", transform=axis.transAxes)
                axis.set_axis_off()
            continue
        cls = depth_class_map(p["depth"]).astype(float)
        shown = np.full(cls.shape, np.nan)
        shown[frame.land] = 0
        shown[frame.compared] = cls[frame.compared]
        shown[frame.land & ~frame.compared] = -1
        left.imshow(
            shown,
            extent=(g.west, g.east, g.south, g.north),
            cmap=ListedColormap(["#f2f2f2", DRY, *DEPTH_COLOURS]),
            vmin=-1.5,
            vmax=3.5,
            interpolation="nearest",
        )
        _outline(left, study, color="black", lw=0.6)
        depth_by_loc = {s["LocNumber"]: s for s in p["assets"]["substations"]}
        listing = []
        for number, (loc, geometry) in enumerate(stations, start=1):
            _outline(left, geometry, color="#dc2626", lw=1.4)
            s = depth_by_loc.get(loc)
            if s is None:
                continue
            pt = geometry.representative_point()
            left.annotate(
                str(number),
                (pt.x, pt.y),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=7,
                fontweight="bold",
                color="#7f1d1d",
                bbox={"boxstyle": "round,pad=0.1", "fc": "white", "ec": "none", "alpha": 0.8},
            )
            name = s["name"] if s["name"] != "(no name)" else loc
            listing.append(f"{number}  {name}: {s['depth_on_25m2_m']:.2f} m")
        _map_axis(left, bounds, f"{p['storm']} ({p['label']}): peak depth at cell centres")
        left.legend(
            handles=[
                Patch(color=DEPTH_COLOURS[0], label="0.05 to 0.1016 m"),
                Patch(color=DEPTH_COLOURS[1], label="0.1016 to 0.3048 m"),
                Patch(color=DEPTH_COLOURS[2], label="0.3048 m and over"),
                Patch(color=DRY, label="compared, under 0.05 m"),
                Patch(color="#f2f2f2", label="study area, not compared"),
                Patch(fc="none", ec="#dc2626", label="substation site, depth on 25 m²"),
            ],
            loc="lower left",
            fontsize=7,
            framealpha=0.9,
        )
        if listing:
            right.text(
                0.98,
                0.97,
                "Substation sites, depth on 25 m² of open ground:\n" + "\n".join(listing),
                transform=right.transAxes,
                ha="right",
                va="top",
                fontsize=7,
                color="#7f1d1d",
                bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#dc2626", "alpha": 0.9},
            )
        forcing = p.get("forcing")
        if forcing is None:
            right.text(
                0.5, 0.5, "forcing summary not found", ha="center", transform=right.transAxes
            )
            right.set_axis_off()
            continue
        rates = forcing["mean_rate_by_step_mm_h"]
        step = forcing["hours"] / len(rates)
        right.bar(
            np.arange(len(rates)) * step, rates, width=step * 0.9, align="edge", color="#4292c6"
        )
        total = sum(rates) * step
        right.set_title(
            f"Square-mean radar rate per step (total {total:.1f} mm)\nfrom {forcing['tref']} UTC",
            fontsize=9,
        )
        right.set_xlabel("hours from the start of the run", fontsize=8)
        right.set_ylabel("mm/h, mean over the 4 km square", fontsize=8)
        right.tick_params(labelsize=7)
    figure.tight_layout()
    return _png(figure, "replays.png")


def figure_atlas14(table: dict[str, Any]) -> str:
    plt = _plt()
    figure, axis = plt.subplots(figsize=(8.0, 5.2))
    styles = {
        "pds": ("#1f77b4", "partial duration (PDS)"),
        "ams": ("#ff7f0e", "annual maximum (AMS)"),
    }
    for name, series in table["series"].items():
        row = series["durations"].get("60-min")
        if row is None:
            continue
        cols = [c for c in series["return_periods"] if c in row]
        t = [return_period(c) for c in cols]
        colour, label = styles.get(name, ("grey", name))
        axis.fill_between(
            t,
            [float(row[c]["lower90"]) for c in cols],
            [float(row[c]["upper90"]) for c in cols],
            color=colour,
            alpha=0.15,
            label=f"{label}, 90% bounds",
        )
        axis.plot(t, [float(row[c]["depth"]) for c in cols], "o-", color=colour, label=label)
    for scenario, inches in calibration.INTENSITY_IN_H.items():
        axis.axhline(inches, color="black", lw=0.9, ls="--")
        axis.text(1.02, inches, f" {scenario} {inches} in/h", fontsize=7.5, va="bottom")
    axis.set_xscale("log")
    axis.set_xlabel("return period, years (AMS: 1 / annual exceedance probability)", fontsize=8)
    axis.set_ylabel("60-minute depth, inches (as tabulated)", fontsize=8)
    header = next(iter(table["series"].values())).get("csv_header", [])
    version = next((h for h in header if "Version" in h), "")
    axis.set_title(f"{version}: 60-minute depth at the study-area centre", fontsize=10)
    axis.legend(fontsize=7.5, loc="upper left")
    axis.grid(True, which="both", alpha=0.3)
    figure.tight_layout()
    return _png(figure, "atlas14.png")


def figure_sensitivity(rows: list[dict]) -> str:
    plt = _plt()
    figure, (a, b) = plt.subplots(1, 2, figsize=(10.0, 1.6 + 0.7 * len(rows)))
    names = [f"{r['kind']} {r['setting']}\n({r['label']} vs {r['against']})" for r in rows]
    y = np.arange(len(rows))
    a.barh(y, [r["change_model_wet_ha"] for r in rows], 0.5, color="#4292c6")
    for i, r in enumerate(rows):
        a.text(0, i, f" {r['change_model_wet_ha']:+.2f} ha ", va="center", fontsize=7)
        if r["change_csi_wet"] is not None:
            b.text(0, i, f" {r['change_csi_wet']:+.4f} ", va="center", fontsize=7)
    a.set_yticks(y, names, fontsize=7.5)
    a.set_xlabel("change in modelled area at 4 in or more, ha (filtered)", fontsize=8)
    b.barh(y, [r["change_csi_wet"] or 0.0 for r in rows], 0.5, color="#6b7280")
    b.set_yticks(y, ["" for _ in rows])
    b.set_xlabel("change in CSI wet (filtered)", fontsize=8)
    for axis in (a, b):
        axis.axvline(0, color="black", lw=0.6)
        axis.tick_params(labelsize=7)
        axis.invert_yaxis()
    figure.suptitle("Sensitivity against the frozen run of the same scenario", fontsize=10)
    figure.tight_layout()
    return _png(figure, "sensitivity.png")


# --- the check -----------------------------------------------------------------------------------


def navy_yard_mask(root: Path) -> np.ndarray:
    import geopandas as gpd
    from rasterio import features
    from rasterio.transform import Affine

    nta = gpd.read_file(root / NTA)
    yard = nta[nta["nta2020"] == NAVY_YARD].to_crs(domain.CRS)
    g = domain.GRID
    if yard.empty:
        return np.zeros((g.height, g.width), dtype=bool)
    return features.rasterize(
        yard.geometry, out_shape=(g.height, g.width), transform=Affine(*g.transform)
    ).astype(bool)


def study_footprints(root: Path, study):
    import geopandas as gpd

    fp = gpd.read_file(root / FOOTPRINTS).to_crs(domain.CRS)
    fp = fp[fp.geometry.notna() & ~fp.geometry.is_empty]
    inside = fp.geometry.representative_point().within(study)
    return fp[inside.to_numpy()].reset_index(drop=True)


def main() -> int:
    try:
        freeze = load_freeze(FREEZE)
        global STATE
        STATE = state_of(freeze)
    except FreezeError as error:
        print(f"f3_model: {error}", file=sys.stderr)
        return 1

    import geopandas as gpd

    root = cache.root()
    runs_dir = root / "f3" / "runs"
    spec_runs = freeze["runs"]
    allowance = float(freeze["allowance_mm_per_h"])
    labels = referenced_labels(spec_runs)
    runs = {label: load_run(runs_dir, label) for label in labels}
    done = {k: v for k, v in runs.items() if v is not None}
    notes_after: list[str] = []
    checks: list[Check] = []
    tables: dict[str, Any] = {}
    numbers: dict[str, Any] = {}

    others = (
        sorted(p.name for p in runs_dir.iterdir() if p.is_dir() and p.name not in runs)
        if runs_dir.exists()
        else []
    )
    if others:
        notes_after.append(
            f"Run folders present but not named in the freeze file: {', '.join(others)}."
        )

    tables["runs"] = [run_row(r) for r in done.values()]
    tables["runs_not_run"] = [k for k, v in runs.items() if v is None]

    # water balance, one check per run
    for label, run in runs.items():
        rule = f"|residual| of the water balance <= {100 * BALANCE_MAX_SHARE:g}% of the rain (FH8)"
        if run is None:
            checks.append(not_run(f"water balance {label}", rule, label))
            continue
        share = run["balance"]["residual_share_of_rain"]
        checks.append(
            Check(
                f"water balance {label}",
                rule,
                None if share is None else bool(abs(share) <= BALANCE_MAX_SHARE),
                value=share,
                threshold=BALANCE_MAX_SHARE,
                note="" if share is not None else "no rain in the run",
            )
        )

    frame = calibration.Frame.load(root, STUDY_AREA)
    study = gpd.read_file(STUDY_AREA).to_crs(domain.CRS).geometry.union_all()
    yard = navy_yard_mask(root)
    numbers["navy_yard_cells_compared"] = int((yard & frame.compared).sum())
    numbers["cells_compared"] = int(frame.compared.sum())
    summaries: dict[tuple[str, str], dict] = {}

    def summary(label: str, city_map: str) -> dict:
        key = (label, city_map)
        if key not in summaries:
            summaries[key] = calibration.summarise_run(
                done[label]["folder"], frame, city_map, {"navy_yard": yard}
            )
        return summaries[key]

    # calibration table
    cal_rows = []
    for label in spec_runs["calibration"]:
        run = done.get(label)
        if run is None:
            cal_rows.append({"label": label, "status": "not run"})
            continue
        city_map = calibration.CALIBRATION_MAPS.get(run["scenario"])
        if city_map is None:
            cal_rows.append(
                {"label": label, "status": f"scenario {run['scenario']} is not a calibration map"}
            )
            continue
        s = summary(label, city_map)
        cal_rows.append(
            {
                "label": label,
                "status": "run",
                "scenario": run["scenario"],
                "city_map": city_map,
                "allowance": run["spec"]["qinf_mm_per_h"],
                "filtered": s["filtered"],
                "raw": s["raw"],
                "filtered_without_navy_yard": s["filtered_without_navy_yard"],
            }
        )
    tables["calibration"] = cal_rows
    ran = [r for r in cal_rows if r["status"] == "run"]
    best = {}
    for scenario in calibration.CALIBRATION_MAPS:
        sel = [r for r in ran if r["scenario"] == scenario]
        if sel:
            low = min(sel, key=lambda r: r["filtered"]["area_error"])
            best[scenario] = {
                "label": low["label"],
                "allowance": low["allowance"],
                "area_error": low["filtered"]["area_error"],
            }
    numbers["lowest_area_error_by_scenario"] = best

    # the frozen value and its fit
    fit: dict[str, Any] = {}
    hit_panels = []
    for scenario, city_map in calibration.CALIBRATION_MAPS.items():
        label = spec_runs["frozen"].get(scenario)
        title = f"{scenario.capitalize()} ({label}) against {city_map}"
        rule = f"CSI wet >= {CSI_MIN} at the {STATE} allowance against {city_map} (plan F3)"
        run = done.get(label) if label else None
        if run is None:
            fit[scenario] = {"label": label, "status": "not run"}
            checks.append(not_run(f"CSI wet {scenario}", rule, label))
            hit_panels.append({"title": title})
            continue
        s = summary(label, city_map)
        fit[scenario] = {
            "label": label,
            "status": "run",
            "allowance_of_run": run["spec"]["qinf_mm_per_h"],
            "filtered": s["filtered"],
            "raw": s["raw"],
            "filtered_without_navy_yard": s["filtered_without_navy_yard"],
        }
        csi = s["filtered"]["csi_wet"]
        checks.append(
            Check(
                f"CSI wet {scenario}",
                rule,
                None if csi is None else bool(csi >= CSI_MIN),
                value=csi,
                threshold=CSI_MIN,
                proposed=True,
                note="filtered classes (model wet patches under a quarter acre removed); raw "
                f"{s['raw']['csi_wet']}, without the Navy Yard "
                f"{s['filtered_without_navy_yard']['csi_wet']}",
            )
        )
        depth = calibration.run_depth(run["folder"], frame)
        hit_panels.append(
            {
                "title": title,
                "result": s["filtered"],
                "classes": {
                    "model": calibration.min_patch_filter(calibration.classify(depth)),
                    "city": calibration.city_class(city_map),
                },
            }
        )
    frozen_allowances = {
        v["label"]: v["allowance_of_run"] for v in fit.values() if v["status"] == "run"
    }
    checks.append(
        Check(
            "frozen runs use the frozen value",
            "qinf of every frozen run (spec.json) equals allowance_mm_per_h of the freeze file",
            None
            if not frozen_allowances
            else all(abs(v - allowance) < 1e-9 for v in frozen_allowances.values()),
            value=frozen_allowances,
            threshold=allowance,
        )
    )
    numbers["frozen"] = {
        "allowance_mm_per_h": allowance,
        "tag": freeze["tag"],
        "frozen_on": freeze.get("frozen_on"),
        "objective": freeze.get("objective"),
        "note": freeze.get("note"),
        "fit": fit,
    }

    # extreme check
    label = spec_runs.get("extreme_check")
    run = done.get(label) if label else None
    if run is None:
        numbers["extreme_check"] = {"label": label, "status": "not run"}
    else:
        s = summary(label, EXTREME_MAP)
        numbers["extreme_check"] = {
            "label": label,
            "status": "run",
            "scenario_of_run": run["scenario"],
            "allowance_of_run": run["spec"]["qinf_mm_per_h"],
            "city_map": EXTREME_MAP,
            "filtered": s["filtered"],
            "raw": s["raw"],
            "note": "The extreme-2080 map includes the sea level of 2080; its tidal code is "
            "left out by city_class, so only the rain classes 1 and 2 are compared. A check, "
            "not a calibration target (FH3).",
        }

    # duration and boundary-level sensitivities
    base_of = {k: v for k, v in spec_runs["frozen"].items()}
    if spec_runs.get("extreme_check"):
        base_of["extreme"] = spec_runs["extreme_check"]
    sens_rows = []
    for kind, table in (("duration", "duration"), ("boundary level", "boundary_level")):
        for setting, label in spec_runs.get(table, {}).items():
            run = done.get(label)
            if run is None:
                sens_rows.append(
                    {"kind": kind, "setting": setting, "label": label, "status": "not run"}
                )
                continue
            against = base_of.get(run["scenario"])
            city_map = city_map_of(run["scenario"])
            if against is None or against not in done or city_map is None:
                sens_rows.append(
                    {
                        "kind": kind,
                        "setting": setting,
                        "label": label,
                        "status": f"no finished frozen run of scenario {run['scenario']}",
                    }
                )
                continue
            s, b = summary(label, city_map)["filtered"], summary(against, city_map)["filtered"]
            sens_rows.append(
                {
                    "kind": kind,
                    "setting": setting,
                    "label": label,
                    "against": against,
                    "status": "run",
                    "scenario": run["scenario"],
                    "city_map": city_map,
                    "rain_h": run_row(run)["rain_h"],
                    "boundary_level_m": run["spec"].get("boundary_level_m"),
                    "model_wet_ha": model_wet_ha(s),
                    "frozen_model_wet_ha": model_wet_ha(b),
                    "change_model_wet_ha": round(model_wet_ha(s) - model_wet_ha(b), 3),
                    "csi_wet": s["csi_wet"],
                    "frozen_csi_wet": b["csi_wet"],
                    "change_csi_wet": None
                    if s["csi_wet"] is None or b["csi_wet"] is None
                    else round(s["csi_wet"] - b["csi_wet"], 4),
                }
            )
    tables["sensitivity"] = sens_rows

    # monotonicity
    mono_rows = []
    for pair in spec_runs.get("monotonicity", []):
        low, high = pair
        name = f"monotonicity {low} <= {high}"
        rule = (
            "at the lower rainfall no compared cell, wet or dry, deeper by over 1 mm (FH8 with the "
            "1 mm tolerance on both clauses, CH-16; cell-centre depths)"
        )
        if low not in done or high not in done:
            missing = [x for x in pair if x not in done]
            checks.append(
                not_run(name, rule, ", ".join(missing), "runs" if len(missing) > 1 else "run")
            )
            mono_rows.append({"low": low, "high": high, "status": "not run"})
            continue
        lo, hi = done[low], done[high]
        r_lo, r_hi = run_row(lo), run_row(hi)
        result = calibration.monotonicity(
            calibration.run_depth(lo["folder"], frame),
            calibration.run_depth(hi["folder"], frame),
            frame.compared,
        )
        differs = [
            k
            for k in ("allowance_mm_per_h", "rain_h", "after_h", "boundary_level_m")
            if r_lo[k] != r_hi[k]
        ]
        if lo["spec"].get("extra_inp", {}) != hi["spec"].get("extra_inp", {}):
            differs.append("solver options (extra_inp)")
        rain_order = (
            r_lo["rain_mm_per_h"] is not None
            and r_hi["rain_mm_per_h"] is not None
            and r_lo["rain_mm_per_h"] < r_hi["rain_mm_per_h"]
        )
        note = f"rain {r_lo['rain_mm_per_h']} < {r_hi['rain_mm_per_h']} mm/h"
        if not rain_order:
            note = (
                "the pair is not in order of rain: "
                f"{r_lo['rain_mm_per_h']}, {r_hi['rain_mm_per_h']}"
            )
        if differs:
            note += f"; the runs also differ in {', '.join(differs)}"
        mono_rows.append({"low": low, "high": high, "status": "run", **result, "note": note})
        checks.append(
            Check(
                name,
                rule,
                bool(result["passed"]) if rain_order else None,
                value={
                    "over_1mm": result["cells_deeper_at_lower_rain_by_over_1mm"],
                    "wet_deeper": result["wet_cells_deeper_at_lower_rain"],
                    "wet_over_1mm": result["wet_cells_deeper_at_lower_rain_by_over_1mm"],
                    "max_excess_m": result["max_excess_m"],
                },
                threshold=calibration.MONOTONE_TOL_M,
                note=note,
            )
        )
    tables["monotonicity"] = mono_rows

    # replays
    mrms_path = root / MRMS_SUMMARY
    mrms = json.loads(mrms_path.read_text()) if mrms_path.exists() else {}
    replay_rows: dict[str, Any] = {}
    replay_panels = []
    footprints = None
    forcing_paths: list[Path] = []
    for storm, label in spec_runs.get("replays", {}).items():
        run = done.get(label)
        if run is None:
            replay_rows[storm] = {"label": label, "status": "not run"}
            replay_panels.append({"storm": storm, "label": label})
            continue
        forcing, fpath = forcing_summary(run["spec"], storm, root)
        if fpath is not None:
            forcing_paths.append(fpath)
        if footprints is None:
            footprints = study_footprints(root, study)
        depth = calibration.run_depth(run["folder"], frame)
        assets = at_assets.run_assets(run["folder"], root, paths.SITE, footprints)
        assets.pop("_wall_depths", None)
        replay_rows[storm] = {
            "label": label,
            "status": "run",
            "scenario_of_run": run["scenario"],
            "allowance_of_run": run["spec"]["qinf_mm_per_h"],
            "wet_area_compared_cells": wet_areas(depth, frame.compared),
            "wet_area_study_area_land": wet_areas(depth, frame.land),
            "substations": assets["substations"],
            "buildings": assets.get("buildings"),
            "rain": radar_totals(forcing, mrms.get(storm)),
        }
        if forcing is None:
            replay_rows[storm]["rain"]["forcing"] = "not found"
        replay_panels.append(
            {"storm": storm, "label": label, "depth": depth, "assets": assets, "forcing": forcing}
        )
    tables["replays"] = replay_rows
    numbers["footprints_in_study_area"] = None if footprints is None else int(len(footprints))
    ran_replays = [v for v in replay_rows.values() if v["status"] == "run"]
    lead_rule = (
        f"some substation site has depth_on_25m2_m >= {at_assets.LEAD_DEPTH_M} m in a replay "
        "(lead-asset rule, informational)"
    )
    lead_note = (
        "Informational: the plan's stop rule for the lead asset applies to the catalogue (F4), "
        "not to the two replays."
    )
    if not ran_replays:
        checks.append(
            Check("lead-asset rule", lead_rule, None, note="not run: no replay ran. " + lead_note)
        )
    else:
        meeting = sorted(
            {
                f"{s['name']} ({storm})"
                for storm, v in replay_rows.items()
                if v["status"] == "run"
                for s in v["substations"]
                if s["depth_on_25m2_m"] >= at_assets.LEAD_DEPTH_M
            }
        )
        deepest = max(
            (s["depth_on_25m2_m"] for v in ran_replays for s in v["substations"]), default=None
        )
        all_ran = len(ran_replays) == len(replay_rows) and len(replay_rows) >= 2
        verdict = True if meeting else (False if all_ran else None)
        extra = "" if all_ran or meeting else " Not every replay ran, so no verdict."
        checks.append(
            Check(
                "lead-asset rule",
                lead_rule,
                verdict,
                value={"sites_meeting": meeting, "deepest_depth_on_25m2_m": deepest},
                threshold=at_assets.LEAD_DEPTH_M,
                proposed=True,
                note=lead_note + extra,
            )
        )

    # Atlas 14
    atlas_path = root / ATLAS14
    atlas = json.loads(atlas_path.read_text()) if atlas_path.exists() else None
    if atlas is not None:
        tables["atlas14_placement"] = atlas14_placement(atlas)
    else:
        tables["atlas14_placement"] = "not found: " + ATLAS14

    # ---- figures --------------------------------------------------------------------------------
    figures: list[str] = []
    captions: dict[str, str] = {}
    bounds = _study_bounds(frame.land)
    cal_points = [
        {
            "scenario": r["scenario"],
            "allowance": r["allowance"],
            "filtered": r["filtered"],
            "raw": r["raw"],
        }
        for r in ran
    ]
    figures.append(figure_calibration(cal_points, allowance))
    captions["calibration_curve.png"] = (
        "Modelled area per city class (4 in to 1 ft, 1 ft and over) on the compared cells against "
        "the drainage allowance, one marker per calibration run, with the city map's area as a "
        "dashed line; below, the critical success index for wet (4 in or more) with model patches "
        "under a quarter acre removed (filtered) and without (raw), and for the deep class; green: "
        f"the frozen value. Limit: {len(cal_points)} runs, each 1 h of uniform rain on the whole "
        "square; the city's maps come from another model, so a match is agreement with that "
        "model, not with observed flooding."
    )
    figures.append(figure_hit_miss(hit_panels, frame, study, bounds))
    captions["hit_miss.png"] = (
        f"Hit, miss and false alarm per compared cell at the {STATE} allowance, wet meaning 4 in "
        "or more, model patches under a quarter acre removed; grey: compared and dry in both; "
        "white: not compared (outside the study area, under a building footprint, a filled pit "
        "or water). "
        "Limit: a cell takes the city's class at its centre; a shift of one cell between the two "
        "maps counts as both a miss and a false alarm."
    )
    bal_rows = tables["runs"]
    if bal_rows:
        figures.append(figure_balance(bal_rows))
        captions["water_balance.png"] = (
            "Rain, drained (the allowance), stored (change in water volume) and out (net outflow "
            "through the four edge cross-sections) per run, thousand m³, over the cells inside the "
            "boundary cells; the residual share of the rain is printed above. Limit: the fluxes "
            "are the solver's own outputs, so the balance tests their consistency, not that the "
            "rain or the drainage are right."
        )
    if any(p.get("depth") is not None for p in replay_panels):
        stations = [
            (loc, group.geometry.union_all())
            for loc, group in gpd.read_file(SUBSTATIONS)
            .to_crs(domain.CRS)
            .pipe(lambda d: d[d["reviewed"].astype(str).str.startswith("kept")])
            .groupby("LocNumber", sort=True)
        ]
        figures.append(figure_replays(replay_panels, frame, study, bounds, stations))
        captions["replays.png"] = (
            "Peak depth at cell centres for each replay on the compared cells of the study area, "
            "in three classes; red: substation sites with the depth exceeded on 25 m² of their "
            "open ground; right: the radar rain each run was forced with, mean over the 4 km "
            "square per step. Limit: radar rain at about 1 km cells, held uniform within each "
            "cell and hour; no sewer network, only the allowance; water from outside the square "
            "cannot enter."
        )
    if atlas is not None:
        figures.append(figure_atlas14(atlas))
        captions["atlas14.png"] = (
            "NOAA Atlas 14 60-minute depth at the study-area centre against return period, partial "
            "duration and annual maximum series, with their 90% bounds, and the three map "
            "intensities held for one hour. Limit: a point estimate for a 4 km area; the city's "
            "storm shape and duration are not a 60-minute block, so a placement is a reading, "
            "not the return period of the map."
        )
    sens_done = [r for r in sens_rows if r["status"] == "run"]
    if sens_done:
        figures.append(figure_sensitivity(sens_done))
        captions["sensitivity.png"] = (
            "Change in modelled area at 4 in or more (filtered) and in CSI wet against the frozen "
            "run of the same scenario, for other durations at the same intensity and other "
            f"boundary levels. Limit: one run per setting, at the {STATE} allowance only."
        )
    else:
        notes_after.append("No duration or boundary-level run has finished; no sensitivity figure.")
    if "replays.png" not in captions:
        notes_after.append("No replay has finished; no replay figure.")
    for name in FIGURE_NAMES:  # a figure of an earlier run that this one did not draw
        if f"{REL}/{name}" not in figures:
            (OUT / name).unlink(missing_ok=True)
    tables["captions"] = captions

    # ---- record ---------------------------------------------------------------------------------
    inputs = [Input.of(FREEZE, root=paths.ROOT), Input.of(STUDY_AREA, root=paths.ROOT)]
    inputs += [
        Input.of(paths.SITE / "data" / "city_flood_maps" / f"{m}.tif", root=paths.ROOT)
        for m in (*calibration.CALIBRATION_MAPS.values(), EXTREME_MAP)
    ]
    model = root / "f3" / "model"
    inputs += [
        Input.of(p, root=root)
        for p in (
            model / "dem_model_1m.tif",
            model / "buildings_1m.tif",
            model / "pits_1m.tif",
            root / "terrain" / "water_1m.tif",
            root / NTA,
        )
    ]
    if ran_replays:
        inputs += [Input.of(SUBSTATIONS, root=paths.ROOT), Input.of(root / FOOTPRINTS, root=root)]
        if mrms_path.exists():
            inputs.append(Input.of(mrms_path, root=root))
        inputs += [Input.of(p, root=root) for p in forcing_paths]
    if atlas is not None:
        inputs.append(Input.of(atlas_path, root=root))
    for run in done.values():
        for name in ("spec.json", "run_run.json", "balance.json", "zsmax.tif"):
            if (run["folder"] / name).exists():
                inputs.append(Input.of(run["folder"] / name, root=root))

    parameters = [
        Parameter(
            "drainage_allowance_mm_per_h", allowance, freeze["tag"], freeze.get("objective", "")
        ),
        Parameter("wet_m", domain.WET_M, "P", "requirements section 5"),
        Parameter("shallow_class_m", calibration.SHALLOW_M, "S", "nyc-stormwater-flood-maps"),
        Parameter("deep_class_m", calibration.DEEP_M, "S", "nyc-stormwater-flood-maps"),
        Parameter(
            "min_patch_m2",
            calibration.MIN_PATCH_M2,
            "P",
            "city's 0.25-acre rule applied to the model",
        ),
        Parameter("patch_connectivity", calibration.PATCH_CONNECTIVITY, "P"),
        Parameter(
            "intensity_in_h", dict(calibration.INTENSITY_IN_H), "S", "nyc-stormwater-flood-maps"
        ),
        Parameter("balance_max_share", BALANCE_MAX_SHARE, "P", "requirements FH8"),
        Parameter("csi_min", CSI_MIN, "P", "plan F3, proposed"),
        Parameter("monotone_tolerance_m", calibration.MONOTONE_TOL_M, "P", "set at the F0 stop"),
        Parameter("lead_depth_m", at_assets.LEAD_DEPTH_M, "P", "demo-concerns §2"),
        Parameter("lead_area_m2", at_assets.LEAD_AREA_M2, "P"),
        Parameter("max_roof_share", at_assets.MAX_ROOF_SHARE, "P"),
        Parameter("building_band_m", at_assets.BAND_M, "P"),
        Parameter("navy_yard_nta2020", NAVY_YARD, "P", "sensitivity of the calibration"),
        Parameter(
            "depth_colours", list(DEPTH_COLOURS), "P", "matplotlib 'Blues'; FP7 has none yet"
        ),
    ]
    finished = len(done)
    first = (
        f"F3 solver model: drainage allowance {STATE} at {allowance:g} mm/h [{freeze['tag']}] "
        f"({freeze.get('frozen_on')}); {finished} of {len(labels)} named runs finished. Calibrated "
        "on the city's two current-sea-level maps (limited 1.77 in/h, moderate 2.13 in/h); the "
        "3.66 in/h run is a check against a 2080 map. Every number comes from the run folders, "
        "the city maps and the cache files listed as inputs. Captions: "
        + " ".join(f"{k}: {v}" for k, v in captions.items())
    )
    record = Record(
        id=RECORD_ID,
        stage="F3",
        title="Solver model: drainage calibration, water balance, monotonicity and two replays",
        inputs=inputs,
        parameters=parameters,
        numbers=numbers,
        tables=tables,
        checks=checks,
        figures=figures,
        notes=[first, *(f"{k}: {v}" for k, v in captions.items()), *notes_after],
    )
    record.software = record.software | {
        name: _version(name)
        for name in ("numpy", "scipy", "rasterio", "geopandas", "shapely", "matplotlib")
    }
    path = record.write(paths.RECORDS)
    print(
        json.dumps(
            {
                "record": str(path),
                "passed": record.passed,
                "checks": [(c.name, c.passed, c.value) for c in checks],
                "figures": figures,
            },
            indent=1,
            default=str,
        )
    )
    return 0


def _version(name: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


if __name__ == "__main__":
    sys.exit(main())
