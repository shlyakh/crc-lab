"""FD6: the rules of the asset table."""

from __future__ import annotations

from flood_lab.assets import schema


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(schema.COLUMNS, "")
    row |= {
        "LocNumber": "S-1",
        "Latitude": 40.70,
        "Longitude": -73.96,
        "lab_asset_type": "substation",
        "lab_ground_elev_m": 3.2,
        "lab_ground_elev_source": "terrain",
        "lab_terrain_elev_m": 3.2,
    }
    return row | changes


def test_a_plain_row_is_accepted() -> None:
    assert schema.validate([_row()]) == []


def test_each_rule_is_reported() -> None:
    cases = {
        "repeated": [_row(), _row()],
        "asset type": [_row(lab_asset_type="pylon")],
        "letter": [_row(LocNumber="B-1")],
        "not in New York": [_row(Latitude=585500.0, Longitude=4504500.0)],
        "ground elevation": [_row(lab_ground_elev_m="")],
        "terrain elevation": [_row(lab_terrain_elev_m="")],
        "without a tag": [_row(lab_value_mid_usd=5e6)],
        "not in order": [
            _row(lab_value_low_usd=9, lab_value_mid_usd=5, lab_value_high_usd=7, lab_value_tag="P")
        ],
        "zero": [_row(lab_value_mid_usd=0, lab_value_tag="P")],
    }
    for words, rows in cases.items():
        faults = schema.validate(rows)
        assert faults and any(words in fault for fault in faults), (words, faults)


def test_wrong_columns_are_named() -> None:
    row = _row()
    del row["lab_bin"]
    assert "lab_bin" in schema.validate([row])[0]
    assert schema.validate([]) == ["the table has no rows"]
