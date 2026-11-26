"""F5, second part: the Jamaica Bay map where it overlaps (FV3) and "who saw the flood" (FV5).

    uv run --with matplotlib python -m flood_lab.checks.f5_who_saw

Offline, from the cache (the 311 rows are fetched once with ``--fetch-311``; see
``sources.nyc_311``). Nothing is fitted or changed (FV4).

**FV3.** The Jamaica Bay Ida depth map (Kasaei et al. 2025) is read from its shapefile
(``sources.jamaica_bay``), every file checked against the SHA-256 the publisher gives. Its overlap
with the square is measured. A comparison of depths is made only where the map overlaps the square;
with no overlap the result is "not applicable", with the numbers.

**FV5.** For each storm, five sources, each with its own time window, rule for "inside the square"
and date matching (stated in ``RULES`` and in the record):

- Groundsource (``sources.groundsource``): dated places whose date range holds a storm day.
- NOAA Storm Events (``sources.storm_events``): flood events of the square's counties and zones
  whose span on the New York clock holds a storm day.
- 311 (``sources.nyc_311``): flooding-related requests created on a storm day, both naming
  schemes, with the twin rows of one request paired.
- FloodNet (``sources.floodnet``): sensors in the square in service on a storm day, and those that
  recorded an event starting that day (New York day).
- USGS high-water marks (``sources.usgs_hwm``): the Ida survey's marks in the square.

Counts are reported, not judged. The map draws each storm's modelled maximum inundation depth
(the frozen F3 replays) under the points for orientation only.

Writes ``site/flood/tests/records/f5-who-saw.json`` and figures under ``docs/flood/figures/f5/``.
"""

from __future__ import annotations

import io
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flood_lab import cache, paths
from flood_lab.domain import GRID, SQUARE
from flood_lab.records import Check, Input, Parameter, Record
from flood_lab.sources import floodnet, groundsource, jamaica_bay, nyc_311, storm_events, usgs_hwm

RECORD_ID = "f5-who-saw"
OUT = paths.FIGURES / "f5"
REL = "docs/flood/figures/f5"
FREEZE = Path(__file__).resolve().parents[1] / "hazard" / "allowance.toml"
STUDY_AREA = paths.SITE / "data" / "study_area.geojson"
MENDELEY = f"{jamaica_bay.FOLDER}/mendeley_record.json"
#: storm key, New York days, label
STORMS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("ida_2021", ("2021-09-01", "2021-09-02"), "Ida, 1-2 Sep 2021"),
    ("sep29_2023", ("2023-09-29",), "29 Sep 2023"),
)
#: Storm Events files of each storm's year (fetched in F0; facts noaa-storm-events)
SE_FILES = {
    "ida_2021": (
        "StormEvents_details-ftp_v1.0_d2021_c20261119.csv.gz",
        "StormEvents_locations-ftp_v1.0_d2021_c20261119.csv.gz",
    ),
    "sep29_2023": (
        "StormEvents_details-ftp_v1.0_d2023_c20261119.csv.gz",
        "StormEvents_locations-ftp_v1.0_d2023_c20261119.csv.gz",
    ),
}
#: the 311 query box round the square (west, south, east, north, degrees); a coarse first cut
BOX_311 = (-73.9892, 40.6855, -73.9392, 40.7240)
#: the Groundsource reader's box for the square: the square's bounds in degrees, rounded outwards
BOX_GS = (-73.9890, 40.6860, -73.9400, 40.7235)
#: FV3: an overlap below this share of the square counts as negligible [P]
NEGLIGIBLE_SHARE = 0.01
#: how each source decides time and place (the record repeats these)
RULES = {
    "groundsource": {
        "window": "a row whose start_date to end_date range (as published: days, no time of day, "
        "no zone) holds one of the storm's days",
        "inside": "main count: the place polygon's centroid lies in the square; context: the "
        "polygon intersects the square (the polygon is the named place, not the flood)",
    },
    "storm_events": {
        "window": "the event's begin to end, turned from its CZ_TIMEZONE clock (EST-5 for every "
        "New York City row, also in September) to UTC and then to the New York wall clock, holds "
        "one of the storm's days",
        "inside": "main count: the begin point, end point or a point of the locations file lies "
        "in the square; context: every flood event of the square's counties (Kings, New York) "
        "and NWS zones (75 Kings (Brooklyn), 72 New York (Manhattan)), county and zone events "
        "both read",
    },
    "nyc_311": {
        "window": "created_date (a floating time stamp, read as the New York wall clock as "
        "written) falls on one of the storm's days",
        "inside": "latitude and longitude, projected to EPSG:32618, fall in the square; requests "
        "with no location cannot be placed and are counted apart for the two boroughs",
    },
    "floodnet": {
        "window": "context: sensors in service on a storm day (installed on or before it, not "
        "removed before it); main count: sensors with an event whose start (GMT) falls on a "
        "storm day on the New York clock",
        "inside": "the sensor table's position, projected to EPSG:32618, lies in the square",
    },
    "usgs_marks": {
        "window": "the survey of Ida (ScienceBase item 618975c8d34ec04fc9c5a049); no date "
        "matching. The cache holds no survey for 29 Sep 2023; whether USGS surveyed marks for "
        "that storm was not checked",
        "inside": "the mark's position, projected to EPSG:32618, lies in the square",
    },
}
#: colours: one per source (validated categorical set of the earlier figures where it exists)
COLOURS = {
    "groundsource": "#eb6834",
    "storm_events": "#c0392b",
    "nyc_311": "#7b4fa0",
    "floodnet": "#1b9e77",
    "usgs_marks": "#222222",
}
NAMES = {
    "groundsource": "Groundsource (news)",
    "storm_events": "NOAA Storm Events",
    "nyc_311": "311 requests",
    "floodnet": "FloodNet sensors",
    "usgs_marks": "USGS high-water marks",
}
DPI = 100


