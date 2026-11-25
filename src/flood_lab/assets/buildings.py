"""Building assets: footprints joined to the elevation table and the structure inventory (FD5).

Three city and federal sources are joined for the buildings whose footprint centroid lies on the
study area (the Brooklyn land inside the square):

* footprints (``nyc-building-footprints``) to the Building Elevation and Subgrade table
  (``nyc-building-elevation-subgrade``) by BIN; "million BINs" (six zeros after the borough digit)
  are placeholders for unassigned buildings and are never joined;
* the National Structure Inventory (``usace-national-structure-inventory``), points without a BIN,
  to footprints by point in polygon; a point in no footprint goes to the nearest footprint within
  ``NEAR_M``, else stays unmatched. A footprint with several points takes the SUM of their
  ``val_struct`` as its value: the inventory's publisher states that stacked structures are several
  records on one footprint with the value divided among them (facts file, fact ``known_limits``).
  Occupancy class, foundation type, stories and inventory id are those of the point of largest
  ``val_struct``; every distinct occupancy class is listed in ``lab_occupancy_all``.

Units are converted once, here: the table's feet (NAVD88) become metres. A table value of 0 means
"not measured" (the table's data dictionary) and is left empty, never read as sea level. A missing
value is never filled with a default. Where the grade is not measured, the table's subgrade flag
is a default too, so ``lab_subgrade`` is left empty there. The table's guidance does not record
whether the grade or the floor was the estimated value of a row whose notes say "not visible": its
ground source says "z_grade (grade or floor estimated)", and its first-floor height carries the
same doubt.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely

from flood_lab import domain

#: an inventory point outside every footprint joins the nearest footprint within this, metres [P]
NEAR_M = 15.0
#: international foot in metres; the US survey foot differs by 2 parts per million
FOOT_M = 0.3048
#: the table's notes1 phrase that marks an estimated (or not seen) grade, matched without case
ESTIMATED = "not visible"

Elevation = Callable[[np.ndarray, np.ndarray], np.ndarray]


def feet_to_m(value: Any) -> float | None:
    """Feet to metres; 0, empty or not a number means not measured and gives None."""
    try:
        feet = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(feet) or feet == 0:
        return None
    return feet * FOOT_M


def normal_bin(value: Any) -> str:
    """A BIN as digits (``"3003138.0"`` and ``3003138`` both give ``"3003138"``); "" if none."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return ""


def is_million_bin(value: str) -> bool:
    """The placeholder BINs 1000000, 2000000, ...: borough digit then six zeros."""
    return len(value) == 7 and value[1:] == "000000"


# readers ---------------------------------------------------------------------------------------


def _transformer():
    import pyproj

    return pyproj.Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True)


def _project(geometry):
    transform = _transformer()
    return shapely.transform(
        geometry, lambda c: np.column_stack(transform.transform(c[:, 0], c[:, 1]))
    )


def read_footprints(path: Path) -> pd.DataFrame:
    """The city's footprints GeoJSON: one row per footprint, geometry in the project CRS."""
    document = json.loads(path.read_text(encoding="utf-8"))
    rows, shapes = [], []
    for feature in document["features"]:
        p = feature["properties"]
        shapes.append(shapely.from_geojson(json.dumps(feature["geometry"])))
        rows.append(
            {
                "bin": normal_bin(p.get("bin")),
                "doitt_id": p.get("doitt_id") or "",
                "construction_year": _int(p.get("construction_year")),
                "feature_code": p.get("feature_code") or "",
                "last_status_type": p.get("last_status_type") or "",
            }
        )
    frame = pd.DataFrame(rows)
    frame["geometry"] = list(_project(np.array(shapes, dtype=object)))
    return frame


def read_bes(path: Path) -> pd.DataFrame:
    """The Building Elevation and Subgrade CSV, with the BIN as digits."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    frame = pd.DataFrame(rows)
    frame["bin"] = frame["bin"].map(normal_bin)
    return frame


def read_nsi(path: Path) -> pd.DataFrame:
    """The structure inventory's feature collection, points in the project CRS."""
    document = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame([f["properties"] for f in document["features"]])
    lon = [f["geometry"]["coordinates"][0] for f in document["features"]]
    lat = [f["geometry"]["coordinates"][1] for f in document["features"]]
    frame["x"], frame["y"] = _transformer().transform(lon, lat)
    return frame


