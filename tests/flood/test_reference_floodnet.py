"""FS3, FS4: the second reader of the FloodNet tables, on two small CSV files built here.

Two sensors and five events. Sensor A's events cross local midnight in summer time (the 03:30 GMT
event is still the previous New York day); sensor B's cross the end of summer time on 2023-11-05
(01:30 EDT and 01:30 EST are an hour apart) and a winter midnight. Sensor B is removed on
2023-11-05, the day of its last events.
"""

from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import pytest

from flood_lab import cache
from flood_lab.reference import floodnet
from flood_lab.reference.compare import compare_tables, outcome

EVENT_FIELDS = [
    "sensor_name",
    "sensor_id",
    "flood_start_time",
    "flood_end_time",
    "max_depth_inches",
    "onset_time_mins",
    "drain_time_mins",
    "duration_mins",
    "duration_above_4_inches_mins",
    "duration_above_12_inches_mins",
    "duration_above_24_inches_mins",
    "flood_profile_depth_inches",
    "flood_profile_time_secs",
]
SENSOR_FIELDS = [
    "sensor_name",
    "sensor_id",
    "date_installed",
    "tidally_influenced",
    "date_removed",
    "borough",
    "latitude",
    "longitude",
]
SENSORS = [
    ("A", "BK-a", "2021-08-01T00:00:00.000", "", "Brooklyn", "40.70", "-73.96"),
    ("B", "Q-b", "2023-01-01T00:00:00.000", "2023-11-05T00:00:00.000", "Queens", "40.69", "-73.79"),
]
#: sensor, start, end, peak in, minutes
EVENTS = [
    ("BK-a", "2021-09-02T01:30:00.000", "2021-09-02T02:30:00.000", "10.00", "60"),
    ("BK-a", "2021-09-02T03:30:00.000", "2021-09-02T04:00:00.000", "5.00", "30"),
    ("BK-a", "2021-09-02T04:30:00.000", "2021-09-02T05:00:00.000", "2.00", "30"),
    ("Q-b", "2023-11-06T04:30:00.000", "2023-11-06T05:15:00.000", "3.00", "45"),
    ("Q-b", "2023-11-05T05:30:00.000", "2023-11-05T06:30:00.000", "4.00", "60"),
]


def write_events(path: Path, events: list[tuple[str, ...]], profiles: dict[int, str] | None = None):
    profiles = profiles or {}
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, EVENT_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for i, (sensor, start, end, peak, minutes) in enumerate(events):
            writer.writerow(
                {
                    "sensor_name": sensor,
                    "sensor_id": sensor,
                    "flood_start_time": start,
                    "flood_end_time": end,
                    "max_depth_inches": peak,
                    "onset_time_mins": "1",
                    "drain_time_mins": "1",
                    "duration_mins": minutes,
                    "duration_above_4_inches_mins": "0",
                    "duration_above_12_inches_mins": "0",
                    "duration_above_24_inches_mins": "0",
                    "flood_profile_depth_inches": profiles.get(i, f"[0.00, {peak}, 0.00]"),
                    "flood_profile_time_secs": "[0, 60, 120]",
                }
            )
    return path


def write_sensors(path: Path, sensors=SENSORS) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(SENSOR_FIELDS)
        for name, sid, installed, removed, borough, lat, lon in sensors:
            writer.writerow([name, sid, installed, "No", removed, borough, lat, lon])
    return path


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    return write_events(tmp_path / "events.csv", EVENTS), write_sensors(tmp_path / "sensors.csv")


def test_events_are_read_as_gmt_and_dated_in_new_york(files: tuple[Path, Path]) -> None:
    rows = floodnet.events(*files)
    assert [(r["sensor_id"], r["start_utc"], r["local_day"]) for r in rows] == [
        ("BK-a", "2021-09-02T01:30:00Z", "2021-09-01"),
        ("BK-a", "2021-09-02T03:30:00Z", "2021-09-01"),
        ("BK-a", "2021-09-02T04:30:00Z", "2021-09-02"),
        ("Q-b", "2023-11-05T05:30:00Z", "2023-11-05"),
        ("Q-b", "2023-11-06T04:30:00Z", "2023-11-05"),
    ]
    first = rows[0]
    assert first["end_utc"] == "2021-09-02T02:30:00Z"
    assert first["peak_depth_m"] == 10.0 * 0.0254
    assert first["duration_min"] == 60.0
    assert (first["longitude"], first["latitude"]) == (-73.96, 40.70)


def test_an_event_of_a_sensor_not_in_the_table_has_no_place(tmp_path: Path) -> None:
    events = write_events(tmp_path / "e.csv", [("X-none", *EVENTS[0][1:])])
    rows = floodnet.events(events, write_sensors(tmp_path / "s.csv"))
    assert rows[0]["longitude"] is None and rows[0]["latitude"] is None


def test_a_time_with_milliseconds_stops_the_reader(tmp_path: Path) -> None:
    events = write_events(tmp_path / "e.csv", [("BK-a", "2021-09-02T01:30:00.250", *EVENTS[0][2:])])
    with pytest.raises(ValueError, match="non-zero fraction"):
        floodnet.events(events, write_sensors(tmp_path / "s.csv"))


def test_consistency_counts_nothing_on_a_consistent_file(files: tuple[Path, Path]) -> None:
    checks = floodnet.consistency(*files)
    assert {k: checks[k] for k in ("rows", "profile_peak_differs", "duration_differs")} == {
        "rows": 5,
        "profile_peak_differs": 0,
        "duration_differs": 0,
    }
    assert checks["duplicate_keys"] == 0 and checks["unknown_sensor"] == 0


