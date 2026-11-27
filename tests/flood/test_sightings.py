"""F5c: the sighting rule (observations.sightings), the late-call baseline and the Groundsource
relations to the square. Offline, on small made-up fixtures written in each test."""

from __future__ import annotations

import pandas as pd
import shapely

from flood_lab.checks import f5_who_saw as f5
from flood_lab.domain import SQUARE
from flood_lab.observations import sightings as s
from flood_lab.sources import ghcn_daily, nyc_311

WEST, SOUTH, EAST, NORTH = SQUARE
X0, Y0 = WEST + 1000.0, SOUTH + 1000.0


def _obs(oid, when, dx=0.0, dy=0.0, source="nyc_311", kind="street flooding", until=None, rows=()):
    start = pd.Timestamp(when)
    return s.Observation(
        source=source,
        id=oid,
        kind=kind,
        start=start,
        end=pd.Timestamp(until) if until else start,
        x=X0 + dx,
        y=Y0 + dy,
        rows=tuple(rows),
    )


def _row(key, when, ctype, desc, address="1 TEST STREET"):
    return {
        "unique_key": key,
        "created_date": when,
        "complaint_type": ctype,
        "descriptor": desc,
        "borough": "BROOKLYN",
        "incident_address": address,
        "latitude": "40.71",
        "longitude": "-73.96",
    }


def test_exact_twins_are_one_observation_with_both_rows() -> None:
    table = nyc_311.requests_table(
        [
            _row("10", "2023-09-29T09:19:34.000", "Sewer Maintenance", "Backup"),
            _row("11", "2023-09-29T09:21:00.000", "Sewer", "Sewer Backup (Use Comments) (SA)"),
            # a second caller at the same address 20 minutes later: not a twin, but near
            _row("12", "2023-09-29T09:40:00.000", "Sewer", "Sewer Backup (Use Comments) (SA)"),
        ]
    )
    xs = pd.Series([X0, X0, X0], index=table.index)
    ys = pd.Series([Y0, Y0, Y0], index=table.index)
    pairs = nyc_311.twins(table, xs, ys)
    assert [(p["current"], p["legacy"], p["seconds"]) for p in pairs] == [("10", "11", 86.0)]
    obs = f5.observations_311(table, xs, ys, pairs)
    assert sorted(o.rows for o in obs) == [("10", "11"), ("12",)]
    one = s.describe(s.group(obs), "t")
    assert len(one) == 1 and one[0]["members"] == 2 and one[0]["rows"] == 3
    assert sorted(r for o in one[0]["observations"] for r in o["rows"]) == ["10", "11", "12"]


def test_duplicate_pairs_with_one_candidate_take_the_closest() -> None:
    rows = pd.DataFrame(
        {
            "unique_key": ["a", "b", "c"],
            "created_date": ["2023-09-29T09:00:00", "2023-09-29T09:05:00", "2023-09-29T09:01:00"],
            "kind": ["backup"] * 3,
            "incident_address": ["X"] * 3,
            "copy": ["one", "two", "two"],
        }
    )
    pairs = s.duplicate_pairs(rows, copy="copy", first="one", second="two")
    assert [(p["one"], p["two"]) for p in pairs] == [("a", "c")]


def test_two_requests_at_one_address_are_not_paired_crosswise() -> None:
    # 29 Sep 2023, 296 Broadway: two requests, each held under both schemes. Closest-first would
    # pair 09:20:09 with 09:20:00 (9 s) and leave 09:17:43 with 09:23:00 (317 s).
    rows = pd.DataFrame(
        {
            "unique_key": ["c1", "c2", "l1", "l2"],
            "created_date": [
                "2023-09-29T09:17:43",
                "2023-09-29T09:20:09",
                "2023-09-29T09:20:00",
                "2023-09-29T09:23:00",
            ],
            "kind": ["backup"] * 4,
            "incident_address": ["296 BROADWAY"] * 4,
            "copy": ["current", "current", "legacy", "legacy"],
        }
    )
    pairs = s.duplicate_pairs(rows, copy="copy", first="current", second="legacy")
    assert [(p["current"], p["legacy"], p["seconds"]) for p in pairs] == [
        ("c1", "l1", 137.0),
        ("c2", "l2", 171.0),
    ]


