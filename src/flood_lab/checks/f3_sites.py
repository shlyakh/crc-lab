"""F3 follow-up: the two lead substation sites, Hudson Avenue and Farragut, on maps, with the asset
details, the modelled depth at each storm and the return period of each storm's rain.

    uv run --with matplotlib python -m flood_lab.checks.f3_sites

Asked for by Yuri on 2026-11-26 when he kept both sites as lead assets. Offline. Reads the frozen
runs named in ``src/flood_lab/hazard/allowance.toml`` (the three city-map storms and the two
replays), the asset table, the substation outlines, the Atlas 14 table of F3 and the replay
forcing summaries. Depth is read exactly as for the lead-asset rule (``at_assets``): open ground
inside the outlines, roofed cells and water standing from the start left out.

Return periods: a city-map storm is its intensity held for one hour, placed on Atlas 14's 60-minute
row. A replay is placed by its largest 1-, 2- and 3-hour rain, from the hourly square-mean rates of
its forcing, on the 60-minute, 2-hour and 3-hour rows. The table is not interpolated: a placement
names the two tabulated return periods it falls between. The Atlas 14 table of F3 stops at 3 hours,
so whole-storm totals are not placed.

Writes ``site/flood/tests/records/f3-sites.json`` and two figures under ``docs/flood/figures/f3/``.
"""

from __future__ import annotations

import csv
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import numpy as np

from flood_lab import cache, paths
from flood_lab.checks import f3_model
from flood_lab.hazard import at_assets, calibration
from flood_lab.records import Check, Input, Parameter, Record

RECORD_ID = "f3-sites"
SUBSTATIONS = paths.SITE / "data" / "substations.geojson"
ASSETS = paths.SITE / "data" / "assets_oed.csv"
REVIEW = Path(__file__).resolve().parents[1] / "assets" / "substation_review.toml"
#: the two lead sites kept by Yuri on 2026-11-26: Hudson Avenue (by the rule) and Farragut
SITES = ("S-383102724", "S-339711332")
#: storms in the order of their peak-hour rain; each names the allowance file's run
STORMS = (
    ("sep29_2023", "29 Sep 2023", "replay"),
    ("limited", "Limited map storm", "design"),
    ("moderate", "Moderate map storm", "design"),
    ("ida_2021", "Ida, 1 Sep 2021", "replay"),
    ("extreme", "Extreme map storm", "design"),
)
REPLAY_FORCING = {
    "ida_2021": "f3/forcing/ida_2021.json",
    "sep29_2023": "f3/forcing/sep29_2023.json",
}
#: windows of the replay rain placed on Atlas 14: hours and the row read
WINDOWS = ((1, "60-min"), (2, "2-hr"), (3, "3-hr"))
#: the two runs drawn on the maps
MAP_STORMS = ("moderate", "ida_2021")
#: margin around a site's outlines on its map, m [P]
MAP_MARGIN_M = 45.0
FT_PER_M = 1 / 0.3048
MM_PER_IN = calibration.MM_PER_IN
#: depth classes on the maps, m: wet, 4 in, 1 ft, 2 ft; the last is added here for the sites [P]
MAP_BREAKS = (0.05, calibration.SHALLOW_M, calibration.DEEP_M, 0.6096)
#: matplotlib "Blues", four steps [P]
MAP_COLOURS = ("#c6dbef", "#6baed6", "#2171b5", "#08306b")
BUILDING_GREY = "#bdbdbd"
#: categorical slots 1 and 2 of the reference palette (dataviz skill), one per site
SITE_COLOURS = {"S-383102724": "#2a78d6", "S-339711332": "#eb6834"}
LEAD_MARK = "#d62728"
FIGURES = ("sites_map.png", "sites_depth.png")


# --- pure helpers (tested without rasters) -------------------------------------------------------


def max_window_sums(rates_mm_h: list[float], hours: int) -> float:
    """Largest sum of ``hours`` consecutive hourly rates (mm/h over 1 h steps), mm."""
    r = np.asarray(rates_mm_h, dtype="float64")
    if len(r) < hours:
        return float(r.sum())
    return float(np.convolve(r, np.ones(hours), mode="valid").max())


