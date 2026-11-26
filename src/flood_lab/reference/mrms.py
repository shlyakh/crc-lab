"""Second reader of the MRMS radar rainfall for one event window (requirement FS4).

Route, chosen to share nothing with a loader built on GDAL and rasterio: the gzip files are
decompressed in memory with the standard library's ``gzip``, and each GRIB2 message is decoded by
ecCodes (``eccodes`` Python bindings); the grid is rebuilt from the message's own integer keys. The
loaded file is read only for its coordinates and its ``precip`` values.

Rules:

1. One file per hour, named ``MRMS_MultiSensor_QPE_01H_Pass2_00.00_YYYYMMDD-HHMMSS.grib2.gz``;
   the time in the name is the end of the hour, in UTC. Each file holds exactly one GRIB2 message,
   whose product must be discipline 209, category 6, parameter 37 (MultiSensor_QPE_01H_Pass2 in
   the NSSL table) and whose reference time (``dataDate``, ``dataTime``, with forecast time 0)
   must equal the time in the name; otherwise the reader raises.
2. The grid must be ``regular_ll``. Point (i, j), counted along the scan, has its centre at
   first point + i * Di (longitude) and first point -/+ j * Dj (latitude), computed in the
   message's integer subdivisions of a degree (``angleSubdivisions``) so no rounding enters.
   The scanning mode is read from the message: bit 1 (i negative), bit 2 (j positive) set the
   directions; bit 3 (j consecutive) and bit 4 (alternate rows) are not handled and raise.
3. Longitudes of the message are 0..360; a requested longitude is taken modulo 360 before it is
   matched. A requested pixel is the grid point whose centre lies within 1e-6 degrees of the
   requested latitude and longitude; a coordinate with no such point raises ``ValueError``.
4. Values are ecCodes' decoded values in mm, in float64. NaN where the message's bitmap marks a
   point missing, and where the decoded value is -1 (missing) or -3 (no coverage). The two codes
   and their meaning come from the NSSL MRMS GRIB2 table (cached as ``raw/mrms-tables.html``,
   sha256 in ``facts/rainfall-mrms.toml``), row "209 6 37 MultiSensor_QPE_01H_Pass2 60-min mm -1
   n/a -3". Any other negative value raises. In the Ida messages there is no bitmap and the
   reference value is 0 with decimal scale 1, so no negative value can be encoded at all.
5. The comparison is cell by cell over the loaded file's times, latitudes and longitudes. A cell
   differs when both are numbers and they differ by more than ``TOLERANCE_MM``; a NaN mismatch
   is a cell that is NaN on one side only. The tolerance holds only for the packing it was
   derived for (decimal scale 1, binary scale 0, integer reference value) and values below
   128 mm; ``compare`` raises otherwise.
6. Every raw file used is checked against the sha256 in the cached manifest.

Not checked: that the hour is an accumulation over the hour before the time stamp (the message
uses product template 0 with forecast time 0 and carries no statistical interval; the meaning
comes from the product name and the NSSL table); the values against gauges or any other source;
the grid outside the loaded window; the loaded file's attributes beyond units.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import eccodes
import numpy as np

from .. import cache

PRODUCT = (209, 6, 37)
NAME = re.compile(r"^MRMS_MultiSensor_QPE_01H_Pass2_00\.00_(\d{8})-(\d{6})\.grib2\.gz$")
#: NSSL MRMS table, row 209 6 37: Missing -1, Range Folded n/a, No Coverage -3
MISSING_CODES = (-1.0, -3.0)
MATCH_DEGREES = 1e-6

# Tolerance. In every Ida message the packing is grid_png, 16 bits, reference value R = 0,
# binary scale E = 0, decimal scale D = 1, so a stored value is (R + X * 2**E) / 10**D = X / 10
# with X an integer: exact multiples of 0.1 mm. The reader here keeps them in float64 (error near
# 1e-14 mm). The loaded file stores float32, so a correct loader can differ by
#   (a) rounding to float32: at most half a float32 spacing; below 128 mm the spacing is 2**-17,
#       so at most 2**-18 mm, and
#   (b) a decoder that multiplies by 10**-D held as float32 (0.1f = 0.1 * (1 + 1.49e-8)): at most
#       the value times that relative error, 128 * |float32(0.1) - 0.1| / 0.1 = 1.9e-6 mm.
# The sum, 5.72e-6 mm, is the smallest bound these two explain; one packing step is 0.1 mm, so any
# real decoding fault (a wrong step, hour or pixel) is four orders of magnitude larger.
VALUE_LIMIT_MM = 128.0
_F32_TENTH = float(np.float32(0.1))
TOLERANCE_MM = 2.0**-18 + VALUE_LIMIT_MM * abs(_F32_TENTH - 0.1) / 0.1


@dataclass(frozen=True)
class Grid:
    """A regular latitude-longitude grid as the message gives it, in integer subdivisions."""

    ni: int
    nj: int
    lat0: int
    lon0: int
    di: int
    dj: int
    subdivisions: int
    scanning_mode: int

    def indices(self, lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Row (j) and column (i) of each requested latitude and longitude (rules 2 and 3)."""
        if self.scanning_mode & 0x20 or self.scanning_mode & 0x10:
            raise ValueError(f"scanning mode {self.scanning_mode:#04x} is not handled")
        i_sign = -1 if self.scanning_mode & 0x80 else 1
        j_sign = 1 if self.scanning_mode & 0x40 else -1
        s = self.subdivisions
        rows = []
        for lat in np.asarray(lats, dtype=float):
            steps = (lat * s - self.lat0) / (j_sign * self.dj)
            j = int(np.rint(steps))
            centre = (self.lat0 + j_sign * j * self.dj) / s
            if not 0 <= j < self.nj or abs(centre - lat) > MATCH_DEGREES:
                raise ValueError(f"latitude {lat!r} is not a grid point centre")
            rows.append(j)
        cols = []
        for lon in np.asarray(lons, dtype=float):
            east = lon % 360.0
            steps = ((east * s - self.lon0) / (i_sign * self.di)) % (360 * s / self.di)
            i = int(np.rint(steps))
            centre = ((self.lon0 + i_sign * i * self.di) / s) % 360.0
            gap = abs((centre - east + 180.0) % 360.0 - 180.0)
            if not 0 <= i < self.ni or gap > MATCH_DEGREES:
                raise ValueError(f"longitude {lon!r} is not a grid point centre")
            cols.append(i)
        return np.array(rows, dtype=int), np.array(cols, dtype=int)


