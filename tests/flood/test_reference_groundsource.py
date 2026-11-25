"""FS2, FS4: the second reader of Groundsource, on a small Parquet file built here.

The file copies the publisher's layout: the five columns, the accidental ``__index_level_0__``
and a ``geo`` metadata entry that names its types under ``geometry_type``, which DuckDB refuses
as GeoParquet. Its
polygons sit inside, outside, across and exactly on the edge or corner of the New York box, and
one triangle has a bounding box that overlaps the box while the triangle itself does not.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely

from flood_lab import cache
from flood_lab.reference import groundsource
from flood_lab.reference.compare import compare_tables, outcome

W, S, E, N = groundsource.BOXES["nyc"]
PLACES = {
    "a-inside": shapely.box(-74.00, 40.70, -73.90, 40.80),
    "b-outside": shapely.box(-75.00, 41.00, -74.90, 41.10),
    "c-across-west-edge": shapely.box(-74.40, 40.60, -74.20, 40.70),
    "d-touches-west-edge": shapely.box(-74.40, 40.60, W, 40.70),
    "e-touches-sw-corner": shapely.box(-74.40, 40.40, W, S),
    # bounding box overlaps the box's south-west corner; the hypotenuse passes it by
    "f-triangle-near-corner": shapely.Polygon([(-74.40, 40.60), (-74.40, 40.40), (-74.20, 40.40)]),
    "g-multi-one-part-in": shapely.MultiPolygon(
        [shapely.box(-73.80, 40.80, -73.75, 40.85), shapely.box(-73.00, 40.80, -72.95, 40.85)]
    ),
    "h-alameda": shapely.box(-122.30, 37.70, -122.20, 37.80),
}
DATES = {"a-inside": ("2021-09-01", "2021-09-02")}
NYC = ["a-inside", "c-across-west-edge", "d-touches-west-edge", "e-touches-sw-corner",
       "g-multi-one-part-in"]  # fmt: skip


def write_file(path: Path, places: dict[str, shapely.Geometry] = PLACES) -> Path:
    names = list(places)
    table = pa.table(
        {
            "uuid": names,
            "area_km2": [float(i) + 0.5 for i in range(len(names))],
            "geometry": pa.array([shapely.to_wkb(places[n]) for n in names], pa.binary()),
            "start_date": [DATES.get(n, ("2020-01-01", "2020-01-03"))[0] for n in names],
            "end_date": [DATES.get(n, ("2020-01-01", "2020-01-03"))[1] for n in names],
            "__index_level_0__": list(range(len(names))),
        }
    )
    # as the publisher's file has it: GeoParquet 0.4.0 with the key "geometry_type", where
    # DuckDB looks for "geometry_types"
    geo = {
        "primary_column": "geometry",
        "columns": {"geometry": {"encoding": "WKB", "geometry_type": ["MultiPolygon", "Polygon"]}},
        "version": "0.4.0",
    }
    table = table.replace_schema_metadata({"geo": json.dumps(geo)})
    pq.write_table(table, path)
    return path


@pytest.fixture
def parquet(tmp_path: Path) -> Path:
    return write_file(tmp_path / "groundsource.parquet")


def test_the_fixture_has_the_publishers_metadata_fault(parquet: Path) -> None:
    con = duckdb.connect()
    try:
        with pytest.raises(duckdb.Error, match="does not have geometry types"):
            con.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet)]).fetchall()
    finally:
        con.close()


def test_rows_intersecting_each_box_exactly(parquet: Path) -> None:
    rows = groundsource.dated_places(parquet)
    assert [(r["box"], r["uuid"]) for r in rows] == [("alameda", "h-alameda")] + [
        ("nyc", n) for n in NYC
    ]


def test_values_are_kept_as_in_the_file(parquet: Path) -> None:
    rows = {r["uuid"]: r for r in groundsource.dated_places(parquet) if r["box"] == "nyc"}
    inside = rows["a-inside"]
    assert inside["geometry_wkb"] == shapely.to_wkb(PLACES["a-inside"])
    assert (inside["start_date"], inside["end_date"]) == ("2021-09-01", "2021-09-02")
    assert inside["area_km2"] == 0.5
    assert inside["centroid_lon"] == pytest.approx(-73.95)
    assert inside["centroid_lat"] == pytest.approx(40.75)
    assert inside["centroid_in_box"] is True
    assert rows["c-across-west-edge"]["centroid_in_box"] is False
    assert rows["d-touches-west-edge"]["centroid_in_box"] is False
    # planar centroid of both parts: east of the box
    assert rows["g-multi-one-part-in"]["centroid_in_box"] is False


def test_a_centroid_on_the_edge_is_in_the_box(tmp_path: Path) -> None:
    path = write_file(tmp_path / "g.parquet", {"edge": shapely.box(W - 0.1, 40.6, W + 0.1, 40.7)})
    (row,) = groundsource.dated_places(path)
    assert row["centroid_lon"] == pytest.approx(W) and row["centroid_in_box"] is True


def test_covering_counts_rows_whose_range_holds_the_day(parquet: Path) -> None:
    rows = groundsource.dated_places(parquet)
    assert groundsource.covering(rows, "nyc", "2021-09-01") == 1
    assert groundsource.covering(rows, "nyc", "2021-09-02") == 1
    assert groundsource.covering(rows, "nyc", "2021-09-03") == 0
    assert groundsource.covering(rows, "nyc", "2020-01-02") == 4


def test_checksum_is_the_md5(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert groundsource.checksum(path) == "900150983cd24fb0d6963f7d28e17f72"


KEY = ("box", "uuid")
EXACT = ("start_date", "end_date", "area_km2", "centroid_in_box")
CLOSE = {"centroid_lon": 1e-9, "centroid_lat": 1e-9}
GEOMETRY = ("geometry_wkb",)


def test_the_same_table_is_confirmed(parquet: Path) -> None:
    rows = groundsource.dated_places(parquet)
    assert outcome(compare_tables(rows, rows, KEY, EXACT, CLOSE, GEOMETRY)) == "confirmed"


def test_a_geometry_with_one_vertex_moved_differs(parquet: Path) -> None:
    good = groundsource.dated_places(parquet)
    bad = [dict(r) for r in good]
    moved = shapely.Polygon([(-74.00, 40.70), (-73.90, 40.70), (-73.90, 40.80), (-74.00, 40.81)])
    i = next(i for i, r in enumerate(bad) if r["uuid"] == "a-inside")
    bad[i]["geometry_wkb"] = shapely.to_wkb(moved)
    result = compare_tables(good, bad, KEY, EXACT, CLOSE, GEOMETRY)
    assert outcome(result) == "differs"
    assert result["columns"]["geometry_wkb"]["differ"] == 1


def test_the_same_geometry_in_other_bytes_is_counted_apart(parquet: Path) -> None:
    good = groundsource.dated_places(parquet)
    recoded = [
        dict(r, geometry_wkb=shapely.to_wkb(shapely.from_wkb(r["geometry_wkb"]), byte_order=0))
        for r in good
    ]
    result = compare_tables(good, recoded, KEY, EXACT, CLOSE, GEOMETRY)
    assert result["columns"]["geometry_wkb"]["bytes_differ_equal"] == len(good)
    assert result["columns"]["geometry_wkb"]["differ"] == 0
    assert outcome(result) == "confirmed"


def test_a_dropped_row_and_a_changed_date_differ(parquet: Path) -> None:
    good = groundsource.dated_places(parquet)
    assert compare_tables(good, good[1:], KEY, EXACT, CLOSE, GEOMETRY)["only_in_a"] == 1
    bad = [dict(r) for r in good]
    bad[1]["end_date"] = "2021-09-03"
    result = compare_tables(good, bad, KEY, EXACT, CLOSE, GEOMETRY)
    assert outcome(result) == "differs" and result["columns"]["end_date"]["differ"] == 1


def test_a_bounding_box_test_would_differ(parquet: Path) -> None:
    good = groundsource.dated_places(parquet)
    triangle = {
        "box": "nyc",
        "uuid": "f-triangle-near-corner",
        **{k: good[1][k] for k in (*EXACT, *CLOSE, *GEOMETRY)},
    }
    result = compare_tables(good, [*good, triangle], KEY, EXACT, CLOSE, GEOMETRY)
    assert outcome(result) == "differs" and result["only_in_b"] == 1


REAL = cache.root() / "groundsource" / groundsource.FILE_NAME


@pytest.mark.skipif(not REAL.exists(), reason="needs the cached Groundsource file")
def test_real_file_gives_the_f0_counts() -> None:
    assert groundsource.checksum(REAL) == groundsource.MD5
    rows = groundsource.dated_places(REAL)
    assert sum(r["box"] == "nyc" for r in rows) == 5772
    assert sum(r["box"] == "alameda" for r in rows) == 1013
    assert groundsource.covering(rows, "nyc", "2021-09-01") == 509
