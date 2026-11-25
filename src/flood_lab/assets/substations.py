"""Substation assets from OpenStreetMap (requirements FD3, FD4, FD7; plan F1 step 2).

An asset is a named substation: the outlines that carry the same ``name`` and lie within
``SAME_NAME_GAP_M`` of each other are one asset; outlines with no name are grouped among themselves
by ``UNNAMED_GAP_M``. Rail traction substations (``substation=traction``) are left out and counted.
Each asset gets the centroid of the union of its outlines, its OpenStreetMap ids, the highest
tagged voltage, its kind, operator, ``location`` and ``building`` tags, an indoor flag, and a value
range by the class rules of ``values.toml`` (placeholders [P]).

The review of each asset on aerial imagery is read from ``substation_review.toml``: an asset is
``not reviewed`` until the file says ``kept`` or ``removed``; a removed asset stays in the table
with the reason. Customers served (FD7) stay empty: no public figure per substation exists.

The ground elevation comes from a function passed in (``elevation(x, y)``, project CRS in, metres
above NAVD88 out), so the terrain can be supplied by ``flood_lab.terrain`` or by a test.
"""

from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from flood_lab import domain

HERE = Path(__file__).resolve().parent
VALUES = HERE / "values.toml"
REVIEW = HERE / "substation_review.toml"
#: outlines with the same name within this distance are one asset, metres [P]
SAME_NAME_GAP_M = 300.0
#: outlines with no name within this distance of each other are one asset, metres [P]
UNNAMED_GAP_M = 150.0
#: the voltage from which a substation is a transmission substation (values.toml rule), kV
TRANSMISSION_KV = 230.0
DECISIONS = ("kept", "removed")
NOT_REVIEWED = "not reviewed"

Elevation = Callable[[np.ndarray, np.ndarray], np.ndarray]


@dataclass(frozen=True)
class Outline:
    """One OpenStreetMap element tagged power=substation, in the project CRS."""

    osm_id: str  # "way/123"
    geometry: Any  # shapely Polygon, or LineString for an unclosed way
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.tags.get("name", "").strip()

    @property
    def number(self) -> int:
        return int(self.osm_id.split("/")[1])


# reading ---------------------------------------------------------------------------------------


def _to_project():
    import pyproj

    return pyproj.Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True)


def _ring(points: list[dict[str, float]], transform) -> Any:
    xs, ys = transform.transform([p["lon"] for p in points], [p["lat"] for p in points])
    coords = list(zip(xs, ys, strict=True))
    if len(coords) >= 4 and coords[0] == coords[-1]:
        return shapely.Polygon(coords)
    return shapely.LineString(coords)  # an unclosed way, such as a fence line


def outlines_from_overpass(document: dict[str, Any]) -> list[Outline]:
    """Every element of an Overpass ``out body geom`` answer as an outline in the project CRS."""
    transform = _to_project()
    found = []
    for element in document["elements"]:
        if element["type"] == "way":
            geometry = _ring(element["geometry"], transform)
        elif element["type"] == "relation":
            parts = [
                _ring(m["geometry"], transform) for m in element["members"] if m.get("geometry")
            ]
            polygons = [p for p in parts if p.geom_type == "Polygon"]
            geometry = shapely.union_all(polygons or parts)
        else:  # a node: none in the F0 file, kept as a point if one appears
            x, y = transform.transform(element["lon"], element["lat"])
            geometry = shapely.Point(x, y)
        found.append(
            Outline(f"{element['type']}/{element['id']}", geometry, element.get("tags", {}))
        )
    return found


def in_square(outlines: Iterable[Outline], square=domain.SQUARE) -> list[Outline]:
    """Outlines whose centroid lies inside the square."""
    box = shapely.box(*square)
    return [o for o in outlines if box.contains(o.geometry.centroid)]


# tags ------------------------------------------------------------------------------------------


def parse_voltage_kv(tag: str | None) -> float | None:
    """Highest voltage of an OpenStreetMap tag in volts (``345000;138000``), in kV; None if none."""
    values = []
    for part in (tag or "").replace(",", ";").split(";"):
        part = part.strip()
        try:
            volts = float(part)
        except ValueError:
            continue
        if volts > 0:
            values.append(volts / 1000.0)
    return max(values) if values else None


def indoor_flag(location: str | None) -> str:
    return {"indoor": "yes", "outdoor": "no"}.get((location or "").strip(), "unknown")


def load_values(path: Path = VALUES) -> dict[str, dict[str, Any]]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def value_class(kind: str, kv: float | None) -> str | None:
    """Class of ``values.toml``: transmission, area, or None when the tags do not tell.

    The file's rules: transmission is ``substation=transmission`` or a highest voltage of 230 kV or
    more; area is ``substation=distribution`` or ``minor_distribution``, or a highest voltage below
    230 kV. Where both rules could apply, transmission is taken.
    """
    if kind == "transmission" or (kv is not None and kv >= TRANSMISSION_KV):
        return "transmission"
    if kind in ("distribution", "minor_distribution") or kv is not None:
        return "area"
    return None