@dataclass(frozen=True)
class Field:
    """One decoded message: its end time, grid, packing and values as (j, i) along the scan."""

    end_time: datetime
    grid: Grid
    packing: dict[str, Any]
    values: np.ndarray


def _get(handle: Any, key: str) -> Any:
    return eccodes.codes_get(handle, key)


def decode(path: Path) -> Field:
    """Decode one ``.grib2.gz`` file (rules 1, 2 and 4)."""
    message = gzip.decompress(path.read_bytes())
    handle = eccodes.codes_new_from_message(message)
    try:
        if _get(handle, "totalLength") != len(message):
            raise ValueError(f"{path.name}: more than one GRIB message")
        if _get(handle, "edition") != 2:
            raise ValueError(f"{path.name}: not GRIB2")
        product = tuple(
            _get(handle, k) for k in ("discipline", "parameterCategory", "parameterNumber")
        )
        if product != PRODUCT:
            raise ValueError(f"{path.name}: product {product}, expected {PRODUCT}")
        if _get(handle, "gridType") != "regular_ll":
            raise ValueError(f"{path.name}: grid {_get(handle, 'gridType')}")
        if _get(handle, "forecastTime") != 0:
            raise ValueError(f"{path.name}: forecast time is not 0")
        date, hhmm = _get(handle, "dataDate"), _get(handle, "dataTime")
        end = datetime(date // 10000, date // 100 % 100, date % 100, hhmm // 100, hhmm % 100)
        end = end.replace(tzinfo=UTC)
        named = end_time_of(path)
        if named != end:
            raise ValueError(f"{path.name}: message time {end} differs from the name")
        subdivisions = _get(handle, "angleSubdivisions")
        if _get(handle, "basicAngleOfTheInitialProductionDomain") not in (0, 1):
            raise ValueError(f"{path.name}: basic angle is not 1 degree")
        grid = Grid(
            ni=_get(handle, "Ni"),
            nj=_get(handle, "Nj"),
            lat0=_get(handle, "latitudeOfFirstGridPoint"),
            lon0=_get(handle, "longitudeOfFirstGridPoint"),
            di=_get(handle, "iDirectionIncrement"),
            dj=_get(handle, "jDirectionIncrement"),
            subdivisions=subdivisions,
            scanning_mode=_get(handle, "scanningMode"),
        )
        packing = {
            k: _get(handle, k)
            for k in (
                "packingType",
                "referenceValue",
                "binaryScaleFactor",
                "decimalScaleFactor",
                "bitsPerValue",
                "bitmapPresent",
            )
        }
        values = np.asarray(eccodes.codes_get_values(handle), dtype=np.float64)
        if packing["bitmapPresent"]:
            values[values == _get(handle, "missingValue")] = np.nan
    finally:
        eccodes.codes_release(handle)
    if values.size != grid.ni * grid.nj:
        raise ValueError(f"{path.name}: {values.size} values for a {grid.nj} x {grid.ni} grid")
    for code in MISSING_CODES:
        values[values == code] = np.nan
    if np.any(values < 0):
        raise ValueError(f"{path.name}: negative value that is not a missing code")
    return Field(end, grid, packing, values.reshape(grid.nj, grid.ni))


def end_time_of(path: Path) -> datetime:
    """The end of the hour from a file name (rule 1)."""
    match = NAME.match(path.name)
    if not match:
        raise ValueError(f"not an MRMS Pass2 1-hour file name: {path.name}")
    return datetime.strptime(match[1] + match[2], "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def file_for(raw_dir: Path, end_time: datetime) -> Path:
    """The file in ``raw_dir`` whose name carries ``end_time`` (naive times are read as UTC)."""
    moment = end_time if end_time.tzinfo else end_time.replace(tzinfo=UTC)
    stamp = moment.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    path = Path(raw_dir) / f"MRMS_MultiSensor_QPE_01H_Pass2_00.00_{stamp}.grib2.gz"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _read(
    raw_dir: Path, end_times: list[datetime], lats: np.ndarray, lons: np.ndarray
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    out = np.empty((len(end_times), len(lats), len(lons)), dtype=np.float64)
    packing = []
    for t, end_time in enumerate(end_times):
        field = decode(file_for(raw_dir, end_time))
        rows, cols = field.grid.indices(lats, lons)
        out[t] = field.values[np.ix_(rows, cols)]
        packing.append(field.packing)
    return out, packing


def read_window(
    raw_dir: Path, end_times: list[datetime], lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Hourly rainfall in mm, shape (time, lat, lon), float64, NaN where missing (rules 1-4)."""
    return _read(raw_dir, end_times, lats, lons)[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checksums(raw_dir: Path, manifest: Path, names: list[str]) -> dict[str, Any]:
    """sha256 of each named file in ``raw_dir`` against the manifest entry of the same name."""
    entries = json.loads(Path(manifest).read_text())[Path(raw_dir).name]["files"]
    expected = {Path(e["file"]).name: e["sha256"] for e in entries}
    verified, mismatched = 0, []
    for name in names:
        if expected.get(name) == _sha256(Path(raw_dir) / name):
            verified += 1
        else:
            mismatched.append(name)
    return {"checksums_verified": verified, "checksum_mismatches": mismatched}


def compare_arrays(decoded: np.ndarray, loaded: np.ndarray) -> dict[str, Any]:
    """Counts of rule 5 for two arrays of the same shape."""
    if decoded.shape != loaded.shape:
        raise ValueError(f"shapes differ: {decoded.shape} and {loaded.shape}")
    loaded = loaded.astype(np.float64)
    nan_a, nan_b = np.isnan(decoded), np.isnan(loaded)
    both = ~nan_a & ~nan_b
    diff = np.abs(decoded - loaded)[both]
    return {
        "cells_compared": int(decoded.size),
        "cells_both_numbers": int(both.sum()),
        "cells_differing": int((diff > TOLERANCE_MM).sum()),
        "nan_mismatches": int((nan_a != nan_b).sum()),
        "nan_both": int((nan_a & nan_b).sum()),
        "largest_difference_mm": float(diff.max()) if diff.size else 0.0,
        "tolerance_mm": TOLERANCE_MM,
    }


def compare(raw_dir: Path, loaded_nc: Path, manifest: Path | None = None) -> dict[str, Any]:
    """Decode the window of ``loaded_nc`` from ``raw_dir`` and compare cell by cell (rules 5, 6).

    ``manifest`` defaults to ``manifest.json`` two levels above ``raw_dir``; its entry is the one
    named like ``raw_dir``.
    """
    import xarray as xr

    raw_dir = Path(raw_dir)
    with xr.open_dataset(loaded_nc) as ds:
        precip = ds["precip"]
        if precip.attrs.get("units") != "mm":
            raise ValueError(f"loaded units {precip.attrs.get('units')!r}, expected 'mm'")
        if precip.dims != ("time", "lat", "lon"):
            raise ValueError(f"loaded dims {precip.dims}")
        times = [
            datetime.fromisoformat(str(t)[:19]).replace(tzinfo=UTC)
            for t in np.datetime_as_string(ds["time"].values, unit="s")
        ]
        lats = ds["lat"].values.astype(np.float64)
        lons = ds["lon"].values.astype(np.float64)
        loaded = precip.values
    decoded, packing_list = _read(raw_dir, times, lats, lons)
    for packing in packing_list:
        if (
            packing["decimalScaleFactor"] != 1
            or packing["binaryScaleFactor"] != 0
            or float(packing["referenceValue"]) != int(packing["referenceValue"])
        ):
            raise ValueError(f"TOLERANCE_MM was not derived for packing {packing}")
    if np.nanmax(np.abs(decoded), initial=0.0) >= VALUE_LIMIT_MM:
        raise ValueError(f"a value reaches {VALUE_LIMIT_MM} mm; TOLERANCE_MM does not hold")
    names = [file_for(raw_dir, t).name for t in times]
    result = compare_arrays(decoded, loaded)
    result["time_stamps_checked"] = len(times)
    result["first_end_time"] = times[0].strftime("%Y-%m-%dT%H:%M:%SZ")
    result["last_end_time"] = times[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    result.update(
        verify_checksums(raw_dir, manifest or raw_dir.parents[1] / "manifest.json", names)
    )
    return result


def main() -> None:  # pragma: no cover - run on the real files by hand
    base = cache.root() / "f3" / "mrms"
    result = compare(base / "raw" / "ida_2021", base / "ida_2021.nc")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