def place(depth_in: float, row: dict[str, Any], labels: list[str]) -> dict[str, Any]:
    cols = [c for c in labels if c in row]
    return f3_model.bracket(depth_in, cols, [row[c]["depth"] for c in cols])


def years_text(placement: dict[str, Any], unit: str = "yr") -> str:
    """'10-25 yr', 'under 1 yr', 'over 1000 yr' from a bracket."""
    text = placement["placement"]
    if "between" in placement:
        a, b = (s.lstrip("'") for s in placement["between"])
        return f"{a}-{b} {unit}"
    if text.startswith("below"):
        return f"under {text.split(' ', 1)[1].lstrip(chr(39))} {unit}"
    if text.startswith("above"):
        return f"over {text.split(' ', 1)[1].lstrip(chr(39))} {unit}"
    return text


def lead_reading(depth: np.ndarray, level: np.ndarray, inside: np.ndarray) -> dict[str, Any]:
    """The lead-asset rule's reading on one site: depth exceeded on ``LEAD_AREA_M2`` of open
    ground, and the peak water level (NAVD88) on those pixels. ``inside`` marks open ground."""
    ok = inside & np.isfinite(depth)
    if not ok.any():
        return {"depth_on_25m2_m": None, "pixels": []}
    values = depth[ok]
    order = np.argsort(values)[::-1][: at_assets.LEAD_AREA_M2]
    rows, cols = np.nonzero(ok)
    lead = float(values[order[-1]])
    levels = level[rows[order], cols[order]]
    return {
        "depth_on_25m2_m": round(lead, 3),
        "depth_on_25m2_ft": round(lead * FT_PER_M, 2),
        "max_depth_m": round(float(values.max()), 3),
        "area_ge_030_m2": int((values >= at_assets.LEAD_DEPTH_M).sum()),
        "area_ge_005_m2": int((values >= at_assets.WET_M).sum()),
        "peak_level_navd88_m": round(float(np.median(levels)), 2),
        "meets_lead_rule": bool(lead >= at_assets.LEAD_DEPTH_M),
        "pixels": list(zip(rows[order].tolist(), cols[order].tolist(), strict=True)),
    }


def non_decreasing(values: list[float | None], tol: float = calibration.MONOTONE_TOL_M) -> bool:
    v = [x for x in values if x is not None]
    return all(b >= a - tol for a, b in zip(v, v[1:], strict=False))


# --- inputs --------------------------------------------------------------------------------------


def asset_rows() -> dict[str, dict[str, str]]:
    with ASSETS.open(newline="") as handle:
        return {r["LocNumber"]: r for r in csv.DictReader(handle) if r["LocNumber"] in SITES}


def site_details(rows: dict[str, dict[str, str]], review: dict[str, Any], outlines) -> list[dict]:
    out = []
    for loc in SITES:
        r = rows[loc]
        group = outlines[outlines["LocNumber"] == loc]
        ground = float(r["lab_ground_elev_m"])
        out.append(
            {
                "LocNumber": loc,
                "name": next(n for n in group["name"] if isinstance(n, str) and n),
                "kind": r["lab_substation_kind"],
                "voltage_kv": float(r["lab_voltage_kv"]),
                "indoor": r["lab_indoor"],
                "osm_ids": r["lab_osm_ids"],
                "outlines": int(r["lab_outlines"]),
                "fenced_area_m2": round(float(group.geometry.area.sum())),
                "ground_elev_navd88_m": ground,
                "ground_elev_navd88_ft": round(ground * FT_PER_M, 1),
                "ground_elev_source": r["lab_ground_elev_source"],
                "value_usd": {
                    "low": int(r["lab_value_low_usd"]),
                    "mid": int(r["lab_value_mid_usd"]),
                    "high": int(r["lab_value_high_usd"]),
                    "tag": r["lab_value_tag"],
                },
                "customers_served": r["lab_customers_served"] or "not public (FD7)",
                "seen_on_imagery": review[loc]["note"],
                "reviewed_by": review.get("reviewed_by", ""),
                "equipment_heights": "not known: no public source gives the height of the "
                "equipment above grade; none is assumed",
            }
        )
    return out


