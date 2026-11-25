"""F1 terrain (FD1, FD2): aggregation, sampling, water rule and study-area clip on tiny cases.

Offline and without the cache: every raster is built in ``tmp_path``.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
import shapely
from rasterio.transform import Affine

from flood_lab import cache, terrain

FLAT = np.float32(terrain.HYDRO_FLAT_M)


def _tile(path, z, west, north, crs="EPSG:26918", nodata=-3.4028234663852886e38):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=z.shape[1],
        height=z.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=Affine(1.0, 0.0, west, 0.0, -1.0, north),
        nodata=nodata,
    ) as dst:
        dst.write(z.astype("float32"), 1)


# --- 1 m to 5 m -----------------------------------------------------------------------------------


def test_aggregate_mean_min_max_on_a_known_array():
    z = np.arange(100, dtype="float32").reshape(10, 10)
    mean, low, high = terrain.aggregate(z, 5)
    assert mean.shape == (2, 2)
    block = z[:5, 5:]
    assert mean[0, 1] == pytest.approx(block.mean())
    assert low[0, 1] == block.min() == 5
    assert high[0, 1] == block.max() == 49
    assert np.all((low <= mean) & (mean <= high))


def test_aggregate_refuses_a_partial_block_and_keeps_nan():
    with pytest.raises(ValueError):
        terrain.aggregate(np.zeros((6, 5), dtype="float32"), 5)
    z = np.ones((5, 10), dtype="float32")
    z[0, 0] = np.nan
    mean, low, high = terrain.aggregate(z, 5)
    assert np.isnan(mean[0, 0]) and np.isnan(low[0, 0]) and np.isnan(high[0, 0])
    assert mean[0, 1] == 1


def test_row_0_is_north_through_the_cut_and_the_aggregation(tmp_path):
    # a 20 x 20 m source tile; the north-west 5 m block is high, the rest low
    z = np.zeros((20, 20), dtype="float32")
    z[:5, :5] = 10.0
    z[19, 19] = -3.4028234663852886e38  # nodata, outside the cut below
    source = tmp_path / "source.tif"
    _tile(source, z, west=1000.0, north=2020.0)
    out = tmp_path / "dem.tif"
    # cut the north-west 10 x 10 m
    info = terrain.cut_terrain(source, out, (1000.0, 2010.0, 1010.0, 2020.0))
    assert info["window_col_row_width_height"] == [0, 0, 10, 10]
    assert info["pixels_without_value"] == 0
    cut, transform = terrain.read_1m(out)
    with rasterio.open(out) as src:
        assert src.crs.to_epsg() == 32618
        assert src.nodata == terrain.NODATA
    assert (transform.c, transform.f, transform.a, transform.e) == (1000.0, 2020.0, 1.0, -1.0)
    mean, low, high = terrain.aggregate(cut, 5)
    assert mean[0, 0] == 10.0 and mean[1, 0] == 0.0  # row 0 north
    assert high[0, 0] == 10.0 and low[0, 1] == 0.0


def test_cut_refuses_bounds_off_the_pixel_edges(tmp_path):
    source = tmp_path / "source.tif"
    _tile(source, np.zeros((10, 10)), west=1000.0, north=2010.0)
    with pytest.raises(ValueError, match="pixel edges"):
        terrain.cut_terrain(source, tmp_path / "x.tif", (1000.5, 2000.0, 1005.5, 2005.0))
    with pytest.raises(ValueError, match="beyond"):
        terrain.cut_terrain(source, tmp_path / "x.tif", (995.0, 2000.0, 1005.0, 2010.0))


def test_cut_marks_source_nodata_with_the_new_nodata(tmp_path):
    z = np.zeros((10, 10), dtype="float32")
    z[2, 3] = -3.4028234663852886e38
    source = tmp_path / "source.tif"
    _tile(source, z, west=0.0, north=10.0)
    info = terrain.cut_terrain(source, tmp_path / "d.tif", (0.0, 0.0, 10.0, 10.0))
    assert info["pixels_without_value"] == 1
    cut, _ = terrain.read_1m(tmp_path / "d.tif")
    assert np.isnan(cut[2, 3]) and np.isfinite(cut).sum() == 99


# --- sampling -------------------------------------------------------------------------------------


def test_ground_elevation_at_pixel_centres_and_refusal_outside(tmp_path):
    z = np.arange(12, dtype="float32").reshape(3, 4)  # rows from north
    path = tmp_path / "dem.tif"
    _tile(path, z, west=100.0, north=203.0, crs="EPSG:32618", nodata=terrain.NODATA)
    x = 100.5 + np.arange(4)
    y = 202.5 - np.arange(3)
    gx, gy = np.meshgrid(x, y)
    assert np.array_equal(terrain.ground_elevation(gx, gy, path=path), z)
    # nearest pixel: any point inside a pixel gives that pixel; an edge belongs east and south
    assert terrain.ground_elevation([100.99], [202.01], path=path)[0] == 0
    assert terrain.ground_elevation([101.0], [202.0], path=path)[0] == 5
    for px, py in ((99.9, 202.5), (104.0, 202.5), (100.5, 203.1), (100.5, 200.0)):
        with pytest.raises(ValueError, match="outside"):
            terrain.ground_elevation([px], [py], path=path)


def test_ground_elevation_refuses_a_pixel_without_value(tmp_path):
    z = np.ones((2, 2), dtype="float32")
    z[0, 0] = terrain.NODATA
    path = tmp_path / "dem.tif"
    _tile(path, z, west=0.0, north=2.0, crs="EPSG:32618", nodata=terrain.NODATA)
    with pytest.raises(ValueError, match="without value"):
        terrain.ground_elevation([0.5], [1.5], path=path)
    assert terrain.ground_elevation([1.5], [0.5], path=path)[0] == 1


# --- water ----------------------------------------------------------------------------------------


def test_water_needs_both_the_flat_level_and_no_outline():
    z = np.array([[FLAT, FLAT, 2.0], [FLAT, -12.0, 3.0]], dtype="float32")
    on_land = np.array([[False, True, True], [False, False, True]])
    water, counts = terrain.water_mask(z, on_land)
    assert water.tolist() == [[True, False, False], [True, False, False]]
    assert counts["flat_at_level"] == 3
    assert counts["outside_outlines"] == 3
    assert counts["water_both_tests"] == 2
    assert counts["flat_inside_outlines_not_water"] == 1
    assert counts["outside_outlines_not_flat_not_water"] == 1


def test_water_takes_the_flat_level_exactly():
    z = np.array([[FLAT + np.float32(0.001), FLAT]], dtype="float32")
    water, counts = terrain.water_mask(z, np.zeros_like(z, dtype=bool))
    assert water.tolist() == [[False, True]]
    assert counts["within_5_mm_of_level_not_equal"] == 1


# --- study area -----------------------------------------------------------------------------------


def _outlines():
    return gpd.GeoDataFrame(
        {
            "boroname": ["Brooklyn", "Brooklyn", "Manhattan"],
            "ntaname": ["a", "b", "c"],
            "ntatype": ["0", "0", "0"],
        },
        geometry=[
            shapely.box(0, 0, 50, 100),
            # 1 cm from "a"
            shapely.box(50.01, 0, 100, 100),
            shapely.box(0, 150, 100, 200),
        ],
        crs="EPSG:32618",
    )


def test_study_area_is_the_borough_land_inside_the_square():
    area = terrain.study_area_polygon(_outlines(), square=(25, 25, 125, 175), borough="Brooklyn")
    # land of the borough in the square: x 25 to 100, y 25 to 100, less the 1 cm gap
    assert area.area == pytest.approx(75 * 75, abs=1.0)
    assert area.bounds == pytest.approx((25, 25, 100, 100))
    assert not area.intersects(shapely.box(0, 150, 100, 200))  # Manhattan left out


def test_seams_between_outlines_are_closed_and_large_holes_kept():
    ring = shapely.box(0, 0, 100, 100).difference(shapely.box(40, 40, 60, 60))  # 400 m² hole
    joined = terrain.land_union([ring], max_hole_m2=300.0)
    assert len(joined.interiors) == 1
    filled = terrain.land_union([ring], max_hole_m2=1000.0)
    assert len(filled.interiors) == 0


def test_study_area_refuses_an_absent_borough():
    with pytest.raises(ValueError, match="Queens"):
        terrain.study_area_polygon(_outlines(), square=(0, 0, 100, 100), borough="Queens")


def test_study_area_file_round_trip(tmp_path):
    polygon = shapely.box(586000, 4505000, 587000, 4506000)
    path = tmp_path / "study_area.geojson"
    terrain.write_study_area(polygon, path)
    first = path.read_bytes()
    terrain.write_study_area(polygon, path)
    assert path.read_bytes() == first
    back = terrain.study_area(path)
    assert back.area == pytest.approx(polygon.area, rel=1e-5)
    assert shapely.hausdorff_distance(back, polygon) < 0.05


# --- footprint ring -------------------------------------------------------------------------------


def test_ring_median_takes_pixels_1_to_3_m_outside_and_skips_excluded():
    z = np.zeros((20, 20), dtype="float32")
    z[:, 13:] = 7.0  # east of the footprint, beyond 3 m: never in the ring
    z[:, 11] = 2.0  # 2 m east of the footprint's east edge: in the ring
    transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 20.0)
    footprint = shapely.box(5, 5, 10, 10)
    exclude = np.zeros_like(z, dtype=bool)
    medians, counts = terrain.ring_medians([footprint], z, transform, exclude, (1.0, 3.0), 1)
    assert counts[0] > 0 and medians[0] == 0.0
    only_east = np.ones_like(exclude)
    only_east[:, 11] = False
    medians, counts = terrain.ring_medians([footprint], z, transform, only_east, (1.0, 3.0), 1)
    # column 11 (centre 1.5 m east of the edge): rows whose centre is 1 to 3 m from the corner too
    assert medians[0] == 2.0 and counts[0] == 11


# --- cache root -----------------------------------------------------------------------------------


def test_cache_root_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOOD_CACHE", str(tmp_path))
    assert cache.root() == tmp_path
    monkeypatch.delenv("FLOOD_CACHE")
    from flood_lab import paths

    assert cache.root() == paths.CACHE