def test_chain_a_near_b_near_c_is_one_sighting() -> None:
    a = _obs("a", "2021-09-01T22:00")
    b = _obs("b", "2021-09-01T23:00", dx=40.0)
    c = _obs("c", "2021-09-02T01:00", dx=80.0)
    assert s.near(a, b) and s.near(b, c) and not s.near(a, c)
    groups = s.group([c, a, b])
    assert len(groups) == 1
    rows = s.describe(groups, "ida")
    assert rows[0]["sighting"] == "ida-001"
    assert rows[0]["extent_m"] == 80.0
    assert [o["id"] for o in rows[0]["observations"]] == ["a", "b", "c"]
    # with a tighter distance the chain breaks
    assert len(s.group([a, b, c], near_m=30.0)) == 3


def test_different_kinds_and_sources_at_one_spot_combine() -> None:
    call = _obs("call", "2023-09-29T09:00", kind="sewer backup")
    street = _obs("street", "2023-09-29T09:30", dx=10.0, kind="street flooding")
    sensor = _obs(
        "fn",
        "2023-09-29T08:40",
        dy=20.0,
        source="floodnet",
        kind="sensor event",
        until="2023-09-29T10:10",
    )
    rows = s.describe(s.group([call, street, sensor]), "x")
    assert len(rows) == 1
    assert rows[0]["sources"] == ["floodnet", "nyc_311"]
    assert rows[0]["kinds"] == ["sensor event", "sewer backup", "street flooding"]
    assert s.by_sources(rows) == {"floodnet + nyc_311": 1}
    # the sensitivity option keeps kinds apart
    assert len(s.group([call, street, sensor], same_kind=True)) == 3


def test_same_spot_on_different_days_stays_apart() -> None:
    first = _obs("d1", "2021-09-01T22:00")
    second = _obs("d2", "2021-09-03T10:00")
    assert len(s.group([first, second])) == 2
    # a mark spans the storm days and joins a call at its spot
    start, end = f5._storm_span(("2021-09-01", "2021-09-02"))
    mark = _obs("m", start, source="usgs_marks", kind="high-water mark", until=end, dx=5.0)
    assert len(s.group([first, mark])) == 1


def test_grouping_does_not_depend_on_order_and_disc_radius_counts() -> None:
    obs = [_obs(str(i), "2023-09-29T09:00", dx=45.0 * i) for i in range(4)]
    assert [len(g) for g in s.group(obs)] == [len(g) for g in s.group(obs[::-1])] == [4]
    far = _obs("far", "2023-09-29T09:00", dx=300.0)
    place = s.Observation(
        "groundsource", "p", "place", far.start, far.end, X0 + 150.0, Y0, radius_m=120.0
    )
    assert s.near(far, place) and not s.near(far, obs[0])
    table = s.sensitivity(obs + [far], [0.0, 50.0, 500.0], [3600.0])
    assert [r["sightings"] for r in table] == [5, 2, 1]


def test_area_reports_hold_members_but_link_nothing() -> None:
    call = _obs("c", "2023-09-29T09:00")
    other = _obs("o", "2023-09-29T09:00", dx=900.0)
    hull = shapely.box(X0 - 100, Y0 - 100, X0 + 100, Y0 + 100)
    area_list = [
        {
            "source": "storm_events",
            "id": "1",
            "shape": hull,
            "start": pd.Timestamp("2023-09-29T09:15"),
            "end": pd.Timestamp("2023-09-29T12:00"),
        }
    ]
    table = f5.sighting_table("t", [call, other], area_list)
    assert table["sightings"] == 2
    assert [r["inside_area_reports"] for r in table["rows"]] == [["storm_events:1"], []]
    assert table["inside_area_reports"] == {"groundsource": 0, "storm_events": 1}