def storm_rain(key: str, kind: str, root: Path, atlas: dict[str, Any]) -> dict[str, Any]:
    pds = atlas["series"]["pds"]
    labels = list(pds["return_periods"])
    if kind == "design":
        inches = calibration.INTENSITY_IN_H[key]
        hour = place(inches, pds["durations"]["60-min"], labels)
        return {
            "peak_1h_mm": round(inches * MM_PER_IN, 1),
            "peak_1h_in": inches,
            "windows": {"60-min": {"in": inches, **hour}},
            "return_period": years_text(hour),
            "how": "the city's intensity held for one hour (block), Atlas 14 PDS 60-minute row",
        }
    forcing = json.loads((root / REPLAY_FORCING[key]).read_text())
    rates = forcing["mean_rate_by_step_mm_h"]
    windows = {}
    for hours, row in WINDOWS:
        mm = max_window_sums(rates, hours)
        inches = round(mm / MM_PER_IN, 3)
        windows[row] = {
            "mm": round(mm, 1),
            "in": inches,
            **place(inches, pds["durations"][row], labels),
        }
    return {
        "peak_1h_mm": windows["60-min"]["mm"],
        "peak_1h_in": windows["60-min"]["in"],
        "storm_total_mm": round(float(sum(rates)), 1),
        "hours": forcing["hours"],
        "windows": windows,
        "return_period": years_text(windows["60-min"]),
        "how": "largest 1-, 2- and 3-hour rain of the square-mean radar forcing (MRMS), Atlas 14 "
        "PDS 60-minute, 2-hour and 3-hour rows",
    }


# --- figures -------------------------------------------------------------------------------------


def _site_bounds(geoms) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = geoms.total_bounds
    m = MAP_MARGIN_M
    w = max(x1 - x0, y1 - y0) + 2 * m  # square window
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - w / 2, cx + w / 2, cy - w / 2, cy + w / 2