def geometric_mean_usd(low: float, high: float) -> int:
    return int(round(math.sqrt(low * high)))


def value_range(klass: str | None, values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Low, mid and high value with tag and source text; all empty when there is no class."""
    if klass is None:
        return {"low": None, "mid": None, "high": None, "tag": "", "source": ""}
    entry = values[klass]
    low, high = entry["low_usd"], entry["high_usd"]
    source = (
        f"placeholder for class '{klass}' ({entry['rule']}): low = {entry['low_source']}; "
        f"high = {entry['high_source']}; mid = the geometric mean of low and high, an inference "
        "with no source of its own; prices as stated by the sources, not adjusted"
    )
    return {
        "low": int(low),
        "mid": geometric_mean_usd(low, high),
        "high": int(high),
        "tag": entry["tag"],
        "source": source,
    }


# grouping --------------------------------------------------------------------------------------


def _clusters(geometries: list[Any], gap: float) -> list[list[int]]:
    """Single-linkage groups: two geometries within ``gap`` metres are in one group."""
    parent = list(range(len(geometries)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(geometries)):
        for j in range(i + 1, len(geometries)):
            if geometries[i].distance(geometries[j]) <= gap:
                parent[root(j)] = root(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(geometries)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def group_outlines(
    outlines: list[Outline],
    *,
    same_name_gap: float = SAME_NAME_GAP_M,
    unnamed_gap: float = UNNAMED_GAP_M,
) -> tuple[list[list[Outline]], list[Outline]]:
    """(assets as lists of outlines, traction outlines left out), each asset sorted by id."""
    traction = [o for o in outlines if o.tags.get("substation", "") == "traction"]
    rest = [o for o in outlines if o.tags.get("substation", "") != "traction"]
    by_name: dict[str, list[Outline]] = {}
    for outline in rest:
        by_name.setdefault(outline.name, []).append(outline)
    assets = []
    for name, members in by_name.items():
        gap = same_name_gap if name else unnamed_gap
        for group in _clusters([m.geometry for m in members], gap):
            assets.append(sorted((members[i] for i in group), key=lambda o: o.osm_id))
    assets.sort(key=lambda group: min(o.number for o in group))
    return assets, sorted(traction, key=lambda o: o.osm_id)


def loc_number(group: list[Outline]) -> str:
    """``S-`` plus the smallest OpenStreetMap id among the asset's outlines: stable across runs."""
    return f"S-{min(o.number for o in group)}"


# review ----------------------------------------------------------------------------------------


def load_review(path: Path = REVIEW) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def review_text(assets: list[dict[str, Any]], existing: dict[str, dict[str, str]]) -> str:
    """The review file with every asset; entries already filled in are kept as they are."""
    lines = [
        "# Review of each substation asset on aerial imagery (requirement FD3, plan F1 step 2).",
        "# Filled in by a person who looked at the contact sheet",
        "# (docs/flood/figures/f1/substation_contact_sheet.png) and the sharper review images in",
        "# the cache (data/cache/flood/assets/review/<LocNumber>_nys2018.png).",
        '# decision: "kept" or "removed" ("not reviewed" until looked at); reason: why, required',
        '# when removed; indoor: "yes", "no" or "unknown" as seen, overrides the location tag when',
        '# "yes" or "no"; seen_on: the imagery looked at; note: anything else.',
        "",
    ]
    for asset in assets:
        key = asset["LocNumber"]
        entry = {"decision": NOT_REVIEWED, "reason": "", "indoor": "", "seen_on": "", "note": ""}
        entry.update(existing.get(key, {}))
        lines.append(f"# {asset['lab_name'] or 'no name'}; {asset['lab_osm_ids']}")
        lines.append(f'["{key}"]')
        for name in ("decision", "reason", "indoor", "seen_on", "note"):
            lines.append(f"{name} = {json.dumps(str(entry.get(name, '')), ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def apply_review(row: dict[str, Any], entry: dict[str, str] | None) -> dict[str, Any]:
    """``lab_reviewed`` and ``lab_indoor`` of one asset from its review entry."""
    row = dict(row)
    decision = (entry or {}).get("decision", NOT_REVIEWED).strip()
    if decision == "kept":
        row["lab_reviewed"] = "kept"
    elif decision == "removed":
        reason = (entry or {}).get("reason", "").strip() or "no reason given"
        row["lab_reviewed"] = f"removed: {reason}"
    else:
        row["lab_reviewed"] = NOT_REVIEWED
    indoor = (entry or {}).get("indoor", "").strip()
    if indoor in ("yes", "no"):
        row["lab_indoor"] = indoor
    return row


# assets ----------------------------------------------------------------------------------------


def _tag(group: list[Outline], name: str) -> str:
    """The values of one tag over the outlines, distinct, joined by ';'."""
    seen = []
    for outline in group:
        value = outline.tags.get(name, "").strip()
        if value and value not in seen:
            seen.append(value)
    return ";".join(seen)


def build(
    outlines: list[Outline],
    *,
    elevation: Elevation,
    land: Any,
    values: dict[str, dict[str, Any]] | None = None,
    review: dict[str, dict[str, str]] | None = None,
    same_name_gap: float = SAME_NAME_GAP_M,
    unnamed_gap: float = UNNAMED_GAP_M,
) -> tuple[list[dict[str, Any]], list[Outline], list[list[Outline]]]:
    """(asset rows, traction outlines left out, the outlines of each asset in row order).

    ``outlines`` are already restricted to the square. Rows carry the lab's substation fields by
    their schema names plus ``lab_name``; ``flood_lab.assets.oed`` turns them into table rows.
    """
    import pyproj

    values = load_values() if values is None else values
    review = {} if review is None else review
    groups, traction = group_outlines(
        outlines, same_name_gap=same_name_gap, unnamed_gap=unnamed_gap
    )
    to_lonlat = pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True)
    rows = []
    centres = [shapely.union_all([o.geometry for o in g]).centroid for g in groups]
    xs = np.array([c.x for c in centres])
    ys = np.array([c.y for c in centres])
    terrain = np.asarray(elevation(xs, ys), dtype=float) if groups else np.array([])
    for group, centre, z in zip(groups, centres, terrain, strict=True):
        kinds = _tag(group, "substation")
        kv_all = [parse_voltage_kv(o.tags.get("voltage")) for o in group]
        known = [v for v in kv_all if v is not None]
        kv = max(known) if known else None
        kind = "transmission" if "transmission" in kinds.split(";") else kinds.split(";")[0]
        klass = value_class(kind, kv)
        money = value_range(klass, values)
        lon, lat = to_lonlat.transform(centre.x, centre.y)
        z = None if not np.isfinite(z) else float(z)
        row = {
            "LocNumber": loc_number(group),
            "lab_name": _tag(group, "name"),
            "Latitude": lat,
            "Longitude": lon,
            "lab_asset_type": "substation",
            "lab_x_m": centre.x,
            "lab_y_m": centre.y,
            "lab_in_study_area": bool(land.covers(centre)),
            "lab_ground_elev_m": z,
            "lab_ground_elev_source": "terrain" if z is not None else "",
            "lab_terrain_elev_m": z,
            "lab_osm_ids": ";".join(o.osm_id for o in group),
            "lab_outlines": len(group),
            "lab_voltage_kv": kv,
            "lab_substation_kind": kinds,
            "lab_operator": _tag(group, "operator"),
            "lab_location_tag": _tag(group, "location"),
            "lab_building_tag": _tag(group, "building"),
            "lab_indoor": indoor_flag(_tag(group, "location")),
            "lab_value_class": klass or "",
            "lab_value_low_usd": money["low"],
            "lab_value_mid_usd": money["mid"],
            "lab_value_high_usd": money["high"],
            "lab_value_tag": money["tag"],
            "lab_value_source": money["source"],
            "lab_customers_served": None,
            "lab_customers_tag": "",
        }
        if len({v for v in (_tag(group, "location") or "").split(";") if v}) > 1:
            row["lab_indoor"] = "unknown"
        rows.append(apply_review(row, review.get(row["LocNumber"])))
    return rows, traction, groups


def geojson(rows: list[dict[str, Any]], groups: list[list[Outline]]) -> dict[str, Any]:
    """The outlines of each asset in WGS84, one feature per outline, for the page."""
    import pyproj

    to_lonlat = pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True)
    features = []
    for row, group in zip(rows, groups, strict=True):
        for outline in group:
            shape = shapely.transform(
                outline.geometry, lambda c: np.column_stack(to_lonlat.transform(c[:, 0], c[:, 1]))
            )
            shape = shapely.set_precision(shape, 1e-7)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "LocNumber": row["LocNumber"],
                        "name": row["lab_name"],
                        "osm_id": outline.osm_id,
                        "closed": outline.geometry.geom_type != "LineString",
                        "kind": outline.tags.get("substation", ""),
                        "voltage_kv": row["lab_voltage_kv"],
                        "reviewed": row["lab_reviewed"],
                    },
                    "geometry": json.loads(shapely.to_geojson(shape)),
                }
            )
    return {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright)",
        "features": features,
    }
