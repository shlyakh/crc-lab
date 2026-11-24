"""NEX-GDDP-CMIP6 annual extremes recomputed from NASA's NetCDF files.

The whole file is downloaded and checksummed (crc-sdk reads it by range requests and keeps no
checksum). It is opened with h5py; crc-sdk opens it with h5netcdf, which sits on the same
HDF5 library, so the two sides share the decompression but nothing above it. Attributes,
the calendar, the selection of grid cells and every rule that turns a year of daily values
into one annual value are applied here in plain Python, one grid cell at a time.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ._retry import again

ARCHIVE = "https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com/NEX-GDDP-CMIP6"
USER_AGENT = "data-source-check"
#: recipe -> (variable, unit the file must declare, unit of the result)
RECIPES = {
    "txx": ("tasmax", "K", "degC"),
    "tnn": ("tasmin", "K", "degC"),
    "rx1day": ("pr", "kg m-2 s-1", "mm/day"),
    "rx5day": ("pr", "kg m-2 s-1", "mm"),
}


@dataclass(frozen=True)
class Rules:
    """The rules as crc-sdk's documentation and code state them (defaults: crc-sdk 0.11)."""

    kelvin_offset: float = -273.15
    seconds_per_day: float = 86400.0
    minimum_valid_fraction: float = 0.9
    window_days: int = 5  # rx5day
    half_cell_margin: bool = (
        True  # a cell is selected when the box, grown by half a cell, holds its centre
    )
    #: rx5day completeness counted on five-day windows (crc-sdk 1.0) rather than on days
    count_windows: bool = False


#: the rules of crc-sdk 1.0 by default: every day (every five-day window) of the year present
RULES_1_0 = Rules(minimum_valid_fraction=1.0, count_windows=True)


def url(variable: str, model: str, scenario: str, member: str, grid: str, year: int,
        version: str) -> str:  # fmt: skip
    suffix = "" if version == "1.0" else f"_v{version}"
    name = f"{variable}_day_{model}_{scenario}_{member}_{grid}_{year}{suffix}.nc"
    return f"{ARCHIVE}/{model}/{scenario}/{member}/{variable}/{name}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status(address: str) -> int:
    request = Request(address, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=60) as response:
            return int(response.status)
    except HTTPError as error:
        return int(error.code)


def _download(address: str, cache_dir: Path, *, live: bool) -> dict[str, Any]:
    """Fetch one file whole, or reuse the cached copy. A 404 is recorded, not raised."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / address.rsplit("/", 1)[-1]
    sidecar = path.with_suffix(".json")
    if sidecar.exists():
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if record["missing"] or path.exists():
            if not record["missing"] and path.stat().st_size != record["bytes"]:
                raise RuntimeError(f"cached reference copy of {path.name} has changed on disk")
            return record | {"path": str(path)}
    if not live:
        raise FileNotFoundError(f"no cached reference copy of {path.name}; run with --live")
    record: dict[str, Any] = {
        "url": address,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "missing": False,
    }
    fd, name = tempfile.mkstemp(dir=cache_dir, prefix="download-", suffix=".tmp")
    temp = Path(name)
    try:
        try:
            request = Request(address, headers={"User-Agent": USER_AGENT})
            with os.fdopen(fd, "wb") as target, urlopen(request, timeout=600) as response:
                while chunk := response.read(1 << 20):
                    target.write(chunk)
                record["etag"] = response.headers.get("ETag")
                record["last_modified"] = response.headers.get("Last-Modified")
                length = response.headers.get("Content-Length")
            record["bytes"] = temp.stat().st_size
            if length is not None and int(length) != record["bytes"]:
                raise RuntimeError(f"incomplete download of {path.name}")
            record["sha256"] = sha256(temp)
            os.replace(temp, path)
        except HTTPError as error:
            if error.code != 404:
                raise
            record["missing"] = True
    finally:
        temp.unlink(missing_ok=True)
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record | {"path": str(path)}


def download(address: str, cache_dir: Path, *, live: bool) -> dict[str, Any]:
    """As ``_download``, tried again when the connection fails part-way."""
    return again(lambda: _download(address, cache_dir, live=live))


def bucket() -> str:
    """The bucket's address, from ``ARCHIVE`` (read at call time, so tests can move it)."""
    return ARCHIVE.rsplit("/", 1)[0]