def figure_map(panels, details, outlines, grid_west, grid_north) -> str:
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    plt = f3_model._plt()
    figure, axes = plt.subplots(len(SITES), len(MAP_STORMS), figsize=(11, 10.6))
    cmap = ListedColormap(MAP_COLOURS)
    norm = BoundaryNorm([*MAP_BREAKS, 99.0], cmap.N)
    by_loc = {d["LocNumber"]: d for d in details}
    for i, loc in enumerate(SITES):
        mine = outlines[outlines["LocNumber"] == loc]
        bounds = _site_bounds(mine.geometry)
        c0, c1 = int(bounds[0] - grid_west), int(bounds[1] - grid_west)
        r0, r1 = int(grid_north - bounds[3]), int(grid_north - bounds[2])
        for j, storm in enumerate(MAP_STORMS):
            axis = axes[i][j]
            p = panels[storm]
            win = (slice(r0, r1), slice(c0, c1))
            extent = (grid_west + c0, grid_west + c1, grid_north - r1, grid_north - r0)
            bld = np.where(p["building"][win], 1.0, np.nan)
            axis.imshow(
                bld,
                extent=extent,
                cmap=ListedColormap([BUILDING_GREY]),
                vmin=0,
                vmax=1,
                interpolation="nearest",
            )
            d = np.where(p["depth"][win] >= MAP_BREAKS[0], p["depth"][win], np.nan)
            axis.imshow(d, extent=extent, cmap=cmap, norm=norm, interpolation="nearest")
            for other, group in outlines.groupby("LocNumber"):
                style = {"color": "black", "linewidth": 2.2 if other == loc else 0.9}
                for g in group.geometry:
                    f3_model._outline(axis, g, **style)
                names = [n for n in group["name"] if isinstance(n, str) and n]
                c = group.geometry.union_all().centroid
                if (
                    other != loc
                    and names
                    and bounds[0] < c.x < bounds[1]
                    and bounds[2] < c.y < bounds[3]
                ):
                    axis.text(
                        c.x,
                        c.y,
                        names[0].replace(" Substation", ""),
                        fontsize=7,
                        ha="center",
                        va="center",
                        color="#333333",
                        bbox={"facecolor": "white", "edgecolor": "none", "pad": 1, "alpha": 0.8},
                    )
            lead = p["readings"][loc]
            if lead["pixels"]:
                ys = [grid_north - r - 0.5 for r, _ in lead["pixels"]]
                xs = [grid_west + c + 0.5 for _, c in lead["pixels"]]
                axis.scatter(xs, ys, s=3, facecolors="none", edgecolors=LEAD_MARK, linewidths=0.5)
            name = by_loc[loc]["name"]
            r = lead
            title = (
                f"{name}: {p['label']} ({p['return_period']})\n"
                f"{r['depth_on_25m2_m']:.2f} m ({r['depth_on_25m2_ft']:.1f} ft) over 25 m², "
                f"{r['area_ge_030_m2']} m² at 0.3 m or more"
            )
            f3_model._map_axis(axis, bounds, title)
    handles = [
        Patch(color=MAP_COLOURS[0], label="0.05 m to 4 in"),
        Patch(color=MAP_COLOURS[1], label="4 in to 1 ft"),
        Patch(color=MAP_COLOURS[2], label="1 ft to 2 ft"),
        Patch(color=MAP_COLOURS[3], label="2 ft and more"),
        Patch(color=BUILDING_GREY, label="building (not read)"),
        plt.Line2D([], [], color="black", linewidth=2.2, label="the site's fence outline"),
        plt.Line2D([], [], color="black", linewidth=0.9, label="other substations"),
        plt.Line2D(
            [],
            [],
            marker="o",
            linestyle="",
            markerfacecolor="none",
            markeredgecolor=LEAD_MARK,
            label="the 25 m² read by the lead-asset rule",
        ),
    ]
    figure.legend(handles=handles, loc="lower center", ncol=4, fontsize=8, frameon=False)
    figure.tight_layout(rect=(0, 0.06, 1, 1))
    return f3_model._png(figure, "sites_map.png")


def figure_depth(storms: list[dict], details: list[dict]) -> str:
    plt = f3_model._plt()
    figure, axis = plt.subplots(figsize=(10, 5))
    x = np.arange(len(storms))
    offsets = np.linspace(-0.08, 0.08, len(details))
    for d, dx in zip(details, offsets, strict=True):
        loc = d["LocNumber"]
        y = [s["sites"][loc]["depth_on_25m2_m"] for s in storms]
        axis.vlines(x + dx, 0, y, color=SITE_COLOURS[loc], linewidth=2, zorder=2)
        axis.scatter(
            x + dx,
            y,
            color=SITE_COLOURS[loc],
            s=64,
            zorder=3,
            label=d["name"],
            edgecolors="white",
            linewidths=2,
        )
        axis.annotate(
            d["name"].replace(" Substation", ""),
            (x[-1] + dx, y[-1]),
            xytext=(10, 0),
            textcoords="offset points",
            va="center",
            fontsize=8.5,
            color="#333333",
        )
    axis.axhline(at_assets.LEAD_DEPTH_M, color="#333333", linestyle="--", linewidth=1.3, zorder=1)
    axis.annotate(
        "lead-asset rule, 0.3 m (about 1 ft)",
        (len(storms) - 0.5, at_assets.LEAD_DEPTH_M),
        xytext=(0, -12),
        textcoords="offset points",
        fontsize=8,
        color="#555555",
        ha="left",
    )
    axis.set_xticks(
        x,
        [
            f"{s['label']}\npeak hour {s['rain']['peak_1h_in']:.2f} in\n"
            f"{s['rain']['return_period']}"
            for s in storms
        ],
        fontsize=8,
    )
    axis.set_ylabel("Depth over 25 m² of open ground, m", fontsize=9)
    axis.set_xlim(-0.5, len(storms) + 0.6)
    top = max(s["sites"][d["LocNumber"]]["depth_on_25m2_m"] for s in storms for d in details)
    axis.set_ylim(0, max(top, at_assets.LEAD_DEPTH_M) * 1.15)
    secondary = axis.secondary_yaxis(
        "right", functions=(lambda m: m * FT_PER_M, lambda f: f / FT_PER_M)
    )
    secondary.set_ylabel("ft", fontsize=9)
    for a in (axis, secondary):
        a.tick_params(labelsize=8)
    axis.grid(axis="y", color="#e5e5e5", linewidth=0.8, zorder=0)
    axis.spines[["top"]].set_visible(False)
    axis.legend(fontsize=8, frameon=False, loc="upper left")
    axis.set_title(
        "Modelled depth at the two lead sites; storms in order of peak-hour rain, "
        "with its Atlas 14 return period",
        fontsize=9.5,
    )
    figure.tight_layout()
    return f3_model._png(figure, "sites_depth.png")


