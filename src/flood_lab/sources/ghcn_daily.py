"""GHCN-Daily rain at New York City's three first-order stations: which days were dry (FV5).

Transformation statement (the data card repeats it):

1. Daily precipitation (``PRCP``) of Central Park (``USW00094728``), LaGuardia (``USW00014732``)
   and JFK (``USW00094789``) comes from NOAA NCEI's Access Data Service, dataset
   ``daily-summaries`` (GHCN-Daily), in metric units (millimetres). ``fetch`` keeps the response
   as returned under ``ghcn-daily/<name>.json``, beside ``<name>.query.json`` with the query, the
   address asked and the time fetched.
2. ``DATE`` is the station's observation day as NCEI writes it; it is used as written. Which
   hours that day covers at these stations (local standard time or the wall clock) was not
   found in the GHCN-Daily readme and is not checked (facts ``ghcn-daily``).
3. A day is **dry** when every station that reported has less than ``DRY_MM`` [P] on that day and
   on each of the ``DRY_BEFORE`` [P] days before it, and at least one station reported each of
   those days. A missing value is not read as zero.

The stations lie 8.2, 10.9 and 18.4 km from the square's centre (6.2 to 15.9 km from its edge);
a dry day at all three is taken to be dry in the square. Rain
that fell only on the square would be missed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ENDPOINT = "https://www.ncei.noaa.gov/access/services/data/v1"
FOLDER = "ghcn-daily"
STATIONS = {
    "USW00094728": "Central Park",
    "USW00014732": "LaGuardia",
    "USW00094789": "JFK",
}
#: statement step 3 [P]: a day is dry below this rain, mm, at every station, on it and before it
DRY_MM = 1.0
DRY_BEFORE = 2


def query(window: tuple[str, str]) -> dict[str, str]:
    first, last = window
    return {
        "dataset": "daily-summaries",
        "stations": ",".join(STATIONS),
        "startDate": first,
        "endDate": last,
        "dataTypes": "PRCP",
        "format": "json",
        "units": "metric",
        "includeStationName": "true",
    }


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
    return hashlib.sha256(data).hexdigest()


def fetch(root: Path, name: str, window: tuple[str, str]) -> dict[str, Any]:
    """Statement step 1, over the network."""
    asked = query(window)
    url = ENDPOINT + "?" + urllib.parse.urlencode(asked)
    for attempt in range(4):
        done = subprocess.run(  # noqa: S603
            ["curl", "-sS", "--fail", "--max-time", "120", "-A", "flood-lab/0.1", url],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if done.returncode == 0:
            break
        if attempt == 3:
            raise OSError(f"curl {done.returncode}: {done.stderr.decode(errors='replace')}")
        time.sleep(5 * (attempt + 1))
    data = done.stdout
    json.loads(data)  # refuse a response that is not JSON before keeping it
    folder = root / FOLDER
    record = {
        "endpoint": ENDPOINT,
        "name": name,
        "query": asked,
        "url": url,
        "file": f"{name}.json",
        "bytes": len(data),
        "sha256": _write(folder / f"{name}.json", data),
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _write(folder / f"{name}.query.json", json.dumps(record, indent=1).encode())
    return record


def read(root: Path, name: str) -> pd.DataFrame:
    """One row per station and day: ``station``, ``day`` (text), ``prcp_mm`` (NaN if absent)."""
    rows = json.loads((root / FOLDER / f"{name}.json").read_text())
    return table(rows)


def table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["STATION", "DATE", "PRCP"])
    return pd.DataFrame(
        {
            "station": frame["STATION"].astype(str),
            "day": frame["DATE"].astype(str),
            "prcp_mm": pd.to_numeric(frame["PRCP"], errors="coerce"),
        }
    )


def dry_days(
    rain: pd.DataFrame, days: list[str], dry_mm: float = DRY_MM, before: int = DRY_BEFORE
) -> dict[str, bool | None]:
    """Statement step 3 for each day: True dry, False wet, None when a needed day has no report."""
    wide = rain.pivot_table(index="day", columns="station", values="prcp_mm", aggfunc="max")
    out: dict[str, bool | None] = {}
    for day in days:
        d0 = date.fromisoformat(day)
        span = [(d0 - timedelta(days=k)).isoformat() for k in range(before + 1)]
        verdict: bool | None = True
        for d in span:
            if d not in wide.index or wide.loc[d].notna().sum() == 0:
                verdict = None
                break
            if (wide.loc[d].dropna() >= dry_mm).any():
                verdict = False
                break
        out[day] = verdict
    return out


def daily_max(rain: pd.DataFrame) -> dict[str, float | None]:
    """The largest rain of the stations on each day, mm."""
    m = rain.groupby("day")["prcp_mm"].max()
    return {d: (None if pd.isna(v) else float(v)) for d, v in m.items()}
