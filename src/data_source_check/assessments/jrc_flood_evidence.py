"""JRC GloFAS flood maps beside outside evidence (Stage 3 of V8, 2026-11-17).

Comparisons, not checks: each gives numbers and their limits and carries no outcome. They say
nothing about crc-sdk's fidelity; they describe the publisher's maps where a user would meet them.

- FEMA flood zones (1 percent annual chance) against the 100-year map, pixel by pixel, in the
  Houston, Austin and Fremont boxes;
- USGS annual peak stages at gauges, with NWS flood stages, against the map's depth at the gauge;
- USGS high-water marks of Hurricane Harvey (2017) against the map's depth at the mark.

    python -m data_source_check.assessments.jrc_flood_evidence --maps
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..core import compare
from ..evidence import fema_nfhl, usgs_peaks, usgs_stn
from ..reference import jrc_flood as reference
from . import jrc_flood_011 as base
from .jrc_flood_areas import FIRST_SHOWN, MAP_PERIODS, MAPS

AREAS = tuple(
    a for a in base.AREAS if a.id in ("glofas-houston", "glofas-austin", "glofas-fremont")
)
GAUGE_AREAS = ("glofas-houston", "glofas-austin")
MARK_AREA = "glofas-houston"
FOOT = 0.3048
#: resolution of the evidence maps (cells of about 0.74 km2, and 0.105 km2 in the Fremont box)
EVIDENCE_RESOLUTION = {"glofas-houston": 8, "glofas-austin": 8, "glofas-fremont": 9}
NEAR = 3  # pixels each way round a gauge: about 270 m
SIR = (Path(__file__).resolve().parents[3] / "docs" / "validation" / "references"
       / "usgs-sir-2018-5070" / "sir20185070.txt")  # fmt: skip
SIR_ROW = re.compile(
    r"^\s+(\d{1,2})\s+(0\d{7})\s+(\d{1,2}/\d{1,2}/2017)\s+([\d.]+|--)\s+([\d,]+)\s+(\d+)\s+(\d+)"
    r"\s+(<?[\d.]+)\s+(<?[\d.]+)\s+(<?[\d.]+)\s*$"
)


def sir_table(text: str) -> dict[str, dict[str, Any]]:
    """Table 3 of USGS SIR 2018-5070 by station: rank of the Harvey peak, years, AEP (percent).

    An estimate printed as "<0.2" is kept as 0.2 with ``below`` true."""
    out = {}
    for line in text.splitlines():
        found = SIR_ROW.match(line)
        if found:
            _, station, date, _, _, rank, years, estimate, _, _ = found.groups()
            out[station] = {"date": date, "rank": int(rank), "years": int(years),
                            "aep_percent": float(estimate.lstrip("<")),
                            "below": estimate.startswith("<")}  # fmt: skip
    return out


def read_area(copy: reference.Copy, area: base.Area, periods: Sequence[int],
              rules: reference.Rules) -> list[dict[str, Any]]:  # fmt: skip
    """The publisher's depths in the box, one part per tile: depth per return period (NaN where
    dry), the permanent-water layer and the grid of the window."""
    tiles = reference.tiles_for(json.loads(copy.text("tile_extents.geojson")), area.bounds)
    parts = []
    for tile in tiles:
        stack = [reference.Tiff(copy.file(reference.depth_name(copy.layout, p, tile)))
                 for p in periods]  # fmt: skip
        first = stack[0]
        window = first.window(area.bounds, rules)
        if window is not None:
            c0, r0, c1, r1 = window
            raw = np.stack([tiff.read(window) for tiff in stack])
            with reference.Tiff(
                copy.file(f"Permanent_WaterBodies/{tile}_permanent_water.tif")
            ) as w:
                water = w.read(window)
                water = (
                    (water != 0)
                    if w.nodata is None
                    else ((water != 0) & (water != np.asarray(w.nodata, dtype=water.dtype)))
                )
            parts.append({
                "tile": tile, "west": first.left + c0 * first.dx,
                "north": first.top - r0 * first.dy,
                "dx": first.dx, "dy": first.dy, "shape": (r1 - r0, c1 - c0),
                "depth": reference.depths(raw, first.nodata, rules), "water": water,
            })  # fmt: skip
        for tiff in stack:
            tiff.close()
    return parts


def rasterize(shapes: Sequence[Any], part: dict[str, Any]) -> np.ndarray:
    """Pixels of a part whose centre lies in any of the polygons."""
    from affine import Affine
    from rasterio import features

    if not shapes:
        return np.zeros(part["shape"], dtype=bool)
    transform = Affine(part["dx"], 0, part["west"], 0, -part["dy"], part["north"])
    return features.rasterize(((s, 1) for s in shapes), out_shape=part["shape"],
                              transform=transform, fill=0, dtype="uint8").astype(bool)  # fmt: skip


def at(part: dict[str, Any], lon: float, lat: float) -> tuple[int, int] | None:
    """Row and column of the pixel that holds a point, or None outside the part."""
    column = int(np.floor((lon - part["west"]) / part["dx"]))
    row = int(np.floor((part["north"] - lat) / part["dy"]))
    rows, columns = part["shape"]
    return (row, column) if 0 <= row < rows and 0 <= column < columns else None


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "none"


def _median(values: Sequence[float]) -> float | None:
    return round(float(np.median(values)), 2) if len(values) else None


# ------------------------------------------------------------------------------- FEMA zones
def fema(area: base.Area, parts: Sequence[dict[str, Any]], periods: Sequence[int],
         evidence: Path, *, live: bool,
         ) -> tuple[dict[str, Any], list[dict[str, np.ndarray]]]:  # fmt: skip
    record = fema_nfhl.fetch(area.bounds, evidence, live=live)
    zones = fema_nfhl.zones(fema_nfhl.read_pages(record))
    by_class: dict[str, list[Any]] = {"1pct-riverine": [], "1pct-coastal": [], "0.2pct": []}
    for zone in zones:
        if zone["class"] in by_class:
            by_class[zone["class"]].append(zone["geometry"])
    i100, i500 = list(periods).index(100), list(periods).index(500)
    total = dict.fromkeys(
        ("pixels", "water", "a", "v", "x02", "j100", "j500", "both", "j_only", "a_only",
         "j500_any", "few", "few_a", "few_any", "fit", "fit_a", "fit_any"), 0)  # fmt: skip
    masks = []
    for part in parts:
        a, v = rasterize(by_class["1pct-riverine"], part), rasterize(by_class["1pct-coastal"], part)
        x02 = rasterize(by_class["0.2pct"], part) & ~a & ~v
        held = np.isfinite(part["depth"])
        land = ~part["water"]
        j100, j500 = held[i100] & land, held[i500] & land
        knots = held.sum(axis=0)
        few = (knots > 0) & (knots < 4) & land
        fit = (knots >= 4) & land
        any_zone = a | v | x02
        for key, value in (
            ("pixels", np.ones_like(a)), ("water", part["water"]), ("a", a & land),
            ("v", v & land), ("x02", x02 & land), ("j100", j100), ("j500", j500),
            ("both", j100 & a), ("j_only", j100 & ~a & ~v), ("a_only", a & land & ~j100),
            ("j500_any", j500 & any_zone), ("few", few), ("few_a", few & a),
            ("few_any", few & any_zone), ("fit", fit), ("fit_a", fit & a),
            ("fit_any", fit & any_zone),
        ):  # fmt: skip
            total[key] += int(value.sum())
        masks.append({"a": a, "v": v, "x02": x02})
    t = total
    dates = sorted(d for ds in record.get("panel_effective_dates", {}).values() for d in ds)
    entry = {
        "id": f"fema[{area.id}]",
        "title": f"FEMA flood zones against the 100-year map: {area.title}",
        "evidence": {
            "name": "FEMA National Flood Hazard Layer, flood hazard zones (layer "
                    f"{record['zone_layer'].get('id', 28)})",
            "url": record["service"], "retrieved_at": record["retrieved_at"],
            "bytes": record["bytes"], "features": record["features_unique"],
            "licence": "none stated by the service; a U.S. federal government work",
            "panel_effective_dates": f"{dates[0]} to {dates[-1]}" if dates else "not given",
        },
        "method": "Every GloFAS pixel of the box is set against the FEMA zone that holds its "
                  "centre. FEMA's 1 percent annual chance zones are the A zones (called riverine "
                  "here) and the V zones (coastal); the 0.2 percent zone is zone X so labelled. "
                  "GloFAS 'flooded' is a published depth at that return period on a pixel "
                  "outside JRC's permanent-water layer.",
        "numbers": [
            ["Pixels in the box", t["pixels"]],
            ["In JRC's permanent water (left out below)", t["water"]],
            ["In a FEMA A zone", t["a"]],
            ["In a FEMA V zone (coastal)", t["v"]],
            ["In FEMA's 0.2 percent zone", t["x02"]],
            ["Flooded in GloFAS at 100 years", t["j100"]],
            ["Flooded at 100 years and in an A zone", t["both"]],
            ["... as a share of the A-zone pixels", _share(t["both"], t["a"])],
            ["... as a share of the GloFAS pixels", _share(t["both"], t["j100"])],
            ["Flooded at 100 years, outside A and V zones", t["j_only"]],
            ["In an A zone, dry in GloFAS at 100 years", t["a_only"]],
            ["Flooded at 500 years", t["j500"]],
            ["... of those, in an A, V or 0.2 percent zone", _share(t["j500_any"], t["j500"])],
            ["Flooded pixels with a depth at fewer than four return periods (no curve in "
             "crc-sdk)", t["few"]],
            ["... of those, in an A zone", _share(t["few_a"], t["few"])],
            ["... of those, in an A, V or 0.2 percent zone", _share(t["few_any"], t["few"])],
            ["Flooded pixels with four or more depths", t["fit"]],
            ["... of those, in an A zone", _share(t["fit_a"], t["fit"])],
            ["... of those, in an A, V or 0.2 percent zone", _share(t["fit_any"], t["fit"])],
        ],
        "limits": [
            "GloFAS models large rivers without flood defences; FEMA zones also cover small "
            "streams, ponding and, in A zones near the coast, storm surge. Much of the "
            "disagreement is a difference of scope.",
            "FEMA zones are regulatory maps of different dates per panel; the 1 percent zone "
            "is not a depth.",
            "The zone polygons were generalised by the service to about 1 m and "
            f"{sum(1 for z in zones if not z['valid'])} of {len(zones)} are not valid polygons "
            "after that; they were rasterised as they came.",
            "A pixel is about 90 m; a zone narrower than that can be missed.",
        ],
    }  # fmt: skip
    return entry, masks


# ------------------------------------------------------------------------------- gauges
def gauges(area: base.Area, parts: Sequence[dict[str, Any]], periods: Sequence[int],
           evidence: Path, *, live: bool,
           ) -> tuple[dict[str, Any], list[dict[str, Any]]]:  # fmt: skip
    record = usgs_peaks.fetch(area.bounds, evidence, live=live)
    data = usgs_peaks.read(record)
    stages = {s["usgs_id"]: s for s in data["stages"]}
    report = sir_table(SIR.read_text(encoding="utf-8")) if SIR.exists() else {}
    index = {p: list(periods).index(p) for p in (10, 100, 500)}
    rows = []
    for site in data["sites"]:
        heights = [p for p in data["peaks"] if p["site_no"] == site["site_no"]
                   and p["gage_height_ft"] is not None]  # fmt: skip
        harvey = [p["gage_height_ft"] for p in heights
                  if "2017-08-25" <= p["date"] <= "2017-09-30"]  # fmt: skip
        near: dict[int, float | None] = dict.fromkeys(index)
        on_water = False
        for part in parts:
            where = at(part, site["lon"], site["lat"])
            if where is None:
                continue
            r, c = where
            box = (slice(max(0, r - NEAR), r + NEAR + 1), slice(max(0, c - NEAR), c + NEAR + 1))
            on_water = bool(part["water"][box].any())
            for period, i in index.items():
                window = np.where(part["water"][box], np.nan, part["depth"][i][box])
                near[period] = float(np.nanmax(window)) if np.isfinite(window).any() else None
        stage = stages.get(site["site_no"], {})
        minor = stage.get("minor_stage")
        top = max((p["gage_height_ft"] for p in heights), default=None)
        rows.append({
            "site_no": site["site_no"], "name": site["name"], "lon": site["lon"],
            "lat": site["lat"], "drainage_area_sqmi": site["drainage_area_sqmi"],
            "peaks_with_a_stage": len(heights),
            "largest_stage_ft": top, "harvey_stage_ft": max(harvey, default=None),
            "nws_minor_flood_stage_ft": minor, "nws_major_flood_stage_ft": stage.get("major_stage"),
            "largest_above_minor_m": round((top - minor) * FOOT, 2)
            if top is not None and minor is not None else None,
            "harvey_above_minor_m": round((max(harvey) - minor) * FOOT, 2)
            if harvey and minor is not None else None,
            "glofas_10_m": near[10], "glofas_100_m": near[100], "glofas_500_m": near[500],
            "permanent_water_nearby": on_water,
            "harvey_aep_percent": report.get(site["site_no"], {}).get("aep_percent"),
            "harvey_aep_below": report.get(site["site_no"], {}).get("below"),
        })  # fmt: skip
    wet = [r for r in rows if r["glofas_100_m"] is not None]
    staged = [r for r in rows if r["largest_above_minor_m"] is not None]
    both = [r for r in staged if r["glofas_100_m"] is not None]
    listed = [r for r in rows if r["harvey_aep_percent"] is not None]
    major = [r for r in rows if r["harvey_stage_ft"] is not None
             and r["nws_major_flood_stage_ft"] is not None]  # fmt: skip
    entry = {
        "id": f"gauges[{area.id}]",
        "title": f"USGS gauge peaks against the map's depth at the gauge: {area.title}",
        "evidence": {
            "name": "USGS NWIS annual peaks (stage and streamflow); NOAA NWPS flood stages; "
                    "USGS SIR 2018-5070, table 3",
            "url": "https://nwis.waterdata.usgs.gov/nwis/peak",
            "retrieved_at": record["retrieved_at"],
            "bytes": record["bytes"], "features": len(rows),
            "licence": "U.S. public domain (USGS); attribution requested; peaks may be provisional",
        },
        "method": "For each stream gauge in the box: its annual peak stages, the NWS minor flood "
                  "stage where NWS has the gauge, and the largest GloFAS depth within three "
                  "pixels (about 270 m) of the gauge at 10, 100 and 500 years, on pixels outside "
                  "JRC's permanent-water layer (where the map holds a patch value). 'Above flood "
                  "stage' is a peak stage minus the minor flood stage, in metres.",
        "numbers": [
            ["Stream gauges with annual peaks", len(rows)],
            ["With GloFAS water within 270 m at 100 years", len(wet)],
            ["With an NWS minor flood stage and a peak stage", len(staged)],
            ["With both", len(both)],
            ["Those with both: median of the record's highest stage above flood stage (m)",
             _median([r["largest_above_minor_m"] for r in both])],
            ["Those with both: median GloFAS depth at 100 years (m)",
             _median([r["glofas_100_m"] for r in both])],
            ["Those with both: median GloFAS depth at 500 years (m)",
             _median([r["glofas_500_m"] for r in both if r["glofas_500_m"] is not None])],
            ["With an NWS flood stage and no GloFAS water within 270 m at 100 years",
             len(staged) - len(both)],
            ["Gauges with a Harvey peak stage and an NWS major flood stage", len(major)],
            ["... where the Harvey peak was above the major flood stage",
             sum(1 for r in major if r["harvey_stage_ft"] > r["nws_major_flood_stage_ft"])],
            ["Gauges listed in USGS SIR 2018-5070, table 3", len(listed)],
            ["... with a Harvey peak rarer than 1 percent a year",
             sum(1 for r in listed if r["harvey_aep_percent"] < 1.0 or
                 (r["harvey_aep_percent"] <= 1.0 and r["harvey_aep_below"]))],
            ["... with a Harvey peak rarer than 0.2 percent a year",
             sum(1 for r in listed if r["harvey_aep_below"])],
        ],
        "table": {
            "title": "Gauges with an NWS flood stage",
            "head": ["Gauge", "Name", "Peaks", "Highest stage above flood stage (m)",
                     "Harvey above flood stage (m)", "GloFAS 10 y (m)", "GloFAS 100 y (m)",
                     "GloFAS 500 y (m)", "Harvey AEP (%)"],
            "rows": [[r["site_no"], r["name"], r["peaks_with_a_stage"],
                      r["largest_above_minor_m"],
                      "" if r["harvey_above_minor_m"] is None else r["harvey_above_minor_m"],
                      *("dry" if r[k] is None else round(r[k], 2)
                        for k in ("glofas_10_m", "glofas_100_m", "glofas_500_m")),
                      "" if r["harvey_aep_percent"] is None else
                      ("<" if r["harvey_aep_below"] else "") + str(r["harvey_aep_percent"])]
                     for r in staged],
        },
        "limits": [
            "A gauge stage is a height above the gauge's own datum, not a depth of water over "
            "land. Stage above the NWS flood stage is used as a rough stand-in for depth over "
            "the banks; it is not the same quantity as a GloFAS depth, which at a channel "
            "pixel includes the channel.",
            "Whether the NWS stage scale and the USGS gage height share a datum at each gauge "
            "was not checked.",
            "Both rivers are regulated (reservoirs upstream of Houston and Austin); the record "
            "is not stationary. A record of a few decades says little about 100 and 500 years.",
            "The largest depth within 270 m may belong to a neighbouring channel.",
        ],
    }  # fmt: skip
    return entry, rows


# ------------------------------------------------------------------------------- Harvey marks
def harvey(area: base.Area, parts: Sequence[dict[str, Any]], periods: Sequence[int],
           evidence: Path, *, live: bool,
           ) -> tuple[dict[str, Any], list[dict[str, Any]]]:  # fmt: skip
    record = usgs_stn.fetch(evidence, live=live)
    west, south, east, north = area.bounds
    inside = [m for m in usgs_stn.read(record)
              if west <= m["longitude"] <= east and south <= m["latitude"] <= north]  # fmt: skip
    i100, i500 = list(periods).index(100), list(periods).index(500)
    rows = []
    for mark in inside:
        entry = {"id": mark["id"], "lon": mark["longitude"], "lat": mark["latitude"],
                 "environment": mark["environment"], "type": mark["type"],
                 "quality": mark["quality"], "waterbody": mark["waterbody"],
                 "county": mark["county"], "site": mark["site_description"],
                 "elevation_ft": mark["elevation_ft"], "vertical_datum": mark["vertical_datum"],
                 "height_above_ground_m": None if mark["height_above_ground_ft"] is None
                 else round(mark["height_above_ground_ft"] * FOOT, 2),
                 "glofas_100_m": None, "glofas_500_m": None, "permanent_water": False}  # fmt: skip
        for part in parts:
            where = at(part, mark["longitude"], mark["latitude"])
            if where is None:
                continue
            for key, i in (("glofas_100_m", i100), ("glofas_500_m", i500)):
                value = float(part["depth"][i][where])
                entry[key] = round(value, 2) if np.isfinite(value) else None
            entry["permanent_water"] = bool(part["water"][where])
        rows.append(entry)
    measured = [r for r in rows if r["height_above_ground_m"] is not None]
    wet = {p: [r for r in measured if r[f"glofas_{p}_m"] is not None] for p in (100, 500)}
    dry500 = [r for r in measured if r["glofas_500_m"] is None]

    def gap(period: int) -> list[float]:
        return [r["height_above_ground_m"] - r[f"glofas_{period}_m"] for r in wet[period]]

    def quartiles(values: Sequence[float]) -> str:
        if not len(values):
            return "none"
        low, mid, high = np.percentile(values, [25, 50, 75])
        return f"{low:.2f}, {mid:.2f}, {high:.2f}"

    numbers = [
        ["High-water marks of Harvey in the box", len(rows)],
        ["Riverine / coastal", f"{sum(1 for r in rows if r['environment'] == 'Riverine')} / "
                               f"{sum(1 for r in rows if r['environment'] == 'Coastal')}"],
        ["With a height above ground", len(measured)],
        ["... height above ground: quartiles (m)",
         quartiles([r["height_above_ground_m"] for r in measured])],
        ["... on a pixel GloFAS floods at 100 years", len(wet[100])],
        ["... on a pixel GloFAS floods at 500 years", len(wet[500])],
        ["... on a pixel dry in GloFAS at 500 years", len(dry500)],
        ["Marks on a dry pixel: height above ground, quartiles (m)",
         quartiles([r["height_above_ground_m"] for r in dry500])],
    ]  # fmt: skip
    for period in (100, 500):
        numbers += [
            [f"Marks on a {period}-year pixel: mark height, quartiles (m)",
             quartiles([r["height_above_ground_m"] for r in wet[period]])],
            [f"Marks on a {period}-year pixel: GloFAS depth, quartiles (m)",
             quartiles([r[f"glofas_{period}_m"] for r in wet[period]])],
            [f"Marks on a {period}-year pixel: mark minus GloFAS, quartiles (m)",
             quartiles(gap(period))],
            [f"Marks on a {period}-year pixel: mark higher than GloFAS",
             f"{sum(1 for g in gap(period) if g > 0)} of {len(wet[period])}"],
        ]  # fmt: skip
    numbers.append(["Marks with a height that lie in JRC's permanent water",
                    sum(1 for r in measured if r["permanent_water"])])  # fmt: skip
    entry = {
        "id": f"harvey[{area.id}]",
        "title": f"High-water marks of Hurricane Harvey (2017) against the map: {area.title}",
        "evidence": {
            "name": "USGS Short-Term Network, event '2017 Harvey', high-water marks in Texas",
            "url": record["service"], "retrieved_at": record["retrieved_at"],
            "bytes": record["bytes"], "features": record["marks"],
            "licence": "U.S. public domain (USGS); attribution requested",
        },
        "method": "For each surveyed high-water mark with a height above ground: the GloFAS "
                  "depth of the pixel that holds the mark, at 100 and 500 years. Quartiles are "
                  "the 25th, 50th and 75th percentiles.",
        "numbers": numbers,
        "limits": [
            "Harvey was a rainfall flood: bayous, streets and reservoir pools flooded far from "
            "the large rivers GloFAS models, so a mark on a pixel that GloFAS leaves dry is "
            "expected and is not an error of the map.",
            "How rare Harvey was differs by place: USGS SIR 2018-5070 gives annual exceedance "
            "probabilities from below 0.2 to 14 percent at 74 gauges "
            "(docs/validation/references/usgs-sir-2018-5070). It is not one return period.",
            "A mark's height above ground is at one point; a pixel is about 90 m and its depth "
            "is over a 90 m terrain model, which in a channel includes the channel.",
            "Marks are where surveyors went, mostly where water was; they do not sample dry "
            "places.",
        ],
    }  # fmt: skip
    return entry, rows


def comparisons(cache: Path, *, live: bool, log: Callable[[str], None] = lambda _: None,
                collect: dict[str, Any] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """Every comparison of this stage. ``collect`` receives what the map files are made from."""
    rules = reference.Rules()
    evidence = cache / "evidence"
    copy = reference.Copy("glofas", cache, live=live)
    periods = reference.periods(copy.index(), copy.layout)
    out = []
    for area in AREAS:
        log(f"{area.id}: outside evidence")
        parts = read_area(copy, area, periods, rules)
        key = area.id.replace("-", "_")
        entry, masks = fema(area, parts, periods, evidence, live=live)
        entry["map"] = [
            {"label": label, "href": f"explore/#tab=crc&layer=jrc_evidence_{key}_{field}"}
            for field, label in (
                ("fema", "FEMA's 1% zone"),
                ("jrc", "Flooded land in JRC's map"),
                ("jrc_only", "Flooded in JRC's map, outside FEMA's zone"),
                ("fema_only", "In FEMA's zone, dry in JRC's map"),
            )
        ]
        points = [{"label": "Gauges and Harvey marks on the map",
                   "href": "explore/#tab=crc&source=flood_evidence"}]  # fmt: skip
        out.append(entry)
        kept: dict[str, Any] = {"parts": parts, "masks": masks, "periods": periods}
        if area.id in GAUGE_AREAS:
            entry, kept["gauges"] = gauges(area, parts, periods, evidence, live=live)
            entry["map"] = points
            out.append(entry)
        if area.id == MARK_AREA:
            entry, kept["marks"] = harvey(area, parts, periods, evidence, live=live)
            entry["map"] = points
            out.append(entry)
        if collect is not None:
            collect[area.id] = kept
    return out


# ------------------------------------------------------------------------------- map files
def _cells(part: dict[str, Any], resolution: int) -> np.ndarray:
    from h3.api import basic_int as h3

    rows, columns = part["shape"]
    lats = part["north"] - (np.arange(rows) + 0.5) * part["dy"]
    lons = part["west"] + (np.arange(columns) + 0.5) * part["dx"]
    return np.fromiter((h3.latlng_to_cell(float(lat), float(lon), resolution)
                        for lat in lats for lon in lons),
                       dtype=np.uint64, count=rows * columns)  # fmt: skip


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def maps(cache: Path, target: Path = MAPS, *, live: bool = False,
         log: Callable[[str], None] = print) -> list[dict[str, Any]]:  # fmt: skip
    """Per area a cell file (FEMA zone and GloFAS shares), and the gauges and marks as points."""
    kept: dict[str, Any] = {}
    comparisons(cache, live=live, log=log, collect=kept)
    shown = [p for p in MAP_PERIODS[FIRST_SHOWN:]]
    written = []
    for area in AREAS:
        got = kept[area.id]
        resolution = EVIDENCE_RESOLUTION[area.id]
        cells = np.concatenate([_cells(part, resolution) for part in got["parts"]])
        unique, inverse = np.unique(cells, return_inverse=True)
        size = len(unique)
        count = np.bincount(inverse, minlength=size)

        def share(mask_parts: Sequence[np.ndarray], inverse=inverse, size=size, count=count):  # noqa: ANN001, ANN202
            flat = np.concatenate([m.ravel() for m in mask_parts])
            return 100.0 * np.bincount(inverse[flat], minlength=size) / count

        zone = [m["a"] | m["v"] for m in got["masks"]]
        water = [part["water"] for part in got["parts"]]
        fields: dict[str, list[np.ndarray]] = {"fema": [], "jrc": [], "jrc_only": [],
                                               "fema_only": [], "water": []}  # fmt: skip
        for period in shown:
            i = list(got["periods"]).index(period)
            flooded = [np.isfinite(part["depth"][i]) & ~part["water"] for part in got["parts"]]
            fields["fema"].append(share(zone))
            fields["water"].append(share(water))
            fields["jrc"].append(share(flooded))
            fields["jrc_only"].append(share([f & ~z for f, z in zip(flooded, zone, strict=True)]))
            fields["fema_only"].append(
                share([z & ~f & ~w
                       for f, z, w in zip(flooded, zone, water, strict=True)]))  # fmt: skip
        # a cell with no zone, no flooded pixel and no water at any return period is left out
        keep = np.zeros(size, dtype=bool)
        for columns in fields.values():
            for column in columns:
                keep |= column > 0
        titles = {
            "fema": ("FEMA 1 percent zone (A or V), share of the cell",
                     "share of the cell's pixels whose centre lies in a FEMA A or V zone; the "
                     "same at every return period"),
            "jrc": ("Flooded land in JRC's map, share of the cell",
                    "share of the cell's pixels with a published depth at this return period, "
                    "permanent water left out"),
            "jrc_only": ("Flooded in JRC's map, outside FEMA's 1 percent zone",
                         "share of the cell's pixels flooded at this return period and outside "
                         "FEMA's A and V zones"),
            "fema_only": ("In FEMA's 1 percent zone, dry in JRC's map",
                          "share of the cell's pixels in a FEMA A or V zone with no published "
                          "depth at this return period, permanent water left out"),
            "water": ("JRC's permanent water, share of the cell",
                      "share of the cell's pixels in the publisher's permanent-water layer; the "
                      "same at every return period"),
        }  # fmt: skip
        payload = {
            "hazard": f"jrc-evidence-{area.id}", "horizon": 0, "pathway": "historical",
            "release": "GloFAS 2.1.2; FEMA NFHL as served 2026-11-17", "unit": "",
            "value_semantics": "", "tail": "upper", "probability_semantics": None,
            "h3_resolution": resolution, "return_periods": list(MAP_PERIODS),
            "probabilities": [1 - 1 / p for p in MAP_PERIODS], "values_from": FIRST_SHOWN,
            "kinds": ["computed by the validation project from JRC's and FEMA's files"],
            "cells": [f"{int(cell):x}" for cell in unique[keep]],
            "params": [[0, int(n)] for n in count[keep]],
            "fields": {
                key: {"title": titles[key][0], "unit": "%", "semantics": titles[key][1],
                      "values": [[round(float(column[k]), 1) for column in columns]
                                 for k in np.flatnonzero(keep)]}
                for key, columns in fields.items()
            },
            "built_at": compare.now(), "bounds": list(area.bounds),
        }  # fmt: skip
        path = target / f"evidence-{area.id}.json"
        _write(path, payload)
        written.append({"file": str(path), "cells": int(keep.sum()),
                        "bytes": path.stat().st_size})  # fmt: skip

    def points(rows: Sequence[dict[str, Any]], label: Callable[[dict[str, Any]], str],
               drop: Sequence[str]) -> dict[str, Any]:  # fmt: skip
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [round(r["lon"], 5), round(r["lat"], 5)]},
             "properties": {"label": label(r), **{k: v for k, v in r.items()
                                                  if k not in ("lon", "lat", *drop)
                                                  and v is not None}}}
            for r in rows]}  # fmt: skip

    stations = [
        {**r, "curve": {
            "return_periods": [10, 100, 500], "unit": "m",
            "values": [None if r[k] is None else round(r[k], 2)
                       for k in ("glofas_10_m", "glofas_100_m", "glofas_500_m")],
            "note": "JRC GloFAS published depth, the largest within about 270 m of the gauge, "
                    "permanent water left out",
        }}
        for a in GAUGE_AREAS for r in kept[a]["gauges"]
    ]  # fmt: skip
    for name, data in (
        ("gauges.geojson", points(stations, lambda r: f"{r['name']} ({r['site_no']})", ("name",))),
        ("harvey-marks.geojson", points(
            [r for r in kept[MARK_AREA]["marks"] if r["height_above_ground_m"] is not None],
            lambda r: f"Mark {r['id']}: {r['height_above_ground_m']} m above ground", ())),
    ):  # fmt: skip
        path = target / name
        _write(path, data)
        written.append({"file": str(path), "features": len(data["features"]),
                        "bytes": path.stat().st_size})  # fmt: skip
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", action="store_true", help="write the map files")
    parser.add_argument("--live", action="store_true", help="download what the cache lacks")
    parser.add_argument("--cache", type=Path, default=Path("data/cache/validation/jrc-flood"))
    args = parser.parse_args()
    if args.maps:
        for entry in maps(args.cache, live=args.live):
            print(json.dumps(entry))
    else:
        print(json.dumps(comparisons(args.cache, live=args.live, log=print), indent=1))


if __name__ == "__main__":
    main()
