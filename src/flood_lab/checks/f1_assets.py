"""F1 visual test: the substations and buildings of the study area as one table (FD3 to FD7).

    FLOOD_CACHE=<cache> uv run --with matplotlib python -m flood_lab.checks.f1_assets

Reads the cached OpenStreetMap substations, the city's footprints and Building Elevation and
Subgrade table, the National Structure Inventory and the neighbourhood outlines; fetches the
substation images once (then offline from the cache). Writes ``site/flood/data/assets_oed.csv``,
``site/flood/data/substations.geojson``, the figures under ``docs/flood/figures/f1/``, the record
``site/flood/tests/records/f1-assets.json``, and a per-building detail file in the cache
(``assets/buildings_detail.csv``) with the fields the table has no column for.

Ground elevation comes from ``flood_lab.terrain.ground_elevation``. While that module does not
exist, a provisional sampler reads the USGS 1 m tile directly (see ``_provisional_terrain``); the
record then says so.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from flood_lab import domain, paths
from flood_lab.assets import buildings as bld
from flood_lab.assets import oed, schema
from flood_lab.assets import substations as sub
from flood_lab.records import Check, Input, Parameter, Record
from lab_common.io import write_text_atomic

OUT = paths.FIGURES / "f1"
FIG = "docs/flood/figures/f1"
GEOJSON = paths.SITE / "data" / "substations.geojson"
#: share of the study area's footprints with a row in the elevation table (plan F1) [P], proposed
MIN_ELEVATION_MATCH = 0.95
#: largest absolute median of table grade minus terrain, metres [P], proposed
MAX_MEDIAN_GRADE_DIFF_M = 0.3
TILE = "f1/terrain/usgs-1m/USGS_one_meter_x58y451_NY_CMPG_2013.tif"
TILE_NODATA = -3.4028234663852886e38
OED_SPEC = "assets/oed-spec"


def _cache() -> Path:
    """The cache root: ``FLOOD_CACHE`` when set (a worktree has no cache of its own)."""
    value = os.environ.get("FLOOD_CACHE")
    return Path(value) if value else paths.CACHE


def study_area(cache: Path):
    """The Brooklyn land inside the square, from the city's 2020 neighbourhood outlines."""
    import geopandas as gpd

    areas = gpd.read_file(cache / "nyc-nta-2020" / "nta2020.geojson").to_crs(domain.CRS)
    land = shapely.union_all(areas.loc[areas["boroname"] == domain.BOROUGH, "geometry"].to_numpy())
    return shapely.intersection(land, shapely.box(*domain.SQUARE))