# --- pure helpers (tested on small fixtures) -----------------------------------------------------


def inside(x: Any, y: Any) -> np.ndarray:
    """Points of EPSG:32618 in the square: west and south edges in, east and north out."""
    west, south, east, north = SQUARE
    x, y = np.asarray(x, dtype="float64"), np.asarray(y, dtype="float64")
    return (x >= west) & (x < east) & (y >= south) & (y < north)


def to_utm(lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    x, y = t.transform(np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64"))
    return np.asarray(x), np.asarray(y)


def square_lonlat():
    """The square as a polygon in degrees (edges densified every 50 m)."""
    import shapely
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)
    ring = shapely.box(*SQUARE).segmentize(50.0).exterior.coords
    lon, lat = t.transform(*map(list, zip(*ring, strict=True)))
    return shapely.Polygon(zip(lon, lat, strict=True))


def on_days(start: pd.Series, end: pd.Series, days: tuple[str, ...]) -> pd.Series:
    """Rows whose text range ``start..end`` (YYYY-MM-DD) holds one of the days."""
    hit = pd.Series(False, index=start.index)
    for day in days:
        hit |= (start <= day) & (end >= day)
    return hit


def count_groundsource(table: pd.DataFrame, days: tuple[str, ...], square) -> dict[str, Any]:
    import shapely

    rows = table[on_days(table["start_date"], table["end_date"], days)]
    shapes = shapely.from_wkb(rows["geometry_wkb"].to_numpy())
    hits = shapely.intersects(shapes, square)
    rows, shapes = rows[hits], shapes[hits]
    centre = shapely.contains_xy(square, rows["centroid_lon"], rows["centroid_lat"])
    listed = [
        {
            "uuid": r["uuid"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "area_km2": round(float(r["area_km2"]), 4),
            "centroid_lon": round(float(r["centroid_lon"]), 6),
            "centroid_lat": round(float(r["centroid_lat"]), 6),
            "centroid_inside": bool(c),
            "contains_square": bool(shapely.contains(s, square)),
        }
        for (_, r), c, s in zip(rows.iterrows(), centre, shapes, strict=True)
    ]
    return {
        "main": int(np.count_nonzero(centre)),
        "context": len(listed),
        "main_label": "places centred in the square",
        "context_label": "places touching the square",
        "larger_than_square": sum(1 for r in listed if r["area_km2"] > 16.0),
        "rows": sorted(listed, key=lambda r: r["area_km2"]),
    }


def count_storm_events(table: pd.DataFrame, days: tuple[str, ...]) -> dict[str, Any]:
    mine = table[table["in_counties_or_zones"]]
    hit = storm_events.covering(mine, list(days))
    written = mine[mine["begin_day_as_written"].isin(days)]
    rows = []
    for _, r in hit.iterrows():
        pts = r["points"]
        if pts:
            x, y = to_utm([p[0] for p in pts], [p[1] for p in pts])
            point_inside = bool(inside(x, y).any())
        else:
            point_inside = False
        rows.append(
            {
                "event_id": int(r["event_id"]),
                "event_type": r["event_type"],
                "cz_type": r["cz_type"],
                "cz_name": r["cz_name"],
                "begin_as_written": r["begin_as_written"],
                "begin_utc": r["begin_utc"],
                "begin_local_day": r["begin_local_day"],
                "points": [[round(a, 4), round(b, 4)] for a, b in pts],
                "point_inside": point_inside,
            }
        )
    return {
        "main": sum(1 for r in rows if r["point_inside"]),
        "context": len(rows),
        "main_label": "events with a point in the square",
        "context_label": "events in the square's counties and zones",
        "zone_events": sum(1 for r in rows if r["cz_type"] == "Z"),
        "by_type": dict(sorted(pd.Series([r["event_type"] for r in rows]).value_counts().items()))
        if rows
        else {},
        "begin_day_as_written_matches": int(len(written)),
        "rows": rows,
    }


def count_311(
    table: pd.DataFrame, days: tuple[str, ...], unplaced: list[dict[str, Any]]
) -> dict[str, Any]:
    flood = table[table["scheme"].notna() & table["local_day"].isin(days)].copy()
    placed = flood["latitude"].notna() & flood["longitude"].notna()
    flood = flood[placed]
    x, y = to_utm(flood["longitude"], flood["latitude"])
    keep = inside(x, y)
    flood = flood[keep]
    xs = pd.Series(x[keep], index=flood.index)
    ys = pd.Series(y[keep], index=flood.index)
    pairs = nyc_311.twins(flood, xs, ys)
    twin_legacy = {p["legacy"] for p in pairs}
    requests = flood[~flood["unique_key"].astype(str).isin(twin_legacy)]
    by_kind = {
        kind: {
            "legacy_rows": int((g["scheme"] == "legacy").sum()),
            "current_rows": int((g["scheme"] == "current").sum()),
            "requests": int((~g["unique_key"].astype(str).isin(twin_legacy)).sum()),
        }
        for kind, g in sorted(flood.groupby("kind"))
    }
    return {
        "main": int(len(requests)),
        "context": int(len(flood)),
        "main_label": "requests (twin rows paired)",
        "context_label": "rows, both naming schemes",
        "legacy_rows": int((flood["scheme"] == "legacy").sum()),
        "current_rows": int((flood["scheme"] == "current").sum()),
        "twin_pairs": len(pairs),
        "twin_pairs_same_address": sum(1 for p in pairs if p["same_address"]),
        "twin_seconds_max": max((p["seconds"] for p in pairs), default=None),
        "by_kind": by_kind,
        "unplaced_in_boroughs": sum(int(u["n"]) for u in unplaced),
        "unplaced_rows": unplaced,
        "points": [
            [round(float(a), 1), round(float(b), 1)]
            for a, b, k in zip(xs, ys, flood["unique_key"].astype(str), strict=True)
            if k not in twin_legacy
        ],
    }


def count_floodnet(table: pd.DataFrame, sensors_csv: Path, days: tuple[str, ...]) -> dict[str, Any]:
    serving: dict[str, dict[str, Any]] = {}
    for day in days:
        s = floodnet.storm_sensors(table, sensors_csv, day)
        x, y = to_utm(s["longitude"], s["latitude"])
        s = s.assign(x=x, y=y)[inside(x, y)]
        for _, r in s.iterrows():
            row = serving.setdefault(
                r["sensor_id"],
                {
                    "sensor_id": r["sensor_id"],
                    "easting_m": round(float(r["x"]), 1),
                    "northing_m": round(float(r["y"]), 1),
                    "recorded_on": [],
                    "peak_depth_m": None,
                },
            )
            if r["recorded"]:
                row["recorded_on"].append(day)
                peak = round(float(r["peak_depth_m"]), 3)
                row["peak_depth_m"] = max(peak, row["peak_depth_m"] or 0.0)
    rows = sorted(serving.values(), key=lambda r: r["sensor_id"])
    return {
        "main": sum(1 for r in rows if r["recorded_on"]),
        "context": len(rows),
        "main_label": "sensors that recorded an event",
        "context_label": "sensors in service",
        "rows": rows,
    }


def count_marks(rows: list[dict[str, Any]], storm: str) -> dict[str, Any]:
    if storm != "ida_2021":
        return {
            "main": None,
            "context": None,
            "main_label": "marks",
            "context_label": "sites",
            "note": "no survey of this storm in the cache",
            "rows": [],
        }
    chosen = [r for r in rows if inside(r["easting_m"], r["northing_m"])]
    return {
        "main": len(chosen),
        "context": len({r["site_no"] for r in chosen}),
        "main_label": "marks",
        "context_label": "sites",
        "rows": [
            {k: r[k] for k in ("hwm_id", "site_no", "easting_m", "northing_m")} for r in chosen
        ],
    }


def fv3_result(overlap: dict[str, Any]) -> dict[str, Any]:
    share = overlap["overlap_area_m2"] / overlap["square_area_m2"]
    applicable = overlap["points_inside"] > 0 and share >= NEGLIGIBLE_SHARE
    if applicable:
        text = (
            f"The map overlaps {share:.1%} of the square ({overlap['points_inside']} points); "
            "a comparison is due."
        )
    else:
        text = (
            f"Not applicable. No point of the Jamaica Bay map lies in the square "
            f"({overlap['points_inside']} of {overlap['points']:,}); the map's cells cover "
            f"{overlap['overlap_area_m2']:,.0f} m² of it; the nearest point is "
            f"{overlap['nearest_distance_m']:,.0f} m from the square."
            if overlap["points_inside"] == 0
            else f"Not applicable: the overlap is {share:.2%} of the square, below "
            f"{NEGLIGIBLE_SHARE:.0%} [P]."
        )
    return {"applicable": applicable, "overlap_share": round(share, 6), "statement": text}


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


def figure_counts(counts: dict[str, dict[str, dict[str, Any]]]) -> str:
    """One panel per source, a pair of bars per storm: main count (dark), context (light)."""
    plt = _plt()
    sources = list(NAMES)
    figure, axes = plt.subplots(len(sources), 1, figsize=(9.5, 8.6), sharex=False)
    for axis, source in zip(axes, sources, strict=True):
        colour = COLOURS[source]
        labels, mains, contexts = [], [], []
        for storm, _days, label in STORMS:
            c = counts[storm][source]
            labels.append(label)
            mains.append(c["main"])
            contexts.append(c["context"])
        top = max([v for v in mains + contexts if v is not None] + [1])
        ys = np.arange(len(labels))[::-1]
        for yy, m, k in zip(ys, mains, contexts, strict=True):
            if m is None:
                axis.text(
                    top * 0.01,
                    yy + 0.1,
                    "no survey in the cache",
                    va="center",
                    fontsize=8.5,
                    color="#555555",
                )
                continue
            axis.barh(yy + 0.18, k, height=0.34, color=colour, alpha=0.3, edgecolor="none")
            axis.barh(yy - 0.18, m, height=0.34, color=colour, edgecolor="none")
            axis.text(k + top * 0.01, yy + 0.18, f"{k}", va="center", fontsize=8.5, color="#333333")
            axis.text(
                m + top * 0.01,
                yy - 0.18,
                f"{m}",
                va="center",
                fontsize=8.5,
                color="#111111",
                fontweight="bold",
            )
        c0 = counts[STORMS[0][0]][source]
        axis.set_yticks(ys, labels, fontsize=8.5)
        axis.set_xlim(0, top * 1.15)
        axis.set_title(
            f"{NAMES[source]}: dark = {c0['main_label']}, light = {c0['context_label']}",
            fontsize=9,
            loc="left",
        )
        axis.tick_params(axis="x", labelsize=8)
        axis.grid(axis="x", color="#eeeeee")
        axis.set_axisbelow(True)
        for side in ("top", "right"):
            axis.spines[side].set_visible(False)
    figure.suptitle(
        "Who saw the flood: counts inside the square per source and storm (reported, not judged)",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.97))
    return _png(figure, "who_saw_counts.png")


def figure_map(
    counts: dict[str, dict[str, dict[str, Any]]],
    depth: dict[str, np.ndarray | None],
    study,
    places: dict[str, list],
) -> str:
    import shapely
    from matplotlib.colors import ListedColormap
    from matplotlib.lines import Line2D

    plt = _plt()
    figure, axes = plt.subplots(1, 2, figsize=(14, 7.2), layout="constrained")
    for axis, (storm, _days, label) in zip(axes, STORMS, strict=True):
        d = depth.get(storm)
        if d is not None:
            step = 5
            view = d[::step, ::step]
            axis.imshow(
                np.where(view >= 0.1, 1.0, np.nan),
                extent=(GRID.west, GRID.east, GRID.south, GRID.north),
                cmap=ListedColormap(["#cfe2f3"]),
                vmin=0,
                vmax=1,
                interpolation="nearest",
            )
        for g in study.geometry:
            for poly in getattr(g, "geoms", [g]):
                axis.plot(*poly.exterior.xy, color="#888888", linewidth=0.6)
        c = counts[storm]
        for shape in places[storm]:
            for poly in getattr(shape, "geoms", [shape]):
                if isinstance(poly, shapely.Polygon):
                    axis.plot(
                        *poly.exterior.xy,
                        color=COLOURS["groundsource"],
                        linewidth=1.0,
                        linestyle="--",
                    )
        pts = np.array(c["nyc_311"]["points"]).reshape(-1, 2)
        if len(pts):
            axis.scatter(
                pts[:, 0],
                pts[:, 1],
                s=9,
                color=COLOURS["nyc_311"],
                alpha=0.75,
                edgecolors="none",
                zorder=3,
            )
        for r in c["storm_events"]["rows"]:
            if not r["points"]:
                continue
            x, y = to_utm([p[0] for p in r["points"]], [p[1] for p in r["points"]])
            keep = inside(x, y)
            axis.scatter(
                x[keep],
                y[keep],
                s=70,
                marker="^",
                color=COLOURS["storm_events"],
                edgecolors="white",
                linewidths=1,
                zorder=5,
            )
        for r in c["floodnet"]["rows"]:
            filled = bool(r["recorded_on"])
            axis.scatter(
                r["easting_m"],
                r["northing_m"],
                s=60,
                marker="s",
                facecolors=COLOURS["floodnet"] if filled else "white",
                edgecolors=COLOURS["floodnet"],
                linewidths=1.6,
                zorder=5,
            )
        for r in c["usgs_marks"]["rows"]:
            axis.scatter(
                r["easting_m"],
                r["northing_m"],
                s=55,
                marker="D",
                color=COLOURS["usgs_marks"],
                edgecolors="white",
                linewidths=1,
                zorder=6,
            )
        axis.set_xlim(GRID.west, GRID.east)
        axis.set_ylim(GRID.south, GRID.north)
        axis.set_aspect("equal")
        axis.set_xticks([])
        axis.set_yticks([])
        g, s, r311 = c["groundsource"], c["storm_events"], c["nyc_311"]
        fn, mk = c["floodnet"], c["usgs_marks"]
        axis.set_title(
            f"{label}\n311: {r311['main']} · Storm Events: {s['main']} · Groundsource: "
            f"{g['main']} · FloodNet: {fn['main']} of {fn['context']} · marks: "
            f"{'none in cache' if mk['main'] is None else mk['main']}",
            fontsize=9,
        )
    handles = [
        Line2D([], [], color="#cfe2f3", linewidth=8, label="modelled depth ≥ 0.1 m (F3 replay)"),
        Line2D(
            [],
            [],
            color=COLOURS["groundsource"],
            linestyle="--",
            label="Groundsource place centred in the square",
        ),
        Line2D(
            [],
            [],
            marker="o",
            linestyle="",
            color=COLOURS["nyc_311"],
            markersize=4,
            label="311 request (twins drawn once)",
        ),
        Line2D(
            [],
            [],
            marker="^",
            linestyle="",
            color=COLOURS["storm_events"],
            markersize=8,
            label="Storm Events point in the square",
        ),
        Line2D(
            [],
            [],
            marker="s",
            linestyle="",
            markerfacecolor=COLOURS["floodnet"],
            markeredgecolor=COLOURS["floodnet"],
            markersize=7,
            label="FloodNet: recorded",
        ),
        Line2D(
            [],
            [],
            marker="s",
            linestyle="",
            markerfacecolor="white",
            markeredgecolor=COLOURS["floodnet"],
            markersize=7,
            label="FloodNet: in service, none recorded",
        ),
        Line2D(
            [],
            [],
            marker="D",
            linestyle="",
            color=COLOURS["usgs_marks"],
            markersize=6,
            label="USGS high-water mark",
        ),
    ]
    figure.legend(handles=handles, loc="outside lower center", ncol=4, fontsize=8, frameon=False)
    figure.suptitle("Who saw the flood, inside the square (grey: study-area outline)", fontsize=10)
    return _png(figure, "who_saw_map.png")


def figure_fv3(x: np.ndarray, y: np.ndarray, depth: np.ndarray, overlap: dict[str, Any]) -> str:
    plt = _plt()
    west, south, east, north = SQUARE
    pad = 3500.0
    keep = (x > west - pad) & (x < east + pad) & (y > south - pad) & (y < north + pad)
    figure, axis = plt.subplots(figsize=(7.6, 7.2), layout="constrained")
    scale = axis.scatter(x[keep], y[keep], c=depth[keep], s=3, cmap="Blues", vmin=0, vmax=0.91)
    axis.plot(
        [west, east, east, west, west],
        [south, south, north, north, south],
        color="black",
        linewidth=1.5,
        label="model square",
    )
    nx, ny = overlap["nearest_point_easting_m"], overlap["nearest_point_northing_m"]
    cx, cy = min(max(nx, west), east), min(max(ny, south), north)
    axis.plot(
        [nx, cx],
        [ny, cy],
        color="#c0392b",
        linewidth=1.5,
        label=f"shortest distance {overlap['nearest_distance_m']:,.0f} m",
    )
    axis.set_xlim(west - pad, east + pad)
    axis.set_ylim(south - pad, north + pad)
    axis.set_aspect("equal")
    axis.ticklabel_format(useOffset=False, style="plain")
    axis.tick_params(labelsize=7)
    axis.set_xlabel("easting, m (EPSG:32618)", fontsize=8)
    axis.set_ylabel("northing, m", fontsize=8)
    axis.legend(fontsize=8, loc="upper left")
    bar = figure.colorbar(scale, ax=axis, shrink=0.7)
    bar.set_label("flood_dept of the Jamaica Bay map, m (capped at 0.91)", fontsize=8)
    axis.set_title(
        f"FV3: the Jamaica Bay Ida map (Kasaei et al. 2025, CC BY 4.0) and the square\n"
        f"{overlap['points_inside']} of {overlap['points']:,} map points inside; "
        f"overlap {overlap['overlap_area_m2']:,.0f} m²",
        fontsize=9,
    )
    return _png(figure, "jamaica_bay_overlap.png")


# --- main ----------------------------------------------------------------------------------------


def _version(name: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def fetch_311(root: Path) -> None:
    for storm, days, _ in STORMS:
        query = nyc_311.fetch(root, storm, (days[0], days[-1]), BOX_311)
        print(storm, [p["rows"] for p in query["pages"]])


def checksums(root: Path) -> dict[str, Any]:
    """Every Jamaica Bay file in the cache against the SHA-256 the Mendeley record gives."""
    from flood_lab.records import sha256_file

    record = json.loads((root / MENDELEY).read_text())
    out = {}
    for f in record["files"]:
        path = root / jamaica_bay.FOLDER / f["filename"]
        want = f["content_details"]["sha256_hash"]
        got = sha256_file(path) if path.exists() else None
        out[f["filename"]] = {
            "publisher_sha256": want,
            "local_sha256": got,
            "bytes": f["size"],
            "match": got == want,
        }
    return out


def model_depths(root: Path) -> dict[str, np.ndarray | None]:
    """Each storm's modelled maximum inundation depth on the 1 m pixels (frozen F3 replays)."""
    from flood_lab.hazard import at_assets

    replays = tomllib.loads(FREEZE.read_text())["runs"]["replays"]
    out: dict[str, np.ndarray | None] = {}
    for storm, *_ in STORMS:
        run = root / "f3" / "runs" / replays[storm]
        out[storm] = at_assets.masked_depth(run, root)[0] if (run / "zsmax.tif").exists() else None
    return out


def main(argv: list[str] | None = None) -> int:
    import geopandas as gpd
    import shapely

    argv = sys.argv[1:] if argv is None else argv
    root = cache.root()
    if "--fetch-311" in argv:
        fetch_311(root)
    needs = [
        root / groundsource.FILE,
        root / floodnet.EVENTS,
        root / floodnet.SENSORS,
        root / usgs_hwm.FILE,
        root / MENDELEY,
        *[root / storm_events.FOLDER / f for pair in SE_FILES.values() for f in pair],
        *[root / nyc_311.FOLDER / s / "query.json" for s, *_ in STORMS],
    ]
    for need in needs:
        if not need.exists():
            print(f"missing input {need}; nothing written", file=sys.stderr)
            return 1

    # FV3 --------------------------------------------------------------------------------------
    sums = checksums(root)
    shapefile_ok = all(
        sums[jamaica_bay.STEM + p]["match"] for p in (".shp", ".shx", ".dbf", ".prj", ".cpg")
    )
    fv3: dict[str, Any] = {"checksums": sums}
    if shapefile_ok:
        x, y, attributes, crs = jamaica_bay.points(root / jamaica_bay.FOLDER)
        cell = jamaica_bay.spacing(x, y)
        overlap = jamaica_bay.overlap(x, y, cell, SQUARE)
        fv3 |= {
            "crs_of_file": crs,
            "overlap": overlap,
            "unit": jamaica_bay.depth_unit(attributes),
            **fv3_result(overlap),
        }
        fv3_figure = figure_fv3(x, y, attributes["flood_dept"].astype("float64"), overlap)
    else:
        fv3 |= {
            "applicable": None,
            "statement": "The shapefile is not in the cache or a checksum differs; FV3 stops.",
        }
        fv3_figure = None

    # FV5 --------------------------------------------------------------------------------------
    square = square_lonlat()
    places_table = groundsource.dated_places(root / groundsource.FILE, {"square": BOX_GS})
    fn_events = floodnet.events(root / floodnet.EVENTS, root / floodnet.SENSORS)
    marks = usgs_hwm.as_rows(usgs_hwm.marks(root / usgs_hwm.FILE))
    counts: dict[str, dict[str, dict[str, Any]]] = {}
    queries: dict[str, Any] = {}
    places: dict[str, list] = {}
    for storm, days, _label in STORMS:
        details, locations = (root / storm_events.FOLDER / f for f in SE_FILES[storm])
        se = storm_events.events(details, locations)
        requests, query = nyc_311.read(root, storm)
        queries[storm] = query
        counts[storm] = {
            "groundsource": count_groundsource(places_table, days, square),
            "storm_events": count_storm_events(se, days),
            "nyc_311": count_311(requests, days, nyc_311.unplaced(root, storm)),
            "floodnet": count_floodnet(fn_events, root / floodnet.SENSORS, days),
            "usgs_marks": count_marks(marks, storm),
        }
        centred = {r["uuid"] for r in counts[storm]["groundsource"]["rows"] if r["centroid_inside"]}
        chosen = places_table[places_table["uuid"].isin(centred)]
        shapes = shapely.from_wkb(chosen["geometry_wkb"].to_numpy())
        utm = gpd.GeoSeries(shapes, crs="EPSG:4326").to_crs("EPSG:32618")
        places[storm] = list(utm.clip(shapely.box(*SQUARE)))

    study = gpd.read_file(STUDY_AREA).to_crs("EPSG:32618")
    depth = model_depths(root)
    figures = [figure_counts(counts), figure_map(counts, depth, study, places)]
    if fv3_figure:
        figures.append(fv3_figure)

    summary = {
        storm: {
            source: {k: c[k] for k in ("main", "main_label", "context", "context_label")}
            for source, c in counts[storm].items()
        }
        for storm, *_ in STORMS
    }
    twins_2023 = counts["sep29_2023"]["nyc_311"]
    checks = [
        Check(
            name="FV3: the Jamaica Bay shapefile matches the publisher's checksums",
            rule="SHA-256 of .shp, .shx, .dbf, .prj and .cpg equal to the Mendeley record's",
            passed=shapefile_ok,
            value={k: v["match"] for k, v in sums.items()},
        ),
        Check(
            name="FV3: comparison where the map overlaps the square",
            rule="compare depths only where the map overlaps; below "
            f"{NEGLIGIBLE_SHARE:.0%} of the square [P] the result is 'not applicable'",
            passed=None,
            value={k: fv3.get(k) for k in ("applicable", "overlap_share")},
            threshold=NEGLIGIBLE_SHARE,
            proposed=True,
            note=fv3["statement"],
        ),
        Check(
            name="FV5: who saw the flood (reported, not judged)",
            rule="for each storm, counts inside the square from Groundsource, Storm Events, 311, "
            "FloodNet and the surveyed marks, each by its stated rule",
            passed=None,
            value=summary,
        ),
        Check(
            name="FV5: 311 counts both naming schemes",
            rule="rows of the legacy and the current scheme are both read; rows of one request "
            "under both schemes are paired (nyc_311.twins) and counted once",
            passed=None,
            value={
                k: twins_2023[k]
                for k in ("legacy_rows", "current_rows", "twin_pairs", "main", "context")
            },
            note="Reported. The facts row says 'count both'; on 29 Sep 2023 most rows of the "
            "current scheme have a twin of the legacy scheme, so counting rows would count most "
            "requests twice.",
        ),
    ]
    captions = {
        "who_saw_counts.png": (
            "Counts inside the model square for each source and storm. Dark bar: the main count "
            "(Groundsource places centred in the square; Storm Events flood events with a point "
            "in it; 311 flooding-related requests with twin rows of the two naming schemes "
            "paired; FloodNet sensors that recorded an event; USGS marks). Light bar: the "
            "context (places touching the square; flood events of the square's counties and "
            "zones; 311 rows of both schemes; sensors in service; mark sites). Windows: Ida "
            "1 and 2 Sep 2021, the other storm 29 Sep 2023, each source by its own date rule "
            "(record, RULES). Counts are reported, not judged: a source with no entry is not "
            "evidence of no flood."
        ),
        "who_saw_map.png": (
            "Where each source placed the flood inside the square. Pale blue: the frozen F3 "
            "replay's maximum inundation depth of at least 0.1 m, for orientation only. "
            "Groundsource places are drawn only when centred in the square (larger places "
            "touching it are counted in the chart). Storm Events points are begin, end and "
            "locations-file points inside the square."
        ),
        "jamaica_bay_overlap.png": (
            "The Jamaica Bay Ida depth map (Kasaei et al. 2025, Mendeley "
            "doi:10.17632/hs2zt6ngwd.1, CC BY 4.0; points of the published shapefile, coloured "
            "by flood_dept, metres) within 3.5 km of the model square, with the shortest "
            "distance between them. Shown with credit; not changed except for the projection "
            "to EPSG:32618."
        ),
    }
    inputs = [
        Input.of(FREEZE, root=paths.ROOT),
        Input.of(STUDY_AREA, root=paths.ROOT),
        *[
            Input.of(root / jamaica_bay.FOLDER / f, root=root)
            for f in sorted(sums)
            if (root / jamaica_bay.FOLDER / f).exists()
        ],
        Input.of(root / MENDELEY, root=root),
        Input.of(root / groundsource.FILE, root=root),
        *[
            Input.of(root / storm_events.FOLDER / f, root=root)
            for p in SE_FILES.values()
            for f in p
        ],
        *[
            Input.of(root / nyc_311.FOLDER / s / name, root=root)
            for s, *_ in STORMS
            for name in (
                "query.json",
                f"unplaced_{s}.json",
                *[p["file"] for p in queries[s]["pages"]],
            )
        ],
        Input.of(root / floodnet.EVENTS, root=root),
        Input.of(root / floodnet.SENSORS, root=root),
        Input.of(root / usgs_hwm.FILE, root=root),
    ]
    replays = tomllib.loads(FREEZE.read_text())["runs"]["replays"]
    inputs += [
        Input.of(root / "f3" / "runs" / replays[s] / "zsmax.tif", root=root)
        for s, *_ in STORMS
        if (root / "f3" / "runs" / replays[s] / "zsmax.tif").exists()
    ]
    record = Record(
        id=RECORD_ID,
        stage="F5",
        title="Jamaica Bay map overlap (FV3) and who saw the flood (FV5)",
        inputs=inputs,
        parameters=[
            Parameter(
                "fv3_negligible_share",
                NEGLIGIBLE_SHARE,
                "P",
                "an overlap below this share of the square is negligible",
            ),
            Parameter(
                "unit_agree_tolerance",
                jamaica_bay.AGREE,
                "P",
                "flood_dept against water_elev - dem_m",
            ),
            Parameter("twin_seconds", nyc_311.TWIN_S, "P", "311 twin rule: created this close"),
            Parameter("twin_metres", nyc_311.TWIN_M, "P", "311 twin rule: placed this close"),
            Parameter("box_311", list(BOX_311), "I", "coarse first cut round the square"),
            Parameter("box_groundsource", list(BOX_GS), "I", "coarse first cut round the square"),
        ],
        numbers={
            "fv3_applicable": fv3.get("applicable"),
            "fv3_points_inside": fv3.get("overlap", {}).get("points_inside"),
            "fv3_overlap_area_m2": fv3.get("overlap", {}).get("overlap_area_m2"),
            "fv3_nearest_distance_m": fv3.get("overlap", {}).get("nearest_distance_m"),
            **{
                f"{storm}_{source}": c["main"]
                for storm, *_ in STORMS
                for source, c in counts[storm].items()
            },
        },
        tables={
            "fv3": fv3,
            "fv5_summary": summary,
            "fv5_counts": counts,
            "rules": RULES,
            "storm_days": {s: list(d) for s, d, _ in STORMS},
            "nyc_311_queries": {
                s: {k: q[k] for k in ("window_local_days", "box_west_south_east_north", "queries")}
                | {"fetched_at": [p["fetched_at"] for p in q["pages"]]}
                for s, q in queries.items()
            },
            "captions": captions,
        },
        checks=checks,
        figures=figures,
        notes=[
            "F5 second part (FV3, FV5). Counts are reported, not judged. " + fv3["statement"],
            "Storm Events clock: every New York City row says EST-5; times are turned into UTC "
            "and then into the New York wall clock before a day is matched (facts "
            "noaa-storm-events, time_zone).",
            "311: created_date has no zone; read as the New York wall clock as written.",
            *(f"{k}: {v}" for k, v in captions.items()),
        ],
    )
    record.software = record.software | {
        n: _version(n) for n in ("numpy", "pandas", "geopandas", "shapely", "matplotlib", "pyproj")
    }
    path = record.write(paths.RECORDS)
    print(
        json.dumps(
            {
                "record": str(path),
                "fv3": {k: fv3.get(k) for k in ("statement", "overlap", "unit")},
                "fv5": summary,
                "written": datetime.now(UTC).isoformat(),
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
