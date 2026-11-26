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

Counts are reported, not judged. The maps (one per storm) draw that storm's modelled maximum
inundation depth (the frozen F3 replays) under the points for orientation only.

**F5c (refinements of 2026-11-26).**

1. *Sightings.* Reports of the same flooding are combined by ``observations.sightings``: 311 twin
   rows first (the strict case), then observations of 311, FloodNet and the marks within
   ``sightings.NEAR_M`` and ``sightings.NEAR_S`` of each other, chained (``SIGHTING_RULE``). A
   sensitivity table gives the count for other thresholds.
2. *Late calls.* The flooding-related 311 requests in the square on the storm days and the
   ``LATE_DAYS`` days after, against dry days of the four weeks each side (GHCN-Daily rain at
   three stations, ``sources.ghcn_daily``). Fetched once with ``--fetch-late``.
3. *Groundsource near the square.* Places by relation: centroid inside, overlapping, and within
   each of ``GS_NEAR_M``.

Writes ``site/flood/tests/records/f5-who-saw.json`` and figures under ``docs/flood/figures/f5/``.
The record keeps its id; F5c adds tables (``sightings*``, ``groundsource_relations``,
``late_calls*``, ``extended_window``) and does not change the earlier counts.
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
from flood_lab.observations import sightings
from flood_lab.records import Check, Input, Parameter, Record
from flood_lab.sources import (
    floodnet,
    ghcn_daily,
    groundsource,
    jamaica_bay,
    nyc_311,
    storm_events,
    usgs_hwm,
)

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
#: the Groundsource reader's wider box, for the places near the square: BOX_GS widened by 0.01
#: degree each way (about 840 m east-west, 1,110 m north-south), more than the largest distance
BOX_GS_NEAR = (-73.9990, 40.6760, -73.9300, 40.7335)
#: Groundsource: distances from the square at which nearby places are counted, m [P]
GS_NEAR_M = (250.0, 500.0)
#: the square's area, km² (4 km by 4 km)
SQUARE_KM2 = 16.0
#: late calls: the flooding-related 311 requests in the box over four weeks each side of the storm
#: (step 1b of sources.nyc_311), and the GHCN-Daily rain of the same weeks and two days before
AROUND = {
    "ida_2021": ("around_ida_2021", ("2021-08-04", "2021-09-29"), ("2021-08-02", "2021-10-01")),
    "sep29_2023": (
        "around_sep29_2023",
        ("2023-09-01", "2023-10-27"),
        ("2023-08-30", "2023-10-29"),
    ),
}
#: late calls: days after the storm compared [I]; days after it kept out of the baseline [P]
LATE_DAYS = 2
EXCLUDED_AFTER = 7
#: late calls, "clearly above" the baseline [P]: above every baseline day and this times its mean
ABOVE_FACTOR = 2.0
#: thresholds of the sensitivity table (the rule's own values are sightings.NEAR_M, NEAR_S)
SENSITIVITY_M = (0.0, 25.0, 50.0, 100.0, 200.0)
SENSITIVITY_H = (1.0, 3.0, 12.0, 24.0)
#: the maps draw modelled depth from this value, m [I]
DEPTH_SHOWN_M = 0.05
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
#: the sighting rule (observations.sightings), as the record states it
SIGHTING_RULE = {
    "observation": "one report of water at a place and time: 311 requests (a twin pair is one "
    "observation keeping both row ids; time = created_date), FloodNet events at sensors in the "
    "square that started on a storm day (time = start to end, New York clock), USGS marks in "
    "the square (no time: the whole storm days)",
    "duplicates": "the strict case, applied first: 311 twin rows of one request (nyc_311.twins = "
    "sightings.duplicate_pairs: other scheme, same kind, within "
    f"{sightings.DUPLICATE_S:.0f} s, same address or within {sightings.DUPLICATE_M:.0f} m)",
    "near": f"two observations within {sightings.NEAR_M:.0f} m [P] and with time windows "
    f"within {sightings.NEAR_S / 3600:.0f} h [P] of each other; any source, any kind",
    "sighting": "observations joined by chains of near pairs (single linkage); every member is "
    "kept with its source and row ids; extent = largest distance between two members",
    "area_reports": "Groundsource places (centred in the square) and Storm Events events (with "
    "a point in the square) name an area, not a spot: they join no sighting and link none; "
    "each sighting lists the area reports whose shape holds a member (Groundsource: the place "
    "polygon over the storm days; Storm Events: the hull of the event's points over its begin "
    f"to end), with windows within {sightings.NEAR_S / 3600:.0f} h",
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
                "end_utc": r["end_utc"],
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


def rows_311(
    table: pd.DataFrame, days: tuple[str, ...]
) -> tuple[pd.DataFrame, pd.Series, pd.Series, list[dict[str, Any]]]:
    """Flooding-related rows placed in the square on the days, their positions and twin pairs."""
    flood = table[table["scheme"].notna() & table["local_day"].isin(days)].copy()
    placed = flood["latitude"].notna() & flood["longitude"].notna()
    flood = flood[placed]
    x, y = to_utm(flood["longitude"], flood["latitude"])
    keep = inside(x, y)
    flood = flood[keep]
    xs = pd.Series(x[keep], index=flood.index)
    ys = pd.Series(y[keep], index=flood.index)
    return flood, xs, ys, nyc_311.twins(flood, xs, ys)


def count_311(
    table: pd.DataFrame, days: tuple[str, ...], unplaced: list[dict[str, Any]]
) -> dict[str, Any]:
    flood, xs, ys, pairs = rows_311(table, days)
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


def _ny(utc: Any) -> pd.Timestamp:
    """A GMT time stamp as the New York wall clock, without a zone."""
    return pd.Timestamp(utc).tz_convert(storm_events.ZONE).tz_localize(None)


def _storm_span(days: tuple[str, ...]) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(days[0]), pd.Timestamp(days[-1]) + pd.Timedelta(days=1)


def observations_311(
    flood: pd.DataFrame, xs: pd.Series, ys: pd.Series, pairs: list[dict[str, Any]]
) -> list[sightings.Observation]:
    """One observation per request: a twin pair becomes one observation with both row ids."""
    partner = {p["current"]: p["legacy"] for p in pairs}
    legacy = set(partner.values())
    by_key = {str(k): i for k, i in zip(flood["unique_key"], flood.index, strict=True)}
    out = []
    for key, i in by_key.items():
        if key in legacy:
            continue
        rows = (key, partner[key]) if key in partner else (key,)
        times = [pd.Timestamp(flood.at[by_key[r], "created_date"]) for r in rows]
        out.append(
            sightings.Observation(
                source="nyc_311",
                id=key,
                kind=str(flood.at[i, "kind"]),
                start=min(times),
                end=max(times),
                x=float(xs[i]),
                y=float(ys[i]),
                rows=rows,
            )
        )
    return out


def observations_floodnet(
    table: pd.DataFrame, days: tuple[str, ...]
) -> list[sightings.Observation]:
    """FloodNet events that started on a storm day (New York day) at a sensor in the square."""
    rows = table[table["local_day"].isin(days)]
    x, y = to_utm(rows["longitude"], rows["latitude"])
    keep = inside(x, y)
    return [
        sightings.Observation(
            source="floodnet",
            id=f"{r['sensor_id']}@{r['start_utc']}",
            kind="sensor event",
            start=_ny(r["start_utc"]),
            end=_ny(r["end_utc"]),
            x=float(xx),
            y=float(yy),
        )
        for (_, r), xx, yy in zip(rows[keep].iterrows(), x[keep], y[keep], strict=True)
    ]


def observations_marks(
    rows: list[dict[str, Any]], storm: str, days: tuple[str, ...]
) -> list[sightings.Observation]:
    """The Ida survey's marks in the square; a mark has no time, so it spans the storm days."""
    if storm != "ida_2021":
        return []
    start, end = _storm_span(days)
    return [
        sightings.Observation(
            source="usgs_marks",
            id=str(r["hwm_id"]),
            kind="high-water mark",
            start=start,
            end=end,
            x=float(r["easting_m"]),
            y=float(r["northing_m"]),
        )
        for r in rows
        if inside(r["easting_m"], r["northing_m"])
    ]


def areas(
    places: pd.DataFrame,
    gs_rows: list[dict[str, Any]],
    se_rows: list[dict[str, Any]],
    days: tuple[str, ...],
) -> list[dict[str, Any]]:
    """The area reports a sighting can fall inside (rule step 6 in ``SIGHTING_RULE``).

    Groundsource: places centred in the square, the polygon in EPSG:32618, over the storm days.
    Storm Events: events with a point in the square, the convex hull of all their points, over
    the event's begin to end on the New York clock.
    """
    import geopandas as gpd
    import shapely

    out = []
    centred = [r for r in gs_rows if r["centroid_inside"]]
    start, end = _storm_span(days)
    for r in centred:
        wkb = places.loc[places["uuid"] == r["uuid"], "geometry_wkb"].iloc[0]
        shape = gpd.GeoSeries([shapely.from_wkb(wkb)], crs="EPSG:4326").to_crs("EPSG:32618")[0]
        out.append(
            {"source": "groundsource", "id": r["uuid"], "shape": shape, "start": start, "end": end}
        )
    for r in se_rows:
        if not r["point_inside"]:
            continue
        x, y = to_utm([p[0] for p in r["points"]], [p[1] for p in r["points"]])
        hull = shapely.MultiPoint(list(zip(x, y, strict=True))).convex_hull
        out.append(
            {
                "source": "storm_events",
                "id": str(r["event_id"]),
                "shape": hull,
                "start": _ny(r["begin_utc"]),
                "end": _ny(r["end_utc"]),
            }
        )
    return out


def covered_by(
    members: list[dict[str, Any]], area_list: list[dict[str, Any]], near_s: float
) -> list[str]:
    """Area reports holding a member (inside the shape, windows within ``near_s``)."""
    import shapely

    found = []
    for a in area_list:
        for m in members:
            t0, t1 = pd.Timestamp(m["start"]), pd.Timestamp(m["end"])
            gap = max(0.0, (a["start"] - t1).total_seconds(), (t0 - a["end"]).total_seconds())
            if gap <= near_s and shapely.covers(
                a["shape"], shapely.Point(m["easting_m"], m["northing_m"])
            ):
                found.append(f"{a['source']}:{a['id']}")
                break
    return found


def sighting_table(
    storm: str,
    observations: list[sightings.Observation],
    area_list: list[dict[str, Any]],
    near_m: float = sightings.NEAR_M,
    near_s: float = sightings.NEAR_S,
) -> dict[str, Any]:
    """The storm's sightings, by source, with the area reports that hold each."""
    rows = sightings.describe(sightings.group(observations, near_m, near_s), storm)
    for r in rows:
        r["inside_area_reports"] = covered_by(r["observations"], area_list, near_s)
    multi = [r for r in rows if r["members"] > 1]
    by_source = {
        s: sum(1 for r in rows if s in r["sources"]) for s in ("nyc_311", "floodnet", "usgs_marks")
    }
    by_area = {
        s: sum(1 for r in rows if any(a.startswith(s + ":") for a in r["inside_area_reports"]))
        for s in ("groundsource", "storm_events")
    }
    largest = max(rows, key=lambda r: (r["members"], r["extent_m"]), default=None)
    return {
        "observations": len(observations),
        "observations_by_source": dict(
            sorted(pd.Series([o.source for o in observations]).value_counts().items())
        )
        if observations
        else {},
        "sightings": len(rows),
        "sightings_with_more_than_one_member": len(multi),
        "sightings_of_more_than_one_source": sum(1 for r in rows if len(r["sources"]) > 1),
        "sightings_of_more_than_one_kind": sum(1 for r in rows if len(r["kinds"]) > 1),
        "by_sources": sightings.by_sources(rows),
        "with_source": by_source,
        "inside_area_reports": by_area,
        "largest": {k: largest[k] for k in ("sighting", "members", "extent_m", "sources")}
        if largest
        else None,
        "extent_m_max": max((r["extent_m"] for r in rows), default=0.0),
        "rows": rows,
    }


def groundsource_relations(
    table: pd.DataFrame, days: tuple[str, ...], square_deg
) -> dict[str, Any]:
    """Groundsource places of the storm days by relation to the square: centroid inside,
    overlapping, and within each of ``GS_NEAR_M`` (distance between polygon and square in
    EPSG:32618; an overlapping place is at 0 m). Counts are cumulative from "overlapping" out."""
    import geopandas as gpd
    import shapely

    rows = table[on_days(table["start_date"], table["end_date"], days)]
    shapes = gpd.GeoSeries(
        shapely.from_wkb(rows["geometry_wkb"].to_numpy()), crs="EPSG:4326"
    ).to_crs("EPSG:32618")
    box = shapely.box(*SQUARE)
    distance = np.asarray(shapes.distance(box), dtype="float64")
    centre = shapely.contains_xy(square_deg, rows["centroid_lon"], rows["centroid_lat"])
    overlap = np.asarray(shapes.intersects(box))
    small = rows["area_km2"].to_numpy() <= SQUARE_KM2
    counts = {
        "centroid_inside": int(centre.sum()),
        "overlapping": int(overlap.sum()),
        **{f"within_{int(m)}_m": int((distance <= m).sum()) for m in GS_NEAR_M},
    }
    no_larger = {
        "centroid_inside": int((centre & small).sum()),
        "overlapping": int((overlap & small).sum()),
        **{f"within_{int(m)}_m": int(((distance <= m) & small).sum()) for m in GS_NEAR_M},
    }
    listed = [
        {
            "uuid": r["uuid"],
            "area_km2": round(float(r["area_km2"]), 4),
            "distance_m": round(float(d), 1),
            "centroid_inside": bool(c),
        }
        for (_, r), d, c in zip(rows.iterrows(), distance, centre, strict=True)
        if d <= max(GS_NEAR_M)
    ]
    return {
        "counts": counts,
        "counts_no_larger_than_square": no_larger,
        "main": counts["centroid_inside"],
        "main_rule": "centroid inside",
        "rows": sorted(listed, key=lambda r: (r["distance_m"], r["area_km2"])),
    }


def daily_requests(table: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Flooding-related rows and requests (twins paired) per day, placed in the square."""
    days = tuple(sorted(table["local_day"].dropna().unique()))
    out = {}
    for day in days:
        flood, _xs, _ys, pairs = rows_311(table, (day,))
        out[day] = {"rows": int(len(flood)), "requests": int(len(flood) - len(pairs))}
    return out


def late_calls(
    daily: dict[str, dict[str, int]],
    dry: dict[str, bool | None],
    rain_max: dict[str, float | None],
    window: tuple[str, str],
    days: tuple[str, ...],
) -> dict[str, Any]:
    """Requests on the storm days and the ``LATE_DAYS`` after, against the dry-day baseline.

    Baseline: the days of ``window`` that are dry by ``ghcn_daily.dry_days``, other than the storm
    days and the ``EXCLUDED_AFTER`` days after them. "Clearly above" [P]: more requests than on
    any baseline day, and at least ``ABOVE_FACTOR`` times the baseline mean.
    """
    from datetime import date, timedelta

    first, last = window
    all_days = []
    d = date.fromisoformat(first)
    while d <= date.fromisoformat(last):
        all_days.append(d.isoformat())
        d += timedelta(days=1)
    end = date.fromisoformat(days[-1])
    after = [(end + timedelta(days=k)).isoformat() for k in range(1, LATE_DAYS + 1)]
    shut = set(days) | {(end + timedelta(days=k)).isoformat() for k in range(1, EXCLUDED_AFTER + 1)}
    base_days = [x for x in all_days if dry.get(x) is True and x not in shut]
    base = [daily.get(x, {"requests": 0})["requests"] for x in base_days]
    mean = float(np.mean(base)) if base else None
    top = max(base) if base else None

    def row(day: str, role: str) -> dict[str, Any]:
        n = daily.get(day, {"requests": 0, "rows": 0})
        above = (
            None
            if mean is None
            else bool(n["requests"] > top and n["requests"] >= ABOVE_FACTOR * mean)
        )
        weekday = date.fromisoformat(day).strftime("%a")
        same = [
            daily.get(x, {"requests": 0})["requests"]
            for x in base_days
            if date.fromisoformat(x).strftime("%a") == weekday
        ]
        return {
            "day": day,
            "weekday": weekday,
            "role": role,
            "rows": n.get("rows", 0),
            "requests": n["requests"],
            "rain_max_mm": rain_max.get(day),
            "excess_over_baseline_mean": None if mean is None else round(n["requests"] - mean, 2),
            "same_weekday_baseline": same,
            "clearly_above": above,
        }

    rows = [row(x, "storm day") for x in days] + [
        row(x, f"day {k} after") for k, x in enumerate(after, start=1)
    ]
    return {
        "rows": rows,
        "baseline": {
            "days": base_days,
            "n_days": len(base_days),
            "requests": base,
            "mean": None if mean is None else round(mean, 2),
            "median": None if not base else float(np.median(base)),
            "max": top,
            "rule": f"dry at Central Park, LaGuardia and JFK (GHCN-Daily PRCP below "
            f"{ghcn_daily.DRY_MM} mm on the day and the {ghcn_daily.DRY_BEFORE} days before) "
            f"within {first} to {last}, other than the storm days and the {EXCLUDED_AFTER} days "
            "after",
        },
        "daily": {x: daily.get(x, {"rows": 0, "requests": 0})["requests"] for x in all_days},
        "dry": {x: dry.get(x) for x in all_days},
        "rain_max_mm": {x: rain_max.get(x) for x in all_days},
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
    storm: str,
    label: str,
    counts: dict[str, dict[str, Any]],
    sight: dict[str, Any],
    depth: np.ndarray | None,
    study,
    gs_shapes: list[tuple[Any, bool]],
    se_shapes: list[Any],
) -> str:
    """One storm: 311 requests, sightings, Groundsource places, FloodNet, marks, on the depth."""
    from matplotlib.colors import ListedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle, Patch

    plt = _plt()
    west, south, east, north = SQUARE
    pad = 250.0
    figure, axis = plt.subplots(figsize=(10.5, 11.4), layout="constrained")
    if depth is not None:
        step = 4
        view = depth[::step, ::step]
        image = axis.imshow(
            np.where(view >= DEPTH_SHOWN_M, view, np.nan),
            extent=(GRID.west, GRID.east, GRID.south, GRID.north),
            cmap=ListedColormap(plt.get_cmap("Blues")(np.linspace(0.3, 1.0, 256))),
            vmin=0.0,
            vmax=1.0,
            alpha=0.9,
            interpolation="nearest",
            zorder=0,
        )
        bar = figure.colorbar(image, ax=axis, shrink=0.55, pad=0.01)
        bar.set_label(
            f"modelled maximum inundation depth, m (F3 replay of this storm; shown from "
            f"{DEPTH_SHOWN_M} m, scale capped at 1 m)",
            fontsize=8,
        )
        bar.ax.tick_params(labelsize=7)
    for g in study.geometry:
        for poly in getattr(g, "geoms", [g]):
            axis.plot(*poly.exterior.xy, color="#aaaaaa", linewidth=0.6, zorder=1)
    axis.plot(
        [west, east, east, west, west],
        [south, south, north, north, south],
        color="#333333",
        linewidth=1.2,
        zorder=1,
    )
    for shape, centred in gs_shapes:
        for poly in getattr(shape, "geoms", [shape]):
            if hasattr(poly, "exterior"):
                axis.plot(
                    *poly.exterior.xy,
                    color=COLOURS["groundsource"],
                    linewidth=1.2 if centred else 0.7,
                    linestyle="-" if centred else "--",
                    alpha=0.85 if centred else 0.4,
                    zorder=2,
                )
    for shape in se_shapes:
        axis.plot(
            *shape.exterior.xy,
            color=COLOURS["storm_events"],
            linewidth=1.4,
            linestyle=":",
            zorder=2,
        )
    pts = [
        (o["easting_m"], o["northing_m"])
        for r in sight["rows"]
        for o in r["observations"]
        if o["source"] == "nyc_311"
    ]
    if pts:
        p = np.array(pts)
        axis.scatter(
            p[:, 0],
            p[:, 1],
            s=16,
            color=COLOURS["nyc_311"],
            edgecolors="white",
            linewidths=0.5,
            zorder=4,
        )
    for r in sight["rows"]:
        if r["members"] < 2:
            continue
        axis.add_patch(
            Circle(
                (r["easting_m"], r["northing_m"]),
                r["extent_m"] / 2 + 35.0,
                fill=False,
                edgecolor="#111111",
                linewidth=1.1,
                zorder=5,
            )
        )
        if r["members"] >= 3:
            axis.annotate(
                str(r["members"]),
                (r["easting_m"], r["northing_m"]),
                xytext=(7, 7),
                textcoords="offset points",
                fontsize=7.5,
                color="#111111",
                zorder=7,
            )
    for r in counts["floodnet"]["rows"]:
        filled = bool(r["recorded_on"])
        axis.scatter(
            r["easting_m"],
            r["northing_m"],
            s=70,
            marker="s",
            facecolors=COLOURS["floodnet"] if filled else "white",
            edgecolors=COLOURS["floodnet"],
            linewidths=1.6,
            zorder=6,
        )
    for r in counts["usgs_marks"]["rows"]:
        axis.scatter(
            r["easting_m"],
            r["northing_m"],
            s=60,
            marker="D",
            color=COLOURS["usgs_marks"],
            edgecolors="white",
            linewidths=1,
            zorder=6,
        )
    axis.set_xlim(west - pad, east + pad)
    axis.set_ylim(south - pad, north + pad)
    axis.set_aspect("equal")
    axis.ticklabel_format(useOffset=False, style="plain")
    axis.tick_params(labelsize=7)
    axis.set_xlabel("easting, m (EPSG:32618)", fontsize=8)
    axis.set_ylabel("northing, m", fontsize=8)
    r311, fn = counts["nyc_311"], counts["floodnet"]
    marks = counts["usgs_marks"]["main"]
    axis.set_title(
        f"Who saw the flood: {label}, inside the square\n"
        f"311: {r311['context']} rows, {r311['main']} requests · {sight['sightings']} sightings "
        f"({sight['sightings_with_more_than_one_member']} of more than one report)\n"
        f"FloodNet: {fn['main']} of {fn['context']} sensors recorded · marks: "
        f"{'none in the cache' if marks is None else marks} · Groundsource places centred in "
        f"the square: {counts['groundsource']['main']}",
        fontsize=9.5,
    )
    handles = [
        Patch(color=plt.get_cmap("Blues")(0.6), alpha=0.75, label="modelled depth (scale right)"),
        Line2D(
            [],
            [],
            marker="o",
            linestyle="",
            color=COLOURS["nyc_311"],
            markersize=5,
            label="311 request (a twin pair drawn once)",
        ),
        Line2D(
            [],
            [],
            marker="o",
            linestyle="",
            markerfacecolor="none",
            markeredgecolor="#111111",
            markersize=11,
            label="sighting of more than one report (number: reports, if 3+)",
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
        Line2D(
            [],
            [],
            color=COLOURS["groundsource"],
            linewidth=1.4,
            label="Groundsource place centred in the square",
        ),
        Line2D(
            [],
            [],
            color=COLOURS["groundsource"],
            linewidth=0.8,
            linestyle="--",
            label=f"other Groundsource place within {int(max(GS_NEAR_M))} m, no larger than "
            "the square",
        ),
        Line2D(
            [],
            [],
            color=COLOURS["storm_events"],
            linewidth=1.4,
            linestyle=":",
            label="Storm Events event with a point in the square (hull of its points)",
        ),
        Line2D([], [], color="#333333", linewidth=1.2, label="model square (grey: study area)"),
    ]
    figure.legend(handles=handles, loc="outside lower center", ncol=2, fontsize=8, frameon=False)
    return _png(figure, f"who_saw_map_{storm}.png")


def figure_late(late: dict[str, dict[str, Any]]) -> str:
    """Daily flooding-related 311 requests in the square, four weeks each side of each storm."""
    from matplotlib.patches import Patch

    plt = _plt()
    figure, axes = plt.subplots(len(STORMS), 1, figsize=(11, 7.4), layout="constrained")
    colours = {
        "storm": COLOURS["nyc_311"],
        "after": "#b79ad6",
        "baseline": "#8a8a8a",
        "other": "#dddddd",
    }
    for axis, (storm, days, label) in zip(axes, STORMS, strict=True):
        lc = late[storm]
        after = [r["day"] for r in lc["rows"] if r["role"] != "storm day"]
        base = set(lc["baseline"]["days"])
        names = list(lc["daily"])
        values = [lc["daily"][d] for d in names]
        role = [
            "storm"
            if d in days
            else "after"
            if d in after
            else "baseline"
            if d in base
            else "other"
            for d in names
        ]
        xs = np.arange(len(names))
        axis.bar(xs, values, width=0.8, color=[colours[r] for r in role], edgecolor="none")
        for x, v, r in zip(xs, values, role, strict=True):
            if r in ("storm", "after"):
                axis.text(x, v + 1, str(v), ha="center", fontsize=7.5, color="#111111")
        b = lc["baseline"]
        if b["mean"] is not None:
            axis.axhline(b["mean"], color="#555555", linewidth=1, linestyle="--")
            axis.axhline(b["max"], color="#555555", linewidth=1, linestyle=":")
            axis.text(
                len(names) - 0.5,
                b["max"] + 1,
                f"dry-day maximum {b['max']}, mean {b['mean']} ({b['n_days']} dry days)",
                ha="right",
                fontsize=7.5,
                color="#333333",
            )
        ticks = [i for i, d in enumerate(names) if d.endswith(("-01", "-08", "-15", "-22"))]
        axis.set_xticks(ticks, [names[i][5:] for i in ticks], fontsize=7.5)
        axis.tick_params(axis="y", labelsize=7.5)
        axis.set_ylabel("requests per day", fontsize=8)
        axis.set_title(
            f"{label}: flooding-related 311 requests in the square, twins paired",
            fontsize=9,
            loc="left",
        )
        axis.grid(axis="y", color="#eeeeee")
        axis.set_axisbelow(True)
        for side in ("top", "right"):
            axis.spines[side].set_visible(False)
    figure.legend(
        handles=[
            Patch(color=colours["storm"], label="storm day"),
            Patch(color=colours["after"], label=f"the {LATE_DAYS} days after"),
            Patch(color=colours["baseline"], label="dry day (baseline)"),
            Patch(color=colours["other"], label="other day (rain, or just after rain)"),
        ],
        loc="outside lower center",
        ncol=4,
        fontsize=8,
        frameon=False,
    )
    return _png(figure, "late_calls.png")


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


def fetch_late(root: Path) -> None:
    """The flooding-related 311 rows and the station rain of the weeks round each storm."""
    for name, window, rain_window in AROUND.values():
        query = nyc_311.fetch_flood(root, name, window, BOX_311)
        rain = ghcn_daily.fetch(root, name, rain_window)
        print(name, [p["rows"] for p in query["pages"]], rain["bytes"])


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
    if "--fetch-late" in argv:
        fetch_late(root)
    needs = [
        root / groundsource.FILE,
        root / floodnet.EVENTS,
        root / floodnet.SENSORS,
        root / usgs_hwm.FILE,
        root / MENDELEY,
        *[root / storm_events.FOLDER / f for pair in SE_FILES.values() for f in pair],
        *[root / nyc_311.FOLDER / s / "query.json" for s, *_ in STORMS],
        *[root / nyc_311.FOLDER / a[0] / "query.json" for a in AROUND.values()],
        *[root / ghcn_daily.FOLDER / f"{a[0]}.json" for a in AROUND.values()],
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
    places_table = groundsource.dated_places(root / groundsource.FILE, {"square": BOX_GS_NEAR})
    fn_events = floodnet.events(root / floodnet.EVENTS, root / floodnet.SENSORS)
    marks = usgs_hwm.as_rows(usgs_hwm.marks(root / usgs_hwm.FILE))
    counts: dict[str, dict[str, dict[str, Any]]] = {}
    queries: dict[str, Any] = {}
    sight: dict[str, dict[str, Any]] = {}
    sensitivity: dict[str, list[dict[str, Any]]] = {}
    relations: dict[str, dict[str, Any]] = {}
    late: dict[str, dict[str, Any]] = {}
    extended: dict[str, dict[str, Any]] = {}
    around_queries: dict[str, Any] = {}
    rain_queries: dict[str, Any] = {}
    map_shapes: dict[str, tuple[list, list]] = {}
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
        # 1. sightings
        flood, xs, ys, pairs = rows_311(requests, days)
        observations = (
            observations_311(flood, xs, ys, pairs)
            + observations_floodnet(fn_events, days)
            + observations_marks(marks, storm, days)
        )
        area_list = areas(
            places_table,
            counts[storm]["groundsource"]["rows"],
            counts[storm]["storm_events"]["rows"],
            days,
        )
        sight[storm] = sighting_table(storm, observations, area_list)
        sensitivity[storm] = sightings.sensitivity(
            observations, SENSITIVITY_M, [h * 3600.0 for h in SENSITIVITY_H]
        )
        # 3. Groundsource by relation to the square
        relations[storm] = groundsource_relations(places_table, days, square)
        near = {r["uuid"]: r for r in relations[storm]["rows"]}
        chosen = places_table[
            places_table["uuid"].isin(near) & (places_table["area_km2"] <= SQUARE_KM2)
        ].drop_duplicates("uuid")
        utm = gpd.GeoSeries(
            shapely.from_wkb(chosen["geometry_wkb"].to_numpy()), crs="EPSG:4326"
        ).to_crs("EPSG:32618")
        view = shapely.box(*SQUARE).buffer(400.0, join_style="mitre")
        map_shapes[storm] = (
            [
                (shape, near[u]["centroid_inside"])
                for shape, u in zip(utm.intersection(view), chosen["uuid"], strict=True)
                if not shape.is_empty
            ],
            [a["shape"] for a in area_list if a["source"] == "storm_events"],
        )
        # 2. late calls
        name, window, rain_window = AROUND[storm]
        around, around_queries[storm] = nyc_311.read(root, name)
        rain = ghcn_daily.read(root, name)
        rain_queries[storm] = json.loads(
            (root / ghcn_daily.FOLDER / f"{name}.query.json").read_text()
        )
        rain_days = sorted(rain["day"].unique())
        late[storm] = late_calls(
            daily_requests(around),
            ghcn_daily.dry_days(rain, rain_days),
            ghcn_daily.daily_max(rain),
            window,
            days,
        )
        plus = tuple(days) + (late[storm]["rows"][len(days)]["day"],)
        e_flood, e_xs, e_ys, e_pairs = rows_311(around, plus)
        e_obs = (
            observations_311(e_flood, e_xs, e_ys, e_pairs)
            + observations_floodnet(fn_events, plus)
            + observations_marks(marks, storm, plus)
        )
        e_sight = sighting_table(storm, e_obs, [])
        extended[storm] = {
            "days": list(plus),
            "rows_311": int(len(e_flood)),
            "requests_311": int(len(e_flood) - len(e_pairs)),
            "sightings": e_sight["sightings"],
            "by_sources": e_sight["by_sources"],
        }

    study = gpd.read_file(STUDY_AREA).to_crs("EPSG:32618")
    depth = model_depths(root)
    figures = [figure_counts(counts)]
    for storm, _days, label in STORMS:
        figures.append(
            figure_map(
                storm,
                label,
                counts[storm],
                sight[storm],
                depth.get(storm),
                study,
                *map_shapes[storm],
            )
        )
    figures.append(figure_late(late))
    if fv3_figure:
        figures.append(fv3_figure)

    summary = {
        storm: {
            source: {k: c[k] for k in ("main", "main_label", "context", "context_label")}
            for source, c in counts[storm].items()
        }
        for storm, *_ in STORMS
    }
    combined = {
        storm: {
            "raw_rows_311": counts[storm]["nyc_311"]["context"],
            "requests_311": counts[storm]["nyc_311"]["main"],
            "twin_pairs_311": counts[storm]["nyc_311"]["twin_pairs"],
            "observations": sight[storm]["observations"],
            "observations_by_source": sight[storm]["observations_by_source"],
            "sightings": sight[storm]["sightings"],
            "sightings_with_more_than_one_member": sight[storm][
                "sightings_with_more_than_one_member"
            ],
            "sightings_of_more_than_one_source": sight[storm]["sightings_of_more_than_one_source"],
            "sightings_of_more_than_one_kind": sight[storm]["sightings_of_more_than_one_kind"],
            "by_sources": sight[storm]["by_sources"],
            "with_source": sight[storm]["with_source"],
            "inside_area_reports": sight[storm]["inside_area_reports"],
            "largest": sight[storm]["largest"],
            "extent_m_max": sight[storm]["extent_m_max"],
        }
        for storm, *_ in STORMS
    }
    late_summary = {
        storm: {
            "baseline": {k: v for k, v in late[storm]["baseline"].items() if k != "requests"},
            "rows": late[storm]["rows"],
        }
        for storm, *_ in STORMS
    }
    proposal = {
        storm: next(r for r in late[storm]["rows"] if r["role"] == "day 1 after")["clearly_above"]
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
            "under both schemes are paired (nyc_311.twins, the strict case of "
            "observations.sightings) and counted once",
            passed=None,
            value={
                k: twins_2023[k]
                for k in ("legacy_rows", "current_rows", "twin_pairs", "main", "context")
            },
            note="Reported. The facts row says 'count both'; on 29 Sep 2023 most rows of the "
            "current scheme have a twin of the legacy scheme, so counting rows would count most "
            "requests twice.",
        ),
        Check(
            name="FV5: reports of the same flooding combined into sightings",
            rule=f"observations of 311, FloodNet and the marks within {sightings.NEAR_M:.0f} m "
            f"[P] and {sightings.NEAR_S / 3600:.0f} h [P] of each other, chained, are one "
            "sighting; every member kept (observations.sightings)",
            passed=None,
            value={s: {k: combined[s][k] for k in ("requests_311", "sightings")} for s in combined},
            proposed=True,
            note="Reported, not judged. The sensitivity table (tables.sightings_sensitivity) "
            "gives the count for other thresholds.",
        ),
        Check(
            name="FV5: late calls, the day after the storm against dry days",
            rule=f"requests on the day after the storm above every dry baseline day and at least "
            f"{ABOVE_FACTOR:g} times the baseline mean [P]",
            passed=None,
            value=proposal,
            proposed=True,
            note="Reported. A True proposes extending that storm's 311 window by the day after; "
            "the window used for the counts is unchanged until Yuri decides.",
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
        **{
            f"who_saw_map_{storm}.png": (
                f"{label}: who saw the flood inside the model square. Background: the frozen F3 "
                "replay of this storm, maximum inundation depth from "
                f"{DEPTH_SHOWN_M} m (for orientation only; nothing is compared). Purple dots: "
                "311 flooding-related requests, a twin pair drawn once. Black rings: sightings "
                "of more than one report (observations.sightings: within "
                f"{sightings.NEAR_M:.0f} m and {sightings.NEAR_S / 3600:.0f} h, chained), the "
                "number of reports beside rings of three or more. Green squares: FloodNet "
                "sensors in service (filled: recorded an event). Black diamonds: USGS marks. "
                "Orange outlines: Groundsource places of the storm days, solid when centred "
                f"in the square, dashed when within {int(max(GS_NEAR_M))} m and no larger than "
                "the square (larger places, such as a borough, are counted but not drawn). "
                "Dotted red: the hull of the points of a Storm Events event with a point in "
                "the square."
            )
            for storm, _d, label in STORMS
        },
        "late_calls.png": (
            "Flooding-related 311 requests per day inside the square (twin rows paired), four "
            "weeks each side of each storm. Dark: the storm days; light purple: the two days "
            "after; grey: dry days, the baseline (GHCN-Daily rain below "
            f"{ghcn_daily.DRY_MM} mm at Central Park, LaGuardia and JFK on the day and the "
            f"{ghcn_daily.DRY_BEFORE} days before, other than the storm and the "
            f"{EXCLUDED_AFTER} days after); pale: other days. Dashed line: baseline mean; "
            "dotted: baseline maximum."
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
        *[
            Input.of(root / nyc_311.FOLDER / AROUND[s][0] / name, root=root)
            for s, *_ in STORMS
            for name in ("query.json", *[p["file"] for p in around_queries[s]["pages"]])
        ],
        *[
            Input.of(root / ghcn_daily.FOLDER / name, root=root, url=rain_queries[s]["url"])
            for s, *_ in STORMS
            for name in (f"{AROUND[s][0]}.json", f"{AROUND[s][0]}.query.json")
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
            Parameter("sighting_metres", sightings.NEAR_M, "P", "sighting rule: discs this close"),
            Parameter(
                "sighting_seconds", sightings.NEAR_S, "P", "sighting rule: windows this close"
            ),
            Parameter(
                "groundsource_near_m", list(GS_NEAR_M), "P", "places counted this near the square"
            ),
            Parameter("dry_mm", ghcn_daily.DRY_MM, "P", "a dry day: less rain than this, mm"),
            Parameter("dry_days_before", ghcn_daily.DRY_BEFORE, "P", "and on these days before"),
            Parameter(
                "baseline_excluded_after", EXCLUDED_AFTER, "P", "days after a storm kept out"
            ),
            Parameter("late_above_factor", ABOVE_FACTOR, "P", "clearly above: this times the mean"),
            Parameter("box_311", list(BOX_311), "I", "coarse first cut round the square"),
            Parameter("box_groundsource", list(BOX_GS_NEAR), "I", "first cut round the square"),
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
            **{f"{storm}_sightings": sight[storm]["sightings"] for storm, *_ in STORMS},
            **{f"{storm}_late_day_after_clearly_above": proposal[storm] for storm, *_ in STORMS},
        },
        tables={
            "fv3": fv3,
            "fv5_summary": summary,
            "fv5_counts": counts,
            "sighting_rule": SIGHTING_RULE,
            "sightings_summary": combined,
            "sightings_sensitivity": sensitivity,
            "sightings": {s: sight[s]["rows"] for s in sight},
            "groundsource_relations": relations,
            "late_calls": late_summary,
            "late_calls_daily": {
                s: {k: late[s][k] for k in ("daily", "dry", "rain_max_mm")} for s in late
            },
            "extended_window": extended,
            "rules": RULES,
            "storm_days": {s: list(d) for s, d, _ in STORMS},
            "nyc_311_queries": {
                s: {k: q[k] for k in ("window_local_days", "box_west_south_east_north", "queries")}
                | {"fetched_at": [p["fetched_at"] for p in q["pages"]]}
                for s, q in queries.items()
            },
            "nyc_311_around_queries": {
                s: {k: q[k] for k in ("window_local_days", "box_west_south_east_north", "queries")}
                | {"fetched_at": [p["fetched_at"] for p in q["pages"]]}
                for s, q in around_queries.items()
            },
            "ghcn_daily_queries": {
                s: {k: q[k] for k in ("url", "fetched_at", "sha256")}
                for s, q in rain_queries.items()
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
            "Sightings (observations.sightings) are the lab's grouping, refining the facts row's "
            "'count both': twin rows are one request, and reports close in place and time are "
            "one sighting with every member kept. Change entry CH-24 is proposed, not entered.",
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
                "sightings": combined,
                "groundsource": {s: relations[s]["counts"] for s in relations},
                "late": {
                    s: {
                        "baseline": late_summary[s]["baseline"]["mean"],
                        "rows": [
                            (r["day"], r["requests"], r["clearly_above"]) for r in late[s]["rows"]
                        ],
                    }
                    for s in late
                },
                "extended": extended,
                "written": datetime.now(UTC).isoformat(),
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