# --- main ----------------------------------------------------------------------------------------


def main() -> int:
    import geopandas as gpd

    root = cache.root()
    freeze = f3_model.load_freeze(f3_model.FREEZE)
    runs = freeze["runs"]
    label_of = {
        "limited": runs["frozen"]["limited"],
        "moderate": runs["frozen"]["moderate"],
        "extreme": runs["extreme_check"],
        **runs["replays"],
    }
    atlas_path = root / f3_model.ATLAS14
    atlas = json.loads(atlas_path.read_text())
    outlines = gpd.read_file(SUBSTATIONS).to_crs("EPSG:32618")
    outlines = outlines[outlines["reviewed"].astype(str).str.startswith("kept")]
    review = tomllib.loads(REVIEW.read_text())
    details = site_details(asset_rows(), review, outlines)

    from flood_lab.domain import GRID

    shape = (GRID.height * int(GRID.cell), GRID.width * int(GRID.cell))
    inside = {}
    storms, panels, inputs = [], {}, []
    building = None
    for key, label, kind in STORMS:
        folder = root / "f3" / "runs" / label_of[key]
        if not (folder / "zsmax.tif").exists():
            print(f"run {label_of[key]} has not finished; nothing written", file=sys.stderr)
            return 1
        depth, building, dem = at_assets.masked_depth(folder, root)
        level = dem + np.nan_to_num(depth)
        readings = {}
        for loc in SITES:
            if loc not in inside:
                geoms = [
                    g if g.geom_type == "Polygon" else g.buffer(1.0)
                    for g in outlines[outlines["LocNumber"] == loc].geometry
                ]
                inside[loc] = at_assets._rasterize(geoms, shape) & ~building
            readings[loc] = lead_reading(depth, level, inside[loc])
        rain = storm_rain(key, kind, root, atlas)
        storms.append(
            {
                "storm": key,
                "label": label,
                "kind": kind,
                "run": label_of[key],
                "rain": rain,
                "sites": {
                    k: {kk: vv for kk, vv in v.items() if kk != "pixels"}
                    for k, v in readings.items()
                },
            }
        )
        if key in MAP_STORMS:
            panels[key] = {
                "depth": depth,
                "building": building,
                "readings": readings,
                "label": label,
                "return_period": rain["return_period"],
            }
        inputs += [Input.of(folder / n, root=root) for n in ("spec.json", "zsmax.tif")]
        if kind == "replay":
            inputs.append(Input.of(root / REPLAY_FORCING[key], root=root))

    figures = [
        figure_map(panels, details, outlines, GRID.west, GRID.north),
        figure_depth(storms, details),
    ]
    checks = []
    for d in details:
        loc = d["LocNumber"]
        design = [s["sites"][loc]["depth_on_25m2_m"] for s in storms if s["kind"] == "design"]
        checks.append(
            Check(
                name=f"depth rises with the design storm at {d['name']}",
                rule="depth over 25 m² at Limited <= Moderate <= Extreme, within 1 mm (FH8's "
                "tolerance)",
                passed=non_decreasing(design),
                value=design,
            )
        )
        ida = next(s for s in storms if s["storm"] == "ida_2021")["sites"][loc]
        checks.append(
            Check(
                name=f"lead-asset rule at Ida, {d['name']}",
                rule="depth over 25 m² of open ground >= 0.3 m in the Ida replay "
                "(demo-concerns §2)",
                passed=ida["meets_lead_rule"],
                value=ida["depth_on_25m2_m"],
                threshold=at_assets.LEAD_DEPTH_M,
                proposed=True,
                note="Informational: the rule as set for the demo.",
            )
        )
    captions = {
        "sites_map.png": (
            "Hudson Avenue (top) and Farragut (bottom) substations: modelled maximum inundation "
            "depth on 1 m "
            "pixels in the Moderate map storm (2.13 in/hr for one hour) and the Ida replay. "
            "Thick line: the site's fence outline from OpenStreetMap; thin: the other "
            "substations of the complex. Red rings: the 25 m² the lead-asset rule reads. "
            "Buildings, cells mostly under roofs and water standing from the start are not "
            "read. Limit: a 5 m solver with one constant loss rate; the depth of a pixel is the"
            " water level of its 5 m cell less the 1 m terrain (ground level), and the terrain "
            "was flown in 2013-2014."
        ),
        "sites_depth.png": (
            "Depth over 25 m² of open ground at the two sites in five storms, ordered by the "
            "rain of their peak hour, with the Atlas 14 return period of that hour (partial-"
            "duration series, between two tabulated columns, no interpolation). Limit: a "
            "storm's return period is not the return period of the depth it causes; the "
            "replays' 2- and 3-hour rain may sit in other classes (record table 'storms'); "
            "equipment heights are unknown."
        ),
    }
    inputs = [
        Input.of(f3_model.FREEZE, root=paths.ROOT),
        Input.of(SUBSTATIONS, root=paths.ROOT),
        Input.of(ASSETS, root=paths.ROOT),
        Input.of(REVIEW, root=paths.ROOT),
        Input.of(atlas_path, root=root),
        *[
            Input.of(root / "f3" / "model" / n, root=root)
            for n in ("dem_model_1m.tif", "buildings_1m.tif", "zb_5m.tif")
        ],
        *inputs,
    ]
    record = Record(
        id=RECORD_ID,
        stage="F3",
        title="The two lead substation sites: maps, asset details, depth by storm, return period",
        inputs=inputs,
        parameters=[
            Parameter("lead_depth_m", at_assets.LEAD_DEPTH_M, "P", "demo-concerns §2"),
            Parameter("lead_area_m2", at_assets.LEAD_AREA_M2, "P"),
            Parameter("max_roof_share", at_assets.MAX_ROOF_SHARE, "P"),
            Parameter("map_margin_m", MAP_MARGIN_M, "P"),
            Parameter("map_breaks_m", list(MAP_BREAKS), "P", "wet, the city's 4 in and 1 ft, 2 ft"),
            Parameter(
                "drainage_allowance_mm_per_h",
                freeze["allowance_mm_per_h"],
                freeze["tag"],
                "frozen F3 value",
            ),
        ],
        numbers={"sites": len(SITES), "storms": len(storms)},
        tables={"sites": details, "storms": storms, "captions": captions},
        checks=checks,
        figures=figures,
        notes=[
            "Asked for by Yuri on 2026-11-26: both Hudson Avenue (lead asset by the rule) and "
            "Farragut are kept as lead sites. Values are placeholders [P] from the asset table; "
            "customers served and equipment heights have no public source.",
            *(f"{k}: {v}" for k, v in captions.items()),
        ],
    )
    record.software = record.software | {
        n: f3_model._version(n) for n in ("numpy", "rasterio", "geopandas", "matplotlib")
    }
    path = record.write(paths.RECORDS)
    print(
        json.dumps(
            {
                "record": str(path),
                "checks": [(c.name, c.passed, c.value) for c in checks],
                "figures": figures,
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
