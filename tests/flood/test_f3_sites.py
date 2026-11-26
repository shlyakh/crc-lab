"""F3 follow-up: helpers of the two lead sites (``flood_lab.checks.f3_sites``), small arrays."""

from __future__ import annotations

import numpy as np
import pytest

from flood_lab.checks import f3_sites as fs
from flood_lab.hazard import at_assets


def test_max_window_sums_takes_the_wettest_consecutive_hours() -> None:
    rates = [0.0, 4.0, 60.0, 30.0, 1.0]
    assert fs.max_window_sums(rates, 1) == 60.0
    assert fs.max_window_sums(rates, 2) == 90.0
    assert fs.max_window_sums(rates, 3) == 94.0
    assert fs.max_window_sums([5.0], 3) == 5.0


ROW = {"1": {"depth": "1.09"}, "2": {"depth": "1.29"}, "5": {"depth": "1.63"}}


def test_place_and_years_text() -> None:
    labels = ["1", "2", "5"]
    assert fs.years_text(fs.place(1.5, ROW, labels)) == "2-5 yr"
    assert fs.years_text(fs.place(1.0, ROW, labels)) == "under 1 yr"
    assert fs.years_text(fs.place(2.0, ROW, labels)) == "over 5 yr"


def test_lead_reading_takes_the_depth_exceeded_on_25_pixels() -> None:
    depth = np.zeros((10, 10))
    depth[:3, :] = 0.4  # 30 pixels at 0.4 m
    depth[0, 0] = 0.9
    level = depth + 2.0
    inside = np.ones_like(depth, dtype=bool)
    inside[9, 9] = False
    r = fs.lead_reading(depth, level, inside)
    assert r["depth_on_25m2_m"] == 0.4
    assert r["max_depth_m"] == 0.9
    assert r["area_ge_030_m2"] == 30
    assert r["meets_lead_rule"] is True
    assert r["peak_level_navd88_m"] == pytest.approx(2.4)
    assert len(r["pixels"]) == at_assets.LEAD_AREA_M2
    assert r["depth_on_25m2_ft"] == round(0.4 / 0.3048, 2)


def test_lead_reading_skips_pixels_not_read() -> None:
    depth = np.full((10, 10), np.nan)
    r = fs.lead_reading(depth, depth, np.ones((10, 10), dtype=bool))
    assert r["depth_on_25m2_m"] is None


def test_non_decreasing_allows_1_mm() -> None:
    assert fs.non_decreasing([0.2, 0.3, 0.2995])
    assert not fs.non_decreasing([0.2, 0.3, 0.298])
    assert fs.non_decreasing([None, 0.1])
