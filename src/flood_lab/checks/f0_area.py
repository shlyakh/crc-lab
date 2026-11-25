"""F0 visual test: candidate study areas scored by what was observed in them (D1, FD1).

    uv run python -m flood_lab.checks.f0_area

Reads the files fetched in F0 from ``data/cache/flood/`` and writes the record
``site/flood/tests/records/f0-area-candidates.json`` and the figures under
``docs/flood/figures/f0/``. Offline. These are quick readers for counting only; the readers the
study uses, each with a second reader, are written in F2 and F5.

Local days are America/New_York (requirements section 5): FloodNet times are GMT in the file and
are converted before a storm's day is matched.
"""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyproj
import shapely

from flood_lab import area_scoring as scoring
from flood_lab import paths
from flood_lab.records import Check, Input, Parameter, Record

STEP_M = 500.0
SIDE_M = 4000.0  # 16 km2, inside the 10 to 20 km2 of decision D1
STORMS = {"ida_2021": ("2021-09-01", "2021-09-02"), "sep29_2023": ("2023-09-29",)}
#: the pass rule of plan F0; all three are proposed starting values
RULE = {"high_water_marks": 8, "sensors_sep29_2023": 5, "substations": 3}
#: what one unit of score means for each criterion (proposed)
SCORE = {
    "high_water_marks": 8,
    "sensors_sep29_2023": 5,
    "sensors_ida_2021": 3,
    "substations_not_rail": 3,
    "deep_flood_ha": 20,
    "groundsource_small_ida": 5,
    "groundsource_small_sep29": 5,
}
#: a Groundsource row counts for a window only if its place is small enough to say where
GROUNDSOURCE_MAX_KM2 = 2.0
MAP_CELL_M = 25.0
MODERATE = "Moderate Flood (2.13 inches per hr) with Current Sea Levels"

_TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", scoring.CRS, always_xy=True)
_TO_LONLAT = pyproj.Transformer.from_crs(scoring.CRS, "EPSG:4326", always_xy=True)


def _marks() -> pd.DataFrame:
    path = paths.CACHE / "usgs-ida-high-water-marks" / "FilteredHWMs_NewYork.csv"
    frame = pd.read_csv(path, skiprows=1)  # the first line is the citation
    frame["x"], frame["y"] = _TO_UTM.transform(frame["longitude_dd"], frame["latitude_dd"])
    return frame


def _sensors() -> tuple[pd.DataFrame, pd.DataFrame]:
    sensors = pd.read_csv(paths.CACHE / "floodnet-sensors" / "kb2e-tjy3.csv")
    events = pd.read_csv(
        paths.CACHE / "floodnet-flood-events" / "aq7i-eu5q.csv",
        usecols=["sensor_id", "flood_start_time", "max_depth_inches"],
    )
    start = pd.to_datetime(events["flood_start_time"], utc=True)
    events["local_day"] = start.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    sensors["x"], sensors["y"] = _TO_UTM.transform(sensors["longitude"], sensors["latitude"])
    return sensors, events


def _substations() -> pd.DataFrame:
    document = json.loads((paths.CACHE / "osm-substations" / "overpass.json").read_text())
    rows = []
    for element in document["elements"]:
        if element["type"] == "way":
            rings = [element["geometry"]]
        else:
            rings = [m["geometry"] for m in element["members"] if m.get("geometry")]
        points = [(p["lon"], p["lat"]) for ring in rings for p in ring]
        centre = shapely.MultiPoint(points).centroid
        tags = element.get("tags", {})
        rows.append(
            {
                "osm_id": f"{element['type']}/{element['id']}",
                "lon": centre.x,
                "lat": centre.y,
                "kind": tags.get("substation", ""),
                "operator": tags.get("operator", ""),
                "voltage": tags.get("voltage", ""),
                "name": tags.get("name", ""),
            }
        )
    frame = pd.DataFrame(rows)
    frame["x"], frame["y"] = _TO_UTM.transform(frame["lon"], frame["lat"])
    frame["rail"] = frame["kind"].eq("traction")
    return frame


def _groundsource() -> pd.DataFrame:
    table = pq.read_table(paths.CACHE / "groundsource" / "extract_nyc_alameda.parquet")
    frame = table.select(["uuid", "area_km2", "start_date", "end_date", "geometry_wkb"]).to_pandas()
    frame = frame[frame["area_km2"] <= GROUNDSOURCE_MAX_KM2].copy()
    centres = shapely.centroid(shapely.from_wkb(frame["geometry_wkb"].to_numpy()))
    frame["x"], frame["y"] = _TO_UTM.transform(shapely.get_x(centres), shapely.get_y(centres))
    return frame.drop(columns="geometry_wkb")


