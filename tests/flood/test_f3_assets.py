"""F3: depth at the assets (``flood_lab.hazard.at_assets``) on a small grid patched in for the
project grid, so the test stays fast; the functions read only the grid's corner and size."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flood_lab.domain import Grid
from flood_lab.hazard import at_assets

WEST, SOUTH = 585_500.0, 4_504_500.0


@pytest.fixture
def small_grid(monkeypatch: pytest.MonkeyPatch):
    def use(cells: int, margin: float = 0.0) -> Grid:
        grid = Grid(WEST, SOUTH, WEST + 5 * cells, SOUTH + 5 * cells, 5.0)
        monkeypatch.setattr(at_assets, "GRID", grid)
        monkeypatch.setattr(at_assets, "TERRAIN_MARGIN_M", margin)
        return grid

    return use


def test_pixel_depth_floors_at_zero_and_handles_nan(small_grid) -> None:
    small_grid(2, margin=2.0)
    dem = np.full((14, 14), 99.0)  # the margin of 2 pixels must not be read
    dem[2:12, 2:12] = 0.5
    dem[2, 2] = 3.0  # above the level of its cell: floored to 0
    dem[7, 7] = np.nan  # no terrain: 0
    zsmax = np.array([[1.0, np.nan], [0.5, 2.0]])  # row 0 north; NaN where never wet
    d = at_assets.pixel_depth(zsmax, dem)
    assert d.shape == (10, 10)
    assert d[0, 0] == 0.0
    assert d[0, 1] == pytest.approx(0.5)
    assert (d[0:5, 5:10] == 0.0).all()  # the cell that was never wet
    assert (d[5:10, 0:5] == 0.0).all()  # level equal to the ground
    assert d[5, 5] == 0.0  # the pixel with no terrain
    assert d[8, 8] == pytest.approx(1.5)
    assert np.isfinite(d).all() and (d >= 0).all()


def _site_file(path: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        {
            "LocNumber": ["S-1", "S-2"],
            "name": ["Kept site", "Removed site"],
            "reviewed": ["kept", "removed at review"],
        },
        # 10 m by 10 m: pixel columns 2 to 11 and rows 2 to 11 from the north-west corner
        geometry=[
            box(WEST + 2, SOUTH + 8, WEST + 12, SOUTH + 18),
            box(WEST, SOUTH, WEST + 4, SOUTH + 4),
        ],
        crs="EPSG:32618",
    )
    gdf.to_file(path, driver="GeoJSON")
    return path


def test_depth_on_25m2_is_the_25th_deepest_open_ground_pixel(small_grid, tmp_path: Path) -> None:
    small_grid(4)  # 20 m square, 20 x 20 pixels of 1 m
    rng = np.random.default_rng(7)
    depth = rng.permutation(400).reshape(20, 20) / 1000.0
    buildings = np.zeros((20, 20), dtype=bool)
    buildings[2:4, 2:12] = True  # 20 pixels of the site under a footprint
    depth[2:4, 2:12] = 9.0  # deepest of all, and must not be read
    sites = at_assets.substation_depths(depth, buildings, _site_file(tmp_path / "s.geojson"))
    assert [s["LocNumber"] for s in sites] == ["S-1"]
    s = sites[0]
    assert s["pixels"] == 100
    assert s["open_ground_pixels_read"] == 80
    ground = np.sort(depth[4:12, 2:12].ravel())[::-1]
    assert s["depth_on_25m2_m"] == round(float(ground[24]), 3)
    assert s["max_depth_m"] == round(float(ground[0]), 3)
    assert s["meets_lead_rule"] is bool(ground[24] >= at_assets.LEAD_DEPTH_M)


def test_nan_pixels_are_not_read(small_grid, tmp_path: Path) -> None:
    small_grid(4)
    depth = np.full((20, 20), 0.4)
    depth[2:12, 2:12] = np.nan  # the whole site in roofed cells
    depth[11, 11] = 0.2
    sites = at_assets.substation_depths(
        depth, np.zeros((20, 20), dtype=bool), _site_file(tmp_path / "s.geojson")
    )
    assert sites[0]["open_ground_pixels_read"] == 1
    assert sites[0]["depth_on_25m2_m"] == 0.2  # fewer than 25 pixels: the shallowest one read
    assert sites[0]["meets_lead_rule"] is False