def _provisional_terrain(cache: Path):
    """Nearest-pixel sampler of the USGS 1 m tile (EPSG:26918, NAVD88 metres), PROVISIONAL.

    The tile's NAD83 / UTM 18N coordinates are taken as equal to the project's WGS84 / UTM 18N;
    the two differ by about a metre or two horizontally, which this sampler ignores.
    """
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(cache / TILE) as source:
        window = from_bounds(*domain.SQUARE, transform=source.transform).round_offsets()
        window = window.round_lengths()
        grid = source.read(1, window=window)
        transform = source.window_transform(window)

    def ground_elevation(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        col = np.floor((x - transform.c) / transform.a).astype(int)
        row = np.floor((y - transform.f) / transform.e).astype(int)
        inside = (row >= 0) & (row < grid.shape[0]) & (col >= 0) & (col < grid.shape[1])
        if not inside.all():
            raise ValueError(f"{int((~inside).sum())} points are outside the terrain")
        values = grid[row, col].astype(float)
        values[(values <= TILE_NODATA / 10) | ~np.isfinite(values)] = np.nan
        return values

    return ground_elevation


def _terrain(cache: Path):
    try:
        from flood_lab.terrain import ground_elevation  # type: ignore[import-not-found]
    except ImportError:
        return _provisional_terrain(cache), True
    return ground_elevation, False


# description -----------------------------------------------------------------------------------


def _quantiles(values: list[float] | np.ndarray) -> dict[str, float] | None:
    values = np.asarray([v for v in values if v is not None], dtype=float)
    if not len(values):
        return None
    q = np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {
        "n": int(len(values)),
        "p05": round(float(q[0]), 3),
        "p25": round(float(q[1]), 3),
        "median": round(float(q[2]), 3),
        "p75": round(float(q[3]), 3),
        "p95": round(float(q[4]), 3),
        "mean": round(float(values.mean()), 3),
    }


def _decade(year: int | None) -> str:
    return "unknown" if year is None else f"{year // 10 * 10}s"


def describe_unmatched(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The buildings without a row in the elevation table, by year, feature code, status, area."""
    missing = [r for r in rows if "elevation" not in r["lab_match"]]
    matched = [r for r in rows if "elevation" in r["lab_match"]]

    def share(selection: list[dict[str, Any]], key) -> dict[str, int]:
        return dict(sorted(Counter(key(r) for r in selection).items()))

    def year(r: dict[str, Any]) -> str:
        y = r["YearBuilt"]
        if y is None:
            return "unknown"
        if y >= 2022:
            return "2022 or later"
        return "2020 to 2021" if y >= 2020 else _decade(y)

    return {
        "count": len(missing),
        "by_construction_year": share(missing, year),
        "by_construction_year_matched": share(matched, year),
        "by_feature_code": share(missing, lambda r: r["detail_feature_code"] or "empty"),
        "by_feature_code_matched": share(matched, lambda r: r["detail_feature_code"] or "empty"),
        "by_last_status": share(missing, lambda r: r["detail_last_status_type"] or "empty"),
        "footprint_area_m2": _quantiles([r["detail_footprint_area_m2"] for r in missing]),
        "footprint_area_m2_matched": _quantiles([r["detail_footprint_area_m2"] for r in matched]),
    }


def voltage_class(kv: float | None) -> str:
    return "untagged" if kv is None else f"{kv:g} kV"


# figures ---------------------------------------------------------------------------------------


def _png(figure, path: Path) -> None:
    import matplotlib.pyplot as plt

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=120, metadata={"Software": None})
    plt.close(figure)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.part")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(path)


MATCH_COLOURS = {
    "footprint+elevation+inventory": "#15803d",
    "footprint+elevation": "#65a30d",
    "footprint+inventory": "#d97706",
    "footprint": "#b91c1c",
}


def figure_map(land, footprints: dict[str, Any], rows, stations, path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    figure, axis = plt.subplots(figsize=(9, 9.6))
    for part in getattr(land, "geoms", [land]):
        xs, ys = part.exterior.xy
        axis.fill(xs, ys, color="#f3f4f6", zorder=0)
        axis.plot(xs, ys, color="#6b7280", linewidth=0.6, zorder=1)
    for match, colour in MATCH_COLOURS.items():
        shapes = [footprints[r["lab_bin"]] for r in rows if r["lab_match"] == match]
        polygons = [
            np.asarray(p.exterior.coords)
            for shape in shapes
            for p in getattr(shape, "geoms", [shape])
        ]
        axis.add_collection(PolyCollection(polygons, facecolor=colour, edgecolor="none", zorder=2))
    for station in stations:
        axis.scatter(
            station["lab_x_m"],
            station["lab_y_m"],
            marker="^",
            s=90,
            facecolor="#fde047",
            edgecolor="black",
            linewidth=1,
            zorder=5,
        )
        axis.annotate(
            station["LocNumber"],
            (station["lab_x_m"], station["lab_y_m"]),
            fontsize=6,
            xytext=(4, 4),
            textcoords="offset points",
            zorder=6,
        )
    west, south, east, north = domain.SQUARE
    axis.plot(
        [west, east, east, west, west],
        [south, south, north, north, south],
        color="black",
        linewidth=0.8,
        linestyle="--",
    )
    axis.set_xlim(west - 50, east + 50)
    axis.set_ylim(south - 50, north + 50)
    axis.set_aspect("equal")
    axis.ticklabel_format(useOffset=False, style="plain")
    axis.set_xlabel("UTM 18N easting, m")
    axis.set_ylabel("UTM 18N northing, m")
    counts = Counter(r["lab_match"] for r in rows)
    handles = [Patch(color=c, label=f"{m} ({counts.get(m, 0)})") for m, c in MATCH_COLOURS.items()]
    handles.append(
        Line2D(
            [],
            [],
            marker="^",
            linestyle="",
            markerfacecolor="#fde047",
            markeredgecolor="black",
            label=f"substation asset ({len(stations)})",
        )
    )
    axis.legend(
        handles=handles, loc="lower left", fontsize=7, title="Buildings by join", title_fontsize=7
    )
    axis.set_title("Assets of the study area (Brooklyn land in the square, dashed)", fontsize=9)
    figure.tight_layout()
    _png(figure, path)


def figure_first_floor(rows, path: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7, 4))
    bins = np.arange(-1.0, 4.01, 0.1)
    for flag, colour in (("Y", "#1d4ed8"), ("N", "#f97316")):
        values = [
            r["lab_first_floor_height_m"]
            for r in rows
            if r["lab_subgrade"] == flag and r["lab_first_floor_height_m"] is not None
        ]
        clipped = np.clip(values, bins[0], bins[-1])
        axis.hist(
            clipped,
            bins=bins,
            alpha=0.6,
            color=colour,
            label=f"subgrade {flag} (n = {len(values)})",
        )
    axis.set_xlabel("first floor above grade, m (z_floor - z_grade; clipped to -1..4)")
    axis.set_ylabel("buildings")
    axis.legend(fontsize=8)
    figure.tight_layout()
    _png(figure, path)


def figure_counts(substations, buildings, path: Path) -> None:
    import matplotlib.pyplot as plt

    figure, (left, right) = plt.subplots(1, 2, figsize=(8, 3.6))
    types = {"substation": len(substations), "building": len(buildings)}
    left.bar(list(types), list(types.values()), color=["#ca8a04", "#4b5563"])
    left.set_yscale("log")
    left.set_ylabel("assets (log scale)")
    for i, v in enumerate(types.values()):
        left.text(i, v, str(v), ha="center", va="bottom", fontsize=8)
    classes = Counter(voltage_class(s["lab_voltage_kv"]) for s in substations)
    names = sorted(
        classes, key=lambda c: (c == "untagged", -float(c.split()[0]) if c != "untagged" else 0)
    )
    right.bar(names, [classes[n] for n in names], color="#ca8a04")
    right.set_ylabel("substation assets")
    right.yaxis.get_major_locator().set_params(integer=True)
    right.set_xlabel("highest tagged voltage")
    figure.tight_layout()
    _png(figure, path)


def figure_grade_terrain(differences: np.ndarray, path: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7, 4))
    bins = np.arange(-3.0, 3.01, 0.05)
    axis.hist(np.clip(differences, bins[0], bins[-1]), bins=bins, color="#4b5563")
    if len(differences):
        axis.axvline(
            float(np.median(differences)),
            color="#dc2626",
            linewidth=1,
            label=f"median {np.median(differences):.3f} m",
        )
        axis.legend(fontsize=8)
    axis.set_xlabel("table grade minus terrain at the footprint centroid, m (clipped to -3..3)")
    axis.set_ylabel("buildings")
    figure.tight_layout()
    _png(figure, path)


# main ------------------------------------------------------------------------------------------


def _write_detail(rows: list[dict[str, Any]], path: Path) -> None:
    columns = ["LocNumber", *sorted(k for k in rows[0] if k.startswith("detail_"))] if rows else []
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: (
                    ""
                    if row[k] is None
                    else round(row[k], 3)
                    if isinstance(row[k], float)
                    else row[k]
                )
                for k in columns
            }
        )
    write_text_atomic(path, buffer.getvalue())


def main() -> None:
    from flood_lab.assets import contact_sheet as cs

    cache = _cache()
    out_cache = cache / "assets"
    elevation, provisional = _terrain(cache)
    land = study_area(cache)
    shapely.prepare(land)

    # substations
    overpass = cache / "osm-substations" / "overpass.json"
    every = sub.outlines_from_overpass(json.loads(overpass.read_text()))
    outlines = sub.in_square(every)
    review = sub.load_review()
    stations, traction, groups = sub.build(outlines, elevation=elevation, land=land, review=review)
    write_text_atomic(sub.REVIEW, sub.review_text(stations, review))
    write_text_atomic(
        GEOJSON,
        json.dumps(sub.geojson(stations, groups), indent=1, sort_keys=True, ensure_ascii=False)
        + "\n",
    )

    # images
    panels, image_inputs, review_images = [], [], []
    for station, group in zip(stations, groups, strict=True):
        view = cs.view_of([o.geometry for o in group])
        key = station["LocNumber"]
        naip = cs.fetch("naip2019", view, out_cache / "imagery" / f"{key}_naip2019.png")
        nys = cs.fetch("nys2018", view, out_cache / "review" / f"{key}_nys2018.png")
        review_images.append(nys.relative_to(cache).as_posix())
        for path, service in ((naip, "naip2019"), (nys, "nys2018")):
            image_inputs.append(Input.of(path, root=cache, url=cs.request_url(service, view)))
        kv = station["lab_voltage_kv"]
        panels.append(
            {
                "image": naip,
                "view": view,
                "outlines": [o.geometry for o in group],
                "label": (
                    f"{key} {station['lab_name'] or '(no name)'}\n"
                    f"{voltage_class(kv)}; kind {station['lab_substation_kind'] or '-'}; "
                    f"location {station['lab_location_tag'] or '-'}; "
                    f"{station['lab_outlines']} outline(s)"
                ),
            }
        )
    cs.sheet(
        panels,
        OUT / "substation_contact_sheet.png",
        title="Substation assets on USGS NAIP 2019 (0.6 m); outlines from OpenStreetMap "
        "(© OpenStreetMap contributors, ODbL); bar 50 m",
    )

    # buildings
    footprints = bld.read_footprints(cache / "nyc-building-footprints" / "footprints-box.geojson")
    bes = bld.read_bes(cache / "nyc-building-elevation-subgrade" / "bes-box.csv")
    nsi = bld.read_nsi(cache / "usace-national-structure-inventory" / "nsi_f1_box.json")
    houses, stats = bld.build(footprints, bes, nsi, land=land, elevation=elevation)
    _write_detail(houses, out_cache / "buildings_detail.csv")

    # table
    rows = oed.table(stations, houses)
    faults = schema.validate(rows)
    written = False
    try:
        oed.write(rows)
        written = True
    except oed.TableFault:
        pass

    # numbers
    everything = stations + houses
    no_ground = [r["LocNumber"] for r in everything if r["lab_ground_elev_m"] is None]
    no_terrain = [r["LocNumber"] for r in everything if r["lab_terrain_elev_m"] is None]
    pairs = [
        (r["detail_grade_m"], r["lab_terrain_elev_m"])
        for r in houses
        if r["detail_grade_m"] is not None and r["lab_terrain_elev_m"] is not None
    ]
    differences = np.array([g - t for g, t in pairs])
    median_difference = float(np.median(differences)) if len(differences) else None
    estimated = [
        r["detail_grade_m"] - r["lab_terrain_elev_m"]
        for r in houses
        if r["detail_grade_estimated"]
        and r["detail_grade_m"] is not None
        and r["lab_terrain_elev_m"] is not None
    ]
    unreviewed = [s["LocNumber"] for s in stations if s["lab_reviewed"] == sub.NOT_REVIEWED]
    rate = stats["rate_buildings_with_elevation_row"]
    kept = [s for s in stations if not s["lab_reviewed"].startswith("removed")]

    def total(selection, level):
        values = [s[f"lab_value_{level}_usd"] for s in selection if s[f"lab_value_{level}_usd"]]
        return int(sum(values))

    numbers: dict[str, Any] = {
        "substation_outlines_in_square": len(outlines),
        "substation_outlines_traction_left_out": len(traction),
        "substation_outlines_in_assets": sum(len(g) for g in groups),
        "substation_outlines_unclosed_ways": sum(
            1 for g in groups for o in g if o.geometry.geom_type == "LineString"
        ),
        "substation_assets": len(stations),
        "substation_assets_on_study_area": sum(1 for s in stations if s["lab_in_study_area"]),
        "substation_assets_by_voltage": dict(
            sorted(Counter(voltage_class(s["lab_voltage_kv"]) for s in stations).items())
        ),
        "substation_assets_by_value_class": dict(
            sorted(Counter(s["lab_value_class"] or "none" for s in stations).items())
        ),
        "substation_assets_by_indoor": dict(
            sorted(Counter(s["lab_indoor"] for s in stations).items())
        ),
        "substation_assets_by_review": dict(
            sorted(Counter(s["lab_reviewed"] for s in stations).items())
        ),
        "substation_value_low_total_usd": total(stations, "low"),
        "substation_value_mid_total_usd": total(stations, "mid"),
        "substation_value_high_total_usd": total(stations, "high"),
        "substation_value_mid_total_kept_usd": total(kept, "mid"),
        "assets_by_type": {"substation": len(stations), "building": len(houses)},
        "building_value_total_usd": int(round(sum(r["BuildingTIV"] or 0 for r in houses))),
        "buildings_with_value": sum(1 for r in houses if r["BuildingTIV"]),
        "buildings_by_match": dict(sorted(Counter(r["lab_match"] for r in houses).items())),
        "buildings_ground_from_table": sum(
            1 for r in houses if r["lab_ground_elev_source"].startswith("z_grade")
        ),
        "buildings_ground_from_table_estimated": sum(
            1 for r in houses if r["lab_ground_elev_source"] == "z_grade (estimated)"
        ),
        "buildings_ground_from_terrain_zero_grade": sum(
            1 for r in houses if "z_grade 0" in r["lab_ground_elev_source"]
        ),
        "buildings_ground_from_terrain_no_row": sum(
            1 for r in houses if "no elevation row" in r["lab_ground_elev_source"]
        ),
        "buildings_with_first_floor_height": sum(
            1 for r in houses if r["lab_first_floor_height_m"] is not None
        ),
        "buildings_by_subgrade": dict(
            sorted(Counter(r["lab_subgrade"] or "no row" for r in houses).items())
        ),
        "buildings_with_storeys": sum(1 for r in houses if r["NumberOfStoreys"] is not None),
        "buildings_with_year_built": sum(1 for r in houses if r["YearBuilt"] is not None),
        "first_floor_height_m_subgrade_Y": _quantiles(
            [r["lab_first_floor_height_m"] for r in houses if r["lab_subgrade"] == "Y"]
        ),
        "first_floor_height_m_subgrade_N": _quantiles(
            [r["lab_first_floor_height_m"] for r in houses if r["lab_subgrade"] == "N"]
        ),
        "grade_minus_terrain_m": _quantiles(differences),
        "grade_minus_terrain_m_estimated_grades": _quantiles(estimated),
        "assets_without_ground_elevation": len(no_ground),
        "assets_without_terrain_elevation": len(no_terrain),
        "table_rows": len(rows),
        "table_faults": len(faults),
        "terrain_provisional": provisional,
        **stats,
    }

    figures = [
        f"{FIG}/substation_contact_sheet.png",
        f"{FIG}/assets_map.png",
        f"{FIG}/first_floor_height.png",
        f"{FIG}/asset_counts.png",
        f"{FIG}/grade_minus_terrain.png",
    ]
    wanted = {h["lab_bin"] for h in houses}
    shapes = {}
    for key, shape in zip(footprints["bin"], footprints["geometry"], strict=True):
        if key in wanted:  # the footprint kept per BIN is the largest one
            if key not in shapes or shape.area > shapes[key].area:
                shapes[key] = shape
    figure_map(land, shapes, houses, stations, OUT / "assets_map.png")
    figure_first_floor(houses, OUT / "first_floor_height.png")
    figure_counts(stations, houses, OUT / "asset_counts.png")
    figure_grade_terrain(differences, OUT / "grade_minus_terrain.png")

    terrain_words = (
        "PROVISIONAL terrain: the USGS 1 m tile sampled directly at the nearest pixel, its NAD83 "
        "UTM 18N coordinates taken as the project's WGS84 UTM 18N (flood_lab.terrain did not "
        "exist yet)"
        if provisional
        else "terrain from flood_lab.terrain.ground_elevation"
    )
    spec = cache / OED_SPEC
    inputs = [
        Input.of(overpass, root=cache, url="https://overpass-api.de/api/interpreter"),
        Input.of(cache / "nyc-building-footprints" / "footprints-box.geojson", root=cache),
        Input.of(cache / "nyc-building-elevation-subgrade" / "bes-box.csv", root=cache),
        Input.of(cache / "usace-national-structure-inventory" / "nsi_f1_box.json", root=cache),
        Input.of(cache / "nyc-nta-2020" / "nta2020.geojson", root=cache),
        Input.of(sub.VALUES, root=paths.ROOT),
        Input.of(sub.REVIEW, root=paths.ROOT),
        *([Input.of(cache / TILE, root=cache)] if provisional else []),
        *image_inputs,
        *[Input.of(p, root=cache) for p in sorted(spec.glob("*")) if p.is_file()],
    ]
    parameters = [
        Parameter("same_name_gap_m", sub.SAME_NAME_GAP_M, "P"),
        Parameter("unnamed_gap_m", sub.UNNAMED_GAP_M, "P", "FD3 (150 m)"),
        Parameter("transmission_from_kv", sub.TRANSMISSION_KV, "P", "values.toml rule"),
        Parameter("inventory_near_m", bld.NEAR_M, "P"),
        Parameter("foot_m", bld.FOOT_M, "I", "international foot; US survey foot differs by 2 ppm"),
        Parameter(
            "estimated_grade_phrase",
            bld.ESTIMATED,
            "I",
            "notes1 phrases of the table's guidance (facts nyc-building-elevation-subgrade)",
        ),
        Parameter("image_margin_m", cs.MARGIN_M, "P"),
        Parameter("image_pixels", cs.PIXELS, "P"),
        Parameter("scale_bar_m", cs.SCALE_BAR_M, "P"),
        Parameter("min_elevation_match", MIN_ELEVATION_MATCH, "P", "plan F1, proposed"),
        Parameter("max_median_grade_minus_terrain_m", MAX_MEDIAN_GRADE_DIFF_M, "P", "proposed"),
        Parameter("oed_spec_version", "5.0.0", "S", "OasisLMF/ODS_OpenExposureData tag 5.0.0"),
        Parameter(
            "LocPerilsCovered",
            oed.PERILS,
            "S",
            "OED 5.0.0 PerilValues.csv: OSF Flash / Surface / Pluvial Flood",
        ),
        Parameter(
            "FirstFloorHeightUnit", oed.METRES, "S", "OED 5.0.0 OtherValues.csv: Units 2 Meters"
        ),
        Parameter(
            "OccupancyCode_substation",
            oed.OCCUPANCY_SUBSTATION,
            "S",
            "OED 5.0.0 OccupancyValues.csv: 1300 Utilities, Electrical",
        ),
        Parameter("PortNumber_AccNumber", "1", "P"),
    ]
    checks = [
        Check(
            "table rules",
            "schema.validate reports no fault; the table is written only then",
            not faults and written,
            len(faults),
            0,
            note="; ".join(faults[:5]),
        ),
        Check(
            "every asset has a ground and a terrain elevation",
            "lab_ground_elev_m and lab_terrain_elev_m are filled for every asset",
            not no_ground and not no_terrain,
            len(no_ground) + len(no_terrain),
            0,
            note=terrain_words,
        ),
        Check(
            "footprints matched to the elevation table",
            "share of the study area's buildings (footprints with a real BIN) whose BIN is in "
            "the Building Elevation and Subgrade table",
            rate is not None and rate >= MIN_ELEVATION_MATCH,
            rate,
            MIN_ELEVATION_MATCH,
            proposed=True,
            note="the unmatched are described in the table 'unmatched_footprints'",
        ),
        Check(
            "every substation looked at",
            "every asset in substation_review.toml is 'kept' or 'removed'",
            not unreviewed,
            len(unreviewed),
            0,
            note=f"not reviewed: {', '.join(unreviewed)}" if unreviewed else "",
        ),
        Check(
            "table grade agrees with terrain",
            "absolute median of z_grade (m) minus terrain at the footprint centroid, where both "
            "exist",
            median_difference is not None and abs(median_difference) <= MAX_MEDIAN_GRADE_DIFF_M,
            None if median_difference is None else round(median_difference, 3),
            MAX_MEDIAN_GRADE_DIFF_M,
            proposed=True,
            note=terrain_words,
        ),
    ]
    tables = {
        "substation_assets": [
            {
                k: s[k]
                for k in (
                    "LocNumber",
                    "lab_name",
                    "lab_osm_ids",
                    "lab_outlines",
                    "lab_voltage_kv",
                    "lab_substation_kind",
                    "lab_operator",
                    "lab_location_tag",
                    "lab_building_tag",
                    "lab_indoor",
                    "lab_in_study_area",
                    "lab_value_class",
                    "lab_value_low_usd",
                    "lab_value_mid_usd",
                    "lab_value_high_usd",
                    "lab_value_tag",
                    "lab_reviewed",
                    "lab_ground_elev_m",
                )
            }
            for s in stations
        ],
        "traction_left_out": [
            {"osm_id": o.osm_id, "name": o.name, "operator": o.tags.get("operator", "")}
            for o in traction
        ],
        "unmatched_footprints": describe_unmatched(houses),
        "review_images_in_cache": review_images,
    }
    notes = [
        "Contact sheet: USGS NAIP 2019 (0.6 m, leaf-on, one date) with OpenStreetMap outlines, "
        "for looking, not measuring; it cannot show change since 2019 or what is inside a "
        "building. Map: buildings coloured by which joins succeeded; it shows the joins, not "
        "flood exposure. First-floor histogram: the city's table only, values read from street "
        "imagery and partly estimated; 0 (not measured) left out. Counts bar: substations are "
        "mapped outlines grouped by a placeholder rule. Grade-minus-terrain histogram: "
        + ("provisional terrain, nearest pixel, datum shift ignored. " if provisional else "")
        + "Values clipped at the axis ends.",
        "Substation values are placeholders [P] bracketed by two published figures for other "
        "substations (values.toml); the mid is their geometric mean. Building values are the "
        "inventory's depreciated replacement value [S], August 2025 prices, not 2026 dollars.",
        "Customers served (FD7): no public figure per substation exists, so lab_customers_served "
        "and lab_customers_tag are empty. A placeholder would need the population of the study "
        "area by census block (2020), a service-area rule assigning each block to one substation "
        "(for example the nearest area substation, which ignores the real feeder network), and a "
        "persons-per-customer ratio from a stated source; none of it is computed here.",
        terrain_words + ".",
        "The table has no column for: footprint area, the estimated-grade note (carried in "
        "lab_ground_elev_source as 'z_grade (estimated)'), the number of inventory points per "
        "footprint, the operator, location and building tags of a substation; they are in this "
        "record and in the cache file assets/buildings_detail.csv.",
    ]
    Record(
        id="f1-assets",
        stage="F1",
        title="Assets of the study area: substations and buildings in one table",
        inputs=inputs,
        parameters=parameters,
        numbers=numbers,
        tables=tables,
        checks=checks,
        figures=figures,
        notes=notes,
    ).write(paths.RECORDS)
    print(json.dumps({k: numbers[k] for k in sorted(numbers)}, indent=1, default=str))
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.value}")


if __name__ == "__main__":
    main()