def _deep_flood_bins(grid: scoring.Grid) -> tuple[np.ndarray, str]:
    """Hectares per bin of the deeper class (1 ft and more) on the 2.13 in/hr current map."""
    import pyogrio
    from rasterio import features
    from rasterio.transform import from_origin

    archive = paths.CACHE / "nyc-stormwater-flood-maps" / "NYCFloodStormwaterFloodMaps.zip"
    folder = paths.CACHE / "nyc-stormwater-flood-maps" / "extracted"
    with zipfile.ZipFile(archive) as bundle:
        names = [n for n in bundle.namelist() if MODERATE in n and ".gdb/" in n]
        bundle.extractall(folder, members=names)
    gdb = next(p for p in folder.rglob("*.gdb") if MODERATE in str(p))
    layer = pyogrio.read_dataframe(gdb).to_crs(scoring.CRS)
    code_column = next(c for c in layer.columns if c.lower().startswith("flooding_category"))
    deep = shapely.force_2d(layer.loc[layer[code_column] == 2, "geometry"].to_numpy())
    fine = int(grid.step / MAP_CELL_M)
    height, width = grid.ny * fine, grid.nx * fine
    transform = from_origin(grid.x0, grid.y0 + grid.ny * grid.step, MAP_CELL_M, MAP_CELL_M)
    burned = features.rasterize(
        [(geometry, 1) for geometry in deep], out_shape=(height, width), transform=transform
    )
    south_up = burned[::-1]  # row 0 at the south, as the grid counts
    bins = south_up.reshape(grid.ny, fine, grid.nx, fine).sum(axis=(1, 3)) * MAP_CELL_M**2 / 1e4
    return bins, code_column


def _figure_map(grid, chosen, table, layers) -> str:
    import plotly.graph_objects as go

    figure = go.Figure()
    styles = {
        "High-water marks (Ida)": ("#1d4ed8", 7, "circle"),
        "Sensors with an event on 2023-09-29": ("#15803d", 9, "square"),
        "Sensors with an Ida event": ("#b45309", 12, "diamond"),
        "Substations (not rail)": ("#111827", 7, "x"),
    }
    for name, frame in layers.items():
        colour, size, symbol = styles[name]
        lon, lat = _TO_LONLAT.transform(frame["x"].to_numpy(), frame["y"].to_numpy())
        figure.add_trace(
            go.Scatter(
                x=lon, y=lat, mode="markers", name=f"{name} ({len(frame)})",
                marker={"color": colour, "size": size, "symbol": symbol, "opacity": 0.8},
            )
        )  # fmt: skip
    for rank, ((row, col), entry) in enumerate(zip(chosen, table, strict=True), start=1):
        west, south, east, north = grid.window_bounds(row, col)
        xs, ys = _TO_LONLAT.transform(
            [west, east, east, west, west], [south, south, north, north, south]
        )
        figure.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines", line={"width": 3 if entry["passes_rule"] else 1.5},
                name=f"Area {rank}: score {entry['score']:.2f}"
                + ("" if entry["passes_rule"] else " (fails the rule)"),
            )
        )  # fmt: skip
    figure.update_layout(
        title="Candidate study areas in Brooklyn and Queens, 16 km² each, best five",
        xaxis_title="Longitude", yaxis_title="Latitude", template="plotly_white",
        yaxis={"scaleanchor": "x", "scaleratio": 1 / np.cos(np.radians(40.67))},
        height=760, legend={"orientation": "h", "y": -0.12},
    )  # fmt: skip
    path = paths.FIGURES / "f0" / "area_candidates.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(path, include_plotlyjs="cdn", full_html=True)
    return str(path.relative_to(paths.ROOT))


