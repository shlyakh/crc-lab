"""Pure helpers of the F4 check (``flood_lab.checks.f4_catalogue``), offline, synthetic arrays."""

from __future__ import annotations

import numpy as np
import pytest

from flood_lab.checks import f4_catalogue as f4
from flood_lab.hazard import catalogue


def test_weibull_positions():
    v, t = f4.weibull_positions([3.0, 1.0, 2.0])
    assert v.tolist() == [3.0, 2.0, 1.0]
    assert t.tolist() == pytest.approx([4.0, 2.0, 4 / 3])


def test_rank_positions_and_value_at_follow_rainyday():
    values = np.arange(1, 1001, dtype=float)  # 1000 years, largest 1000
    v, t = f4.rank_positions(values)
    assert t[0] == 1000 and t[-1] == 1
    assert f4.value_at(values, 2) == 501.0  # rank 500 of 1000
    assert f4.value_at(values, 100) == 991.0  # rank 10
    assert f4.value_at(values, 1000) == 1000.0
    with pytest.raises(ValueError):
        f4.value_at(values, 5000)


def test_band_rows_inside_and_below():
    values = np.arange(1, 1001, dtype=float)
    band = {2.0: (500.0, 490.0, 510.0), 5.0: (900.0, 850.0, 950.0)}
    rows = f4.band_rows(values, band, years=(2, 5))
    assert rows[0]["inside"] and rows[0]["catalogue_mm"] == 501.0
    assert not rows[1]["inside"] and rows[1]["catalogue_mm"] == 801.0
    assert f4._where(rows[1]) == "below"


def test_non_decreasing_cells():
    raw = np.array([[0.0, 0.2, 0.0], [0.1, 0.1, 0.0], [0.3, 0.4, 0.0]])
    assert f4.non_decreasing_cells(raw).tolist() == [True, False, True]
    # agrees with the clean-up's count of cells changed
    _, changed = catalogue.make_non_decreasing(raw)
    assert changed == int((~f4.non_decreasing_cells(raw)).sum())


def test_depth_at_output_is_non_decreasing():
    rng = np.random.default_rng(1)
    depth = rng.gamma(0.5, 0.2, size=(40, 300))
    w = np.full(40, 1000 / 40)
    raw = catalogue.depth_at(depth, w, 1000)
    assert f4.non_decreasing_cells(raw).all()


def _selection():
    return catalogue.select(1000)


def test_progress_and_interim():
    sel = _selection()
    t1 = [x["label"] for x in sel if x["stratum"] == "T1"]
    one_each = {next(x["label"] for x in sel if x["stratum"] == s) for s in ("T1", "T2", "T3")}
    prog = f4.stratum_progress(sel, one_each, 1000)
    assert [p["finished"] for p in prog] == [1, 1, 1]
    assert [p["runs"] for p in prog] == [30, 60, 60]
    assert f4.is_interim(sel, one_each, 1000)
    assert catalogue.covered_years(sel, one_each, 1000) == 1000
    only_t1 = set(t1)
    assert f4.stratum_progress(sel, only_t1, 1000)[0]["complete"]
    assert catalogue.covered_years(sel, only_t1, 1000) == 30
    everything = {x["label"] for x in sel}
    assert not f4.is_interim(sel, everything, 1000)


def test_finished_labels_needs_balance_and_peak(tmp_path):
    for label, files in (
        ("cat_r0001", ("balance.json", "zsmax.tif")),
        ("cat_r0002", ("zsmax.tif",)),  # still running or stopped
        ("cat_r0003", ()),
    ):
        (tmp_path / label).mkdir()
        for f in files:
            (tmp_path / label / f).write_text("x")
    labels = ["cat_r0003", "cat_r0001", "cat_r0002", "cat_r0004"]
    assert f4.finished_labels(labels, tmp_path) == ["cat_r0001"]


def test_counts_wet():
    assert f4.counts_wet([0.0, 0.05, 0.29, 0.3, 1.0]) == {"0.05": 4, "0.3": 2}


def test_no_flood_marks_dry_storms_and_storms_under_the_allowance():
    base = {"rain_mm_per_h": 40.0, "allowance_mm_per_h": 30.0, "wet_cells_005": 10}
    assert not f4.no_flood(base)
    assert f4.no_flood(base | {"wet_cells_005": 0})
    assert f4.no_flood(base | {"rain_mm_per_h": 28.2})
    assert f4.no_flood(base | {"rain_mm_per_h": 30.0})
    assert not f4.no_flood(base | {"rain_mm_per_h": None})
