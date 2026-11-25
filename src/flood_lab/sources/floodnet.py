"""FloodNet: one row per sensor and flood event, and the same rows in CRC (FS3).

Transformation statement (the data card repeats it):

1. The flood-events table (NYC Open Data ``aq7i-eu5q``) has one row per event a sensor recorded;
   the sensor table (``kb2e-tjy3``) gives each sensor's position and dates of service.
2. Times are GMT, written without a zone; they are kept as GMT (``start_utc``, ``end_utc``) and
   the New York calendar day of the start is added (``local_day``).
3. ``peak_depth_m`` is the publisher's ``max_depth_inches`` times 0.0254. ``duration_min`` is the
   publisher's ``duration_mins``. Neither is recomputed from the depth profile.
4. Longitude and latitude come from the sensor table by ``sensor_id``.
5. For CRC the rows go to ``Observations.from_table``: station is the sensor, time the start in
   GMT, value the peak depth in metres. Duration and the end time have no place in that record
   and stay in the lab's table.

A sensor measures water under itself at one point of a street. No event is not no flood nearby.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from flood_lab import localtime

EVENTS = "floodnet-flood-events/aq7i-eu5q.csv"
SENSORS = "floodnet-sensors/kb2e-tjy3.csv"
INCH_M = 0.0254
STAMP = "%Y-%m-%dT%H:%M:%SZ"
COLUMNS = [
    "sensor_id",
    "start_utc",
    "end_utc",
    "local_day",
    "peak_depth_m",
    "duration_min",
    "longitude",
    "latitude",
]


def events(events_csv: Path, sensors_csv: Path) -> pd.DataFrame:
    """Statement steps 1 to 4: one row per event, sorted by sensor and start."""
    raw = pd.read_csv(events_csv, dtype={"sensor_id": "string"})
    sensors = pd.read_csv(sensors_csv, dtype={"sensor_id": "string"})
    start = pd.to_datetime(raw["flood_start_time"], utc=True)
    end = pd.to_datetime(raw["flood_end_time"], utc=True)
    table = pd.DataFrame(
        {
            "sensor_id": raw["sensor_id"],
            "start_utc": start.dt.strftime(STAMP),
            "end_utc": end.dt.strftime(STAMP),
            "local_day": localtime.local_day(raw["flood_start_time"]).to_numpy(),
            "peak_depth_m": raw["max_depth_inches"].astype(float) * INCH_M,
            "duration_min": raw["duration_mins"].astype(float),
        }
    )
    table = table.merge(
        sensors[["sensor_id", "longitude", "latitude"]], on="sensor_id", how="left", validate="m:1"
    )
    return table.sort_values(["sensor_id", "start_utc"], kind="stable").reset_index(drop=True)[
        COLUMNS
    ]


def storm_sensors(table: pd.DataFrame, sensors_csv: Path, local_day: str) -> pd.DataFrame:
    """Sensors in service on a local day, and whether each recorded an event that day.

    In service: installed on or before the day and not removed before it. The two dates are
    calendar dates the publisher writes as midnight; the date part is taken as written.
    """
    sensors = pd.read_csv(sensors_csv, dtype={"sensor_id": "string"})
    installed = sensors["date_installed"].str.slice(0, 10)
    removed = sensors["date_removed"].str.slice(0, 10)
    serving = sensors[(installed <= local_day) & (removed.isna() | (removed >= local_day))]
    peak = table[table["local_day"] == local_day].groupby("sensor_id")["peak_depth_m"].max()
    out = serving[["sensor_id", "longitude", "latitude", "borough"]].copy()
    out["peak_depth_m"] = out["sensor_id"].map(peak)
    out["recorded"] = out["peak_depth_m"].notna()
    return out.sort_values("sensor_id").reset_index(drop=True)


def variable() -> Any:
    from crc_framework import DepthAboveGround, LengthUnit
    from crc_sdk import Variable

    return Variable(
        "flood-lab:floodnet-event-peak-depth",
        measurement=DepthAboveGround(unit=LengthUnit.METRE),
    )


def crc_table(table: pd.DataFrame) -> dict[str, list[Any]]:
    """Statement step 5: the rows given to ``Observations.from_table``."""
    placed = table[table["longitude"].notna() & table["latitude"].notna()]
    return {
        "support_id": placed["sensor_id"].astype(str).tolist(),
        "longitude": placed["longitude"].astype(float).tolist(),
        "latitude": placed["latitude"].astype(float).tolist(),
        "time": placed["start_utc"].tolist(),
        "value": placed["peak_depth_m"].astype(float).tolist(),
    }


def to_crc(rows: dict[str, list[Any]]) -> Any:
    """Load the events into CRC as observations and return what CRC reads back."""
    from crc_sdk import Observations

    return Observations.from_table(rows, variable=variable()).read().table


def read_back_differences(rows: dict[str, list[Any]], got: Any) -> dict[str, int]:
    """Rows of the CRC observations that differ from what was put in."""
    import shapely

    put = {
        (s, t): (v, x, y)
        for s, t, v, x, y in zip(
            rows["support_id"],
            rows["time"],
            rows["value"],
            rows["longitude"],
            rows["latitude"],
            strict=True,
        )
    }
    back: dict[tuple[str, str], tuple[float, float, float]] = {}
    for row in got.to_pylist():
        point = shapely.from_wkb(row["geometry"])
        stamp = pd.Timestamp(row["time"]).tz_convert("UTC").strftime(STAMP)
        back[(row["support_id"], stamp)] = (row["value"], point.x, point.y)
    shared = set(put) & set(back)
    return {
        "rows_in": len(put),
        "rows_back": got.num_rows,
        "missing": len(set(put) - set(back)),
        "extra": len(set(back) - set(put)),
        "value_differs": sum(put[k][0] != back[k][0] for k in shared),
        "position_differs": sum(put[k][1:] != back[k][1:] for k in shared),
    }
