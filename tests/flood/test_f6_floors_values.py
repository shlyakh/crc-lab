"""F6: first-floor heights, basements and values taken from the asset table (FR3, FD4, FD5)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from flood_lab.assets import floors_values as fv
from flood_lab.assets.buildings import FOOT_M

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "f6_floors_values"
REAL_ASSETS = ROOT / "site" / "flood" / "data" / "assets_oed.csv"
REAL_NSI = (
    ROOT / "data" / "cache" / "flood" / "usace-national-structure-inventory" / "nsi_f1_box.json"
)


def _assets(path: Path = FIXTURES / "assets.csv") -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@pytest.fixture
def floors() -> pd.DataFrame:
    return fv.first_floors(_assets(), FIXTURES / "nsi.json").set_index("LocNumber")


@pytest.fixture
def values() -> pd.DataFrame:
    return fv.asset_values(_assets()).set_index("LocNumber")


def test_columns_are_exactly_the_contract() -> None:
    floors = fv.first_floors(_assets(), FIXTURES / "nsi.json")
    values = fv.asset_values(_assets())
    assert tuple(floors.columns) == fv.FIRST_FLOOR_COLUMNS
    assert tuple(values.columns) == fv.VALUE_COLUMNS
    assert fv.FIRST_FLOOR_COLUMNS == (
        "LocNumber",
        "ffh_m",
        "ffh_source",
        "ffh_tag",
        "basement",
        "basement_source",
    )
    assert fv.VALUE_COLUMNS == (
        "LocNumber",
        "asset_type",
        "value_low_usd",
        "value_mid_usd",
        "value_high_usd",
        "value_tag",
        "value_source",
        "price_year",
        "price_year_source",
    )


def test_one_row_per_building_only(floors: pd.DataFrame) -> None:
    assert list(floors.index) == ["B-1", "B-2", "B-3", "B-4", "B-5", "B-6"]


def test_fallback_order_city_then_inventory_then_empty(floors: pd.DataFrame) -> None:
    # the city's height wins even where an inventory point exists
    assert floors.loc["B-1", "ffh_m"] == 1.25
    assert (floors.loc["B-1", "ffh_source"], floors.loc["B-1", "ffh_tag"]) == ("city table", "S")
    # negative city heights are kept as they are
    assert floors.loc["B-5", "ffh_m"] == -0.25
    assert floors.loc["B-6", "ffh_m"] == 0.0
    # no city height: the inventory's found_ht in metres, labelled as the publisher's default
    assert floors.loc["B-2", "ffh_m"] == pytest.approx(2.0 * FOOT_M)
    assert floors.loc["B-3", "ffh_m"] == pytest.approx(0.25 * FOOT_M)
    assert (floors.loc["B-2", "ffh_source"], floors.loc["B-2", "ffh_tag"]) == (
        "NSI found_ht",
        "default",
    )
    # neither: empty, no source, no tag
    assert pd.isna(floors.loc["B-4", "ffh_m"])
    assert (floors.loc["B-4", "ffh_source"], floors.loc["B-4", "ffh_tag"]) == ("", "")


def test_a_default_is_never_tagged_as_stated_measurement(floors: pd.DataFrame) -> None:
    assert set(floors.loc[floors["ffh_source"] == "NSI found_ht", "ffh_tag"]) == {"default"}
    assert set(floors.loc[floors["ffh_tag"] == "S", "ffh_source"]) == {"city table"}


def test_empty_is_never_zero(tmp_path: Path, floors: pd.DataFrame, values: pd.DataFrame) -> None:
    assert pd.isna(floors.loc["B-4", "ffh_m"])
    assert (
        values.loc[["B-4", "S-3"], ["value_low_usd", "value_mid_usd", "value_high_usd"]]
        .isna()
        .all(axis=None)
    )
    out = tmp_path / "floors.csv"
    fv.write_csv(floors.reset_index(), out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(fv.FIRST_FLOOR_COLUMNS)
    assert next(line for line in lines if line.startswith("B-4,")) == "B-4,,,,,"
    assert not list(tmp_path.glob(".*.tmp"))


def test_basement_from_city_flag_then_inventory_type(floors: pd.DataFrame) -> None:
    assert tuple(floors.loc["B-1", ["basement", "basement_source"]]) == ("Y", "city table")
    # the city says N although the inventory point says B: the city's flag holds
    assert tuple(floors.loc["B-5", ["basement", "basement_source"]]) == ("N", "city table")
    assert tuple(floors.loc["B-2", ["basement", "basement_source"]]) == ("Y", "NSI found_type")
    assert tuple(floors.loc["B-3", ["basement", "basement_source"]]) == ("N", "NSI found_type")
    assert tuple(floors.loc["B-4", ["basement", "basement_source"]]) == ("", "")


def test_an_unknown_subgrade_flag_stops() -> None:
    assets = _assets()
    assets.loc[assets["LocNumber"] == "B-1", "lab_subgrade"] = "maybe"
    with pytest.raises(ValueError, match="lab_subgrade"):
        fv.first_floors(assets, FIXTURES / "nsi.json")


def test_removed_substations_are_excluded(values: pd.DataFrame) -> None:
    assert "S-2" not in values.index
    assert {"S-1", "S-3"} <= set(values.index)
    assert len(values) == len(_assets()) - 1


def test_values_are_taken_as_they_are(values: pd.DataFrame) -> None:
    assert tuple(values.loc["S-1", ["value_low_usd", "value_mid_usd", "value_high_usd"]]) == (
        9_100_000,
        58_804_762,
        380_000_000,
    )
    assert values.loc["S-1", "value_tag"] == "P"
    assert values.loc["B-1", "value_mid_usd"] == 500_000
    assert pd.isna(values.loc["B-1", "value_low_usd"])


def test_price_years(values: pd.DataFrame) -> None:
    assert values.loc["B-1", "price_year"] == "2025-08"
    assert "August 2025" in values.loc["B-1", "price_year_source"]
    # neither substation source states one price year: left empty, with the reason
    assert values.loc["S-1", "price_year"] == ""
    assert "MISO" in values.loc["S-1", "price_year_source"]
    # no value, no price year
    assert tuple(values.loc["B-4", ["price_year", "price_year_source"]]) == ("", "")


def test_a_value_without_a_tag_cannot_appear() -> None:
    assets = _assets()
    assets.loc[assets["LocNumber"] == "B-1", "lab_value_tag"] = ""
    with pytest.raises(ValueError, match="without a tag"):
        fv.asset_values(assets)
    assets.loc[assets["LocNumber"] == "B-1", "lab_value_tag"] = "X"
    with pytest.raises(ValueError, match="without a tag"):
        fv.asset_values(assets)


def test_a_zero_value_stops() -> None:
    assets = _assets()
    assets.loc[assets["LocNumber"] == "B-2", "lab_value_mid_usd"] = "0"
    with pytest.raises(ValueError, match="zero"):
        fv.asset_values(assets)


def test_numeric_input_with_nan_gives_the_same_result() -> None:
    numeric = pd.read_csv(FIXTURES / "assets.csv")
    floors = fv.first_floors(numeric, FIXTURES / "nsi.json").set_index("LocNumber")
    assert floors.loc["B-2", "ffh_source"] == "NSI found_ht"
    assert pd.isna(floors.loc["B-4", "ffh_m"])
    values = fv.asset_values(numeric).set_index("LocNumber")
    assert "S-2" not in values.index
    assert values.loc["B-4", "value_tag"] == ""


@pytest.mark.skipif(
    not (REAL_ASSETS.exists() and REAL_NSI.exists()), reason="asset table or NSI cache absent"
)
def test_real_table_keeps_the_rules() -> None:
    assets = _assets(REAL_ASSETS)
    floors = fv.first_floors(assets, REAL_NSI)
    buildings = assets[assets["lab_asset_type"] == "building"]
    assert len(floors) == len(buildings)
    assert floors["LocNumber"].is_unique
    assert set(floors["ffh_source"]) <= {"city table", "NSI found_ht", ""}
    known = floors["ffh_m"].notna()
    assert (floors.loc[known, "ffh_tag"] != "").all()
    assert (floors.loc[~known, "ffh_source"] == "").all()
    assert (floors["ffh_source"] == "city table").sum() == (
        buildings["lab_first_floor_height_m"] != ""
    ).sum()
    values = fv.asset_values(assets)
    removed = assets["lab_reviewed"].str.startswith("removed").sum()
    assert len(values) == len(assets) - removed
    given = values[["value_low_usd", "value_mid_usd", "value_high_usd"]].notna().any(axis=1)
    assert values.loc[given, "value_tag"].isin(fv.VALUE_TAGS).all()
