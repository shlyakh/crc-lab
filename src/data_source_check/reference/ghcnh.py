"""GHCNh annual temperature extremes recomputed from NOAA's per-station, per-year files.

Two readers, neither of which uses the framework or pyarrow (the framework's parser):

- ``read_psv``: NOAA's pipe-separated file, with the standard library only;
- ``read_parquet``: NOAA's Parquet file, through DuckDB's own Parquet reader, returning plain
  Python rows. (crc-sdk reads the Parquet file with pyarrow; the SQL here only selects columns.)

Every rule that turns hourly reports into an annual value is applied in Python. Two rule sets:

- ``Rules`` and ``annual_row``: the rules crc-sdk 0.11 stated (18 hours make a day, 90 per cent
  of days make a year, one row per station and year). Kept to count what 1.0 changed.
- ``Rules1`` and ``annual_rows``: the rules crc-sdk 1.0 states for its default ``read()`` of an
  annual indicator (24 hours make a day, a ``Coverage`` fraction of days makes a year, one row
  per station position and year, and the reports that make the whole read fail).

The rules are an argument so that a test can make one deliberately wrong.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import struct
import tempfile
from calendar import isleap
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = "https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/access/by-year"
USER_AGENT = "data-source-check"
COLUMNS = (
    "STATION",
    "DATE",
    "LATITUDE",
    "LONGITUDE",
    "ELEVATION",
    "temperature",
    "temperature_Quality_Code",
    "temperature_Source_Code",
)
#: (station, time text, latitude, longitude, elevation, temperature, quality code, source code)
Report = tuple[Any, Any, Any, Any, Any, Any, Any, Any]


@dataclass(frozen=True)
class Rules:
    """The rules as crc-sdk's documentation and code state them (defaults)."""

    quality_codes: tuple[str, ...] = ("", "1", "5")
    #: source codes for which quality code "5" is accepted
    sources_for_5: tuple[str, ...] = ("313", "314", "315", "322", "335", "343", "344", "346")
    #: source codes for which quality code "1" is accepted
    sources_for_1: tuple[str, ...] = (
        "313", "314", "315", "322", "335", "343", "344", "346",
        "220", "221", "222", "223", "347", "348",
    )  # fmt: skip
    lowest: float = -93.2
    highest: float = 61.8
    hours_per_day: int = 18  # ceil(24 * 0.75)
    day_fraction: float = 0.9
    day_offset_hours: int = 0  # days are UTC
    missing_elevation: float = -999.9
    coordinate_tolerance: float = 0.05


def url(station: str, year: int, kind: str) -> str:
    return f"{ROOT}/{year}/{kind}/GHCNh_{station}_{year}.{kind}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: tries per file; a download that fails part-way is started again from the beginning
ATTEMPTS = 4


def download(station: str, year: int, kind: str, cache_dir: Path, *, live: bool) -> dict[str, Any]:
    """Fetch one station-year file, or reuse the cached copy. A 404 is recorded, not raised."""
    return download_file(
        url(station, year, kind), cache_dir / kind, f"GHCNh_{station}_{year}.{kind}", live=live
    )


def download_file(address: str, folder: Path, filename: str, *, live: bool) -> dict[str, Any]:
    """Fetch one file into ``folder``, or reuse the cached copy. A 404 is recorded, not raised."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    sidecar = folder / f"{Path(filename).stem}.json"
    if sidecar.exists() and (
        not live or path.exists() or json.loads(sidecar.read_text())["missing"]
    ):
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if not record["missing"] and sha256(path) != record["sha256"]:
            raise RuntimeError(f"cached reference copy of {path.name} has changed on disk")
        return record | {"path": str(path)}
    if not live:
        raise FileNotFoundError(f"no cached reference copy of {path.name}; run with --live")
    record: dict[str, Any] = {
        "url": address,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "missing": False,
    }
    fd, name = tempfile.mkstemp(dir=folder, prefix="download-", suffix=".tmp")
    temp = Path(name)
    try:
        os.close(fd)
        try:
            request = Request(address, headers={"User-Agent": USER_AGENT})
            for attempt in range(ATTEMPTS):
                try:
                    with temp.open("wb") as target, urlopen(request, timeout=300) as response:
                        while chunk := response.read(1 << 20):
                            target.write(chunk)
                        record["etag"] = response.headers.get("ETag")
                        record["last_modified"] = response.headers.get("Last-Modified")
                    break
                except HTTPError:
                    raise
                except OSError:  # a reset or a timeout part-way: NOAA drops some of 1,000 requests
                    if attempt == ATTEMPTS - 1:
                        raise
                    sleep(5 * (attempt + 1))
            record["bytes"] = temp.stat().st_size
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


def _number(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def read_psv(path: Path) -> Iterator[Report]:
    """Reports from NOAA's pipe-separated file (standard library only)."""
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source, delimiter="|")
        head = next(reader)
        index = [head.index(name) for name in COLUMNS]
        for row in reader:
            station, time, lat, lon, elevation, value, quality, code = (row[i] for i in index)
            yield (
                station,
                time,
                _number(lat),
                _number(lon),
                _number(elevation),
                _number(value),
                quality,
                code,
            )