def listing(prefix: str) -> dict[str, dict[str, Any]]:
    """Every object under ``prefix`` in NASA's bucket (S3 ListObjectsV2), page by page."""
    import xml.etree.ElementTree as ET
    from urllib.parse import quote

    out: dict[str, dict[str, Any]] = {}
    token = None
    while True:
        address = f"{bucket()}/?list-type=2&prefix={quote(prefix, safe='')}"
        if token:
            address += f"&continuation-token={quote(token, safe='')}"
        request = Request(address, headers={"User-Agent": USER_AGENT})
        page = again(lambda r=request: urlopen(r, timeout=120).read())
        tree = ET.fromstring(page)
        for item in tree.iter():
            if item.tag.rsplit("}", 1)[-1] != "Contents":
                continue
            fields = {child.tag.rsplit("}", 1)[-1]: child.text for child in item}
            out[fields["Key"]] = {"etag": fields.get("ETag"), "bytes": int(fields.get("Size") or 0),
                                  "last_modified": fields.get("LastModified")}  # fmt: skip
        token = next((i.text for i in tree.iter() if i.tag.endswith("NextContinuationToken")), None)
        truncated = next((i.text for i in tree.iter() if i.tag.endswith("IsTruncated")), "false")
        if truncated != "true" or not token:
            return out


def folder(variable: str, model: str, scenario: str, member: str) -> str:
    """The listing prefix of one variable, model, scenario and member."""
    return f"{ARCHIVE.rsplit('/', 1)[-1]}/{model}/{scenario}/{member}/{variable}/"


def file_version(name: str) -> tuple[int, str] | None:
    """(year, version) from a file name: no suffix is version 1.0, ``_v1.1`` is 1.1."""
    import re

    match = re.search(r"_(\d{4})(?:_v(\d+(?:\.\d+)*))?\.nc$", name)
    return None if match is None else (int(match[1]), match[2] or "1.0")


def versions_by_year(keys: Any) -> dict[int, list[str]]:
    """The file versions present for each year, oldest first."""
    out: dict[int, list[str]] = {}
    for key in keys:
        found = file_version(key.rsplit("/", 1)[-1])
        if found is not None:
            out.setdefault(found[0], []).append(found[1])
    number = lambda v: tuple(int(p) for p in v.split("."))  # noqa: E731
    return {year: sorted(set(v), key=number) for year, v in sorted(out.items())}


class _Ranges:
    """A remote file read by HTTP range requests, enough for h5py to read a header."""

    def __init__(self, address: str) -> None:
        request = Request(address, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=60) as response:
            self.size = int(response.headers["Content-Length"])
        self.address, self.position = address, 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self.position, 2: self.size}[whence]
        self.position = base + offset
        return self.position

    def tell(self) -> int:
        return self.position

    def read(self, size: int = -1) -> bytes:
        end = self.size if size is None or size < 0 else min(self.size, self.position + size)
        if end <= self.position:
            return b""
        headers = {"User-Agent": USER_AGENT, "Range": f"bytes={self.position}-{end - 1}"}
        request = Request(self.address, headers=headers)
        data = again(lambda: urlopen(request, timeout=60).read())
        self.position += len(data)
        return data

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def header(address: str) -> dict[str, Any]:
    """The global attributes and the time calendar of a remote file, without downloading it."""
    import h5py

    with h5py.File(_Ranges(address), "r") as file:
        return {
            "attrs": {key: _text(value) for key, value in file.attrs.items()},
            "calendar": _text(file["time"].attrs.get("calendar", "standard")),
        }


def cell_id(latitude: float, longitude: float) -> int:
    """The H3 cell (resolution 9) that holds a grid cell's centre."""
    import h3

    return int(h3.str_to_int(h3.latlng_to_cell(latitude, longitude, 9)))