def _int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number != 0 else None


# joins -----------------------------------------------------------------------------------------


def join_inventory(
    footprints: list[Any], xs: np.ndarray, ys: np.ndarray, near_m: float = NEAR_M
) -> tuple[np.ndarray, np.ndarray]:
    """Per inventory point: index of its footprint (-1 if none) and how ("inside", "near", "")."""
    points = shapely.points(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
    tree = shapely.STRtree(footprints)
    index = np.full(len(points), -1, dtype=int)
    how = np.full(len(points), "", dtype=object)
    if not len(points):
        return index, how
    pairs = tree.query(points, predicate="intersects")
    for point, footprint in zip(pairs[0], pairs[1], strict=True):
        if index[point] == -1 or footprint < index[point]:  # the first footprint, deterministic
            index[point] = footprint
            how[point] = "inside"
    outside = np.flatnonzero(index == -1)
    if len(outside):
        found, distance = tree.query_nearest(
            points[outside], max_distance=near_m, return_distance=True, all_matches=False
        )
        for (i, j), d in zip(found.T, distance, strict=True):
            if d <= near_m:
                index[outside[i]] = j
                how[outside[i]] = "near"
    return index, how


def pick_inventory(
    nsi: pd.DataFrame, index: np.ndarray
) -> tuple[dict[int, int], dict[int, list[int]]]:
    """(footprint -> row of its point of largest value, footprint -> rows of all its points)."""
    chosen: dict[int, int] = {}
    members: dict[int, list[int]] = {}
    value = pd.to_numeric(nsi["val_struct"], errors="coerce").to_numpy() if len(nsi) else []
    for row, footprint in enumerate(index):
        if footprint < 0:
            continue
        members.setdefault(footprint, []).append(row)
        best = chosen.get(footprint)
        if best is None or (value[row], -row) > (value[best], -best):
            chosen[footprint] = row
    return chosen, members


def summed_value(values: np.ndarray, rows: list[int]) -> float | None:
    """Sum of ``val_struct`` over the rows; None when no row has a value above zero."""
    known = [float(values[r]) for r in rows if np.isfinite(values[r])]
    total = float(sum(known))
    return total if total else None


def real_footprint_id(value: Any) -> str:
    """The inventory's own footprint id (``36047_123``), or "" for ``none_...`` and empty."""
    text = "" if value is None else str(value).strip()
    return "" if not text or text.lower().startswith("none") or text == "nan" else text


def match_words(has_bes: bool, has_nsi: bool) -> str:
    return "+".join(
        ["footprint", *(["elevation"] if has_bes else []), *(["inventory"] if has_nsi else [])]
    )


# build -----------------------------------------------------------------------------------------


def build(
    footprints: pd.DataFrame,
    bes: pd.DataFrame,
    nsi: pd.DataFrame,
    *,
    land: Any,
    elevation: Elevation,
    near_m: float = NEAR_M,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(building rows, counts and rates of every join).

    ``footprints`` holds every footprint read (the box), ``bes`` and ``nsi`` every row read; the
    study area is decided here by the footprint centroid. Rows carry schema names plus a few
    ``detail_`` fields that the table has no column for.
    """
    import pyproj

    stats: dict[str, Any] = {}
    shapes = footprints["geometry"].to_numpy()
    centres = shapely.centroid(shapes)
    shapely.prepare(land)
    on_land = shapely.covers(land, centres)
    million = footprints["bin"].map(is_million_bin).to_numpy()
    empty_bin = footprints["bin"].eq("").to_numpy()
    stats["footprints_read"] = int(len(footprints))
    stats["footprints_on_study_area"] = int(on_land.sum())
    stats["footprints_on_study_area_million_bin_excluded"] = int((on_land & million).sum())
    stats["footprints_on_study_area_without_bin_excluded"] = int((on_land & empty_bin).sum())
    keep = on_land & ~million & ~empty_bin
    study = footprints[keep].copy()
    study["centre"] = centres[keep]
    duplicated = study["bin"].duplicated(keep=False)
    stats["footprints_sharing_a_bin_with_another"] = int(duplicated.sum())
    if duplicated.any():  # one asset per BIN: the largest footprint is kept, the rest counted
        study["_area"] = shapely.area(study["geometry"].to_numpy())
        study = study.sort_values(["bin", "_area"], ascending=[True, False])
        study = study[~study["bin"].duplicated(keep="first")].drop(columns="_area")
    stats["buildings"] = int(len(study))

    # footprint to elevation table, by BIN
    bes = bes[~bes["bin"].map(is_million_bin) & bes["bin"].ne("")]
    table = bes.drop_duplicates("bin").set_index("bin")
    has_bes = study["bin"].isin(table.index).to_numpy()
    stats["buildings_with_elevation_row"] = int(has_bes.sum())
    stats["buildings_without_elevation_row"] = int((~has_bes).sum())
    stats["rate_buildings_with_elevation_row"] = _rate(has_bes.sum(), len(study))
    bes_points = shapely.points(
        pd.to_numeric(bes["longitude"], errors="coerce").to_numpy(),
        pd.to_numeric(bes["latitude"], errors="coerce").to_numpy(),
    )
    bes_xy = _project(bes_points)
    bes_on = shapely.covers(land, bes_xy)
    all_bins = set(footprints.loc[~million, "bin"])
    bes_here = bes[bes_on]
    stats["elevation_rows_on_study_area"] = int(len(bes_here))
    stats["elevation_rows_on_study_area_without_footprint_in_file"] = int(
        (~bes_here["bin"].isin(all_bins)).sum()
    )
    stats["elevation_rows_on_study_area_without_study_area_building"] = int(
        (~bes_here["bin"].isin(set(study["bin"]))).sum()
    )

    # inventory to footprints: every point read, against every footprint read; then counted for
    # the points that end on a study-area building, or that are unmatched on the study area
    index, how = join_inventory(list(shapes), nsi["x"].to_numpy(), nsi["y"].to_numpy(), near_m)
    position = {original: i for i, original in enumerate(study.index)}
    study_index = np.array([position.get(i, -1) if i >= 0 else -1 for i in index], dtype=int)
    nsi_on = (
        shapely.covers(land, shapely.points(nsi["x"].to_numpy(), nsi["y"].to_numpy()))
        if len(nsi)
        else np.zeros(0, dtype=bool)
    )
    to_study = study_index >= 0
    unmatched_here = (index < 0) & nsi_on
    stats["inventory_points_read"] = int(len(nsi))
    stats["inventory_points_counted"] = int(to_study.sum() + unmatched_here.sum())
    stats["inventory_points_inside_a_footprint"] = int((to_study & (how == "inside")).sum())
    stats["inventory_points_to_nearest_footprint"] = int((to_study & (how == "near")).sum())
    stats["inventory_points_unmatched"] = int(unmatched_here.sum())
    stats["inventory_points_on_other_footprints"] = int(((index >= 0) & ~to_study & nsi_on).sum())
    chosen, members = pick_inventory(nsi, study_index)
    counts = {k: len(v) for k, v in members.items()}
    values = pd.to_numeric(nsi["val_struct"], errors="coerce").to_numpy() if len(nsi) else []
    ids = nsi["ftprntid"].to_numpy() if "ftprntid" in nsi else np.full(len(nsi), "", dtype=object)
    stats["buildings_with_inventory"] = len(chosen)
    stats["rate_buildings_with_inventory"] = _rate(len(chosen), len(study))
    stats["buildings_with_several_inventory_points"] = sum(1 for c in counts.values() if c > 1)
    stats["inventory_points_on_buildings_with_several"] = sum(c for c in counts.values() if c > 1)
    stats["inventory_value_of_points_on_buildings_usd"] = int(round(np.nansum(values[to_study])))
    largest = {f: values[r] for f, r in chosen.items()}
    summed = {f: summed_value(values, rows) for f, rows in members.items()}
    stats["inventory_value_summed_usd"] = int(round(sum(v or 0.0 for v in summed.values())))
    stats["inventory_value_largest_point_only_usd"] = int(
        round(sum(float(v) for v in largest.values() if np.isfinite(v)))
    )
    tied = {"by_inventory_footprint_id": [], "by_position": []}
    for footprint, rows in members.items():
        if len(rows) < 2:
            continue
        own = {real_footprint_id(ids[r]) for r in rows}
        key = "by_inventory_footprint_id" if len(own) == 1 and "" not in own else "by_position"
        tied[key].append(footprint)
    for key, group in tied.items():
        stats[f"buildings_with_several_points_tied_{key}"] = {
            "buildings": len(group),
            "points": sum(counts[f] for f in group),
            "value_summed_usd": int(round(sum(summed[f] or 0.0 for f in group))),
            "value_of_largest_point_usd": int(
                round(sum(float(largest[f]) for f in group if np.isfinite(largest[f])))
            ),
        }

    # terrain, always
    cx = shapely.get_x(study["centre"].to_numpy())
    cy = shapely.get_y(study["centre"].to_numpy())
    terrain = np.asarray(elevation(cx, cy), dtype=float) if len(study) else np.zeros(0)
    to_lonlat = pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True)
    lon, lat = to_lonlat.transform(cx, cy)
    area = shapely.area(study["geometry"].to_numpy())

    occupancy = nsi["occtype"].to_numpy() if len(nsi) else np.zeros(0, dtype=object)
    stats["buildings_subgrade_left_empty_grade_not_measured"] = 0
    rows = []
    for i, (_, building) in enumerate(study.iterrows()):
        record = table.loc[building["bin"]] if has_bes[i] else None
        grade = feet_to_m(record["z_grade"]) if record is not None else None
        floor = feet_to_m(record["z_floor"]) if record is not None else None
        z = float(terrain[i]) if np.isfinite(terrain[i]) else None
        estimated = record is not None and ESTIMATED in str(record.get("notes1", "")).lower()
        if grade is not None:
            ground = grade
            source = "z_grade (grade or floor estimated)" if estimated else "z_grade"
        elif z is not None:
            ground = z
            source = (
                "terrain (z_grade 0: not measured)"
                if record is not None
                else "terrain (no elevation row)"
            )
        else:
            ground, source = None, ""
        height = floor - grade if floor is not None and grade is not None else None
        # the subgrade flag is a default where the grade was not measured: left empty there
        subgrade = (
            str(record["subgrade"]).strip() if record is not None and grade is not None else ""
        )
        if record is not None and grade is None and str(record["subgrade"]).strip():
            stats["buildings_subgrade_left_empty_grade_not_measured"] += 1
        point = chosen.get(i)
        inv = nsi.iloc[point] if point is not None else None
        value = summed.get(i)
        classes = sorted({str(occupancy[r]) for r in members.get(i, []) if pd.notna(occupancy[r])})
        rows.append(
            {
                "LocNumber": f"B-{building['bin']}",
                "Latitude": lat[i],
                "Longitude": lon[i],
                "NumberOfStoreys": _int(inv["num_story"]) if inv is not None else None,
                "YearBuilt": _int(building["construction_year"]),
                "BuildingTIV": value,
                "FirstFloorHeight": height,
                "lab_asset_type": "building",
                "lab_x_m": cx[i],
                "lab_y_m": cy[i],
                "lab_in_study_area": True,
                "lab_ground_elev_m": ground,
                "lab_ground_elev_source": source,
                "lab_terrain_elev_m": z,
                "lab_first_floor_elev_m": floor,
                "lab_first_floor_height_m": height,
                "lab_subgrade": subgrade,
                "lab_bin": building["bin"],
                "lab_match": match_words(bool(has_bes[i]), inv is not None),
                "lab_occupancy_hazus": str(inv["occtype"]) if inv is not None else "",
                "lab_occupancy_all": ";".join(classes),
                "lab_inventory_points": counts.get(i) or None,
                "lab_foundation_type": str(inv["found_type"]) if inv is not None else "",
                "lab_nsi_id": str(inv["fd_id"]) if inv is not None else "",
                "lab_value_mid_usd": value,
                "lab_value_tag": "S" if value is not None else "",
                "lab_value_source": (
                    "USACE NSI 2026 Base val_struct summed over the building's inventory "
                    "records (lab_inventory_points): depreciated replacement value, Aug 2025 prices"
                    if value is not None
                    else ""
                ),
                "detail_footprint_area_m2": float(area[i]),
                "detail_grade_estimated": bool(estimated),
                "detail_grade_m": grade,
                "detail_inventory_points": counts.get(i, 0),
                "detail_inventory_join": how[point] if point is not None else "",
                "detail_feature_code": building["feature_code"],
                "detail_last_status_type": building["last_status_type"],
                "detail_doitt_id": building["doitt_id"],
            }
        )
    rows.sort(key=lambda r: r["LocNumber"])
    return rows, stats


def _rate(part: int, whole: int) -> float | None:
    return round(float(part) / whole, 6) if whole else None
