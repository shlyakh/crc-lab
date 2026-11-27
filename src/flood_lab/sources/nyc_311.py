"""NYC 311 service requests: the flooding-related requests of a storm inside the square (FV5).

Transformation statement:

1. The rows come from NYC Open Data ``erm2-nwe9`` ("311 Service Requests from 2020 to Present")
   through its Socrata API. ``fetch`` asks for every request whose ``created_date`` falls in the
   storm's window and whose ``location`` lies in a latitude-longitude box drawn round the square
   (``within_box``), every complaint type, ordered by ``unique_key`` and paged. Each page is kept
   as returned under ``nyc-311/<storm>/page_<n>.json``, beside ``query.json`` with the query, the
   addresses asked and the time fetched. A second query counts the flooding-related requests in
   the square's boroughs that carry no location at all (``unplaced_<storm>.json``): those cannot
   be placed and are only reported. For the late-call and baseline counts, ``fetch_flood`` asks
   the same box for the flooding-related requests only (``FLOOD_TYPES``) over a longer window
   (step 1b), cached the same way under ``nyc-311/<name>/``.
2. ``created_date`` is a floating time stamp (no zone); the dictionary read states none. It is
   read as the New York wall clock, as written, and the request belongs to the calendar day of
   that clock.
3. A request is flooding-related when its complaint type and descriptor are in ``FLOOD_TYPES``.
   Two naming schemes are in use for the same DEP requests (facts ``nyc-311``,
   ``flood_complaint_types``): the legacy ``Sewer`` descriptors with a code in brackets and the
   current ``Sewer Maintenance`` descriptors. Both are counted, each pair mapped to one common
   kind (the mapping is the lab's; the dictionary lists the current names only).
   **The two schemes can hold the same request twice.** In the 2023 rows most current-scheme
   requests have a legacy-scheme row of the same kind at the same address a few minutes later,
   with a different ``unique_key``. ``twins`` pairs them (same kind; same address, or positions
   within ``TWIN_M``; created within ``TWIN_S``; each row used once, closest in time first).
   Rows of both schemes are reported, and the count of requests is rows less twins.
4. Inside the square: the request's latitude and longitude, projected to EPSG:32618, fall in
   ``domain.SQUARE`` (west and south edges inside, east and north outside). The box of step 1 is
   only a coarse first cut.

A request says that someone called about water at an address. It is not a measurement, and no
request is not no water.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from flood_lab.observations import sightings

DATASET = "erm2-nwe9"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
FOLDER = "nyc-311"
PAGE = 50_000
#: the square's boroughs as the 311 table writes them (Brooklyn and Manhattan: nyc-nta-2020)
BOROUGHS = ("BROOKLYN", "MANHATTAN")
#: (complaint_type, descriptor) -> (scheme, kind). Facts nyc-311, flood_complaint_types.
FLOOD_TYPES: dict[tuple[str, str], tuple[str, str]] = {
    ("Sewer", "Street Flooding (SJ)"): ("legacy", "street flooding"),
    ("Sewer", "Highway Flooding (SH)"): ("legacy", "highway flooding"),
    ("Sewer", "Sewer Backup (Use Comments) (SA)"): ("legacy", "sewer backup"),
    ("Sewer", "Catch Basin Clogged/Flooding (Use Comments) (SC)"): (
        "legacy",
        "catch basin clogged",
    ),
    ("Sewer", "Manhole Overflow (Use Comments) (SA1)"): ("legacy", "manhole overflow"),
    ("Sewer Maintenance", "Flooding on Street"): ("current", "street flooding"),
    ("Sewer Maintenance", "Flooding on Highway"): ("current", "highway flooding"),
    ("Sewer Maintenance", "Backup"): ("current", "sewer backup"),
    ("Sewer Maintenance", "Catch Basin Clogged"): ("current", "catch basin clogged"),
    ("Sewer Maintenance", "Manhole Overflow"): ("current", "manhole overflow"),
    ("Water System", "Excessive Water In Basement (WEFB)"): ("legacy", "water in basement"),
    ("Water Maintenance", "Water in Basement"): ("current", "water in basement"),
}
#: twin rule of statement step 3 [P]: created this close in time, s, and placed this close, m
TWIN_S = sightings.DUPLICATE_S
TWIN_M = sightings.DUPLICATE_M
COLUMNS = [
    "unique_key",
    "created_date",
    "local_day",
    "complaint_type",
    "descriptor",
    "scheme",
    "kind",
    "borough",
    "incident_address",
    "latitude",
    "longitude",
]


def _where_types() -> str:
    pairs = " OR ".join(
        f"(complaint_type='{c}' AND descriptor='{d}')" for c, d in sorted(FLOOD_TYPES)
    )
    return f"({pairs})"


def queries(
    window: tuple[str, str], box: tuple[float, float, float, float]
) -> dict[str, dict[str, str]]:
    """The two queries of statement step 1 for a window ``(first, last)`` of local days.

    ``box`` is west, south, east, north in degrees.
    """
    first, last = window
    when = f"created_date between '{first}T00:00:00' and '{last}T23:59:59'"
    west, south, east, north = box
    placed = {
        "$where": f"{when} AND within_box(location, {north}, {west}, {south}, {east})",
        "$order": "unique_key",
        "$limit": str(PAGE),
    }
    boroughs = ", ".join(f"'{b}'" for b in BOROUGHS)
    unplaced = {
        "$select": "borough, complaint_type, descriptor, count(*) AS n",
        "$where": f"{when} AND location IS NULL AND borough IN ({boroughs}) AND {_where_types()}",
        "$group": "borough, complaint_type, descriptor",
        "$order": "borough, complaint_type, descriptor",
    }
    return {"placed": placed, "unplaced": unplaced}


def _get(params: dict[str, str]) -> tuple[str, bytes]:
    """One GET with curl (as ``assets.contact_sheet``; Python's own TLS store fails here)."""
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        done = subprocess.run(  # noqa: S603
            ["curl", "-sS", "--fail", "--max-time", "180", "-A", "flood-lab/0.1", url],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if done.returncode == 0:
            return url, done.stdout
        if attempt == 3:
            raise OSError(f"curl {done.returncode}: {done.stderr.decode(errors='replace')}")
        time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
    return hashlib.sha256(data).hexdigest()


def flood_query(window: tuple[str, str], box: tuple[float, float, float, float]) -> dict[str, str]:
    """Statement step 1b: the flooding-related requests only, in the box, over a longer window.

    Used for the late-call and baseline counts; the same box and the same ``FLOOD_TYPES``.
    """
    first, last = window
    west, south, east, north = box
    return {
        "$where": f"created_date between '{first}T00:00:00' and '{last}T23:59:59' AND "
        f"within_box(location, {north}, {west}, {south}, {east}) AND {_where_types()}",
        "$order": "unique_key",
        "$limit": str(PAGE),
    }


def _fetch_pages(folder: Path, asked: dict[str, str]) -> list[dict[str, Any]]:
    pages, offset = [], 0
    while True:
        params = dict(asked, **{"$offset": str(offset)})
        url, data = _get(params)
        rows = json.loads(data)
        name = f"page_{len(pages) + 1}.json"
        pages.append(
            {
                "file": name,
                "url": url,
                "rows": len(rows),
                "bytes": len(data),
                "sha256": _write(folder / name, data),
                "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        if len(rows) < PAGE:
            break
        offset += PAGE
    return pages


def fetch(
    root: Path, storm: str, window: tuple[str, str], box: tuple[float, float, float, float]
) -> dict[str, Any]:
    """Statement step 1, over the network. Writes the raw pages and ``query.json``."""
    folder = root / FOLDER / storm
    asked = queries(window, box)
    pages = _fetch_pages(folder, asked["placed"])
    url, data = _get(asked["unplaced"])
    unplaced = {
        "file": f"unplaced_{storm}.json",
        "url": url,
        "bytes": len(data),
        "sha256": _write(folder / f"unplaced_{storm}.json", data),
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    query = {
        "dataset": DATASET,
        "endpoint": ENDPOINT,
        "storm": storm,
        "window_local_days": list(window),
        "box_west_south_east_north": list(box),
        "queries": asked,
        "pages": pages,
        "unplaced": unplaced,
    }
    _write(folder / "query.json", json.dumps(query, indent=1).encode())
    return query


def fetch_flood(
    root: Path, name: str, window: tuple[str, str], box: tuple[float, float, float, float]
) -> dict[str, Any]:
    """Statement step 1b, over the network: pages and ``query.json`` under ``nyc-311/<name>/``."""
    folder = root / FOLDER / name
    asked = flood_query(window, box)
    query = {
        "dataset": DATASET,
        "endpoint": ENDPOINT,
        "name": name,
        "what": "flooding-related requests only (FLOOD_TYPES), placed in the box",
        "window_local_days": list(window),
        "box_west_south_east_north": list(box),
        "queries": {"placed": asked},
        "pages": _fetch_pages(folder, asked),
    }
    _write(folder / "query.json", json.dumps(query, indent=1).encode())
    return query


def read(root: Path, storm: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Every cached request of a storm (all types), with the scheme and kind of statement step 3."""
    folder = root / FOLDER / storm
    query = json.loads((folder / "query.json").read_text())
    rows: list[dict[str, Any]] = []
    for page in query["pages"]:
        rows += json.loads((folder / page["file"]).read_text())
    return requests_table(rows), query


def requests_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Statement steps 2 and 3 on raw API rows."""
    table = pd.DataFrame(rows)
    for column in (
        "unique_key",
        "created_date",
        "complaint_type",
        "descriptor",
        "borough",
        "incident_address",
    ):
        if column not in table:
            table[column] = pd.Series(dtype="object")
    for column in ("latitude", "longitude"):
        table[column] = pd.to_numeric(table.get(column), errors="coerce")
    table["local_day"] = table["created_date"].astype(str).str.slice(0, 10)
    mapped = [
        FLOOD_TYPES.get((str(c), str(d)))
        for c, d in zip(table["complaint_type"], table["descriptor"], strict=True)
    ]
    table["scheme"] = [m[0] if m else None for m in mapped]
    table["kind"] = [m[1] if m else None for m in mapped]
    return table[COLUMNS].sort_values("unique_key", kind="stable").reset_index(drop=True)


def unplaced(root: Path, storm: str) -> list[dict[str, Any]]:
    folder = root / FOLDER / storm
    return json.loads((folder / f"unplaced_{storm}.json").read_text())


def twins(
    table: pd.DataFrame,
    x: pd.Series | None = None,
    y: pd.Series | None = None,
    max_s: float = TWIN_S,
    max_m: float = TWIN_M,
) -> list[dict[str, Any]]:
    """Statement step 3: pairs of one current-scheme and one legacy-scheme row of one request.

    ``x`` and ``y`` are projected positions in metres (same index as ``table``); without them only
    the address is used. The rule is the strict case of ``observations.sightings``
    (``duplicate_pairs``, rule step 2), with the scheme as the copy.
    """
    flood = table[table["scheme"].notna()]
    return sightings.duplicate_pairs(
        flood, copy="scheme", first="current", second="legacy", x=x, y=y, max_s=max_s, max_m=max_m
    )