def test_consistency_counts_each_kind_of_fault(tmp_path: Path) -> None:
    events = [*EVENTS, EVENTS[0], ("X-none", *EVENTS[1][1:])]
    events[2] = (*EVENTS[2][:4], "30.03")  # end minus start is 30 min: off by 0.03 min
    path = write_events(tmp_path / "e.csv", events, profiles={1: "[0.00, 4.99, 0.00]"})
    checks = floodnet.consistency(path, write_sensors(tmp_path / "s.csv"))
    # the profile of row 1 peaks 0.01 in below max_depth_inches
    assert checks["profile_peak_differs"] == 1
    assert checks["duration_differs"] == 1
    assert checks["duplicate_keys"] == 1 and checks["duplicate_rows"] == 1
    assert checks["unknown_sensor"] == 1
    assert floodnet.consistency(path)["unknown_sensor"] is None


def test_storm_sensors_follow_the_deployment_rule(files: tuple[Path, Path]) -> None:
    ida = floodnet.storm_sensors(*files, "2021-09-01")
    assert [(r["sensor_id"], r["recorded"], r["peak_depth_m"]) for r in ida] == [
        ("BK-a", True, 10.0 * 0.0254)
    ]
    assert ida[0]["borough"] == "Brooklyn"
    # removed on 2023-11-05: still deployed that day, not the next
    nov5 = floodnet.storm_sensors(*files, "2023-11-05")
    assert [(r["sensor_id"], r["recorded"], r["peak_depth_m"]) for r in nov5] == [
        ("BK-a", False, None),
        ("Q-b", True, 4.0 * 0.0254),
    ]
    assert [r["sensor_id"] for r in floodnet.storm_sensors(*files, "2023-11-06")] == ["BK-a"]
    assert floodnet.storm_sensors(*files, "2021-07-31") == []


def _table(files: tuple[Path, Path]) -> list[dict]:
    return floodnet.events(*files)


KEY = ("sensor_id", "start_utc")
EXACT = ("end_utc", "local_day", "duration_min", "longitude", "latitude")
CLOSE = {"peak_depth_m": 1e-6}


def test_the_same_table_is_confirmed(files: tuple[Path, Path]) -> None:
    result = compare_tables(_table(files), _table(files), KEY, EXACT, CLOSE)
    assert outcome(result) == "confirmed"


def test_a_dropped_row_differs(files: tuple[Path, Path]) -> None:
    good = _table(files)
    result = compare_tables(good, good[:2] + good[3:], KEY, EXACT, CLOSE)
    assert outcome(result) == "differs" and result["only_in_a"] == 1


def test_a_changed_date_differs(files: tuple[Path, Path]) -> None:
    good = _table(files)
    bad = [dict(r) for r in good]
    bad[4]["end_utc"] = "2023-11-07T05:15:00Z"
    result = compare_tables(good, bad, KEY, EXACT, CLOSE)
    assert outcome(result) == "differs" and result["columns"]["end_utc"]["differ"] == 1


def test_a_depth_off_by_a_millimetre_differs(files: tuple[Path, Path]) -> None:
    good = _table(files)
    bad = [dict(r) for r in good]
    bad[0]["peak_depth_m"] += 0.001
    result = compare_tables(good, bad, KEY, EXACT, CLOSE)
    assert outcome(result) == "differs" and result["columns"]["peak_depth_m"]["differ"] == 1
    bad[0]["peak_depth_m"] = good[0]["peak_depth_m"] + 1e-9
    assert outcome(compare_tables(good, bad, KEY, EXACT, CLOSE)) == "confirmed"


def test_a_day_taken_in_gmt_differs_for_the_0330_event(files: tuple[Path, Path]) -> None:
    good = _table(files)
    gmt_days = [dict(r, local_day=r["start_utc"][:10]) for r in good]
    result = compare_tables(good, gmt_days, KEY, EXACT, CLOSE)
    assert outcome(result) == "differs"
    assert ("BK-a", "2021-09-02T03:30:00Z") in result["columns"]["local_day"]["first"]
    # a fixed summer offset of four hours puts the winter-evening event on the wrong day
    four_hours = [
        dict(
            r,
            local_day=(floodnet.parse_gmt(r["start_utc"][:19]) - timedelta(hours=4))
            .date()
            .isoformat(),
        )
        for r in good
    ]
    result = compare_tables(good, four_hours, KEY, EXACT, CLOSE)
    assert result["columns"]["local_day"]["first"] == [("Q-b", "2023-11-06T04:30:00Z")]


EVENTS_CSV = cache.root() / "floodnet-flood-events" / "aq7i-eu5q.csv"
SENSORS_CSV = cache.root() / "floodnet-sensors" / "kb2e-tjy3.csv"


@pytest.mark.skipif(not EVENTS_CSV.exists(), reason="needs the cached FloodNet tables")
def test_real_tables_give_the_f0_storm_counts_for_brooklyn_and_queens() -> None:
    found = {}
    for day in ("2021-09-01", "2023-09-29"):
        rows = [
            r
            for r in floodnet.storm_sensors(EVENTS_CSV, SENSORS_CSV, day)
            if r["borough"] in ("Brooklyn", "Queens")
        ]
        found[day] = (len(rows), sum(r["recorded"] for r in rows))
    assert found == {"2021-09-01": (9, 5), "2023-09-29": (44, 17)}
    assert len(floodnet.events(EVENTS_CSV, SENSORS_CSV)) == 3611
