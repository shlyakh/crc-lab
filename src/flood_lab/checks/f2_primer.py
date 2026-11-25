"""The script of the primer ``docs/primers/point-observations.md`` (FS5).

    uv run --with matplotlib python -m flood_lab.checks.f2_primer

Offline, from the cache. Makes the primer's figures (``docs/flood/figures/f2-primer/``)
and the record ``f2-primer`` that holds every number the primer quotes. It uses the loaders of
``flood_lab.sources``: FloodNet events go into CRC as observations and are read back; Groundsource
stays a table of dated places.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyproj  # noqa: E402
import shapely  # noqa: E402

from flood_lab import cache, domain, paths  # noqa: E402
from flood_lab.records import Check, Input, Parameter, Record  # noqa: E402
from flood_lab.sources import floodnet, groundsource  # noqa: E402

OUT = paths.FIGURES / "f2-primer"
FIG = "docs/flood/figures/f2-primer"
DAYS = {"2021-09-01": "Ida", "2023-09-29": "29 September 2023"}
#: a dry day to set beside the two storms: no named storm, chosen before looking [P]
QUIET_DAY = "2022-06-15"
BLUE, GREY, RED = "#1d4ed8", "#6b7280", "#b91c1c"
#: a place is "about the size of the study square or smaller" up to this area, km2 [P]
SMALL_PLACE_KM2 = 16.0


def _png(figure: Any, name: str) -> str:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=130, metadata={"Software": None})
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".png.part")
    part.write_bytes(buffer.getvalue())
    part.replace(path)
    plt.close(figure)
    return f"{FIG}/{name}"


def _square_lonlat() -> shapely.Polygon:
    west, south, east, north = domain.SQUARE
    to_lonlat = pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True)
    xs, ys = to_lonlat.transform([west, east, east, west], [south, south, north, north])
    return shapely.Polygon(zip(xs, ys, strict=True))


def _network_figure(events: pd.DataFrame, sensors_csv: Path) -> tuple[str, dict[str, Any]]:
    sensors = pd.read_csv(sensors_csv)
    installed = pd.to_datetime(sensors["date_installed"]).sort_values()
    removed = pd.to_datetime(sensors["date_removed"].dropna()).sort_values()
    months = pd.date_range("2020-10-01", events["local_day"].max(), freq="MS")
    serving = [int((installed <= m).sum() - (removed < m).sum()) for m in months]
    per_month = pd.to_datetime(events["local_day"]).dt.to_period("M").value_counts().sort_index()
    figure, (top, bottom) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    top.step(months, serving, where="post", color=BLUE)
    top.set_ylabel("Sensors in service")
    bottom.bar(per_month.index.to_timestamp(), per_month.to_numpy(), width=25, color=GREY)
    bottom.set_ylabel("Events per month")
    for day, name in DAYS.items():
        for axis in (top, bottom):
            axis.axvline(pd.Timestamp(day), color=RED, linewidth=0.8)
        top.text(pd.Timestamp(day), max(serving) * 0.9, f" {name}", color=RED, fontsize=8)
    top.set_title("FloodNet: the network grew, and the count of events grew with it", fontsize=10)
    figure.text(
        0.01,
        0.01,
        "Sensors in service at the start of each month, and flood events recorded per month, all "
        "boroughs. Limit: more events later means more sensors, not more flooding.",
        fontsize=7,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    numbers = {
        "sensors_in_table": len(sensors),
        "sensors_in_service_at_ida": int(
            floodnet.storm_sensors(events, sensors_csv, "2021-09-01").shape[0]
        ),
        "sensors_in_service_on_2023_09_29": int(
            floodnet.storm_sensors(events, sensors_csv, "2023-09-29").shape[0]
        ),
        "sensors_in_service_latest_month": serving[-1],
        "events": len(events),
        "median_peak_depth_m": float(events["peak_depth_m"].median()),
        "largest_peak_depth_m": float(events["peak_depth_m"].max()),
        "median_duration_min": float(events["duration_min"].median()),
    }
    return _png(figure, "floodnet_network.png"), numbers


def _place_figure(
    places: pd.DataFrame, square: shapely.Polygon, study_km2: float
) -> tuple[str, dict[str, Any]]:
    nyc = places[places["box"] == "nyc"]
    day = groundsource.covering(places, "nyc", "2021-09-01")
    shapes = shapely.from_wkb(day["geometry_wkb"].to_numpy())
    touching = day[shapely.intersects(shapes, square)]
    west, south, east, north = groundsource.BOXES["nyc"]
    figure, (left, right) = plt.subplots(1, 2, figsize=(12.5, 5.8))
    ordered = touching.sort_values("area_km2", ascending=False)
    for wkb, lon, lat in zip(
        ordered["geometry_wkb"], ordered["centroid_lon"], ordered["centroid_lat"], strict=True
    ):
        shape = shapely.from_wkb(wkb)
        for part in getattr(shape, "geoms", [shape]):
            left.plot(*part.exterior.xy, color=GREY, linewidth=0.7)
        left.plot(lon, lat, marker="+", color=BLUE, markersize=6)
    left.fill(*square.exterior.xy, facecolor="none", edgecolor=RED, linewidth=1.8, zorder=5)
    left.set_xlim(west + 0.1, east - 0.1)
    left.set_ylim(south + 0.08, north - 0.08)
    left.set_aspect(1 / np.cos(np.radians(40.7)))
    left.set_title(
        f"Places whose polygon reaches the study square (red), 2021-09-01: {len(touching)}",
        fontsize=9,
    )
    left.set_xlabel("Longitude")
    left.set_ylabel("Latitude")
    bins = np.logspace(-5, 4, 46)
    right.hist(nyc["area_km2"], bins=bins, color=GREY)
    right.set_xscale("log")
    right.axvline(study_km2, color=RED, linewidth=1.0)
    right.text(
        study_km2,
        right.get_ylim()[1] * 0.92,
        f" study area, {study_km2:.1f} km²",
        color=RED,
        fontsize=8,
    )
    right.set_xlabel("area_km2 of the named place")
    right.set_ylabel("Rows, New York box, all dates")
    right.set_title("How big is the place a row names?", fontsize=9)
    figure.text(
        0.01,
        0.01,
        "Left: outlines of the named places, with each polygon's centroid as a cross; the largest "
        "run off the frame. Right: the "
        "area of the named place for every row in the New York box.\nLimit: a polygon is the place "
        "a report named (a street, a neighbourhood, a borough, a county), never the flooded area.",
        fontsize=7,
    )
    figure.tight_layout(rect=(0, 0.06, 1, 1))
    centroid_in = shapely.contains_xy(
        square, touching["centroid_lon"].to_numpy(), touching["centroid_lat"].to_numpy()
    )
    numbers = {
        "rows_nyc_box": len(nyc),
        "median_area_km2_nyc": float(nyc["area_km2"].median()),
        "share_of_nyc_rows_larger_than_the_study_area": float((nyc["area_km2"] > study_km2).mean()),
        "largest_area_km2_nyc": float(nyc["area_km2"].max()),
        "rows_reaching_the_square_on_2021_09_01": len(touching),
        "of_them_with_centroid_in_the_square": int(centroid_in.sum()),
        "centroid_outside_and_place_smaller_than_the_study_area": int(
            (~centroid_in & (touching["area_km2"].to_numpy() <= study_km2)).sum()
        ),
        "centroid_outside_and_place_larger_than_the_study_area": int(
            (~centroid_in & (touching["area_km2"].to_numpy() > study_km2)).sum()
        ),
        "areas_km2_of_the_larger_places_with_centroid_outside": sorted(
            round(float(a), 1)
            for a in touching["area_km2"].to_numpy()[
                ~centroid_in & (touching["area_km2"].to_numpy() > study_km2)
            ]
        ),
    }
    return _png(figure, "groundsource_places.png"), numbers


def _year_figure(places: pd.DataFrame) -> tuple[str, list[dict[str, Any]]]:
    years = places.assign(year=places["start_date"].str.slice(0, 4).astype(int))
    counts = years.groupby(["year", "box"]).size().unstack(fill_value=0)
    figure, axis = plt.subplots(figsize=(10, 4.2))
    width = 0.4
    axis.bar(
        counts.index - width / 2, counts.get("nyc", 0), width, color=BLUE, label="New York box"
    )
    axis.bar(
        counts.index + width / 2,
        counts.get("alameda", 0),
        width,
        color=GREY,
        label="Alameda County box",
    )
    axis.set_ylabel("Rows by year of the start date")
    axis.legend(fontsize=8)
    axis.set_title("Groundsource rows per year: who was reporting, and when", fontsize=10)
    figure.text(
        0.01,
        0.01,
        "Limit: the count follows how much news was published and could be read by the "
        "publisher's pipeline, as well as how often it flooded. The last year is part of a year.",
        fontsize=7,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 1))
    table = [
        {"year": int(year), **{box: int(row[box]) for box in counts.columns}}
        for year, row in counts.iterrows()
    ]
    return _png(figure, "groundsource_rows_per_year.png"), table


def _question_table(
    events: pd.DataFrame, sensors_csv: Path, places: pd.DataFrame, square: shapely.Polygon
) -> list[dict[str, Any]]:
    """Did something happen in the study square on this day? What each source can say."""
    west, south, east, north = domain.SQUARE
    to_grid = pyproj.Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True)
    rows = []
    for day in (*DAYS, QUIET_DAY):
        serving = floodnet.storm_sensors(events, sensors_csv, day)
        x, y = to_grid.transform(serving["longitude"].to_numpy(), serving["latitude"].to_numpy())
        here = serving[(x >= west) & (x <= east) & (y >= south) & (y <= north)]
        covering = groundsource.covering(places, "nyc", day)
        reach = covering[
            shapely.intersects(shapely.from_wkb(covering["geometry_wkb"].to_numpy()), square)
        ]
        small = reach[reach["area_km2"] <= SMALL_PLACE_KM2]
        peak = here["peak_depth_m"].max()
        rows.append(
            {
                "local day": day,
                "FloodNet sensors in service in the square": len(here),
                "of them with an event": int(here["recorded"].sum()),
                "largest peak depth there, m": None if pd.isna(peak) else round(float(peak), 3),
                "Groundsource rows reaching the square": len(reach),
                f"of them naming a place of {SMALL_PLACE_KM2:g} km² or less": len(small),
            }
        )
    return rows


def main() -> None:
    root = cache.root()
    events_csv, sensors_csv = root / floodnet.EVENTS, root / floodnet.SENSORS
    places_path = root / "f2" / "groundsource_places.parquet"
    if not places_path.exists():
        raise SystemExit("run flood_lab.checks.f2_sources first: it writes the dated places")
    events = floodnet.events(events_csv, sensors_csv)
    places = pd.read_parquet(places_path)
    square = _square_lonlat()
    terrain = json.loads((paths.RECORDS / "f1-terrain.json").read_text(encoding="utf-8"))
    study_km2 = float(terrain["numbers"]["study_area_km2"])

    record = Record(
        id="f2-primer",
        stage="F2",
        title="Primer on point observations: its figures and numbers",
        inputs=[
            Input.of(events_csv, root=root),
            Input.of(sensors_csv, root=root),
            Input.of(places_path, root=root),
        ],
        parameters=[
            Parameter("study area, km2", study_km2, "S", "record f1-terrain, study_area_km2"),
            Parameter("quiet day for comparison", QUIET_DAY, "P"),
            Parameter("small place, km2", SMALL_PLACE_KM2, "P"),
        ],
    )
    crc_rows = floodnet.crc_table(events)
    got = floodnet.to_crc(crc_rows)
    back = floodnet.read_back_differences(crc_rows, got)
    record.checks.append(
        Check(
            "FloodNet in CRC",
            "the events read back from CRC equal what was put in",
            sum(v for k, v in back.items() if k not in ("rows_in", "rows_back")) == 0
            and back["rows_in"] == back["rows_back"],
            value=back,
        )
    )
    record.numbers["crc_observation_columns"] = list(got.column_names)
    figure, numbers = _network_figure(events, sensors_csv)
    record.figures.append(figure)
    record.numbers["floodnet"] = numbers
    figure, numbers = _place_figure(places, square, study_km2)
    record.figures.append(figure)
    record.numbers["groundsource"] = numbers
    figure, by_year = _year_figure(places)
    record.figures.append(figure)
    record.tables["Groundsource rows per year"] = by_year
    record.tables["did something happen in the study square on this day"] = _question_table(
        events, sensors_csv, places, square
    )
    record.notes.append(
        "Counts of what was observed and reported. None is a count of floods, and an empty cell "
        "of the table is not evidence that nothing happened."
    )
    path = record.write(paths.RECORDS)
    print(f"{path.name}: {record.passed}")


if __name__ == "__main__":
    main()
