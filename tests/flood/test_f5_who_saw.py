"""F5 second part: the readers of Storm Events, 311 and the Jamaica Bay map, and the counting (FV3,
FV5). Offline, on small made-up fixtures written in each test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import shapely

from flood_lab.checks import f5_who_saw as f5b
from flood_lab.domain import SQUARE
from flood_lab.sources import jamaica_bay, nyc_311, storm_events

# a point inside the square (Williamsburg) and one outside it (Park Slope), in degrees
IN_LON, IN_LAT = -73.9600, 40.7100
OUT_LON, OUT_LAT = -73.9800, 40.6650

HEADER = (
    "BEGIN_YEARMONTH,EPISODE_ID,EVENT_ID,STATE,EVENT_TYPE,CZ_TYPE,CZ_FIPS,CZ_NAME,WFO,"
    "BEGIN_DATE_TIME,CZ_TIMEZONE,END_DATE_TIME,BEGIN_LAT,BEGIN_LON,END_LAT,END_LON"
)


def _details(tmp_path, rows: list[str]):
    path = tmp_path / "details.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n")
    return path


def test_offset_and_clock_rule() -> None:
    assert storm_events.offset_hours("EST-5") == -5
    assert storm_events.offset_hours("CST-6") == -6
    with pytest.raises(ValueError):
        storm_events.offset_hours("EST")
    # 23:30 EST on 1 Sep is 04:30 UTC on 2 Sep, which is 00:30 EDT on 2 Sep in New York
    utc = storm_events.to_utc(pd.Series(["01-SEP-21 23:30:00"]), pd.Series(["EST-5"]))
    assert utc.iloc[0].isoformat() == "2021-09-02T04:30:00+00:00"


def test_storm_events_reads_counties_and_zones(tmp_path) -> None:
    path = _details(
        tmp_path,
        [
            # Kings county, inside the square by its begin point, wall-clock day 2 Sep
            f"202109,1,11,NEW YORK,Flash Flood,C,47,KINGS,OKX,01-SEP-21 23:30:00,EST-5,"
            f"01-SEP-21 23:50:00,{IN_LAT},{IN_LON},{IN_LAT},{IN_LON}",
            # Kings zone, coastal flood, no coordinates
            "202109,1,12,NEW YORK,Coastal Flood,Z,75,KINGS (BROOKLYN),OKX,01-SEP-21 10:00:00,"
            "EST-5,01-SEP-21 12:00:00,,,,",
            # Queens county: not the square's
            f"202109,1,13,NEW YORK,Flash Flood,C,81,QUEENS,OKX,01-SEP-21 10:00:00,EST-5,"
            f"01-SEP-21 11:00:00,{OUT_LAT},{OUT_LON},{OUT_LAT},{OUT_LON}",
            # not a flood type
            "202109,1,14,NEW YORK,Hail,C,47,KINGS,OKX,01-SEP-21 10:00:00,EST-5,"
            "01-SEP-21 11:00:00,,,,",
        ],
    )
    table = storm_events.events(path)
    assert list(table["event_id"]) == [11, 12, 13]
    assert list(table["in_counties_or_zones"]) == [True, True, False]
    first = table.iloc[0]
    assert first["begin_day_as_written"] == "2021-09-01"
    assert first["begin_local_day"] == "2021-09-02"
    one = f5b.count_storm_events(table, ("2021-09-01",))
    assert one["context"] == 1 and one["zone_events"] == 1 and one["main"] == 0
    both = f5b.count_storm_events(table, ("2021-09-01", "2021-09-02"))
    assert both["context"] == 2 and both["main"] == 1
    assert both["begin_day_as_written_matches"] == 2


def test_storm_events_locations_file_adds_points(tmp_path) -> None:
    path = _details(
        tmp_path,
        [
            f"202309,2,21,NEW YORK,Flash Flood,C,47,KINGS,OKX,29-SEP-23 09:00:00,EST-5,"
            f"29-SEP-23 09:30:00,{OUT_LAT},{OUT_LON},{OUT_LAT},{OUT_LON}",
        ],
    )
    locations = tmp_path / "locations.csv"
    locations.write_text(
        "YEARMONTH,EPISODE_ID,EVENT_ID,LOCATION_INDEX,LATITUDE,LONGITUDE\n"
        f"202309,2,21,1,{IN_LAT},{IN_LON}\n"
    )
    assert f5b.count_storm_events(storm_events.events(path), ("2023-09-29",))["main"] == 0
    table = storm_events.events(path, locations)
    assert len(table.iloc[0]["points"]) == 3
    assert f5b.count_storm_events(table, ("2023-09-29",))["main"] == 1


def _row(key, when, ctype, desc, lon=IN_LON, lat=IN_LAT, address="1 TEST STREET"):
    return {
        "unique_key": key,
        "created_date": when,
        "complaint_type": ctype,
        "descriptor": desc,
        "borough": "BROOKLYN",
        "incident_address": address,
        "latitude": str(lat),
        "longitude": str(lon),
    }


def test_311_both_schemes_and_twins() -> None:
    rows = [
        # one request recorded twice, two minutes apart: one twin pair
        _row("1", "2023-09-29T09:00:00.000", "Sewer Maintenance", "Flooding on Street"),
        _row("2", "2023-09-29T09:02:00.000", "Sewer", "Street Flooding (SJ)"),
        # legacy only, other address
        _row(
            "3",
            "2023-09-29T10:00:00.000",
            "Sewer",
            "Sewer Backup (Use Comments) (SA)",
            address="9 OTHER STREET",
            lon=-73.9500,
            lat=40.7000,
        ),
        # same address and kind but an hour later: not a twin
        _row("4", "2023-09-29T10:00:00.000", "Sewer", "Street Flooding (SJ)"),
        # outside the square
        _row(
            "5",
            "2023-09-29T09:00:00.000",
            "Sewer",
            "Street Flooding (SJ)",
            OUT_LON,
            OUT_LAT,
            "5 FAR STREET",
        ),
        # other day
        _row("6", "2023-09-30T09:00:00.000", "Sewer", "Street Flooding (SJ)"),
        # not flooding-related
        _row("7", "2023-09-29T09:00:00.000", "Noise", "Loud Music/Party"),
        # no location
        _row("8", "2023-09-29T09:00:00.000", "Sewer", "Street Flooding (SJ)", "", "", "8 NOWHERE"),
    ]
    table = nyc_311.requests_table(rows)
    assert table.set_index("unique_key").loc["1", "scheme"] == "current"
    assert table.set_index("unique_key").loc["2", "kind"] == "street flooding"
    assert pd.isna(table.set_index("unique_key").loc["7", "scheme"])
    pairs = nyc_311.twins(table)
    assert [(p["current"], p["legacy"]) for p in pairs] == [("1", "2")]
    unplaced = [{"borough": "BROOKLYN", "complaint_type": "Sewer", "descriptor": "x", "n": "3"}]
    c = f5b.count_311(table, ("2023-09-29",), unplaced)
    assert c["context"] == 4  # rows 1-4 in the square on the day
    assert c["legacy_rows"] == 3 and c["current_rows"] == 1
    assert c["twin_pairs"] == 1 and c["main"] == 3
    assert c["unplaced_in_boroughs"] == 3
    assert c["by_kind"]["street flooding"] == {"legacy_rows": 2, "current_rows": 1, "requests": 2}
    # CH-24: over the 311 window (the storm day and the day after) row 6 counts too
    assert f5b.window_311(("2023-09-29",)) == ("2023-09-29", "2023-09-30")
    w = f5b.count_311(table, f5b.window_311(("2023-09-29",)), unplaced)
    assert w["context"] == 5 and w["main"] == 4 and w["twin_pairs"] == 1


def test_311_twins_by_position_when_addresses_differ() -> None:
    rows = [
        _row("1", "2023-09-29T09:00:00.000", "Sewer Maintenance", "Backup", address="A"),
        _row(
            "2", "2023-09-29T09:01:00.000", "Sewer", "Sewer Backup (Use Comments) (SA)", address="B"
        ),
    ]
    table = nyc_311.requests_table(rows)
    assert nyc_311.twins(table) == []
    x = pd.Series([0.0, 10.0], index=table.index)
    y = pd.Series([0.0, 0.0], index=table.index)
    assert len(nyc_311.twins(table, x, y)) == 1
    assert nyc_311.twins(table, x, y, max_m=5.0) == []


def test_311_queries_name_both_schemes() -> None:
    q = nyc_311.queries(("2021-09-01", "2021-09-02"), (-74.0, 40.6, -73.9, 40.8))
    assert "within_box(location, 40.8, -74.0, 40.6, -73.9)" in q["placed"]["$where"]
    assert "'2021-09-02T23:59:59'" in q["placed"]["$where"]
    where = q["unplaced"]["$where"]
    assert "complaint_type='Sewer Maintenance'" in where and "complaint_type='Sewer'" in where


def test_groundsource_counting() -> None:
    square = f5b.square_lonlat()
    small = shapely.box(IN_LON - 0.001, IN_LAT - 0.001, IN_LON + 0.001, IN_LAT + 0.001)
    big = shapely.box(-74.1, 40.6, -73.8, 40.8)
    away = shapely.box(OUT_LON - 0.001, OUT_LAT - 0.001, OUT_LON + 0.001, OUT_LAT + 0.001)
    table = pd.DataFrame(
        {
            "uuid": ["a", "b", "c", "d"],
            "start_date": ["2021-09-01", "2021-08-30", "2021-09-01", "2021-09-03"],
            "end_date": ["2021-09-01", "2021-09-02", "2021-09-01", "2021-09-03"],
            "area_km2": [0.05, 600.0, 0.05, 0.05],
            "geometry_wkb": [shapely.to_wkb(g) for g in (small, big, away, small)],
            "centroid_lon": [IN_LON, -73.95, OUT_LON, IN_LON],
            "centroid_lat": [IN_LAT, 40.70, OUT_LAT, IN_LAT],
        }
    )
    c = f5b.count_groundsource(table, ("2021-09-01", "2021-09-02"), square)
    assert c["context"] == 2  # a and b touch the square; c is away; d is another day
    assert c["main"] == 2  # both centroids lie in the square
    assert c["larger_than_square"] == 1
    assert [r["uuid"] for r in c["rows"] if r["contains_square"]] == ["b"]


def test_floodnet_counting_over_two_days(tmp_path) -> None:
    sensors = tmp_path / "sensors.csv"
    sensors.write_text(
        "sensor_id,longitude,latitude,borough,date_installed,date_removed\n"
        f"in1,{IN_LON},{IN_LAT},Brooklyn,2021-01-01T00:00:00,\n"
        f"in2,{IN_LON + 0.001},{IN_LAT},Brooklyn,2021-09-02T00:00:00,\n"
        f"out,{OUT_LON},{OUT_LAT},Brooklyn,2021-01-01T00:00:00,2030-01-01T00:00:00\n"
    )
    events = pd.DataFrame(
        {
            "sensor_id": ["in2", "out"],
            "local_day": ["2021-09-02", "2021-09-01"],
            "peak_depth_m": [0.2, 0.5],
        }
    )
    c = f5b.count_floodnet(events, sensors, ("2021-09-01", "2021-09-02"))
    assert c["context"] == 2 and c["main"] == 1
    assert [r["recorded_on"] for r in c["rows"]] == [[], ["2021-09-02"]]


def test_marks_counting() -> None:
    west, south, *_ = SQUARE
    rows = [
        {"hwm_id": 1, "site_no": "A", "easting_m": west + 10, "northing_m": south + 10},
        {"hwm_id": 2, "site_no": "A", "easting_m": west + 12, "northing_m": south + 10},
        {"hwm_id": 3, "site_no": "B", "easting_m": west - 10, "northing_m": south + 10},
    ]
    c = f5b.count_marks(rows, "ida_2021")
    assert (c["main"], c["context"]) == (2, 1)
    assert f5b.count_marks(rows, "sep29_2023")["main"] is None


def test_inside_edges() -> None:
    west, south, east, north = SQUARE
    assert list(f5b.inside([west, east, west], [south, south, north])) == [True, False, False]


def test_jamaica_bay_overlap_and_result() -> None:
    west, south, east, north = SQUARE
    # a 3 x 3 grid of points 30 m apart, the middle column on the square's west edge
    xs, ys = np.meshgrid(west + np.array([-30.0, 0.0, 30.0]), south + 100 + np.arange(3) * 30.0)
    x, y = xs.ravel(), ys.ravel()
    assert jamaica_bay.spacing(x, y) == pytest.approx(30.0)
    o = jamaica_bay.overlap(x, y, 30.0, SQUARE)
    assert o["points_inside"] == 6
    assert o["overlap_area_m2"] == pytest.approx(45.0 * 90.0)
    assert o["nearest_distance_m"] == 0.0
    r = f5b.fv3_result(o)
    assert not r["applicable"] and "below" in r["statement"]
    far = jamaica_bay.overlap(x, y - 3000.0, 30.0, SQUARE)
    assert far["points_inside"] == 0 and far["overlap_area_m2"] == 0.0
    assert far["nearest_distance_m"] == pytest.approx(3000.0 - 100.0 - 60.0)
    assert "Not applicable" in f5b.fv3_result(far)["statement"]
    big = jamaica_bay.overlap(xs.ravel() + 500, ys.ravel(), 1000.0, SQUARE)
    assert f5b.fv3_result(big)["applicable"]
    assert east > west and north > south


def test_jamaica_bay_depth_unit_evidence() -> None:
    attributes = {
        "water_elev": np.array([1.05, 2.40, 3.00, 5.00]),
        "dem_m": np.array([1.00, 2.20, 2.50, 3.00]),
        "flood_dept": np.array([0.05, 0.20, 0.50, 0.91]),  # last capped at the class-3 bound
        "class": np.array([0, 1, 2, 3]),
    }
    u = jamaica_bay.depth_unit(attributes)
    assert u["rows_equal_to_water_elev_minus_dem_m"] == 3
    assert u["rows_off_equal_and_class_3"] == 1
    assert u["rows_inside_their_class_bounds_in_m"] == 4
    assert u["flood_dept_max"] == 0.91
    # depths in feet would break the class bounds
    feet = dict(attributes, flood_dept=attributes["flood_dept"] / 0.3048)
    assert jamaica_bay.depth_unit(feet)["rows_inside_their_class_bounds_in_m"] < 4
