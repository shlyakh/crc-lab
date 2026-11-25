"""FD3 to FD6: substation grouping, values, review, building joins and the table writer.

Offline and without the cache: every input is built here.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
import shapely

from flood_lab import domain
from flood_lab.assets import buildings as bld
from flood_lab.assets import oed, schema
from flood_lab.assets import substations as sub

X0, Y0 = 587_000.0, 4_506_000.0  # inside the square
LAND = shapely.box(*domain.SQUARE)


def flat(level: float = 3.0):
    def elevation(x, y):
        return np.full(len(np.asarray(x)), level)

    return elevation


def outline(number: int, dx: float, dy: float = 0.0, size: float = 20.0, **tags) -> sub.Outline:
    x, y = X0 + dx, Y0 + dy
    return sub.Outline(f"way/{number}", shapely.box(x, y, x + size, y + size), tags)


# substations -----------------------------------------------------------------------------------


def test_outlines_are_grouped_by_name_and_distance_and_traction_is_left_out() -> None:
    outlines = [
        outline(1, 0, name="Alpha", substation="transmission"),
        outline(2, 200, name="Alpha"),  # same name, 180 m apart: same asset
        outline(3, 1000, name="Alpha"),  # same name, far: another asset
        outline(4, 0, 500),  # unnamed
        outline(5, 100, 500),  # unnamed, 80 m from 4: same asset
        outline(6, 0, -500, name="Beta", substation="traction"),
    ]
    groups, traction = sub.group_outlines(outlines)
    assert [[o.osm_id for o in g] for g in groups] == [
        ["way/1", "way/2"],
        ["way/3"],
        ["way/4", "way/5"],
    ]
    assert [o.osm_id for o in traction] == ["way/6"]
    assert sub.loc_number(groups[0]) == "S-1"


def test_unnamed_outlines_farther_than_the_gap_stay_apart() -> None:
    groups, _ = sub.group_outlines([outline(1, 0), outline(2, 200)])
    assert len(groups) == 2


def test_voltage_is_the_highest_tagged_in_kv() -> None:
    assert sub.parse_voltage_kv("345000;138000") == 345.0
    assert sub.parse_voltage_kv("27000;4000") == 27.0
    assert sub.parse_voltage_kv("13800") == 13.8
    assert sub.parse_voltage_kv("") is None
    assert sub.parse_voltage_kv(None) is None
    assert sub.parse_voltage_kv("medium") is None


def test_value_class_and_geometric_mean() -> None:
    assert sub.value_class("transmission", None) == "transmission"
    assert sub.value_class("", 345.0) == "transmission"
    assert sub.value_class("distribution", 138.0) == "area"
    assert sub.value_class("", 69.0) == "area"
    assert sub.value_class("", None) is None
    assert sub.geometric_mean_usd(4, 9) == 6
    values = sub.load_values()
    money = sub.value_range("area", values)
    low, high = values["area"]["low_usd"], values["area"]["high_usd"]
    assert money["mid"] == round(math.sqrt(low * high))
    assert money["low"] < money["mid"] < money["high"] and money["tag"] == "P"
    assert "geometric mean" in money["source"] and values["area"]["low_source"] in money["source"]
    assert sub.value_range(None, values)["mid"] is None


def test_the_review_is_applied() -> None:
    row = {"lab_indoor": "unknown"}
    assert sub.apply_review(row, None)["lab_reviewed"] == "not reviewed"
    assert sub.apply_review(row, {"decision": "not reviewed"})["lab_reviewed"] == "not reviewed"
    kept = sub.apply_review(row, {"decision": "kept", "indoor": "yes"})
    assert kept["lab_reviewed"] == "kept" and kept["lab_indoor"] == "yes"
    removed = sub.apply_review(row, {"decision": "removed", "reason": "a parking lot"})
    assert removed["lab_reviewed"] == "removed: a parking lot"
    assert (
        sub.apply_review({"lab_indoor": "yes"}, {"decision": "kept", "indoor": ""})["lab_indoor"]
        == "yes"
    )


def test_build_gives_one_row_per_asset_with_values_and_review(tmp_path) -> None:
    outlines = [
        outline(
            10,
            0,
            name="Alpha",
            substation="transmission",
            voltage="345000;138000",
            location="outdoor",
        ),
        outline(11, 50, name="Alpha", voltage="138000"),
        outline(20, 0, 600, name="Gamma", location="indoor"),
        outline(30, 0, -600, substation="traction"),
    ]
    review = {"S-20": {"decision": "removed", "reason": "not a substation", "indoor": "no"}}
    rows, traction, groups = sub.build(outlines, elevation=flat(), land=LAND, review=review)
    assert [r["LocNumber"] for r in rows] == ["S-10", "S-20"] and len(traction) == 1
    alpha, gamma = rows
    assert alpha["lab_outlines"] == 2 and alpha["lab_voltage_kv"] == 345.0
    assert alpha["lab_value_class"] == "transmission" and alpha["lab_value_tag"] == "P"
    assert alpha["lab_reviewed"] == "not reviewed" and alpha["lab_indoor"] == "no"
    assert gamma["lab_value_mid_usd"] is None and gamma["lab_value_tag"] == ""
    assert gamma["lab_reviewed"] == "removed: not a substation" and gamma["lab_indoor"] == "no"
    assert alpha["lab_ground_elev_m"] == 3.0 and alpha["lab_customers_served"] is None
    text = sub.review_text(rows, review)
    path = tmp_path / "review.toml"
    path.write_text(text)
    loaded = sub.load_review(path)
    assert loaded["S-10"]["decision"] == "not reviewed"
    assert loaded["S-20"]["reason"] == "not a substation"
    assert sub.geojson(rows, groups)["features"][0]["properties"]["LocNumber"] == "S-10"


# buildings -------------------------------------------------------------------------------------


def test_feet_to_metres_and_zero_means_not_measured() -> None:
    assert bld.feet_to_m("10") == pytest.approx(3.048)
    assert bld.feet_to_m(-2.5) == pytest.approx(-0.762)
    assert bld.feet_to_m("0.0") is None
    assert bld.feet_to_m("") is None and bld.feet_to_m(None) is None


def test_bins() -> None:
    assert bld.normal_bin("3003138.0") == "3003138" and bld.normal_bin(3003138) == "3003138"
    assert bld.is_million_bin("3000000") and not bld.is_million_bin("3000001")


def _footprints(specs: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    """(bin, x offset, y offset, side) per footprint."""
    rows = [
        {
            "bin": b,
            "doitt_id": str(i),
            "construction_year": 1920,
            "feature_code": "2100",
            "last_status_type": "Constructed",
            "geometry": shapely.box(X0 + dx, Y0 + dy, X0 + dx + side, Y0 + dy + side),
        }
        for i, (b, dx, dy, side) in enumerate(specs)
    ]
    return pd.DataFrame(rows)


def _lonlat(x: float, y: float) -> tuple[float, float]:
    import pyproj

    return pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True).transform(x, y)


def test_building_joins() -> None:
    footprints = _footprints(
        [
            ("3000001", 0, 0, 20),  # BES row; two inventory points inside
            ("3000002", 100, 0, 20),  # BES row with grade 0; one point 10 m away
            ("3000003", 200, 0, 20),  # no BES row; a point 40 m away stays unmatched
            ("3000000", 300, 0, 20),  # million BIN: excluded
        ]
    )
    bes_rows = []
    for b, dx, grade, floor, note in (
        ("3000001", 10, "10.0", "13.0", "Property not Visible from Street"),
        ("3000002", 110, "0.0", "0.0", "Property was Successfully Measured"),
        ("3000000", 310, "5.0", "6.0", ""),
        ("3999999", 500, "5.0", "6.0", ""),  # no footprint
    ):
        lon, lat = _lonlat(X0 + dx, Y0 + 10)
        bes_rows.append(
            {
                "bin": b,
                "z_grade": grade,
                "z_floor": floor,
                "subgrade": "Y",
                "notes1": note,
                "latitude": str(lat),
                "longitude": str(lon),
            }
        )
    bes = pd.DataFrame(bes_rows)
    nsi = pd.DataFrame(
        {
            "x": [X0 + 5, X0 + 15, X0 + 130, X0 + 260],
            "y": [Y0 + 5, Y0 + 15, Y0 + 10, Y0 + 10],
            "val_struct": [100.0, 300.0, 50.0, 70.0],
            "occtype": ["RES3A", "COM1", "RES1", "RES1"],
            "found_type": ["B", "S", "B", "B"],
            "fd_id": [1, 2, 3, 4],
            "num_story": [2, 5, 1, 1],
        }
    )
    rows, stats = bld.build(footprints, bes, nsi, land=LAND, elevation=flat(2.0))
    by = {r["lab_bin"]: r for r in rows}
    assert sorted(by) == ["3000001", "3000002", "3000003"]
    assert stats["footprints_on_study_area_million_bin_excluded"] == 1
    assert (
        stats["buildings_with_elevation_row"] == 2 and stats["buildings_without_elevation_row"] == 1
    )
    assert stats["elevation_rows_on_study_area_without_footprint_in_file"] == 1
    assert stats["inventory_points_inside_a_footprint"] == 2
    assert stats["inventory_points_to_nearest_footprint"] == 1
    assert stats["inventory_points_unmatched"] == 1
    assert stats["buildings_with_several_inventory_points"] == 1

    one = by["3000001"]
    assert one["lab_match"] == "footprint+elevation+inventory"
    assert one["lab_nsi_id"] == "2" and one["BuildingTIV"] == 300.0  # the larger val_struct
    assert one["detail_inventory_points"] == 2 and one["NumberOfStoreys"] == 5
    assert one["lab_ground_elev_m"] == pytest.approx(3.048)
    assert one["lab_ground_elev_source"] == "z_grade (estimated)"
    assert one["lab_first_floor_height_m"] == pytest.approx(0.9144)
    assert one["lab_value_tag"] == "S" and one["lab_terrain_elev_m"] == 2.0

    two = by["3000002"]
    assert two["lab_match"] == "footprint+elevation+inventory"
    assert two["detail_inventory_join"] == "near"
    assert two["lab_ground_elev_m"] == 2.0 and two["lab_ground_elev_source"].startswith("terrain")
    assert two["lab_first_floor_height_m"] is None and two["lab_first_floor_elev_m"] is None

    three = by["3000003"]
    assert three["lab_match"] == "footprint" and three["BuildingTIV"] is None
    assert three["lab_subgrade"] == "" and three["lab_value_tag"] == ""


# table -----------------------------------------------------------------------------------------


def _asset(**changes) -> dict:
    row = {
        "LocNumber": "B-3000001",
        "Latitude": 40.7,
        "Longitude": -73.96,
        "lab_asset_type": "building",
        "lab_x_m": X0,
        "lab_y_m": Y0,
        "lab_in_study_area": True,
        "lab_ground_elev_m": 3.0,
        "lab_ground_elev_source": "z_grade",
        "lab_terrain_elev_m": 3.1,
        "FirstFloorHeight": 0.5,
        "BuildingTIV": 1234.4,
        "lab_value_mid_usd": 1234.4,
        "lab_value_tag": "S",
    }
    return row | changes


def test_the_writer_refuses_a_faulty_table(tmp_path) -> None:
    rows = oed.table([], [_asset(lab_ground_elev_m=None)])
    path = tmp_path / "assets_oed.csv"
    with pytest.raises(oed.TableFault, match="ground elevation"):
        oed.write(rows, path)
    assert not path.exists()


def test_the_writer_writes_the_same_bytes_twice(tmp_path) -> None:
    station = _asset(
        LocNumber="S-5",
        lab_asset_type="substation",
        lab_name="Hudson Avenue Substation",
        FirstFloorHeight=None,
        BuildingTIV=None,
    )
    rows = oed.table([station], [_asset(LocNumber="B-3000009"), _asset()])
    assert schema.validate(rows) == []
    assert [r["LocNumber"] for r in rows] == ["S-5", "B-3000001", "B-3000009"]
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    oed.write(rows, first)
    oed.write(oed.table([station], [_asset(), _asset(LocNumber="B-3000009")]), second)
    assert first.read_bytes() == second.read_bytes()
    lines = first.read_text().splitlines()
    assert lines[0] == ",".join(schema.COLUMNS)
    building = dict(zip(schema.COLUMNS, lines[2].split(","), strict=True))
    assert building["Latitude"] == "40.7000000" and building["BuildingTIV"] == "1234"
    assert building["FirstFloorHeight"] == "0.500" and building["FirstFloorHeightUnit"] == "2"
    assert building["LocPerilsCovered"] == "OSF" and building["OccupancyCode"] == ""
    substation = dict(zip(schema.COLUMNS, lines[1].split(","), strict=True))
    assert substation["LocName"] == "Hudson Avenue" and substation["FirstFloorHeightUnit"] == ""