def main() -> None:
    marks, (sensors, events), stations, reports = (
        _marks(),
        _sensors(),
        _substations(),
        _groundsource(),
    )
    west, south = _TO_UTM.transform(scoring.BOX_LONLAT[0], scoring.BOX_LONLAT[1])
    east, north = _TO_UTM.transform(scoring.BOX_LONLAT[2], scoring.BOX_LONLAT[3])
    grid = scoring.make_grid((west, south, east, north), step=STEP_M, side=SIDE_M)

    def with_event(days: tuple[str, ...]) -> pd.DataFrame:
        ids = events.loc[events["local_day"].isin(days), "sensor_id"].unique()
        return sensors[sensors["sensor_id"].isin(ids)]

    def reports_on(days: tuple[str, ...]) -> pd.DataFrame:
        covers = np.zeros(len(reports), dtype=bool)
        for day in days:
            covers |= (reports["start_date"] <= day) & (reports["end_date"] >= day)
        return reports[covers]

    ida, sep29 = with_event(STORMS["ida_2021"]), with_event(STORMS["sep29_2023"])
    deep_bins, code_column = _deep_flood_bins(grid)
    not_rail = stations[~stations["rail"]]
    bins = {
        "high_water_marks": grid.count(marks["x"], marks["y"]),
        "sensors_sep29_2023": grid.count(sep29["x"], sep29["y"]),
        "sensors_ida_2021": grid.count(ida["x"], ida["y"]),
        "substations": grid.count(stations["x"], stations["y"]),
        "substations_not_rail": grid.count(not_rail["x"], not_rail["y"]),
        "deep_flood_ha": deep_bins,
        "groundsource_small_ida": grid.count(
            *reports_on(STORMS["ida_2021"])[["x", "y"]].T.to_numpy()
        ),
        "groundsource_small_sep29": grid.count(
            *reports_on(STORMS["sep29_2023"])[["x", "y"]].T.to_numpy()
        ),
    }
    counts = {name: grid.window_sums(values) for name, values in bins.items()}
    scores = scoring.score(counts, SCORE)
    passing = scoring.passes(counts, RULE)
    chosen = scoring.pick(scores, grid, n=5, max_overlap=0.25)

    table = []
    for row, col in chosen:
        w, s, e, n = grid.window_bounds(row, col)
        lon, lat = _TO_LONLAT.transform((w + e) / 2, (s + n) / 2)
        entry = {
            "centre_lonlat": [round(lon, 4), round(lat, 4)],
            "bounds_utm18n_m": [w, s, e, n],
            "score": round(float(scores[row, col]), 3),
            "passes_rule": bool(passing[row, col]),
        }
        entry |= {name: round(float(values[row, col]), 1) for name, values in counts.items()}
        table.append(entry)

    best_passing = [e for e in table if e["passes_rule"]]
    maxima = {name: float(values.max()) for name, values in counts.items()}
    figure = _figure_map(
        grid, chosen, table,
        {
            "High-water marks (Ida)": marks,
            "Sensors with an event on 2023-09-29": sep29,
            "Sensors with an Ida event": ida,
            "Substations (not rail)": not_rail,
        },
    )  # fmt: skip
    cache = paths.CACHE
    record = Record(
        id="f0-area-candidates",
        stage="F0",
        title="Candidate study areas scored by what was observed in them",
        inputs=[
            Input.of(cache / "usgs-ida-high-water-marks" / "FilteredHWMs_NewYork.csv", root=cache),
            Input.of(cache / "floodnet-sensors" / "kb2e-tjy3.csv", root=cache),
            Input.of(cache / "floodnet-flood-events" / "aq7i-eu5q.csv", root=cache),
            Input.of(cache / "osm-substations" / "overpass.json", root=cache),
            Input.of(cache / "groundsource" / "extract_nyc_alameda.parquet", root=cache),
            Input.of(
                cache / "nyc-stormwater-flood-maps" / "NYCFloodStormwaterFloodMaps.zip", root=cache
            ),
        ],
        parameters=[
            Parameter("window_side_m", SIDE_M, "P"),
            Parameter("window_step_m", STEP_M, "P"),
            Parameter("search_box_lonlat", list(scoring.BOX_LONLAT), "P"),
            Parameter("pass_rule_minimum_counts", RULE, "P"),
            Parameter("score_unit_per_criterion", SCORE, "P"),
            Parameter("groundsource_largest_place_km2", GROUNDSOURCE_MAX_KM2, "P"),
            Parameter("deep_class_code", 2, "S", "flood-map data dictionary: 1 ft and greater"),
            Parameter("flood_map_class_column", code_column, "I"),
        ],
        numbers={
            "windows_scored": int(scores.size),
            "windows_passing_rule": int(passing.sum()),
            "largest_count_in_any_window": maxima,
            "marks_in_box": int(bins["high_water_marks"].sum()),
            "sensors_with_event_sep29_2023_in_box": int(bins["sensors_sep29_2023"].sum()),
            "sensors_with_event_ida_in_box": int(bins["sensors_ida_2021"].sum()),
            "substations_in_box": int(bins["substations"].sum()),
            "substations_not_rail_in_box": int(bins["substations_not_rail"].sum()),
        },
        tables={"best_five": table},
        checks=[
            Check(
                "an area passes the rule",
                "at least 8 high-water marks, 5 sensors with a 2023-09-29 event and 3 substations",
                bool(best_passing),
                value=int(passing.sum()),
                threshold=1,
                proposed=True,
                note="thresholds are the proposed starting values of plan F0",
            )
        ],
        figures=[figure],
        notes=[
            "Counts in 16 km² windows on a 500 m step. The search box is a rectangle, so it also "
            "takes in parts of Manhattan, Nassau County and New Jersey; the Jamaica Bay watershed "
            "boundary was not used. The Limited Flood map could not be read and is not counted.",
        ],
    )
    print("record:", record.write(paths.RECORDS))
    print(json.dumps({"passing": int(passing.sum()), "maxima": maxima}, indent=1))
    print(pd.DataFrame(table).drop(columns=["bounds_utm18n_m"]).to_string())


if __name__ == "__main__":
    main()
