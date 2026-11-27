"""Rules BD-1 to BD-5 (docs/flood/loss-rules.md): the depth a building curve is read at."""

from __future__ import annotations

import numpy as np
import pytest

from flood_lab.risk.building_depth import Case, curve_depth

FT = 0.3048
LOW, HIGH = -4 * FT, 24 * FT


def _one(depth: float, ffh: float, basement: str) -> tuple[float, Case]:
    at, case = curve_depth(np.array([depth]), np.array([ffh]), np.array([basement]), LOW, HIGH)
    return float(at[0]), Case(int(case[0]))


def test_depth_above_first_floor() -> None:  # BD-2
    at, case = _one(1.0, 0.25, "N")
    assert case is Case.READ and at == pytest.approx(0.75)


def test_dry_building_has_no_loss_even_with_a_basement_or_no_height() -> None:  # BD-1
    assert _one(0.0, 2.5, "Y")[1] is Case.NO_LOSS
    assert _one(0.0, float("nan"), "")[1] is Case.NO_LOSS


def test_below_the_lowest_point() -> None:  # BD-3
    at, case = _one(0.3, 2.5, "Y")  # 0.3 - 2.5 = -2.2 m, below -4 ft
    assert case is Case.READ and at == pytest.approx(LOW)
    assert _one(0.3, 2.5, "N")[1] is Case.NO_LOSS
    assert _one(0.3, 2.5, "")[1] is Case.FAILED
    # inside the curve, an unknown flag does not matter here (it does for the curve's choice)
    assert _one(1.0, 0.5, "")[1] is Case.READ


def test_above_the_highest_point_and_no_height_fail() -> None:  # BD-4, BD-5
    assert _one(8.0, 0.2, "N")[1] is Case.FAILED
    at, case = _one(1.0, float("nan"), "Y")
    assert case is Case.FAILED and np.isnan(at)


def test_bad_inputs_stop() -> None:
    with pytest.raises(ValueError, match="basement"):
        _one(1.0, 0.5, "maybe")
    with pytest.raises(ValueError, match="shape"):
        curve_depth(np.zeros(2), np.zeros(1), np.array(["N"]), LOW, HIGH)
