"""FS4: the second reader of the MRMS radar rainfall.

Unit tests build small GRIB2 messages with ecCodes (scanning modes, longitudes beyond 180, the
missing codes); the window tests run on the cached Ida files and skip when they are absent.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

eccodes = pytest.importorskip("eccodes")  # the radar extra; CI installs it

from flood_lab import cache  # noqa: E402
from flood_lab.reference import mrms  # noqa: E402

END = datetime(2021, 9, 1, 18, tzinfo=UTC)


def _write(path_dir: Path, values: np.ndarray, scanning_mode: int, lat0: float, lon0: float):
    """A 3 x 4 grid at 0.01 degrees, first point (lat0, lon0), values in scan order."""
    handle = eccodes.codes_grib_new_from_samples("GRIB2")
    j_sign = 1 if scanning_mode & 0x40 else -1
    i_sign = -1 if scanning_mode & 0x80 else 1
    first_lat, first_lon = round(lat0 * 1e6), round(lon0 * 1e6)
    for key, value in [
        ("gridType", "regular_ll"),
        ("Ni", 4),
        ("Nj", 3),
        ("scanningMode", scanning_mode),
        ("latitudeOfFirstGridPoint", first_lat),
        ("longitudeOfFirstGridPoint", first_lon),
        ("latitudeOfLastGridPoint", first_lat + j_sign * 2 * 10000),
        ("longitudeOfLastGridPoint", first_lon + i_sign * 3 * 10000),
        ("iDirectionIncrement", 10000),
        ("jDirectionIncrement", 10000),
        ("discipline", 209),
        ("parameterCategory", 6),
        ("parameterNumber", 37),
        ("dataDate", 20210901),
        ("dataTime", 1800),
        ("decimalScaleFactor", 1),
    ]:
        eccodes.codes_set(handle, key, value)
    eccodes.codes_set_values(handle, values.astype(float).ravel())
    message = eccodes.codes_get_message(handle)
    eccodes.codes_release(handle)
    path = path_dir / "MRMS_MultiSensor_QPE_01H_Pass2_00.00_20210901-180000.grib2.gz"
    path.write_bytes(gzip.compress(message))
    return path


VALUES = np.arange(12, dtype=float).reshape(3, 4) / 10  # value 10*j + i in tenths, scan order


@pytest.mark.parametrize(
    ("mode", "lat0", "lon0"),
    [
        (0x00, 40.895, 285.805),  # i east, j south: the MRMS layout
        (0x40, 40.875, 285.805),  # j north
        (0x80, 40.895, 285.835),  # i west
        (0xC0, 40.875, 285.835),  # both
    ],
)
def test_scanning_modes_and_longitudes(tmp_path, mode, lat0, lon0):
    _write(tmp_path, VALUES, mode, lat0, lon0)
    lats = np.array([40.895, 40.885, 40.875])  # descending, as the loaded file
    lons = np.array([-74.195, -74.185, -74.175, -74.165])  # -180..180
    got = mrms.read_window(tmp_path, [END], lats, lons)[0]
    # expected: the scan-order value at the point whose centre is each (lat, lon)
    j_of = {0x00: [0, 1, 2], 0x40: [2, 1, 0], 0x80: [0, 1, 2], 0xC0: [2, 1, 0]}[mode]
    i_of = {0x00: [0, 1, 2, 3], 0x40: [0, 1, 2, 3], 0x80: [3, 2, 1, 0], 0xC0: [3, 2, 1, 0]}[mode]
    np.testing.assert_allclose(got, VALUES[np.ix_(j_of, i_of)], atol=1e-12)


def test_missing_codes_and_off_grid(tmp_path):
    values = VALUES.copy()
    values[0, 1], values[2, 3] = -1.0, -3.0
    _write(tmp_path, values, 0x00, 40.895, 285.805)
    lats = np.array([40.895, 40.875])
    lons = np.array([-74.195, -74.185, -74.165])
    got = mrms.read_window(tmp_path, [END], lats, lons)[0]
    assert np.isnan(got[0, 1]) and np.isnan(got[1, 2])
    assert got[0, 0] == pytest.approx(0.0) and got[1, 1] == pytest.approx(0.9)
    with pytest.raises(ValueError, match="longitude"):
        mrms.read_window(tmp_path, [END], lats, np.array([-74.19]))
    with pytest.raises(ValueError, match="latitude"):
        mrms.read_window(tmp_path, [END], np.array([40.8951]), lons)
    with pytest.raises(ValueError, match="latitude"):
        mrms.read_window(tmp_path, [END], np.array([40.905]), lons)  # outside the grid


def test_tolerance_is_below_one_packing_step():
    assert 2.0**-18 < mrms.TOLERANCE_MM < 2.0**-17 < 0.1


BASE = cache.root() / "f3" / "mrms"
RAW = BASE / "raw" / "ida_2021"
NC = BASE / "ida_2021.nc"
needs_cache = pytest.mark.skipif(not (RAW.is_dir() and NC.exists()), reason="no cached MRMS")


@pytest.fixture(scope="module")
def loaded():
    xr = pytest.importorskip("xarray")
    with xr.open_dataset(NC) as ds:
        return ds.load()


@needs_cache
def test_full_window_agrees():
    result = mrms.compare(RAW, NC)
    assert result["cells_differing"] == 0
    assert result["nan_mismatches"] == 0
    assert result["largest_difference_mm"] <= mrms.TOLERANCE_MM
    assert result["checksums_verified"] == result["time_stamps_checked"] == 17
    assert result["checksum_mismatches"] == []


@needs_cache
def test_shifted_hour_differs(tmp_path, loaded):
    faulty = loaded.copy(deep=True)
    faulty["precip"].values[:] = np.roll(loaded["precip"].values, 1, axis=0)
    path = tmp_path / "shifted.nc"
    faulty.to_netcdf(path)
    result = mrms.compare(RAW, path)
    assert result["cells_differing"] > 0
    assert result["largest_difference_mm"] > 1.0


@needs_cache
def test_one_cell_plus_one_mm_differs(tmp_path, loaded):
    faulty = loaded.copy(deep=True)
    faulty["precip"].values[5, 10, 20] += 1.0
    path = tmp_path / "plus.nc"
    faulty.to_netcdf(path)
    result = mrms.compare(RAW, path)
    assert result["cells_differing"] == 1
    assert result["largest_difference_mm"] == pytest.approx(1.0, abs=1e-5)


@needs_cache
def test_off_grid_coordinate_raises(loaded):
    times = [END]
    lats = loaded["lat"].values
    lons = loaded["lon"].values.copy()
    lons[3] += 0.004
    with pytest.raises(ValueError, match="not a grid point centre"):
        mrms.read_window(RAW, times, lats, lons)
