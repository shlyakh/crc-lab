"""F0: maps of the candidate study areas as images, for the report and the gallery (D1, FD1).

    uv run --with matplotlib python -m flood_lab.checks.f0_area_maps

Draws what ``checks/f0_area.py`` counted: the five best windows from its record, over the city's
neighbourhood outlines and the 2.13 in/hr flood map, with the surveyed marks, the sensors and the
substations. One overview and one map per area, written to ``docs/flood/figures/f0/`` as PNG, and
the record ``f0-area-maps``. Offline, from the cache. matplotlib is not a dependency of the
project, so it is supplied on the command line (requirement FG4).

Nothing here is a result of the flood model: the flooded areas shown are the city's published map.
"""

from __future__ import annotations

import io
import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import shapely  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from flood_lab import area_scoring as scoring  # noqa: E402
from flood_lab import paths  # noqa: E402
from flood_lab.checks import f0_area  # noqa: E402
from flood_lab.records import Check, Input, Parameter, Record  # noqa: E402

OUT = paths.FIGURES / "f0"
NUISANCE, DEEP = "#93c5fd", "#1d4ed8"
AREA_COLOURS = ["#b91c1c", "#c2410c", "#15803d", "#7e22ce", "#0f766e"]
MARGIN_M = 600.0


def _png(figure, path) -> None:
    """Write a figure atomically, without the timestamp matplotlib would put in the file."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=130, metadata={"Software": None})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.part")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(path)
    plt.close(figure)


def _points(frame: pd.DataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        frame, geometry=gpd.points_from_xy(frame["x"], frame["y"]), crs=scoring.CRS
    )


STYLE = {
    "marks": ("o", "#111827", "#fde047", 26, "Surveyed high-water mark, Ida"),
    "sep29": ("s", "#14532d", "#4ade80", 34, "Sensor with an event on 2023-09-29"),
    "ida": ("D", "#7c2d12", "#fb923c", 48, "Sensor with an Ida event"),
    "sites": ("^", "#111827", "#ffffff", 44, "Substation site, not rail"),
    "exposed": ("^", "#111827", "#dc2626", 60, "Substation site within 100 m of mapped flooding"),
}


def _draw_points(axis, layers: dict[str, gpd.GeoDataFrame], scale: float) -> None:
    for order, (name, (marker, edge, face, size, _)) in enumerate(STYLE.items()):
        frame = layers[name]
        if len(frame):
            axis.scatter(
                frame.geometry.x,
                frame.geometry.y,
                marker=marker,
                s=size * scale,
                facecolor=face,
                edgecolor=edge,
                linewidth=0.8,
                zorder=5 + order,
            )


def _legend(figure, layers: dict[str, gpd.GeoDataFrame] | None = None) -> None:
    handles = [
        Patch(facecolor=NUISANCE, label="City map, 2.13 in/hr: 4 in to 1 ft"),
        Patch(facecolor=DEEP, label="City map, 2.13 in/hr: 1 ft and more"),
    ]
    for name, (marker, edge, face, _, label) in STYLE.items():
        count = f" ({len(layers[name])})" if layers is not None else ""
        handles.append(
            Line2D(
                [],
                [],
                marker=marker,
                linestyle="",
                markerfacecolor=face,
                markeredgecolor=edge,
                markersize=8,
                label=label + count,
            )
        )
    figure.legend(handles=handles, loc="lower center", ncol=3, fontsize=8.5, frameon=False)


def _frame(axis, bounds, title: str) -> None:
    west, south, east, north = bounds
    axis.set_xlim(west, east)
    axis.set_ylim(south, north)
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])
    axis.set_xlabel("")
    axis.set_ylabel("")
    axis.set_title(title, fontsize=10, loc="left")
    # one-kilometre scale bar, top right
    x1, y1 = east - 0.05 * (east - west), north - 0.045 * (north - south)
    axis.plot([x1 - 1000, x1], [y1, y1], color="black", linewidth=2.5, zorder=12)
    axis.text(x1 - 500, y1 - 0.012 * (north - south), "1 km", ha="center", va="top", fontsize=8)


def _outline(axis, area: dict, colour: str, width: float) -> None:
    w, s, e, n = area["bounds_utm18n_m"]
    style = "-" if area["passes_rule"] else "--"
    axis.plot(
        [w, e, e, w, w], [s, s, n, n, s], color=colour, linewidth=width, linestyle=style, zorder=11
    )


def main() -> None:
    record = json.loads((paths.RECORDS / "f0-area-candidates.json").read_text())
    areas = record["tables"]["best_five"]
    names_path = paths.CACHE / "nyc-nta-2020" / "nta2020.geojson"
    names = gpd.read_file(names_path).to_crs(scoring.CRS)
    layer, column = f0_area._flood_layer()
    flood = gpd.GeoDataFrame({"category": layer[column]}, geometry=layer.geometry, crs=scoring.CRS)
    land = f0_area._borough_land()
    shapely.prepare(land)
    sensors, events = f0_area._sensors()
    sensors = f0_area._on_land(sensors, land)
    stations = f0_area._on_land(f0_area._substations(), land)
    mapped = shapely.union_all(flood.loc[flood["category"].isin([1, 2]), "geometry"].to_numpy())
    sites = f0_area._sites(stations[~stations["rail"]], mapped)

    def with_event(days: tuple[str, ...]) -> pd.DataFrame:
        ids = events.loc[events["local_day"].isin(days), "sensor_id"].unique()
        return sensors[sensors["sensor_id"].isin(ids)]

    layers = {
        "marks": _points(f0_area._on_land(f0_area._marks(), land)),
        "sep29": _points(with_event(f0_area.STORMS["sep29_2023"])),
        "ida": _points(with_event(f0_area.STORMS["ida_2021"])),
        "sites": _points(sites[~sites["near_mapped_flood"]]),
        "exposed": _points(sites[sites["near_mapped_flood"]]),
    }
    figures, table = [], []

    lon0, lat0, lon1, lat1 = scoring.BOX_LONLAT
    west, south = f0_area._TO_UTM.transform(lon0, lat0)
    east, north = f0_area._TO_UTM.transform(lon1, lat1)
    figure, axis = plt.subplots(figsize=(11, 9.4))
    names.plot(ax=axis, facecolor="#f3f4f6", edgecolor="#9ca3af", linewidth=0.4)
    flood[flood["category"] == 2].plot(ax=axis, color=DEEP, linewidth=0)
    _draw_points(axis, layers, 0.5)
    for rank, area in enumerate(areas, start=1):
        colour = AREA_COLOURS[rank - 1]
        _outline(axis, area, colour, 2.6 if area["passes_rule"] else 1.8)
        w, _, _, n = area["bounds_utm18n_m"]
        box = {"facecolor": colour, "edgecolor": "none", "boxstyle": "round,pad=0.25"}
        axis.text(
            w + 120, n - 120, str(rank), color="white", fontsize=11, fontweight="bold",
            va="top", bbox=box, zorder=12,
        )  # fmt: skip
    title = (
        "Candidate study areas, 16 km² each, best five by score. "
        "Solid outline: passes the F0 rule. Dashed: does not."
    )
    _frame(axis, (west, south, east, north), title)
    _legend(figure)
    figure.tight_layout(rect=(0, 0.06, 1, 1))
    _png(figure, OUT / "area_overview.png")
    figures.append("docs/flood/figures/f0/area_overview.png")

    for rank, area in enumerate(areas, start=1):
        w, s, e, n = area["bounds_utm18n_m"]
        view = (w - MARGIN_M, s - MARGIN_M, e + MARGIN_M, n + MARGIN_M)
        box, inside = shapely.box(*view), shapely.box(w, s, e, n)
        figure, axis = plt.subplots(figsize=(9.2, 9.9))
        near = names[names.intersects(box)]
        near.plot(ax=axis, facecolor="#f9fafb", edgecolor="#9ca3af", linewidth=0.6)
        local = flood[flood.intersects(box)].copy()
        local["geometry"] = local.geometry.intersection(box)
        local[local["category"] == 1].plot(ax=axis, color=NUISANCE, linewidth=0)
        local[local["category"] == 2].plot(ax=axis, color=DEEP, linewidth=0)
        here = {k: v[v.within(inside)] for k, v in layers.items()}
        around = {k: v[v.within(box) & ~v.within(inside)] for k, v in layers.items()}
        _draw_points(axis, around, 0.45)
        _draw_points(axis, here, 1.0)
        _outline(axis, area, AREA_COLOURS[rank - 1], 2.4)
        labelled = []
        for _, row in near.iterrows():
            part = row.geometry.intersection(box)
            if part.area > 250_000 and row["ntatype"] == "0":  # residential, big enough to label
                spot = part.representative_point()
                axis.text(
                    spot.x, spot.y, row["ntaname"], fontsize=7, ha="center", va="center",
                    color="#374151", zorder=4,
                )  # fmt: skip
                if row.geometry.intersection(inside).area > 400_000:
                    labelled.append(row["ntaname"])
        verdict = "passes the F0 rule" if area["passes_rule"] else "does not pass the F0 rule"
        lon, lat = area["centre_lonlat"]
        centre = f"Centre {lat:.4f} N, {abs(lon):.4f} W"
        title = f"Area {rank}: score {area['score']:.2f}, {verdict}. {centre}"
        _frame(axis, view, title)
        _legend(figure, here)
        figure.tight_layout(rect=(0, 0.07, 1, 1))
        _png(figure, OUT / f"area_{rank}.png")
        figures.append(f"docs/flood/figures/f0/area_{rank}.png")
        drawn = {k: int(len(v)) for k, v in here.items()}
        table.append(
            {
                "area": rank,
                "neighbourhoods_with_over_0.4_km2_inside": sorted(labelled),
                "drawn_inside": {
                    "marks": drawn["marks"],
                    "sep29": drawn["sep29"],
                    "ida": drawn["ida"],
                    "sites": drawn["sites"] + drawn["exposed"],
                    "exposed": drawn["exposed"],
                },
                "counted_by_f0_area": {
                    "marks": area["high_water_marks"],
                    "sep29": area["sensors_sep29_2023"],
                    "ida": area["sensors_ida_2021"],
                    "sites": area["substation_sites"],
                    "exposed": area["substation_sites_near_mapped_flood"],
                },
            }
        )

    agree = all(
        entry["drawn_inside"][key] == int(entry["counted_by_f0_area"][key])
        for entry in table
        for key in entry["drawn_inside"]
    )
    cache = paths.CACHE
    flood_zip = cache / "nyc-stormwater-flood-maps" / "NYCFloodStormwaterFloodMaps.zip"
    Record(
        id="f0-area-maps",
        stage="F0",
        title="Maps of the five candidate study areas",
        inputs=[
            Input.of(paths.RECORDS / "f0-area-candidates.json", root=paths.ROOT),
            Input.of(names_path, root=cache),
            Input.of(flood_zip, root=cache),
        ],
        parameters=[Parameter("margin_around_each_area_m", MARGIN_M, "P")],
        tables={"areas": table},
        checks=[
            Check(
                "the points drawn inside each area equal the counts of the scoring",
                "for every area: marks, sensors of each storm, substation sites and sites near "
                "mapped flooding drawn inside the outline equal the counts in the record "
                "f0-area-candidates",
                agree,
                note="the scoring counts in bins and the map tests each point against the "
                "outline, so this compares two ways of counting",
            )
        ],
        figures=figures,
        notes=[
            "Flooded areas are the city's published 2.13 in/hr map with current sea levels, not a "
            "result of this study. Neighbourhood names and outlines are the planning department's "
            "2020 tabulation areas. Only points on Brooklyn or Queens land are drawn. Points "
            "outside an area's outline are drawn smaller. No streets are drawn.",
        ],
    ).write(paths.RECORDS)
    print(json.dumps(table))
    print("points drawn equal the scoring's counts:", agree)


if __name__ == "__main__":
    main()