def read_parquet(path: Path) -> list[Report]:
    """Reports from NOAA's Parquet file, read by DuckDB into plain Python rows."""
    import duckdb

    with duckdb.connect() as con:
        columns = ", ".join(f'"{name}"' for name in COLUMNS)
        return con.execute(f"SELECT {columns} FROM read_parquet(?)", [str(path)]).fetchall()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def accepted(value: Any, quality: Any, code: Any, rules: Rules) -> tuple[bool, str]:
    """Whether a report's temperature is used, and if not, the first rule that excludes it."""
    if value is None:
        return False, "no temperature"
    flag, source = _text(quality), _text(code)
    if flag not in rules.quality_codes:
        return False, "quality code not accepted"
    if flag == "1" and source not in rules.sources_for_1:
        return False, "quality code 1 from a source not accepted"
    if flag == "5" and source not in rules.sources_for_5:
        return False, "quality code 5 from a source not accepted"
    if not math.isfinite(value):
        return False, "not a finite number"
    if not rules.lowest <= value <= rules.highest:
        return False, "outside the physical range"
    return True, ""


def empty_row(station: str, year: int) -> dict[str, Any]:
    """The annual row for a station-year NOAA has no file for."""
    return {
        "station": station, "year": year, "latitude": None, "longitude": None,
        "elevation": None, "valid_days": 0, "expected_days": 366 if isleap(year) else 365,
        "accepted_reports": 0, "reports": 0, "value_max": None, "value_min": None,
        "complete": False, "error": "", "excluded": {},
    }  # fmt: skip


def annual_row(
    reports: Iterable[Report], station: str, year: int, rules: Rules | None = None
) -> dict[str, Any]:
    """One station-year reduced to its annual maximum and minimum, with the audit counts."""
    rules = rules or Rules()
    out = empty_row(station, year)
    days: dict[Any, dict[str, Any]] = {}
    lats: list[float] = []
    lons: list[float] = []
    elevations: list[float] = []
    excluded: Counter[str] = Counter()
    shift = timedelta(hours=rules.day_offset_hours)
    for name, time, lat, lon, elevation, value, quality, code in reports:
        if name != station or not time:
            continue
        try:
            moment = datetime.fromisoformat(str(time))
        except ValueError:
            continue
        if moment.year != year:
            continue
        moment += shift
        day = days.setdefault(
            moment.date(), {"reports": 0, "hours": set(), "values": [], "lat": False, "lon": False}
        )
        day["reports"] += 1
        if lat is not None:
            day["lat"] = True
            lats.append(lat)
        if lon is not None:
            day["lon"] = True
            lons.append(lon)
        if elevation is not None and elevation != rules.missing_elevation:
            elevations.append(elevation)
        ok, reason = accepted(value, quality, code, rules)
        if ok:
            day["values"].append(value)
            day["hours"].add(moment.replace(minute=0, second=0, microsecond=0))
        else:
            excluded[reason] += 1
    out["excluded"] = dict(sorted(excluded.items()))
    if not days:
        out["error"] = "no matching observations"
        return out
    out["reports"] = sum(day["reports"] for day in days.values())
    out["accepted_reports"] = sum(len(day["values"]) for day in days.values())
    if not all(day["lat"] and day["lon"] for day in days.values()):
        out["error"] = "missing coordinates"
        return out
    out["latitude"], out["longitude"] = min(lats), min(lons)
    out["elevation"] = min(elevations, default=None)
    if (
        not -90 <= out["latitude"] <= 90
        or not -180 <= out["longitude"] <= 180
        or max(lats) - min(lats) > rules.coordinate_tolerance
        or max(lons) - min(lons) > rules.coordinate_tolerance
    ):
        out["error"] = "invalid or moving coordinates"
        return out
    valid = [day for day in days.values() if len(day["hours"]) >= rules.hours_per_day]
    out["valid_days"] = len(valid)
    out["complete"] = len(valid) >= math.ceil(out["expected_days"] * rules.day_fraction)
    if out["complete"]:
        out["value_max"] = max(max(day["values"]) for day in valid)
        out["value_min"] = min(min(day["values"]) for day in valid)
    return out


