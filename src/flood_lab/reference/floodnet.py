"""Second reader of the FloodNet event and sensor tables (requirements FS3, FS4).

Route, chosen to share nothing with a loader built on pandas: the standard library's ``csv``
reads both files as text, ``datetime`` parses the times and ``zoneinfo`` gives the New York day.

The publisher writes times as ``YYYY-MM-DDTHH:MM:SS.000`` without a zone; they are GMT (data
description, and the F0 facts). Depths are in inches, durations in minutes. The sensor table's
``date_installed`` and ``date_removed`` are calendar dates written as midnight; an empty
``date_removed`` means the sensor is still deployed.
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import cache, domain

ZONE = ZoneInfo(domain.TIMEZONE)
INCH_M = 0.0254
#: consistency tolerances (the file gives depths to 0.01 in and times to the second)
PROFILE_TOLERANCE_IN = 0.006
DURATION_TOLERANCE_MIN = 0.02
_TIME = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?$")
_DATE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)(?:T00:00:00(?:\.0+)?)?$")


def parse_gmt(text: str) -> datetime:
    """A FloodNet time read as GMT.

    Rule: ``YYYY-MM-DDTHH:MM:SS`` with an optional fraction and no zone suffix. The files give
    ``.000``; a non-zero fraction raises ``ValueError``, because the outputs are kept to the
    second and the brief says to stop and report such a time rather than round it.
    """
    match = _TIME.match(text.strip())
    if not match:
        raise ValueError(f"not a FloodNet time: {text!r}")
    year, month, day, hour, minute, second, fraction = match.groups()
    if fraction is not None and int(fraction) != 0:
        raise ValueError(f"time with non-zero fraction of a second: {text!r}")
    return datetime(
        int(year), int(month), int(day), int(hour), int(minute), int(second), tzinfo=UTC
    )


def utc_text(moment: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ``."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day_of(moment: datetime) -> str:
    """The America/New_York calendar day of a moment, ``YYYY-MM-DD``."""
    return moment.astimezone(ZONE).date().isoformat()


def calendar_date(text: str) -> date:
    """The date part of a sensor-table date written as midnight, as written (no zone change)."""
    match = _DATE.match(text.strip())
    if not match:
        raise ValueError(f"not a calendar date written as midnight: {text!r}")
    return date(int(match[1]), int(match[2]), int(match[3]))


def _read(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_sensors(sensors_csv: str | Path) -> dict[str, dict[str, str]]:
    """The sensor table by ``sensor_id``; a repeated ``sensor_id`` raises ``ValueError``."""
    sensors: dict[str, dict[str, str]] = {}
    for row in _read(sensors_csv):
        if row["sensor_id"] in sensors:
            raise ValueError(f"sensor_id {row['sensor_id']!r} appears twice in {sensors_csv}")
        sensors[row["sensor_id"]] = row
    return sensors


def _float_or_none(text: str | None) -> float | None:
    return None if text is None or text.strip() == "" else float(text)


def events(events_csv: str | Path, sensors_csv: str | Path) -> list[dict[str, Any]]:
    """One row per row of the events file, sorted by (``sensor_id``, ``start_utc``).

    Rules: ``start_utc`` and ``end_utc`` are the file's times read as GMT; ``local_day`` is the
    New York calendar day of the start; ``peak_depth_m`` is ``max_depth_inches`` times 0.0254,
    not rounded; ``duration_min`` is ``duration_mins`` as given; ``longitude`` and ``latitude``
    come from the sensor table by ``sensor_id``, None where the sensor is not in it.
    """
    sensors = read_sensors(sensors_csv)
    rows = []
    for row in _read(events_csv):
        start = parse_gmt(row["flood_start_time"])
        end = parse_gmt(row["flood_end_time"])
        sensor = sensors.get(row["sensor_id"])
        rows.append(
            {
                "sensor_id": row["sensor_id"],
                "start_utc": utc_text(start),
                "end_utc": utc_text(end),
                "local_day": local_day_of(start),
                "peak_depth_m": float(row["max_depth_inches"]) * INCH_M,
                "duration_min": float(row["duration_mins"]),
                "longitude": _float_or_none(sensor["longitude"]) if sensor else None,
                "latitude": _float_or_none(sensor["latitude"]) if sensor else None,
            }
        )
    rows.sort(key=lambda r: (r["sensor_id"], r["start_utc"]))
    return rows


def consistency(events_csv: str | Path, sensors_csv: str | Path | None = None) -> dict[str, Any]:
    """Counts that check the events file against itself; they are not part of the comparison.

    * ``profile_peak_differs``: events whose largest ``flood_profile_depth_inches`` value differs
      from ``max_depth_inches`` by more than 0.006 in (an empty profile counts here too);
    * ``duration_differs``: events whose end minus start differs from ``duration_mins`` by more
      than 0.02 min;
    * ``duplicate_keys``: (``sensor_id``, start) keys that occur more than once, and
      ``duplicate_rows`` the rows beyond the first of each;
    * ``unknown_sensor``: events naming a sensor that is not in the sensor table (None when no
      sensor table is given).
    """
    rows = _read(events_csv)
    known = set(read_sensors(sensors_csv)) if sensors_csv is not None else None
    profile = duration = 0
    examples: dict[str, list[str]] = {"profile_peak_differs": [], "duration_differs": []}
    keys: Counter[tuple[str, str]] = Counter()
    for row in rows:
        start = parse_gmt(row["flood_start_time"])
        end = parse_gmt(row["flood_end_time"])
        key = (row["sensor_id"], utc_text(start))
        keys[key] += 1
        depths = json.loads(row["flood_profile_depth_inches"] or "[]")
        peak = float(row["max_depth_inches"])
        if not depths or abs(max(float(d) for d in depths) - peak) > PROFILE_TOLERANCE_IN:
            profile += 1
            examples["profile_peak_differs"].append(" ".join(key))
        minutes = (end - start).total_seconds() / 60.0
        if abs(minutes - float(row["duration_mins"])) > DURATION_TOLERANCE_MIN:
            duration += 1
            examples["duration_differs"].append(" ".join(key))
    duplicates = {k: n for k, n in keys.items() if n > 1}
    return {
        "rows": len(rows),
        "profile_peak_differs": profile,
        "duration_differs": duration,
        "duplicate_keys": len(duplicates),
        "duplicate_rows": sum(n - 1 for n in duplicates.values()),
        "unknown_sensor": None
        if known is None
        else sum(1 for row in rows if row["sensor_id"] not in known),
        "examples": {name: found[:10] for name, found in examples.items()},
    }


def deployed_on(sensor: dict[str, str], day: date) -> bool:
    """``date_installed`` on or before ``day``, and ``date_removed`` empty or on or after it."""
    if calendar_date(sensor["date_installed"]) > day:
        return False
    removed = sensor["date_removed"].strip()
    return removed == "" or calendar_date(removed) >= day


def storm_sensors(
    events_csv: str | Path, sensors_csv: str | Path, local_day: str
) -> list[dict[str, Any]]:
    """One row per sensor deployed on ``local_day`` (``YYYY-MM-DD``), sorted by ``sensor_id``.

    Rules: deployed as in ``deployed_on``; ``recorded`` is True when the sensor has at least one
    event whose New York start day is ``local_day``; ``peak_depth_m`` is the largest
    ``peak_depth_m`` of those events, else None. Events of sensors not deployed that day are
    not counted (a sensor recording before its install date is not deployed by this rule).
    """
    day = date.fromisoformat(local_day)
    peaks: dict[str, float] = {}
    for row in events(events_csv, sensors_csv):
        if row["local_day"] == local_day:
            peaks[row["sensor_id"]] = max(peaks.get(row["sensor_id"], 0.0), row["peak_depth_m"])
    rows = []
    for sensor_id, sensor in sorted(read_sensors(sensors_csv).items()):
        if not deployed_on(sensor, day):
            continue
        rows.append(
            {
                "sensor_id": sensor_id,
                "longitude": _float_or_none(sensor["longitude"]),
                "latitude": _float_or_none(sensor["latitude"]),
                "borough": sensor["borough"],
                "recorded": sensor_id in peaks,
                "peak_depth_m": peaks.get(sensor_id),
            }
        )
    return rows


STORMS = ("2021-09-01", "2023-09-29")
BOROUGHS = ("Brooklyn", "Queens")


def main() -> None:  # pragma: no cover - run on the real files by hand
    from . import peak_memory_bytes, scratch_dir, write_json, write_json_lines

    root = cache.root()
    events_csv = root / "floodnet-flood-events" / "aq7i-eu5q.csv"
    sensors_csv = root / "floodnet-sensors" / "kb2e-tjy3.csv"
    out = scratch_dir() / "floodnet"
    start = time.perf_counter()
    table = events(events_csv, sensors_csv)
    checks = consistency(events_csv, sensors_csv)
    storms: dict[str, Any] = {}
    for day in STORMS:
        rows = storm_sensors(events_csv, sensors_csv, day)
        write_json_lines(out / f"storm-sensors-{day}.jsonl", rows)
        local = [r for r in rows if r["borough"] in BOROUGHS]
        storms[day] = {
            "deployed_all": len(rows),
            "recorded_all": sum(r["recorded"] for r in rows),
            "deployed_brooklyn_queens": len(local),
            "recorded_brooklyn_queens": sum(r["recorded"] for r in local),
        }
    seconds = time.perf_counter() - start
    write_json_lines(out / "events.jsonl", table)
    summary = {
        "inputs": [str(events_csv), str(sensors_csv)],
        "rows": len(table),
        "consistency": checks,
        "storms": storms,
        "seconds": round(seconds, 2),
        "peak_memory_bytes": peak_memory_bytes(),
    }
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
