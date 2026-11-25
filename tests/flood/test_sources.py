"""The F2 loaders on small constructed files (FS1 to FS3). Offline; no cache."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely

from flood_lab import domain
from flood_lab.sources import floodnet, groundsource, nyc_flood_maps

GRID = domain.Grid(586_000.0, 4_505_000.0, 586_050.0, 4_505_040.0, 5.0)  # 10 columns, 8 rows
TOY = nyc_flood_maps.Scenario("toy", "Toy", 1.0, "current", "folder", "toy.gdb")


def _box(col0: int, row0: int, col1: int, row1: int) -> shapely.Polygon:
    """A rectangle covering whole cells, columns col0..col1-1 and rows row0..row1-1."""
    return shapely.box(
        GRID.west + 5 * col0, GRID.north - 5 * row1, GRID.west + 5 * col1, GRID.north - 5 * row0
    )


def _maps_file(tmp_path: Path, shapes: list[tuple[int, shapely.Polygon]]) -> Path:
    frame = gpd.GeoDataFrame(
        {nyc_flood_maps.FIELD: [code for code, _ in shapes]},
        geometry=[shapely.MultiPolygon([shape]) for _, shape in shapes],
        crs=nyc_flood_maps.GRID_FRAME_CRS,
    ).to_crs(nyc_flood_maps.SOURCE_CRS)
    path = tmp_path / "maps.gpkg"
    frame.to_file(path, layer="toy", driver="GPKG")
    return path


def _classes(path: Path) -> dict:
    polygons = nyc_flood_maps.on_grid_frame(nyc_flood_maps.read_polygons(path))
    return nyc_flood_maps.classes_on_grid(polygons, GRID)


def test_depth_classes_follow_the_cell_centre_and_class_two_wins(tmp_path: Path) -> None:
    # class 1 over columns 1..5, rows 1..4; class 2 over columns 3..4, rows 2..3, inside it;
    # class 3 (tidal) over column 8; a sliver that reaches no cell centre
    sliver = shapely.box(GRID.west + 30.5, GRID.south + 0.5, GRID.west + 31.5, GRID.south + 1.5)
    path = _maps_file(
        tmp_path, [(1, _box(1, 1, 6, 5)), (2, _box(3, 2, 5, 4)), (3, _box(8, 0, 9, 8)), (1, sliver)]
    )
    got = _classes(path)
    expected = np.zeros((8, 10), dtype=np.uint8)
    expected[1:5, 1:6] = 1
    expected[2:4, 3:5] = 2
    assert np.array_equal(got["depth_class"], expected)
    tidal = np.zeros((8, 10), dtype=bool)
    tidal[:, 8] = True
    assert np.array_equal(got["tidal"], tidal)
    assert got["area_m2"][2] == pytest.approx(100.0, abs=1e-3)
    assert got["area_m2"][3] == pytest.approx(200.0, abs=1e-3)
    assert got["area_m2"][1] == pytest.approx(501.0, abs=1e-3)  # the sliver counts in area


def test_a_tidal_polygon_never_becomes_a_depth_class(tmp_path: Path) -> None:
    got = _classes(_maps_file(tmp_path, [(3, _box(0, 0, 10, 8))]))
    assert not got["depth_class"].any()
    assert got["tidal"].all()


def test_an_unknown_code_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not in the data dictionary"):
        nyc_flood_maps.read_polygons(_maps_file(tmp_path, [(4, _box(0, 0, 2, 2))]))


def test_an_unreadable_geodatabase_is_an_error_not_an_empty_map(tmp_path: Path) -> None:
    folder = tmp_path / "broken.gdb"
    folder.mkdir()
    (folder / "gdb").write_bytes(b"\x05\x00\x00\x00")
    with pytest.raises(nyc_flood_maps.UnreadableLayer):
        nyc_flood_maps.read_polygons(folder)


def test_the_limited_map_is_read_from_its_export_when_one_exists(tmp_path: Path) -> None:
    export = tmp_path / nyc_flood_maps.LIMITED_EXPORT
    export.parent.mkdir(parents=True)
    export.write_bytes(b"")
    limited = nyc_flood_maps.SCENARIOS["limited-current"]
    assert nyc_flood_maps.source_path(limited, tmp_path) == export


def test_layer_rows_are_cut_to_the_square_and_read_back_from_crc(tmp_path: Path) -> None:
    beyond = shapely.box(GRID.east - 10, GRID.south, GRID.east + 500, GRID.north)
    path = _maps_file(tmp_path, [(1, _box(1, 1, 6, 5)), (2, beyond)])
    polygons = nyc_flood_maps.on_grid_frame(nyc_flood_maps.read_polygons(path))
    rows = nyc_flood_maps.layer_table(TOY, polygons, GRID)
    assert rows["support_id"] == ["toy/class-1/00001", "toy/class-2/00001"]
    assert rows["value"] == [1.0, 2.0]
    assert rows["label"][1] == nyc_flood_maps.LABELS[2]
    cut = gpd.GeoSeries.from_wkb(rows["geometry"], crs="EPSG:4326").to_crs(domain.CRS)
    assert cut.iloc[1].area == pytest.approx(10 * 40, rel=1e-6)  # only the part in the square
    back = nyc_flood_maps.read_back_differences(rows, nyc_flood_maps.to_crc(TOY, rows))
    assert back["rows_back"] == 2
    assert back["missing"] == back["extra"] == back["value_differs"] == 0
    assert back["label_differs"] == back["geometry_shape_differs"] == 0


EVENTS = """sensor_name,sensor_id,flood_start_time,flood_end_time,max_depth_inches,duration_mins
A,a,2023-09-29T13:10:00.000,2023-09-29T15:10:00.000,10,120
A,a,2023-09-30T03:30:00.000,2023-09-30T04:00:00.000,4,30
B,b,2021-09-02T01:15:00.000,2021-09-02T03:15:00.000,20,120
B,b,2023-01-10T04:59:00.000,2023-01-10T05:30:00.000,2,31
B,b,2023-01-10T05:00:00.000,2023-01-10T05:10:00.000,1,10
"""
SENSORS = """sensor_id,date_installed,date_removed,borough,latitude,longitude
a,2023-09-29T00:00:00.000,,Brooklyn,40.70,-73.96
b,2021-08-01T00:00:00.000,2023-09-29T00:00:00.000,Queens,40.72,-73.80
c,2023-09-30T00:00:00.000,,Brooklyn,40.71,-73.95
"""


def _floodnet(tmp_path: Path) -> tuple[Path, Path]:
    events, sensors = tmp_path / "events.csv", tmp_path / "sensors.csv"
    events.write_text(EVENTS)
    sensors.write_text(SENSORS)
    return events, sensors


def test_floodnet_days_are_new_york_days_and_depths_are_metres(tmp_path: Path) -> None:
    events, sensors = _floodnet(tmp_path)
    table = floodnet.events(events, sensors)
    assert list(table.columns) == floodnet.COLUMNS
    by_start = table.set_index("start_utc")
    # 03:30 GMT in summer time is 23:30 the evening before; Ida's night is the local 1 September
    assert by_start.loc["2023-09-30T03:30:00Z", "local_day"] == "2023-09-29"
    assert by_start.loc["2021-09-02T01:15:00Z", "local_day"] == "2021-09-01"
    # winter time: 04:59 GMT is 23:59 the day before, 05:00 GMT is midnight
    assert by_start.loc["2023-01-10T04:59:00Z", "local_day"] == "2023-01-09"
    assert by_start.loc["2023-01-10T05:00:00Z", "local_day"] == "2023-01-10"
    assert by_start.loc["2023-09-29T13:10:00Z", "peak_depth_m"] == pytest.approx(0.254)
    assert by_start.loc["2021-09-02T01:15:00Z", "longitude"] == -73.80
    assert list(table["sensor_id"]) == ["a", "a", "b", "b", "b"]


def test_sensors_in_service_on_a_day(tmp_path: Path) -> None:
    events, sensors = _floodnet(tmp_path)
    table = floodnet.events(events, sensors)
    day = floodnet.storm_sensors(table, sensors, "2023-09-29")
    # a was installed that day, b removed that day (both in service), c came a day later
    assert list(day["sensor_id"]) == ["a", "b"]
    assert list(day["recorded"]) == [True, False]
    assert day.loc[0, "peak_depth_m"] == pytest.approx(0.254)  # the larger of a's two events
    ida = floodnet.storm_sensors(table, sensors, "2021-09-01")
    assert list(ida["sensor_id"]) == ["b"] and bool(ida.loc[0, "recorded"])


def test_floodnet_events_read_back_from_crc(tmp_path: Path) -> None:
    events, sensors = _floodnet(tmp_path)
    rows = floodnet.crc_table(floodnet.events(events, sensors))
    assert len(rows["support_id"]) == 5
    back = floodnet.read_back_differences(rows, floodnet.to_crc(rows))
    assert back == {
        "rows_in": 5,
        "rows_back": 5,
        "missing": 0,
        "extra": 0,
        "value_differs": 0,
        "position_differs": 0,
        "station_is_not_the_sensor": 0,
    }


def test_groundsource_keeps_rows_that_intersect_a_box(tmp_path: Path) -> None:
    box = {"toy": (0.0, 0.0, 10.0, 10.0)}
    shapes = {
        "inside": shapely.box(2, 2, 3, 3),
        "outside": shapely.box(20, 20, 21, 21),
        "straddling": shapely.box(9, 9, 13, 13),  # centroid outside the box
        "touching": shapely.box(10, 4, 11, 5),  # shares an edge with the box
        # its bounding box overlaps the box, the polygon itself does not reach it
        "near-miss": shapely.Polygon([(10.5, 11), (14, 11), (14, 8)]),
        "two-parts": shapely.MultiPolygon([shapely.box(1, 1, 2, 2), shapely.box(30, 30, 31, 31)]),
    }
    path = tmp_path / "toy.parquet"
    pq.write_table(
        pa.table(
            {
                "uuid": list(shapes),
                "area_km2": [float(i) for i in range(len(shapes))],
                "geometry": [shape.wkb for shape in shapes.values()],
                "start_date": ["2021-09-01"] * len(shapes),
                "end_date": ["2021-09-02"] * len(shapes),
                "__index_level_0__": list(range(len(shapes))),
            }
        ),
        path,
        row_group_size=2,
    )
    table = groundsource.dated_places(path, box)
    assert list(table.columns) == groundsource.COLUMNS
    assert list(table["uuid"]) == ["inside", "straddling", "touching", "two-parts"]
    flags = dict(zip(table["uuid"], table["centroid_in_box"], strict=True))
    assert flags == {"inside": True, "straddling": False, "touching": False, "two-parts": False}
    assert table.loc[0, "geometry_wkb"] == shapes["inside"].wkb
    assert len(groundsource.covering(table, "toy", "2021-09-02")) == 4
    assert len(groundsource.covering(table, "toy", "2021-09-03")) == 0
    assert isinstance(table, pd.DataFrame)


def test_the_export_tool_gives_a_hole_to_the_ring_that_holds_it() -> None:
    """tools/flood/limited_flood_map/export.py: rings to polygons by orientation."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "tools/flood/limited_flood_map/export.py"
    spec = importlib.util.spec_from_file_location("limited_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def ring(x0: float, y0: float, x1: float, y1: float, clockwise: bool) -> list:
        points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]  # clockwise as written
        return points if clockwise else points[::-1]

    rings = [
        ring(0, 0, 10, 10, True),  # outer
        ring(2, 2, 4, 4, False),  # its hole
        ring(10, 0, 20, 10, True),  # a second outer sharing the edge x = 10
        ring(10, 4, 12, 6, False),  # a hole of the second that touches the first along x = 10
    ]
    xy = np.array([p for r in rings for p in r], dtype=float)
    starts = np.cumsum([0] + [len(r) for r in rings[:-1]])
    shape, facts = module.assemble({"starts": starts, "xy": xy})
    assert facts["outer_rings"] == 2 and facts["holes"] == 2
    assert facts["holes_without_an_outer_ring"] == 0 and facts["rings_not_closed"] == 0
    first, second = shape.geoms
    assert first.area == pytest.approx(100 - 4) and second.area == pytest.approx(100 - 4)
    assert module.signed_area(np.array(rings[0], dtype=float)) < 0