def station_year(
    station: str, year: int, kind: str, cache_dir: Path, *, live: bool, rules: Rules | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The annual row recomputed from one file of the given kind, and the file's provenance."""
    provenance = download(station, year, kind, cache_dir, live=live)
    if provenance["missing"]:
        return empty_row(station, year), provenance
    path = Path(provenance["path"])
    reports = read_psv(path) if kind == "psv" else read_parquet(path)
    return annual_row(reports, station, year, rules), provenance


# --- the rules crc-sdk 1.0 states ---------------------------------------------------------


@dataclass(frozen=True)
class Rules1:
    """The rules of crc-sdk 1.0's default ``read()`` of a GHCNh annual indicator (defaults)."""

    quality_codes: tuple[str, ...] = Rules.quality_codes
    sources_for_5: tuple[str, ...] = Rules.sources_for_5
    sources_for_1: tuple[str, ...] = Rules.sources_for_1
    lowest: float = Rules.lowest
    highest: float = Rules.highest
    #: distinct clock hours with an accepted report that make a day complete
    hours_per_day: int = 24
    #: the fraction of complete days that ``Coverage.complete()`` stands for
    complete_fraction: float = 1.0
    day_offset_hours: int = 0  # days are the calendar days of the published (UTC) time
    #: one output row per distinct reported position; False keeps one row per station
    split_positions: bool = True
    #: a report of another station or year, an unreadable time, missing coordinates, a
    #: temperature that is not finite, or two reports at one time and position stop the read;
    #: False drops such a report instead
    refuse_bad_reports: bool = True
    cell_resolution: int = 9


_TIME = re.compile(r"\d{4}(-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?)?")


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def support_id(station: str, longitude: float, latitude: float) -> str:
    """The identity crc-sdk 1.0 states for a station position: the station, then the first 20
    hexadecimal digits of the SHA-256 of the position as a little-endian WKB point."""
    point = struct.pack("<BIdd", 1, 1, longitude, latitude)
    return f"{station}@{hashlib.sha256(point).hexdigest()[:20]}"


def cell_id(longitude: float, latitude: float, resolution: int) -> int:
    from h3.api import basic_int

    return int(basic_int.latlng_to_cell(latitude, longitude, resolution))


def _bad_report(
    name: Any, text: str, lat: Any, lon: Any, value: Any, station: str, year: int
) -> tuple[str, datetime | None]:
    """The reason a report stops crc-sdk 1.0's read, or "" ; and the report's time."""
    if name != station:
        return "a report of another station", None
    try:
        if not _TIME.fullmatch(text):
            raise ValueError(text)
        moment = datetime.fromisoformat(text)
    except ValueError:
        return "a report whose time cannot be read", None
    if moment.year != year:
        return "a report of another year", moment
    if not (_finite(lat) and _finite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return "a report with missing or invalid coordinates", moment
    if value is not None and not _finite(value):
        return "a temperature that is not a finite number", moment
    return "", moment


def annual_rows(
    reports: Iterable[Report],
    station: str,
    year: int,
    rules: Rules1 | None = None,
    fraction: float | None = None,
) -> dict[str, Any]:
    """One station-year reduced as crc-sdk 1.0 states: one row per position, with the annual
    maximum and minimum of complete days when enough days are complete, and audit counts.

    ``fraction`` is the ``Coverage`` asked for; None is the default, ``Coverage.complete()``.
    """
    rules = rules or Rules1()
    fraction = rules.complete_fraction if fraction is None else fraction
    expected = 366 if isleap(year) else 365
    out: dict[str, Any] = {
        "station": station, "year": year, "rows": [], "error": "", "unavailable": False,
        "reports": 0, "accepted_reports": 0, "excluded": {},
    }  # fmt: skip
    excluded: Counter[str] = Counter()
    supports: dict[tuple[float, float], dict[Any, dict[str, Any]]] = {}
    seen: set[tuple[float, float, str]] = set()
    shift = timedelta(hours=rules.day_offset_hours)
    first: tuple[float, float] | None = None
    for name, time, lat, lon, _elevation, value, quality, code in reports:
        text = "" if time is None else str(time).replace(" ", "T")
        reason, moment = _bad_report(name, text, lat, lon, value, station, year)
        if not reason:
            key = (float(lon), float(lat), text)
            if key in seen:
                reason = "two reports at one time and position"
            seen.add(key)
        if reason:
            if rules.refuse_bad_reports:
                out["error"] = out["error"] or reason
            excluded[f"bad report: {reason}"] += 1
            continue
        assert moment is not None
        out["reports"] += 1
        position = (float(lon), float(lat))
        first = first or position
        days = supports.setdefault(position if rules.split_positions else first, {})
        ok, why = accepted(value, quality, code, rules)  # type: ignore[arg-type]
        if not ok:  # the position keeps its row even if none of its reports is accepted
            excluded[why] += 1
            continue
        out["accepted_reports"] += 1
        moment += shift
        day = days.setdefault(moment.date(), {"hours": set(), "values": []})
        day["hours"].add(moment.hour)
        day["values"].append(value)
    out["excluded"] = dict(sorted(excluded.items()))
    if out["error"]:
        return out
    if not out["reports"]:
        out["unavailable"] = True  # crc-sdk: no row, a diagnostic for the station-year
        return out
    for (lon, lat), days in sorted(supports.items()):
        complete = [
            day
            for when, day in days.items()
            if when.year == year and len(day["hours"]) >= rules.hours_per_day
        ]
        valid = len(complete)
        whole = bool(complete) and valid / expected >= fraction
        out["rows"].append(
            {
                "support_id": support_id(station, lon, lat),
                "longitude": lon,
                "latitude": lat,
                "cell_id": cell_id(lon, lat, rules.cell_resolution),
                "valid_days": valid,
                "expected_days": expected,
                "minimum_fraction": float(fraction),
                "complete": whole,
                "value_max": max(max(day["values"]) for day in complete) if whole else None,
                "value_min": min(min(day["values"]) for day in complete) if whole else None,
            }
        )
    return out


STATION_LIST = "https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/doc/ghcnh-station-list.csv"


def station_list(cache_dir: Path, *, live: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """NOAA's station list (identifier, name, position) and the file's provenance.

    A position is kept only when both coordinates are numbers inside WGS84; otherwise the
    station has no position. A blank name is replaced by the identifier.
    """
    provenance = download_file(STATION_LIST, cache_dir / "doc", "ghcnh-station-list.csv", live=live)
    rows = []
    with Path(provenance["path"]).open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            try:
                lon, lat = float(row["LONGITUDE"]), float(row["LATITUDE"])
            except (TypeError, ValueError):
                lon = lat = None
            if lon is None or lat is None or not (_finite(lon) and _finite(lat)):
                lon = lat = None
            elif not (-180 <= lon <= 180 and -90 <= lat <= 90):
                lon = lat = None
            ident = row["GHCN_ID"]
            rows.append(
                {"station": ident, "name": row["NAME"] or ident, "longitude": lon, "latitude": lat}
            )
    return rows, provenance


def in_box(stations: Iterable[dict[str, Any]], bounds: tuple[float, ...]) -> list[dict[str, Any]]:
    """Stations whose listed position lies in the box, edges included, in the list's order."""
    west, south, east, north = bounds
    return [
        item
        for item in stations
        if item["longitude"] is not None
        and south <= item["latitude"] <= north
        and west <= item["longitude"] <= east
    ]


def read_reports(path: Path, kind: str) -> list[Report]:
    """Every report of one file of the given kind."""
    return list(read_psv(path)) if kind == "psv" else read_parquet(path)
