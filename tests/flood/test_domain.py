"""D1, FD1: the project grid."""

from __future__ import annotations

import pytest

from flood_lab import domain


def test_the_grid_is_800_by_800_cells_of_5_m() -> None:
    assert (domain.GRID.width, domain.GRID.height) == (800, 800)
    assert domain.GRID.transform == (5.0, 0.0, 585_500.0, 0.0, -5.0, 4_508_500.0)


def test_a_point_falls_in_one_cell_with_row_zero_at_the_north() -> None:
    grid = domain.GRID
    assert grid.cell_of(585_500.0, 4_508_499.0) == (0, 0)
    assert grid.cell_of(589_499.0, 4_504_500.5) == (799, 799)
    # on a shared edge the point belongs to the cell to the north and to the east
    assert grid.cell_of(585_505.0, 4_508_495.0) == (0, 1)
    with pytest.raises(ValueError):
        grid.cell_of(589_500.0, 4_506_000.0)


def test_the_centre_recorded_is_the_centre_of_the_square() -> None:
    import pyproj

    x, y = pyproj.Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True).transform(
        *domain.CENTRE_LONLAT
    )
    west, south, east, north = domain.SQUARE
    assert abs(x - (west + east) / 2) < 10 and abs(y - (south + north) / 2) < 10