def test_dry_days_rule() -> None:
    rain = ghcn_daily.table(
        [
            {"STATION": "A", "DATE": "2021-08-01", "PRCP": "0.0"},
            {"STATION": "A", "DATE": "2021-08-02", "PRCP": "0.5"},
            {"STATION": "A", "DATE": "2021-08-03", "PRCP": "0.0"},
            {"STATION": "B", "DATE": "2021-08-03", "PRCP": "1.2"},
            {"STATION": "A", "DATE": "2021-08-04", "PRCP": "0.0"},
            {"STATION": "A", "DATE": "2021-08-05", "PRCP": ""},
        ]
    )
    days = ["2021-08-02", "2021-08-03", "2021-08-04", "2021-08-05", "2021-08-06"]
    got = ghcn_daily.dry_days(rain, days, dry_mm=1.0, before=1)
    # 02: 0.5 and 0.0 the day before; 03: B has 1.2; 04: the day before wet;
    # 05: nobody reported; 06: not in the table
    assert got == {
        "2021-08-02": True,
        "2021-08-03": False,
        "2021-08-04": False,
        "2021-08-05": None,
        "2021-08-06": None,
    }


def test_late_calls_against_the_dry_baseline() -> None:
    days = [f"2021-08-{d:02d}" for d in range(1, 21)]
    daily = {d: {"rows": 2, "requests": 2} for d in days}
    daily["2021-08-10"] = {"rows": 40, "requests": 40}
    daily["2021-08-11"] = {"rows": 9, "requests": 9}
    daily["2021-08-12"] = {"rows": 3, "requests": 3}
    dry = {d: True for d in days}
    dry["2021-08-10"] = False
    got = f5.late_calls(daily, dry, {}, ("2021-08-01", "2021-08-20"), ("2021-08-10",))
    base = got["baseline"]
    # the storm day and the 7 days after (11 to 17) are kept out of the baseline
    assert base["n_days"] == 12 and base["mean"] == 2.0 and base["max"] == 2
    assert [(r["day"], r["clearly_above"]) for r in got["rows"]] == [
        ("2021-08-10", True),
        ("2021-08-11", True),
        ("2021-08-12", False),
    ]


def test_groundsource_relations_by_distance() -> None:
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)

    def box_deg(x0, y0, x1, y1):
        lons, lats = t.transform([x0, x1], [y0, y1])
        return shapely.box(lons[0], lats[0], lons[1], lats[1])

    shapes = {
        "in": box_deg(X0, Y0, X0 + 100, Y0 + 100),
        "edge": box_deg(EAST - 50, Y0, EAST + 500, Y0 + 100),  # overlaps, centroid outside
        "near": box_deg(EAST + 200, Y0, EAST + 300, Y0 + 100),  # 200 m away
        "far": box_deg(EAST + 400, Y0, EAST + 450, Y0 + 100),  # 400 m away
        "off": box_deg(EAST + 2000, Y0, EAST + 2100, Y0 + 100),
    }
    centroids = {k: v.centroid for k, v in shapes.items()}
    table = pd.DataFrame(
        {
            "uuid": list(shapes),
            "start_date": ["2021-09-01"] * 5,
            "end_date": ["2021-09-02"] * 5,
            "area_km2": [0.01] * 5,
            "geometry_wkb": [shapely.to_wkb(v) for v in shapes.values()],
            "centroid_lon": [c.x for c in centroids.values()],
            "centroid_lat": [c.y for c in centroids.values()],
        }
    )
    got = f5.groundsource_relations(table, ("2021-09-01",), f5.square_lonlat())
    assert got["counts"] == {
        "centroid_inside": 1,
        "overlapping": 2,
        "within_250_m": 3,
        "within_500_m": 4,
    }
    assert [r["uuid"] for r in got["rows"]] == ["in", "edge", "near", "far"]
