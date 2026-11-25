"""FS1, FS4: the second reader of the city's flood maps, on a GeoPackage built here.

The fixture is a 6 x 6 grid of 10 m cells near the study square. Polygons are drawn in grid
metres around whole cells (1 m inside the cell edges, so each centre is 4 m from any edge), moved
to EPSG:2263 and written with a Z, as the publisher's layers are. The class raster is then known
by hand.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyogrio
import pyproj
import pytest
import shapely

from flood_lab import cache, domain
from flood_lab.reference import nyc_flood_maps as maps
from flood_lab.reference.compare import compare_grids, outcome

GRID = domain.Grid(586_000.0, 4_505_940.0, 586_060.0, 4_506_000.0, 10.0)
MARGIN = 1.0


def cells(r0: int, r1: int, c0: int, c1: int, east_extra: float = 0.0) -> shapely.Polygon:
    """A rectangle in grid metres holding the centres of rows r0..r1 and columns c0..c1."""
    return shapely.box(
        GRID.west + c0 * GRID.cell + MARGIN,
        GRID.north - (r1 + 1) * GRID.cell + MARGIN,
        GRID.west + (c1 + 1) * GRID.cell - MARGIN + east_extra,
        GRID.north - r0 * GRID.cell - MARGIN,
    )


#: (code, polygon in grid metres)
POLYGONS = [
    (1, cells(0, 1, 0, 3)),
    (2, cells(1, 2, 2, 4)),
    (1, cells(4, 4, 1, 2)),
    (3, cells(4, 5, 0, 1)),
    # reaches 21 m east of the grid: only 19 m x 8 m of it lies inside
    (2, cells(5, 5, 4, 4, east_extra=GRID.cell + 2 * MARGIN + 9.0)),
]
DEPTH = np.array(
    [
        [1, 1, 1, 1, 0, 0],
        [1, 1, 2, 2, 2, 0],
        [0, 0, 2, 2, 2, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 1, 1, 0, 0, 0],
        [0, 0, 0, 0, 2, 2],
    ],
    dtype=np.uint8,
)
TIDAL = np.zeros((6, 6), dtype=bool)
TIDAL[4:6, 0:2] = True
AREA = {1: 38 * 18 + 18 * 8, 2: 28 * 18 + 19 * 8, 3: 18 * 18}


def to_2263(geom: shapely.Geometry) -> shapely.Geometry:
    t = pyproj.Transformer.from_crs("EPSG:26918", "EPSG:2263", always_xy=True)
    return shapely.transform(geom, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))


def write_map(
    path: Path, polygons: list[tuple[int, shapely.Geometry]], crs: str = "EPSG:2263"
) -> Path:
    geoms = [shapely.MultiPolygon([to_2263(g)]) for _, g in polygons]
    geoms = [shapely.force_3d(g, 7.0) for g in geoms]
    pyogrio.raw.write(
        str(path),
        geometry=shapely.to_wkb(geoms),
        field_data=[np.array([code for code, _ in polygons], dtype=np.int16)],
        fields=["Flooding_Category"],
        driver="GPKG",
        geometry_type="MultiPolygon Z",
        crs=crs,
        layer="flood",
    )
    return path


@pytest.fixture
def flood_map(tmp_path: Path) -> Path:
    return write_map(tmp_path / "map.gpkg", POLYGONS)


def test_read_polygons_gives_codes_in_2263_without_z(flood_map: Path) -> None:
    rows = maps.read_polygons(flood_map)
    assert [code for code, _ in rows] == [1, 2, 1, 3, 2]
    assert not any(shapely.has_z(geom) for _, geom in rows)
    # New York Long Island state plane, US feet: about 1 million feet east
    x, y = rows[0][1].centroid.x, rows[0][1].centroid.y
    assert 900_000 < x < 1_100_000 and 100_000 < y < 300_000


def test_classes_are_the_hand_drawn_raster(flood_map: Path) -> None:
    result = maps.classes_on_grid(flood_map, GRID)
    assert result["depth_class"].dtype == np.uint8
    assert result["depth_class"].shape == (GRID.height, GRID.width)
    np.testing.assert_array_equal(result["depth_class"], DEPTH)
    np.testing.assert_array_equal(result["tidal"], TIDAL)
    assert result["tidal_and_depth_cells"] == 1
    assert result["cells"] == {
        "class_1": 8,
        "class_2": 8,
        "tidal": 4,
        "tidal_and_depth_cells": 1,
        "code_1_and_code_2": 2,
    }


def test_areas_are_cut_to_the_grid_in_square_metres(flood_map: Path) -> None:
    area = maps.classes_on_grid(flood_map, GRID)["area_m2"]
    assert sorted(area) == [1, 2, 3]
    for code, expected in AREA.items():
        assert area[code] == pytest.approx(expected, rel=1e-6)


def test_a_scenario_without_code_3_has_no_tidal_cell(tmp_path: Path) -> None:
    path = write_map(tmp_path / "m.gpkg", [(c, g) for c, g in POLYGONS if c != 3])
    result = maps.classes_on_grid(path, GRID)
    assert not result["tidal"].any()
    assert 3 not in result["area_m2"]
    np.testing.assert_array_equal(result["depth_class"], DEPTH)


def test_code_3_never_enters_a_depth_class(tmp_path: Path) -> None:
    path = write_map(tmp_path / "m.gpkg", [(3, cells(0, 5, 0, 5))])
    result = maps.classes_on_grid(path, GRID)
    assert not result["depth_class"].any()
    assert result["tidal"].all()


def test_a_polygon_shifted_by_one_cell_differs(flood_map: Path, tmp_path: Path) -> None:
    shifted = [
        (code, shapely.affinity.translate(geom, xoff=GRID.cell) if i == 1 else geom)
        for i, (code, geom) in enumerate(POLYGONS)
    ]
    path = write_map(tmp_path / "shifted.gpkg", shifted)
    good = maps.classes_on_grid(flood_map, GRID)["depth_class"]
    bad = maps.classes_on_grid(path, GRID)["depth_class"]
    result = compare_grids(good, bad)
    assert outcome(result) == "differs"
    assert result["differing_cells"] == 4
    assert outcome(compare_grids(good, maps.classes_on_grid(flood_map, GRID)["depth_class"])) == (
        "confirmed"
    )


def test_a_swapped_class_code_differs(flood_map: Path, tmp_path: Path) -> None:
    swapped = [
        ({1: 2, 2: 1}.get(code, code) if i == 0 else code, g)
        for i, (code, g) in enumerate(POLYGONS)
    ]
    path = write_map(tmp_path / "swapped.gpkg", swapped)
    good = maps.classes_on_grid(flood_map, GRID)["depth_class"]
    result = compare_grids(good, maps.classes_on_grid(path, GRID)["depth_class"])
    assert outcome(result) == "differs"
    assert result["differing_cells"] == 6


def test_an_unreadable_geodatabase_raises_rather_than_returning_an_empty_raster(
    tmp_path: Path,
) -> None:
    gdb = tmp_path / "broken.gdb"
    gdb.mkdir()
    (gdb / "a00000001.gdbtable").write_bytes(b"not a table" * 10)
    (gdb / "gdb").write_bytes(b"\x05\x00\x00\x00")
    with pytest.raises(maps.UnreadableMap, match="cannot read the flood map"):
        maps.classes_on_grid(gdb, GRID)
    junk = tmp_path / "junk.gpkg"
    junk.write_text("this is not a GeoPackage")
    with pytest.raises(maps.UnreadableMap, match="Compressed Data Format"):
        maps.read_polygons(junk)
    with pytest.raises(maps.UnreadableMap):
        maps.read_polygons(tmp_path / "missing.gdb")


def test_a_layer_in_another_crs_is_refused(tmp_path: Path) -> None:
    path = write_map(tmp_path / "m.gpkg", POLYGONS[:1], crs="EPSG:4326")
    with pytest.raises(ValueError, match="expected EPSG:2263"):
        maps.read_polygons(path)


def test_an_unknown_code_is_refused(tmp_path: Path) -> None:
    path = write_map(tmp_path / "m.gpkg", [(4, cells(0, 0, 0, 0))])
    with pytest.raises(ValueError, match="unknown Flooding_Category 4"):
        maps.read_polygons(path)


def test_cell_centres_follow_the_contract() -> None:
    xs, ys = maps.cell_centres(GRID)
    assert xs[0, 0] == GRID.west + 5.0 and ys[0, 0] == GRID.north - 5.0
    assert xs[2, 3] == GRID.west + 35.0 and ys[2, 3] == GRID.north - 25.0


def test_the_transformation_has_no_datum_shift() -> None:
    text = maps.transformation()
    assert "helmert" not in text.lower()
    assert "utm" in text.lower()


ZIP = cache.root() / "nyc-stormwater-flood-maps" / maps.ZIP_NAME


@pytest.mark.skipif(not ZIP.exists(), reason="needs the cached flood-map zip")
def test_real_moderate_current_layer_has_codes_1_and_2_only() -> None:
    rows = maps.read_polygons(maps.zip_path(ZIP, "moderate-current"))
    assert sorted(code for code, _ in rows) == [1, 2]
    with pytest.raises(maps.UnreadableMap):
        maps.read_polygons(maps.zip_path(ZIP, "limited-current"))
