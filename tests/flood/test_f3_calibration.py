"""F3: classes, the quarter-acre filter, the comparison with a city map and FH8's monotonicity
(``flood_lab.hazard.calibration``), on small synthetic arrays."""

from __future__ import annotations

import numpy as np
import pytest

from flood_lab.domain import GRID
from flood_lab.hazard import calibration as cal


def test_classify_at_the_city_thresholds() -> None:
    depth = np.array([0.0, 0.1015, 0.1016, 0.3047, 0.3048, 2.0, np.nan])
    assert cal.classify(depth).tolist() == [0, 0, 1, 1, 2, 2, 0]


def test_intensities_in_mm_per_hour() -> None:
    assert cal.intensity_mm_h("limited") == 44.958
    assert cal.intensity_mm_h("moderate") == 54.102
    assert cal.intensity_mm_h("extreme") == 92.964


def test_quarter_acre_lies_between_40_and_41_cells() -> None:
    assert GRID.cell == 5.0
    assert 40 * 25 < cal.MIN_PATCH_M2 < 41 * 25
    assert cal.MIN_PATCH_M2 == pytest.approx(1011.7141, abs=1e-4)


def test_min_patch_filter_keeps_41_cells_and_drops_40() -> None:
    a = np.zeros((20, 60), dtype="uint8")
    a[2, 0:41] = 1  # 41 cells in a row
    a[2, 40] = 2  # a deep cell in it keeps its class
    a[10, 0:40] = 1  # 40 cells
    out = cal.min_patch_filter(a)
    assert (out[2, 0:41] == a[2, 0:41]).all()
    assert out[2, 40] == 2
    assert (out[10] == 0).all()
    assert out.dtype == a.dtype


def test_min_patch_filter_joins_cells_touching_at_a_corner() -> None:
    a = np.zeros((10, 60), dtype="uint8")
    a[2, 0:21] = 1  # 21 cells
    a[3, 21:41] = 1  # 20 cells, touching the first run only at a corner
    out = cal.min_patch_filter(a)
    assert int((out > 0).sum()) == 41  # one patch of 41 under 8-connectivity: kept
    a[3, 21] = 0  # now 21 and 19 cells that no longer touch: both dropped
    out = cal.min_patch_filter(a)
    assert int((out > 0).sum()) == 0


#: 4 x 4 example, worked by hand in the test below
MODEL = np.array([[0, 1, 1, 2], [0, 0, 2, 2], [1, 0, 0, 0], [0, 0, 0, 1]], dtype="uint8")
CITY = np.array([[0, 1, 0, 2], [1, 0, 2, 1], [0, 0, 1, 0], [0, 0, 0, 0]], dtype="uint8")


def test_compare_on_a_hand_worked_example() -> None:
    where = np.ones((4, 4), dtype=bool)
    where[3, 3] = False  # a model-only wet cell outside the comparison
    r = cal.compare(MODEL, CITY, where)
    # wet: hits (0,1) (0,3) (1,2) (1,3); misses (1,0) (2,2); false alarms (0,2) (2,0)
    assert r["cells_compared"] == 15
    assert (r["wet_hits"], r["wet_misses"], r["wet_false_alarms"]) == (4, 2, 2)
    assert r["csi_wet"] == 0.5
    # deep: model (0,3) (1,2) (1,3), city (0,3) (1,2): 2 hits, 0 misses, 1 false alarm
    assert r["csi_deep"] == round(2 / 3, 4)
    # a 5 m cell is 0.0025 ha; compare rounds areas to 0.001 ha
    assert r["model_shallow_ha"] == round(3 * 0.0025, 3)  # (0,1) (0,2) (2,0)
    assert r["model_deep_ha"] == round(3 * 0.0025, 3)  # (0,3) (1,2) (1,3)
    assert r["city_shallow_ha"] == round(4 * 0.0025, 3)  # (0,1) (1,0) (1,3) (2,2)
    assert r["city_deep_ha"] == round(2 * 0.0025, 3)  # (0,3) (1,2)
    # same class at 3 of the city's 6 wet cells: (0,1) (0,3) (1,2)
    assert r["same_class_share_of_city_wet"] == 0.5


def test_compare_with_nothing_wet_has_no_index() -> None:
    zero = np.zeros((4, 4), dtype="uint8")
    r = cal.compare(zero, zero, np.ones((4, 4), dtype=bool))
    assert r["csi_wet"] is None and r["csi_deep"] is None
    assert r["same_class_share_of_city_wet"] is None


def test_area_error_is_zero_when_areas_match() -> None:
    same = {"model_shallow_ha": 3.0, "city_shallow_ha": 3.0, "model_deep_ha": 1.5}
    same["city_deep_ha"] = 1.5
    assert cal.area_error(same) == 0.0
    off = same | {"model_deep_ha": 3.0}
    assert cal.area_error(off) == pytest.approx(np.log(3.01 / 1.51) ** 2)


def test_monotonicity_allows_under_1_mm_in_a_dry_cell() -> None:
    where = np.ones(3, dtype=bool)
    high = np.array([0.02, 0.2, 0.0])
    low = np.array([0.0205, 0.1, 0.0])  # dry cell 0.5 mm deeper at the lower rain
    r = cal.monotonicity(low, high, where)
    assert r["passed"] is True
    assert r["cells_deeper_at_lower_rain_by_over_1mm"] == 0
    assert r["wet_cells_deeper_at_lower_rain"] == 0
    assert r["max_excess_m"] == pytest.approx(0.0005)


def test_monotonicity_allows_under_1_mm_in_a_wet_cell_and_fails_over() -> None:
    # CH-16: the wet-cell clause takes the same 1 mm tolerance as the dry one
    where = np.ones(2, dtype=bool)
    high = np.array([0.1, 0.2])
    low = np.array([0.1001, 0.2])  # wet, 0.1 mm deeper at the lower rain
    r = cal.monotonicity(low, high, where)
    assert r["passed"] is True
    assert r["wet_cells_deeper_at_lower_rain"] == 1
    assert r["wet_cells_deeper_at_lower_rain_by_over_1mm"] == 0
    low = np.array([0.1001, 0.2015])  # second wet cell 1.5 mm deeper
    r = cal.monotonicity(low, high, where)
    assert r["passed"] is False
    assert r["wet_cells_deeper_at_lower_rain_by_over_1mm"] == 1


def test_monotonicity_fails_over_1_mm_in_a_dry_cell_and_ignores_cells_left_out() -> None:
    high = np.array([0.0, 0.0])
    low = np.array([0.003, 0.5])
    r = cal.monotonicity(low, high, np.array([True, False]))
    assert r["passed"] is False
    assert r["cells"] == 1
    assert r["cells_deeper_at_lower_rain_by_over_1mm"] == 1
    assert r["wet_cells_deeper_at_lower_rain"] == 0
