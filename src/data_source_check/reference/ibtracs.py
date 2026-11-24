"""IBTrACS read from NOAA's CSV files with the standard library only.

This is the independent side of the comparison: it must not import the framework under
test, nor pyarrow. The rules applied to each value are arguments so that a test can make
one of them deliberately wrong. One library is shared with the framework: h3, for the H3
cell of a point (through its string interface; the framework uses the integer one).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import struct
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ._retry import again

ROOT = (
    "https://www.ncei.noaa.gov/data/"
    "international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv"
)
USER_AGENT = "data-source-check"

Row = list[str | None]


#: NOAA's directory spells one file name in capitals; every other name is the subset's own.
FILE_NAMES = {"active": "ACTIVE"}


def url(subset: str) -> str:
    """The address of a subset's file, with the name as NOAA's directory spells it."""
    return f"{ROOT}/ibtracs.{FILE_NAMES.get(subset, subset)}.list.v04r01.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status(subset: str) -> int:
    """HTTP status of a HEAD request for the subset's file."""
    request = Request(url(subset), method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=60) as response:
            return int(response.status)
    except HTTPError as error:
        return int(error.code)


def directory_listing() -> list[str]:
    """File names in NOAA's CSV directory (from its HTML index)."""
    request = Request(f"{ROOT}/", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8", "replace")
    names = []
    for part in html.split('href="')[1:]:
        name = part.split('"', 1)[0]
        if name.endswith(".csv"):
            names.append(name)
    return sorted(set(names))


def _download(subset: str, cache_dir: Path, *, live: bool) -> dict[str, Any]:
    """Fetch the subset's file (``live``) or reuse the cached copy; return its provenance."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{subset}.csv"
    sidecar = cache_dir / f"{subset}.json"
    if not live:
        if not (path.exists() and sidecar.exists()):
            raise FileNotFoundError(
                f"no cached reference copy of IBTrACS {subset}; run with --live"
            )
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if sha256(path) != record["sha256"]:
            raise RuntimeError(f"cached reference copy of IBTrACS {subset} has changed on disk")
        return record | {"path": str(path)}
    request = Request(url(subset), headers={"User-Agent": USER_AGENT})
    fd, name = tempfile.mkstemp(dir=cache_dir, prefix="download-", suffix=".tmp")
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, urlopen(request, timeout=300) as response:
            while chunk := response.read(1 << 20):
                target.write(chunk)
            headers = response.headers
            record = {
                "url": url(subset),
                "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
                "content_length": headers.get("Content-Length"),
            }
        record["bytes"] = temp.stat().st_size
        if (
            record["content_length"] is not None
            and int(record["content_length"]) != record["bytes"]
        ):
            raise RuntimeError(f"incomplete download of IBTrACS {subset}")
        record["sha256"] = sha256(temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record | {"path": str(path)}


def download(subset: str, cache_dir: Path, *, live: bool) -> dict[str, Any]:
    """As ``_download``, tried again when the connection fails part-way."""
    return again(lambda: _download(subset, cache_dir, live=live))


def header(path: Path) -> tuple[list[str], list[str]]:
    """Column names (first line) and units (second line)."""
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source)
        return next(reader), next(reader)


def rows(path: Path, *, trim: bool = True, empty_as_null: bool = True) -> Iterator[Row]:
    """Data rows in file order, after the two rules crc-sdk states.

    ``trim``: leading and trailing whitespace is removed from every value.
    ``empty_as_null``: a value that is then empty becomes ``None``.
    """
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source)
        next(reader)
        next(reader)
        for raw in reader:
            values: Iterable[str] = (value.strip() for value in raw) if trim else raw
            yield [None if empty_as_null and value == "" else value for value in values]


def select(
    data: Iterable[Row],
    columns: Sequence[str],
    *,
    storm_ids: Sequence[str] | None = None,
    seasons: tuple[int, int] | None = None,
) -> Iterator[Row]:
    """Rows of the given storms (by ``SID``) and of seasons in an inclusive range."""
    sid, season = columns.index("SID"), columns.index("SEASON")
    wanted = set(storm_ids) if storm_ids is not None else None
    for row in data:
        if wanted is not None and row[sid] not in wanted:
            continue
        if seasons is not None:
            value = row[season]
            if value is None or not seasons[0] <= int(value) <= seasons[1]:
                continue
        yield row


def explore(path: Path) -> dict[str, Any]:
    """Counts that describe one file: size, coverage in time and space, missing values."""
    columns, units = header(path)
    index = {name: position for position, name in enumerate(columns)}
    missing = [0] * len(columns)
    widths: Counter[int] = Counter()
    storms_by_season: dict[int, set[str]] = {}
    points_by_season: Counter[int] = Counter()
    track_types: Counter[str] = Counter()
    basins: Counter[str] = Counter()
    storms: set[str] = set()
    trimmed = total = blank_season = 0
    first_time = last_time = None
    lat_range = [None, None]
    lon_range = [None, None]
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source)
        next(reader)
        next(reader)
        for raw in reader:
            total += 1
            widths[len(raw)] += 1
            for position, value in enumerate(raw[: len(columns)]):
                stripped = value.strip()
                if stripped != value:
                    trimmed += 1
                if stripped == "":
                    missing[position] += 1
            if len(raw) != len(columns):
                continue
            sid = raw[index["SID"]].strip()
            storms.add(sid)
            season = raw[index["SEASON"]].strip()
            if season == "":
                blank_season += 1
            else:
                storms_by_season.setdefault(int(season), set()).add(sid)
                points_by_season[int(season)] += 1
            if "TRACK_TYPE" in index:
                track_types[raw[index["TRACK_TYPE"]].strip()] += 1
            if "BASIN" in index:
                basins[raw[index["BASIN"]].strip()] += 1
            time = raw[index["ISO_TIME"]].strip()
            if time:
                first_time = time if first_time is None or time < first_time else first_time
                last_time = time if last_time is None or time > last_time else last_time
            for name, span in (("LAT", lat_range), ("LON", lon_range)):
                text = raw[index[name]].strip() if name in index else ""
                if text:
                    number = float(text)
                    span[0] = number if span[0] is None or number < span[0] else span[0]
                    span[1] = number if span[1] is None or number > span[1] else span[1]
    seasons = sorted(storms_by_season)
    return {
        "rows": total,
        "columns": len(columns),
        "storms": len(storms),
        "seasons": [seasons[0], seasons[-1]] if seasons else None,
        "first_time": first_time,
        "last_time": last_time,
        "lat_range": lat_range,
        "lon_range": lon_range,
        "rows_with_wrong_field_count": total - widths.get(len(columns), 0),
        "rows_with_blank_season": blank_season,
        "values_with_outer_whitespace": trimmed,
        "values_empty_after_trim": sum(missing),
        "values_total": total * len(columns),
        "track_types": dict(sorted(track_types.items())),
        "basins": dict(sorted(basins.items())),
        "storms_by_season": [[season, len(storms_by_season[season])] for season in seasons],
        "points_by_season": [[season, points_by_season[season]] for season in seasons],
        "missing_by_column": [
            {"column": name, "unit": unit.strip(), "missing": count}
            for name, unit, count in zip(columns, units, missing, strict=True)
        ],
    }


#: The agencies whose wind and pressure columns NOAA's file carries (``<AGENCY>_WIND``,
#: ``<AGENCY>_PRES``), as named in NOAA's column documentation for v04r01.
AGENCIES = (
    "USA",
    "TOKYO",
    "CMA",
    "HKO",
    "NEWDELHI",
    "REUNION",
    "BOM",
    "NADI",
    "WELLINGTON",
    "WMO",
)
#: NOAA's unit labels (line 2 of the file) and their usual names; a millibar is a hectopascal,
#: so neither needs a conversion.
UNIT_NAMES = {"kts": "knots", "mb": "hPa"}
#: DOI of IBTrACS v04r01, as NOAA's landing page gives it for citing the data.
DOI = "10.25921/82ty-9e16"
#: The fields of one output row, in the order they are compared.
FIELDS = (
    "variable_id",
    "scenario_id",
    "period_id",
    "support_position",
    "cell_id",
    "wkb_header",
    "longitude",
    "latitude",
    "time",
    "value",
    "station_id",
    "group_id",
    "failure_code",
    "failure_message",
    "coverage",
)
MISSING_MESSAGE = "The source reports no valid observation."


def wkb_point(longitude: float, latitude: float) -> bytes:
    """Little-endian ISO WKB of a 2-D point: byte order 1, geometry type 1, x, y."""
    return struct.pack("<BIdd", 1, 1, longitude, latitude)


def wrapped(text: str) -> float:
    """A longitude east of 180 degrees moved into -180..180 by exact decimal subtraction."""
    value = Decimal(text)
    return float(value - 360 if value >= 180 else value)


def agency_points(
    path: Path,
    agency: str,
    *,
    wrap_longitude: bool = True,
    time_separator: str = "T",
    resolution: int = 9,
    empty_as_null: bool = True,
    pressure_first: bool = False,
) -> Iterator[dict[str, Any]]:
    """What one agency's reading of NOAA's file should give, row by row, in file order.

    Each data row gives two records, the agency's wind and then its pressure, at IBTrACS's
    combined position (``LAT``, ``LON``), whether or not the agency reported a value. The
    keyword arguments are the rules, so that a test can make one of them deliberately wrong.
    The H3 cell is computed with h3's string API, a different route from the framework's.
    """
    import h3

    columns, _ = header(path)
    index = {name: position for position, name in enumerate(columns)}
    fields = ("PRES", "WIND") if pressure_first else ("WIND", "PRES")
    names = {"WIND": "maximum_sustained_wind", "PRES": "minimum_central_pressure"}
    for row in rows(path):
        sid, when = row[index["SID"]], str(row[index["ISO_TIME"]]).replace(" ", time_separator)
        lon_text, lat_text = str(row[index["LON"]]), str(row[index["LAT"]])
        longitude = wrapped(lon_text) if wrap_longitude else float(lon_text)
        latitude = float(lat_text)
        cell = h3.str_to_int(h3.latlng_to_cell(latitude, longitude, resolution))
        for field in fields:
            text = row[index[f"{agency}_{field}"]]
            value = None if text is None else float(text)
            if text is None and not empty_as_null:
                value = 0.0
            yield {
                "variable_id": f"ibtracs:{agency}:{names[field]}",
                "scenario_id": None,
                "period_id": None,
                "support_position": f"{sid}:{when}",
                "cell_id": cell,
                "wkb_header": "0101000000",
                "longitude": longitude,
                "latitude": latitude,
                "time": when,
                "value": value,
                "station_id": None,
                "group_id": sid,
                "failure_code": None if value is not None else "source_no_data",
                "failure_message": None if value is not None else MISSING_MESSAGE,
                "coverage": None,
                "wkb": wkb_point(longitude, latitude),
            }


def release_digest(resources: Iterable[tuple[str, str]]) -> str:
    """SHA-256 over the sorted (address, checksum) pairs, written as compact JSON."""
    data = json.dumps(sorted(dict(resources).items()), ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def agency_counts(path: Path) -> dict[str, dict[str, int]]:
    """For each agency: points in the file, points with a wind, with a pressure, storms."""
    columns, _ = header(path)
    index = {name: position for position, name in enumerate(columns)}
    out = {agency: {"points": 0, "wind": 0, "pressure": 0} for agency in AGENCIES}
    storms: dict[str, set[str]] = {agency: set() for agency in AGENCIES}
    for row in rows(path):
        for agency in AGENCIES:
            wind = row[index[f"{agency}_WIND"]]
            pressure = row[index[f"{agency}_PRES"]]
            out[agency]["points"] += 1
            out[agency]["wind"] += wind is not None
            out[agency]["pressure"] += pressure is not None
            if wind is not None or pressure is not None:
                storms[agency].add(str(row[index["SID"]]))
    for agency in AGENCIES:
        out[agency]["storms_with_a_value"] = len(storms[agency])
    return out


def storm_seasons(path: Path) -> dict[str, int]:
    """Season of each storm (``SID``), from the first row that carries one."""
    columns, _ = header(path)
    sid, season = columns.index("SID"), columns.index("SEASON")
    out: dict[str, int] = {}
    for row in rows(path):
        if row[sid] is not None and row[season] is not None and row[sid] not in out:
            out[row[sid]] = int(row[season])  # type: ignore[arg-type,index]
    return out