def _text(value: Any) -> str:
    """An attribute as text, whatever form the HDF5 layer hands it over in."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "tolist"):
        value = value.tolist()
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
    return str(value)


#: CF calendar names that mean the same thing (for dates after 1582)
CALENDAR_ALIASES = {
    "standard": "proleptic_gregorian",
    "gregorian": "proleptic_gregorian",
    "365_day": "noleap",
    "366_day": "all_leap",
}


def calendar_name(calendar: str) -> str:
    """One name per calendar, so that aliases compare equal."""
    return CALENDAR_ALIASES.get(calendar, calendar)


def _days_in_year(calendar: str, year: int) -> int:
    if calendar in ("noleap", "365_day"):
        return 365
    if calendar == "360_day":
        return 360
    if calendar in ("all_leap", "366_day"):
        return 366
    if calendar in ("standard", "gregorian", "proleptic_gregorian"):
        return 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    raise ValueError(f"calendar {calendar!r} is not handled by the reference reader")


def _day_number(calendar: str, year: int, month: int, day: int) -> int:
    """Days since year 1, January 1, in the given calendar."""
    if calendar in ("standard", "gregorian", "proleptic_gregorian"):
        return date(year, month, day).toordinal() - 1
    if calendar == "360_day":
        return (year - 1) * 360 + (month - 1) * 30 + (day - 1)
    lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if calendar in ("all_leap", "366_day"):
        lengths[1] = 29
    return (year - 1) * sum(lengths) + sum(lengths[: month - 1]) + (day - 1)


def read_box(path: Path, variable: str, bounds: tuple[float, float, float, float],
             year: int, rules: Rules | None = None) -> dict[str, Any]:  # fmt: skip
    """The file's attributes and, for the grid cells the box selects, a year of daily values."""
    import h5py

    rules = rules or Rules()
    with h5py.File(path, "r") as file:
        attrs = {key: _text(value) for key, value in file.attrs.items()}
        data = file[variable]
        var_attrs = {
            key: _text(value)
            for key, value in data.attrs.items()
            if key not in ("DIMENSION_LIST", "REFERENCE_LIST")
        }
        dims = [_text(file[ref[0]].name).lstrip("/") for ref in data.attrs["DIMENSION_LIST"]]
        if dims != ["time", "lat", "lon"]:
            raise ValueError(f"{path.name}: dimensions are {dims}, expected time, lat, lon")
        lat = [float(v) for v in file["lat"][:]]
        lon = [float(v) for v in file["lon"][:]]
        time = file["time"]
        calendar = _text(time.attrs["calendar"])
        time_units = _text(time.attrs["units"])
        stamps = [float(v) for v in time[:]]
        fills = set()
        for key in ("_FillValue", "missing_value"):
            if key in data.attrs:
                fills.update(float(v) for v in data.attrs[key].reshape(-1))
        half_lat = abs(lat[1] - lat[0]) / 2 if rules.half_cell_margin else 0.0
        half_lon = abs(lon[1] - lon[0]) / 2 if rules.half_cell_margin else 0.0
        lon180 = [((v + 180.0) % 360.0) - 180.0 for v in lon]
        west, south, east, north = bounds
        rows = [i for i, v in enumerate(lat) if south - half_lat <= v <= north + half_lat]
        cols = sorted(
            (j for j, v in enumerate(lon180) if west - half_lon <= v <= east + half_lon),
            key=lambda j: lon180[j],
        )
        if not rows or not cols:
            raise ValueError("the box selects no grid cell")
        if cols != list(range(cols[0], cols[-1] + 1)) or rows != list(range(rows[0], rows[-1] + 1)):
            raise ValueError("the reference reader handles a box that does not cross the seam")
        block = data[:, rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
        dtype = str(data.dtype)
        values = block.astype("float64").tolist()  # the stored float32 values, exactly

    if not time_units.startswith("days since "):
        raise ValueError(f"{path.name}: time units are {time_units!r}")
    origin = time_units.removeprefix("days since ").split()[0]
    oy, om, od = (int(part) for part in origin.split("-"))
    start = _day_number(calendar, year, 1, 1)
    offsets = [math.floor(_day_number(calendar, oy, om, od) + stamp) - start for stamp in stamps]
    return {
        "attrs": attrs,
        "variable_attrs": var_attrs,
        "dtype": dtype,
        "calendar": calendar,
        "days_expected": _days_in_year(calendar, year),
        "day_offsets": offsets,  # position of each time step within the year, 0 = January 1
        "lat": [lat[i] for i in rows],
        "lon": [lon180[j] for j in cols],
        "row_index": list(rows),  # position of each selected row and column in the file
        "column_index": list(cols),
        "half_cell": (abs(lat[1] - lat[0]) / 2, abs(lon[1] - lon[0]) / 2),
        "fills": sorted(fills),
        "values": values,  # [time][row][column]
        "grid": {"rows": len(lat), "columns": len(lon), "step_lat": abs(lat[1] - lat[0]),
                 "step_lon": abs(lon[1] - lon[0])},
    }  # fmt: skip


def annual_value(series: list[float | None], recipe: str, days_expected: int,
                 rules: Rules | None = None) -> float | None:  # fmt: skip
    """One grid cell's year of daily values (None = missing), reduced as the recipe states."""
    rules = rules or Rules()
    valid = sum(1 for value in series if value is not None)
    needed = max(1, math.ceil(rules.minimum_valid_fraction * days_expected - 1e-9))
    if valid < needed:
        return None
    if recipe in ("txx", "tnn"):
        converted = [None if v is None else v + rules.kelvin_offset for v in series]
    else:
        converted = [None if v is None else v * rules.seconds_per_day for v in series]
    if recipe == "rx5day":
        width = rules.window_days
        if len(converted) < width:
            return None
        sums = []
        for first in range(len(converted) - width + 1):
            window = converted[first : first + width]
            if None not in window:
                total = 0.0
                for value in window:  # summed in order
                    total += value  # type: ignore[operator]
                sums.append(total)
        return max(sums) if sums else None
    present = [value for value in converted if value is not None]
    return min(present) if recipe == "tnn" else max(present)


def annual_rows(box: dict[str, Any], recipe: str, year: int,
                rules: Rules | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """One row per grid cell that has an annual value, ordered south to north, west to east."""
    fills = set(box["fills"])
    expected = box["days_expected"]
    out = []
    for i, lat in enumerate(box["lat"]):
        for j, lon in enumerate(box["lon"]):
            series: list[float | None] = [None] * expected
            for step, offset in enumerate(box["day_offsets"]):
                value = box["values"][step][i][j]
                if 0 <= offset < expected and value not in fills and math.isfinite(value):
                    series[offset] = value
            value = annual_value(series, recipe, expected, rules)
            if value is not None:
                out.append({"year": year, "latitude": lat, "longitude": lon, "value": value})
    return out


def annual_outcome(series: list[float | None], recipe: str, days_expected: int,
                   rules: Rules | None = None) -> dict[str, Any]:  # fmt: skip
    """One grid cell's year: the annual value (None when too incomplete) and its coverage.

    Coverage counts days, or with ``count_windows`` the five-day windows for rx5day, and the
    value is kept when the share present reaches ``minimum_valid_fraction``.
    """
    rules = rules or Rules()
    if recipe in ("txx", "tnn"):
        converted = [None if v is None else v + rules.kelvin_offset for v in series]
    else:
        converted = [None if v is None else v * rules.seconds_per_day for v in series]
    if recipe == "rx5day" and rules.count_windows:
        width = rules.window_days
        candidates: list[float | None] = []
        for first in range(len(converted) - width + 1):
            window = converted[first : first + width]
            total = None
            if None not in window:
                total = 0.0
                for value in window:  # summed in order
                    total += value  # type: ignore[operator]
            candidates.append(total)
        valid, expected = sum(1 for c in candidates if c is not None), len(candidates)
        present = [c for c in candidates if c is not None]
        enough = bool(present) and valid / expected >= rules.minimum_valid_fraction
        return {"value": max(present) if enough else None, "valid": valid, "expected": expected}
    valid = sum(1 for v in series if v is not None)
    value = annual_value(series, recipe, days_expected, rules)
    if value is not None and valid / days_expected < rules.minimum_valid_fraction:
        value = None  # annual_value rounds the count up; here the share itself is compared
    return {"value": value, "valid": valid, "expected": days_expected}


def annual_cells(box: dict[str, Any], recipe: str, year: int,
                 rules: Rules | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """One row per grid cell of the box, with or without a value, south to north and then in
    the file's column order, with the cell's edges, its place in the file and its H3 cell."""
    fills = set(box["fills"])
    expected = box["days_expected"]
    half_lat, half_lon = box["half_cell"]
    out = []
    for i, lat in enumerate(box["lat"]):
        for j, lon in enumerate(box["lon"]):
            series: list[float | None] = [None] * expected
            for step, offset in enumerate(box["day_offsets"]):
                value = box["values"][step][i][j]
                if 0 <= offset < expected and value not in fills and math.isfinite(value):
                    series[offset] = value
            outcome = annual_outcome(series, recipe, expected, rules)
            out.append({
                "year": year, "row": box["row_index"][i], "column": box["column_index"][j],
                "latitude": lat, "longitude": lon,
                "west": lon - half_lon, "south": lat - half_lat,
                "east": lon + half_lon, "north": lat + half_lat,
                "cell_id": cell_id(lat, lon), **outcome,
            })  # fmt: skip
    return out
