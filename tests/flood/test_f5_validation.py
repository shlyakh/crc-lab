"""F5: helpers of ``flood_lab.checks.f5_validation`` and the deliberate-fault tests of FS4."""

from __future__ import annotations

import math

import numpy as np
import pytest

from flood_lab import paths
from flood_lab.checks import f5_validation as f5
from flood_lab.domain import GRID
from flood_lab.sources import usgs_hwm


def test_error_stats() -> None:
    s = f5.error_stats([0.1, -0.3, None, float("nan")])
    assert s["n"] == 2
    assert s["bias_m"] == -0.1
    assert s["rmse_m"] == round(math.sqrt((0.01 + 0.09) / 2), 3)
    assert s["mae_m"] == 0.2
    assert f5.error_stats([None])["rmse_m"] is None


def test_pixel_of_and_near_max() -> None:
    assert f5.pixel_of(GRID.west + 0.5, GRID.north - 0.5) == (0, 0)
    assert f5.pixel_of(GRID.west + 12.3, GRID.north - 7.9) == (7, 12)
    with pytest.raises(ValueError):
        f5.pixel_of(GRID.west - 1, GRID.north - 1)
    values = np.full((40, 40), np.nan)
    values[20, 20] = 0.2  # pixel centre 0.5 m from the point
    values[20, 31] = 0.9  # 11 m east: outside 10 m
    x, y = GRID.west + 20.5, GRID.north - 20.0
    assert f5.near_max(values, x, y, 10.0) == 0.2
    assert f5.near_max(values, x, y, 12.0) == 0.9


def test_site_means_and_summary_leave_flagged_marks_out() -> None:
    rows = [
        {"site_no": "A", "level_error_m": 0.2, "depth_error_m": 0.1, "flags": []},
        {"site_no": "A", "level_error_m": 0.4, "depth_error_m": None, "flags": []},
        {"site_no": "B", "level_error_m": None, "depth_error_m": -0.5, "flags": ["x"]},
    ]
    assert f5.site_means(rows, "level_error_m") == [pytest.approx(0.3), None]
    s = f5.fv1_summary(rows)
    assert s["all"]["depth_per_mark"]["n"] == 2
    assert s["unflagged"]["marks"] == 2 and s["unflagged"]["sites"] == 1
    assert s["unflagged"]["level_per_site"]["bias_m"] == 0.3


def test_fv4_statement() -> None:
    assert "does not support substation-level" in f5.fv4_statement(0.51)
    assert "not required" in f5.fv4_statement(0.5)
    assert "cannot be judged" in f5.fv4_statement(None)


def test_mark_flags() -> None:
    mark = {"quality": "Poor: +/- 0.40 ft", "uncertainty_m": 0.1524}
    flags = f5.mark_flags(mark, ["pit in the cell"], True, False)
    assert flags == [
        "cell not read: pit in the cell",
        "pixel inside a building footprint",
        "quality Poor: +/- 0.40 ft",
        "survey uncertainty 0.1524 m",
    ]
    assert f5.mark_flags({"quality": "Good", "uncertainty_m": 0.0305}, [], False, False) == []


def test_compare_rain_rules() -> None:
    a = np.array([[[1.0, np.nan], [2.0, 3.0]]])
    assert f5.compare_rain(a, a.copy(), 1e-6)["outcome"] == "confirmed"
    b = a.copy()
    b[0, 0, 1] = 0.0
    assert f5.compare_rain(a, b, 1e-6)["nan_mismatch"] == 1
    for broken in f5.rain_faults(np.arange(8.0).reshape(2, 2, 2)).values():
        assert f5.compare_rain(np.arange(8.0).reshape(2, 2, 2), broken, 1e-6)["outcome"] == (
            "differs"
        )


def test_height_in_feet_fault_is_caught_by_the_table_rule() -> None:
    rows = [
        {
            "hwm_id": 1,
            "site_no": "A",
            "longitude": -73.9,
            "latitude": 40.7,
            "easting_m": 1.0,
            "northing_m": 2.0,
            "vertical_datum": "NAVD88",
            "elev_navd88_m": 3.0,
            "height_above_ground_m": 0.3048,
            "uncertainty_m": None,
            "quality": "Good",
            "survey_date": "9/7/2021",
            "in_square": True,
        }
    ]
    assert f5.compare_marks(rows, rows)["outcome"] == "confirmed"
    broken = f5.with_height_in_feet(rows)
    assert broken[0]["height_above_ground_m"] == 1.0
    assert rows[0]["height_above_ground_m"] == 0.3048  # the original is untouched
    assert f5.compare_marks(broken, rows)["outcome"] == "differs"


# --- FS4 against the real cache and the second readers -------------------------------------------

MARKS = paths.CACHE / usgs_hwm.FILE
MRMS_NC = paths.CACHE / f5.MRMS_LOADED
MRMS_RAW = paths.CACHE / f5.MRMS_RAW


@pytest.fixture(scope="module")
def loaded_marks() -> list[dict]:
    if not MARKS.exists():
        pytest.skip("high-water marks not in the cache")
    return usgs_hwm.as_rows(usgs_hwm.marks(MARKS))


def test_second_reader_marks_confirms_and_catches_feet(loaded_marks) -> None:
    reader = pytest.importorskip("flood_lab.reference.usgs_hwm")
    other = reader.marks(MARKS)
    assert f5.compare_marks(loaded_marks, other)["outcome"] == "confirmed"
    assert f5.compare_marks(f5.with_height_in_feet(loaded_marks), other)["outcome"] == "differs"


@pytest.fixture(scope="module")
def rain():
    if not (MRMS_NC.exists() and MRMS_RAW.is_dir()):
        pytest.skip("MRMS window not in the cache")
    reader = pytest.importorskip("flood_lab.reference.mrms")
    from datetime import UTC

    import pandas as pd
    import xarray as xr

    with xr.open_dataset(MRMS_NC, engine="h5netcdf") as ds:
        loaded = ds["precip"].values.astype("float64")
        times = [t.replace(tzinfo=UTC) for t in pd.to_datetime(ds["time"].values).to_pydatetime()]
        lats, lons = ds["lat"].values, ds["lon"].values
    other = np.asarray(reader.read_window(MRMS_RAW, times, lats, lons))
    return loaded, other, float(reader.TOLERANCE_MM)


def test_second_reader_mrms_confirms(rain) -> None:
    loaded, other, tolerance = rain
    assert f5.compare_rain(loaded, other, tolerance)["outcome"] == "confirmed"


@pytest.mark.parametrize("fault", ["hours shifted by one", "one cell plus 1 mm"])
def test_second_reader_mrms_catches_a_fault(rain, fault: str) -> None:
    loaded, other, tolerance = rain
    broken = f5.rain_faults(loaded)[fault]
    assert f5.compare_rain(broken, other, tolerance)["outcome"] == "differs"
