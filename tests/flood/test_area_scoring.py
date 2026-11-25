"""F0: the window arithmetic of the area scoring, on counts that can be checked by hand."""

from __future__ import annotations

import numpy as np
import pytest

from flood_lab import area_scoring as scoring


def _grid() -> scoring.Grid:
    return scoring.make_grid((0.0, 0.0, 5000.0, 4000.0), step=500.0, side=2000.0)


def test_points_are_counted_in_their_bin_and_outside_points_are_left_out() -> None:
    grid = _grid()
    bins = grid.count(
        np.array([10.0, 499.0, 500.0, -1.0, 5000.0]), np.array([10.0, 10.0, 600.0, 5.0, 5.0])
    )
    assert bins[0, 0] == 2 and bins[1, 1] == 1 and bins.sum() == 3


def test_a_window_sum_is_the_sum_of_its_bins() -> None:
    grid = _grid()
    bins = np.arange(grid.ny * grid.nx, dtype=float).reshape(grid.ny, grid.nx)
    sums = grid.window_sums(bins)
    assert sums.shape == (grid.ny - 3, grid.nx - 3)
    assert sums[2, 3] == bins[2:6, 3:7].sum()
    assert grid.window_bounds(2, 3) == (1500.0, 1000.0, 3500.0, 3000.0)
    assert grid.window_km2 == 4.0


def test_score_caps_each_criterion_at_two_and_the_rule_needs_every_count() -> None:
    counts = {"a": np.array([[8.0, 80.0]]), "b": np.array([[5.0, 0.0]])}
    assert scoring.score(counts, {"a": 8, "b": 5}).tolist() == [[2.0, 2.0]]
    assert scoring.passes(counts, {"a": 8, "b": 5}).tolist() == [[True, False]]


def test_the_best_windows_do_not_overlap_more_than_allowed() -> None:
    grid = _grid()
    scores = np.zeros((grid.ny - 3, grid.nx - 3))
    scores[0, 0], scores[0, 1], scores[4, 6] = 5.0, 4.9, 3.0
    assert scoring.pick(scores, grid, n=2, max_overlap=0.25) == [(0, 0), (4, 6)]


def test_a_window_must_be_a_whole_number_of_bins() -> None:
    with pytest.raises(ValueError):
        scoring.make_grid((0.0, 0.0, 1000.0, 1000.0), step=300.0, side=1000.0)


def test_a_fine_raster_north_row_first_lands_in_the_bin_counted_from_the_south() -> None:
    grid = scoring.make_grid((0.0, 0.0, 1500.0, 1000.0), step=500.0, side=500.0)  # 2 rows, 3 cols
    fine = np.zeros((grid.ny * 2, grid.nx * 2), dtype=np.uint8)  # 250 m cells, 2 to a bin
    fine[0, 5] = 1  # the north-east fine cell of the raster
    bins = scoring.fine_to_bins(fine, grid, 250.0)
    assert bins.shape == (2, 3)
    assert bins[1, 2] == 6.25 and bins.sum() == 6.25  # 250 m x 250 m is 6.25 ha, north-east bin
    assert grid.count(np.array([1400.0]), np.array([900.0]))[1, 2] == 1  # same bin as a point
    with pytest.raises(ValueError):
        scoring.fine_to_bins(fine[1:], grid, 250.0)
