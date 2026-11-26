"""NOAA Storm Events: the flood events of a storm in the square's counties and zones (FV5, FT5).

Transformation statement:

1. The details file of a year (``StormEvents_details-ftp_v1.0_d<year>_c<created>.csv.gz``, NCEI
   bulk CSV) is read with pandas; rows of ``STATE`` NEW YORK whose ``EVENT_TYPE`` is in
   ``FLOOD_TYPES`` are kept. The locations file of the same year adds each event's further points
   (``LATITUDE``, ``LONGITUDE``) by ``EVENT_ID``.
2. **Clock rule.** ``BEGIN_DATE_TIME`` and ``END_DATE_TIME`` are written on the clock named in
   ``CZ_TIMEZONE`` (facts ``noaa-storm-events``, ``time_zone``: "EST-5" for every New York City row,
   also in September, when New York keeps daylight time). The offset is read from that field
   (``EST-5`` is UTC−5), the time is turned into UTC and then into the New York wall clock (zone
   database), and the event covers every New York calendar day from its begin to its end on that
   clock. The day on the clock as written is kept beside it (``begin_day_as_written``).
3. **Place.** ``CZ_TYPE`` C is a county, Z an NWS public forecast zone (Coastal Flood, Storm
   Surge/Tide and Lakeshore Flood are zone events). Both are read. An event is in the square's
   counties or zones when its county is in ``COUNTIES`` or its zone in ``ZONES``: Kings and New
   York, the two the square touches (Brooklyn 12.5 km², Manhattan 1.6 km² of land, from the city's
   2020 neighbourhood layer).
4. **Inside the square.** An event is inside when its begin point, its end point or one of its
   points in the locations file, projected to EPSG:32618, falls in ``domain.SQUARE``. An event in
   the counties or zones with no point inside is counted apart; it may still have touched the
   square, as a county or zone event names an area, not a spot.

An event is a forecaster's entry, not a measurement; no event is not no flood.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

FOLDER = "noaa-storm-events"
FLOOD_TYPES = (
    "Flash Flood",
    "Flood",
    "Heavy Rain",
    "Coastal Flood",
    "Storm Surge/Tide",
    "Lakeshore Flood",
    "Debris Flow",
)
#: CZ_FIPS of the square's counties (CZ_TYPE C) and NWS zones (CZ_TYPE Z, WFO OKX), as written
COUNTIES = {47: "KINGS", 61: "NEW YORK"}
ZONES = {75: "KINGS (BROOKLYN)", 72: "NEW YORK (MANHATTAN)"}
STAMP = "%d-%b-%y %H:%M:%S"
ZONE = "America/New_York"
COLUMNS = [
    "event_id",
    "episode_id",
    "event_type",
    "cz_type",
    "cz_fips",
    "cz_name",
    "cz_timezone",
    "begin_as_written",
    "end_as_written",
    "begin_day_as_written",
    "begin_utc",
    "end_utc",
    "begin_local_day",
    "end_local_day",
    "in_counties_or_zones",
    "points",
]


def offset_hours(cz_timezone: str) -> int:
    """UTC offset of a ``CZ_TIMEZONE`` value such as ``EST-5`` (−5) or ``CST-6``."""
    found = re.fullmatch(r"[A-Z]{3}([+-]\d{1,2})", str(cz_timezone).strip())
    if not found:
        raise ValueError(f"CZ_TIMEZONE {cz_timezone!r} has no offset")
    return int(found.group(1))


def to_utc(written: pd.Series, cz_timezone: pd.Series) -> pd.Series:
    """Statement step 2: a written time on its zone's clock, as UTC."""
    naive = pd.to_datetime(written, format=STAMP)
    hours = pd.Series([offset_hours(z) for z in cz_timezone], index=written.index)
    return (naive - pd.to_timedelta(hours, unit="h")).dt.tz_localize("UTC")


def events(details_csv: Path, locations_csv: Path | None = None) -> pd.DataFrame:
    """Statement steps 1 to 3: New York flood events with UTC times, local days and points."""
    raw = pd.read_csv(details_csv, low_memory=False)
    raw = raw[(raw["STATE"] == "NEW YORK") & raw["EVENT_TYPE"].isin(FLOOD_TYPES)].copy()
    begin = to_utc(raw["BEGIN_DATE_TIME"], raw["CZ_TIMEZONE"])
    end = to_utc(raw["END_DATE_TIME"], raw["CZ_TIMEZONE"])
    points: dict[int, list[tuple[float, float]]] = {}
    for _, r in raw.iterrows():
        own = [
            (float(r[f"{w}_LON"]), float(r[f"{w}_LAT"]))
            for w in ("BEGIN", "END")
            if pd.notna(r[f"{w}_LAT"]) and pd.notna(r[f"{w}_LON"])
        ]
        points[int(r["EVENT_ID"])] = own
    if locations_csv is not None:
        located = pd.read_csv(locations_csv)
        located = located[located["EVENT_ID"].isin(points)]
        for _, r in located.iterrows():
            if pd.notna(r["LATITUDE"]) and pd.notna(r["LONGITUDE"]):
                points[int(r["EVENT_ID"])].append((float(r["LONGITUDE"]), float(r["LATITUDE"])))
    fips = raw["CZ_FIPS"].astype(int)
    mine = ((raw["CZ_TYPE"] == "C") & fips.isin(COUNTIES)) | (
        (raw["CZ_TYPE"] == "Z") & fips.isin(ZONES) & (raw["WFO"] == "OKX")
    )
    table = pd.DataFrame(
        {
            "event_id": raw["EVENT_ID"].astype(int),
            "episode_id": raw["EPISODE_ID"].astype(int),
            "event_type": raw["EVENT_TYPE"],
            "cz_type": raw["CZ_TYPE"],
            "cz_fips": fips,
            "cz_name": raw["CZ_NAME"],
            "cz_timezone": raw["CZ_TIMEZONE"],
            "begin_as_written": raw["BEGIN_DATE_TIME"],
            "end_as_written": raw["END_DATE_TIME"],
            "begin_day_as_written": pd.to_datetime(
                raw["BEGIN_DATE_TIME"], format=STAMP
            ).dt.strftime("%Y-%m-%d"),
            "begin_utc": begin.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": end.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "begin_local_day": begin.dt.tz_convert(ZONE).dt.strftime("%Y-%m-%d"),
            "end_local_day": end.dt.tz_convert(ZONE).dt.strftime("%Y-%m-%d"),
            "in_counties_or_zones": mine,
            "points": [points[int(i)] for i in raw["EVENT_ID"]],
        }
    )
    return table.sort_values("event_id").reset_index(drop=True)[COLUMNS]


def covering(table: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    """Events whose local begin-to-end span holds one of the days (text dates sort as dates)."""
    hit = pd.Series(False, index=table.index)
    for day in days:
        hit |= (table["begin_local_day"] <= day) & (table["end_local_day"] >= day)
    return table[hit]
