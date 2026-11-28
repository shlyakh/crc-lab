"""F6 exposures (CH-31): suffix pre-step, PLUTO mapping, substitutes, routes, atomic write.

Offline. The small frames below are synthetic (they test the rules, not the sources); the tests on
the committed ``site/flood/data/exposures.csv`` reproduce the counts of the report, and the test on
the cached PLUTO lots skips when the cache does not hold them.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest
import shapely

from flood_lab import cache, paths
from flood_lab.assets import exposures as X
from flood_lab.sources import nyc_pluto

EXPOSURES = paths.SITE / "data" / "exposures.csv"
FT2 = X.FT2_PER_M2


def test_suffix_parts() -> None:
    assert X.suffix_parts("RES1-2SWB") == ("RES1", 2, "Y")
    assert X.suffix_parts("RES1-3SNB") == ("RES1", 3, "N")
    assert X.suffix_parts(" RES1-1SWB ") == ("RES1", 1, "Y")
    for plain in ("RES1", "RES3B", "COM1", "RES1-2XWB", "", "RES1-22SWB"):
        assert X.suffix_parts(plain) is None


def test_units_and_classes() -> None:
    assert X.units_class(2) == "RES3A"
    assert X.units_class(1) == "RES3A"
    assert X.units_class(3) == "RES3B"
    assert X.units_class(9) == "RES3C"
    assert X.units_class(10) == "RES3D"
    assert X.units_class(49) == "RES3E"
    assert X.units_class(50) == "RES3F"
    assert X.units_class(0) == "" and X.units_class(None) == "" and X.units_class(math.nan) == ""
    assert X.pluto_occupancy("C0", 3)[0] == "RES3B"
    assert X.pluto_occupancy("D1", 25)[0] == "RES3E"
    assert X.pluto_occupancy("D1", 0)[0] == ""  # units not known: falls to the neighbour route
    assert X.pluto_occupancy("V1", 0)[0] == ""
    with pytest.raises(KeyError):
        X.pluto_occupancy("XX", 1)
    for target, _reason in X.PLUTO_CLASS.values():
        assert target in ("", X.BY_UNITS) or target in X.HAZUS_COST_FT2 or target == "RES1"


def test_pluto_basement() -> None:
    assert X.pluto_basement("2", "A1", True) == "Y"
    assert X.pluto_basement("0", "B2", True) == "N"
    assert X.pluto_basement("5", "A1", True) == ""  # unknown
    assert X.pluto_basement("2", "A1", False) == ""  # lot with several buildings
    assert X.pluto_basement("2", "K1", True) == ""  # not a 1-3 family class: not verified


def test_hazus_cost_and_value() -> None:
    assert X.hazus_cost("RES3B", 2, "Y") == {"low": None, "mid": 118.30, "high": None}
    res1 = X.hazus_cost("RES1", 5, "Y")  # above three storeys: Table 6-3 three-story
    assert res1 == {"low": 127.75, "mid": 143.73, "high": 229.53}
    unknown = X.hazus_cost("RES1", 1, "")
    assert unknown["mid"] == pytest.approx(0.58 * 140.95 + 0.42 * 128.20)
    value = X.hazus_value("RES3B", 2, "N", 100.0)
    expected = 118.30 * 100.0 * FT2 * 2 * 1207.05 / 1143.96
    assert value["mid"] == pytest.approx(expected)
    for empty in (
        X.hazus_value("RES3B", None, "N", 100.0),
        X.hazus_value("RES3B", 2, "N", None),
        X.hazus_value("RES3B", 2, "N", 0.0),
        X.hazus_value("", 2, "N", 100.0),
    ):
        assert empty == {"low": None, "mid": None, "high": None}


def test_price_conversion() -> None:
    assert X.to_2026(None, "4Q25") is None
    assert X.to_2026(math.nan, "4Q25") is None
    assert X.to_2026(1175.35, "4Q25") == pytest.approx(1207.05)
    assert X.factor("4Q24") == pytest.approx(1207.05 / 1137.95)


def _fixture() -> dict[str, pd.DataFrame]:
    def box(x: float, y: float, side: float) -> shapely.Polygon:
        return shapely.box(x, y, x + side, y + side)

    rows = [
        # LocNumber, nsi id, occupancy, storeys, value, x, y
        ("B-1", "11", "RES3B", 2, 1_000_000.0, 0.0, 0.0),
        ("B-2", "12", "RES1-2SWB", 2, 500_000.0, 20.0, 0.0),
        ("B-8", "13", "RES3B", 3, 800_000.0, 40.0, 0.0),
        ("B-3", "", "", None, None, 0.0, 30.0),
        ("B-4", "", "", None, None, 5.0, 5.0),
        ("B-5", "", "", None, None, 30.0, 30.0),
        ("B-6", "", "", None, None, 60.0, 30.0),
    ]
    assets = pd.DataFrame(
        [
            {
                "LocNumber": loc,
                "lab_asset_type": "building",
                "lab_nsi_id": nsi or None,
                "lab_occupancy_hazus": occ or None,
                "NumberOfStoreys": st,
                "lab_value_mid_usd": val,
                "lab_value_tag": "S" if val else None,
                "lab_value_source": "USACE NSI val_struct" if val else None,
                "lab_x_m": x,
                "lab_y_m": y,
            }
            for loc, nsi, occ, st, val, x, y in rows
        ]
        + [
            {
                "LocNumber": "S-1",
                "lab_asset_type": "substation",
                "lab_voltage_kv": 138.0,
                "lab_substation_kind": "distribution",
                "lab_reviewed": "kept",
                "lab_value_low_usd": 9_100_000.0,
                "lab_value_mid_usd": 58_804_762.0,
                "lab_value_high_usd": 380_000_000.0,
                "lab_value_tag": "P",
                "lab_value_source": "MISO and Con Edison placeholder",
                "lab_x_m": 100.0,
                "lab_y_m": 100.0,
            }
        ]
    )
    sides = {"B-1": 10.0, "B-2": 8.0, "B-8": 8.0, "B-3": 9.0, "B-4": 4.0, "B-5": 7.0, "B-6": 6.0}
    xy = {loc: (x, y) for loc, *_rest, x, y in rows}
    lots = {
        "B-1": "3000010001",
        "B-2": "3000010002",
        "B-8": "3000010008",
        "B-3": "3000010003",
        "B-4": "3000010001",  # shares B-1's lot: cause A
        "B-5": "3999999999",  # no PLUTO lot
        "B-6": "3000010006",  # vacant class
    }
    footprints = pd.DataFrame(
        [
            {
                "doitt_id": f"d{loc}",
                "base_bbl": lots[loc],
                "mappluto_bbl": lots[loc],
                "height_roof_ft": 25.0,
                "geometry": box(*xy[loc], sides[loc]),
            }
            for loc in sides
        ]
    )
    footprints["area_m2"] = shapely.area(footprints["geometry"].to_numpy())
    detail = pd.DataFrame(
        [
            {
                "LocNumber": loc,
                "detail_doitt_id": f"d{loc}",
                "detail_feature_code": "5110" if loc == "B-4" else "2100",
                "detail_footprint_area_m2": sides[loc] ** 2,
            }
            for loc in sides
        ]
    )
    pluto = nyc_pluto.frame(
        [
            {"bbl": "3000010001.00000000", "bldgclass": "C0", "numbldgs": "2", "numfloors": "3",
             "unitsres": "3", "bsmtcode": "2", "version": "26v3"},
            {"bbl": "3000010002.00000000", "bldgclass": "A5", "numbldgs": "1", "numfloors": "2",
             "unitsres": "1", "bsmtcode": "2", "version": "26v3"},
            {"bbl": "3000010008.00000000", "bldgclass": "C0", "numbldgs": "1", "numfloors": "2",
             "unitsres": "3", "bsmtcode": "0", "version": "26v3"},
            {"bbl": "3000010003.00000000", "bldgclass": "C0", "numbldgs": "1", "numfloors": "2.5",
             "unitsres": "3", "bsmtcode": "2", "version": "26v3"},
            {"bbl": "3000010006.00000000", "bldgclass": "V1", "numbldgs": "1", "numfloors": "",
             "unitsres": "0", "bsmtcode": "5", "version": "26v3"},
        ]
    )  # fmt: skip
    floors = pd.DataFrame(
        [
            {"LocNumber": "B-1", "ffh_m": 1.0, "ffh_source": "city table", "basement": "Y",
             "basement_source": "city table"},
            {"LocNumber": "B-2", "ffh_m": 0.6, "ffh_source": "NSI found_ht", "basement": "N",
             "basement_source": "city table"},
            {"LocNumber": "B-8", "ffh_m": 1.0, "ffh_source": "city table", "basement": "Y",
             "basement_source": "city table"},
            {"LocNumber": "B-3", "ffh_m": 1.2, "ffh_source": "city table", "basement": "N",
             "basement_source": "city table"},
            {"LocNumber": "B-4", "ffh_m": None, "ffh_source": "", "basement": "",
             "basement_source": ""},
            {"LocNumber": "B-5", "ffh_m": 0.5, "ffh_source": "city table", "basement": "N",
             "basement_source": "city table"},
            {"LocNumber": "B-6", "ffh_m": 0.5, "ffh_source": "city table", "basement": "Y",
             "basement_source": "city table"},
        ]
    )  # fmt: skip
    lut = pd.DataFrame(
        {
            "SpecificOccupId": ["R12N", "R12B", "R3B3B", "R3B1N"],
            "DDF_ID": [1, 2, 3, 4],
        }
    )
    return {
        "assets": assets,
        "detail": detail,
        "footprints": footprints,
        "pluto": pluto,
        "floors": floors,
        "lut": lut,
    }


@pytest.fixture
def built() -> tuple[pd.DataFrame, dict]:
    f = _fixture()
    causes = {"dB-3": "C", "dB-4": "A", "dB-5": "B", "dB-6": "C"}
    return X.build(
        f["assets"], f["detail"], f["footprints"], f["pluto"], f["floors"], f["lut"], causes
    )


def test_routes_reconcile(built: tuple[pd.DataFrame, dict]) -> None:
    frame, summary = built
    b = frame[frame["asset_type"] == "building"].set_index("LocNumber")
    assert b["route"].to_dict() == {
        "B-1": "nsi",
        "B-2": "nsi suffix",
        "B-8": "nsi",
        "B-3": "pluto",
        "B-4": "pluto",
        "B-5": "neighbour",
        "B-6": "neighbour",
    }
    assert sum(summary["by_route"].values()) == len(b) == b.index.nunique()
    assert (frame["asset_type"] == "substation").sum() == 1


def test_suffix_route(built: tuple[pd.DataFrame, dict]) -> None:
    b = built[0].set_index("LocNumber")
    row = b.loc["B-2"]
    assert row["occupancy"] == "RES1" and row["storeys"] == 2 and row["basement"] == "N"
    assert (
        bool(row["occupancy_substitute"]) and "suffix base class" in row["asset_substitute_class"]
    )
    assert "suffix basement Y vs flag N" in row["notes"]
    assert row["curve_id"] == "hazus_struct_1"  # R12N
    assert built[1]["suffix_basement_disagree"] == 1


def test_pluto_route_and_flags(built: tuple[pd.DataFrame, dict]) -> None:
    b = built[0].set_index("LocNumber")
    single = b.loc["B-3"]
    assert single["occupancy"] == "RES3B" and single["storeys"] == 3  # 2.5 rounded half up
    assert single["basement"] == "Y" and "BsmtCode 2" in single["basement_source"]
    assert "BsmtCode Y vs city flag N" in single["notes"]
    assert not single["storeys_substitute"] and single["occupancy_substitute"]
    assert single["value_mid_usd_2026"] == pytest.approx(
        118.30 * 81.0 * FT2 * 3 * 1207.05 / 1143.96
    )
    assert single["value_substitute"] and single["value_tag"] == "I"
    assert single["asset_substitute_class"] == "PLUTO class;Hazus cost per ft²"
    assert single["curve_id"] == "hazus_struct_3"  # R3B3B
    shared = b.loc["B-4"]
    assert shared["lot_shared_with_nsi"] and shared["minor_structure"]
    assert shared["storeys_substitute"] and "roof height" in shared["storeys_source"]
    assert shared["basement"] == ""  # neither BsmtCode (two buildings) nor the city flag
    assert shared["curve_id"] == ""  # no basement, no curve


def test_neighbour_route(built: tuple[pd.DataFrame, dict]) -> None:
    b = built[0].set_index("LocNumber")
    for loc in ("B-5", "B-6"):
        row = b.loc[loc]
        assert row["occupancy"] == "RES3B"  # two of three NSI neighbours
        assert "neighbour mode class" in row["asset_substitute_class"]
        assert row["occupancy_substitute"] and row["value_substitute"]


def test_nsi_route_and_substation(built: tuple[pd.DataFrame, dict]) -> None:
    frame = built[0].set_index("LocNumber")
    nsi = frame.loc["B-1"]
    assert nsi["value_mid_usd_2026"] == pytest.approx(1_000_000 * 1207.05 / 1175.35)
    assert not nsi["value_substitute"] and nsi["asset_substitute_class"] == ""
    assert pd.isna(nsi["value_low_usd_2026"]) and pd.isna(nsi["value_high_usd_2026"])
    sub = frame.loc["S-1"]
    assert sub["value_mid_usd_2026"] == pytest.approx(58_804_762 * 1207.05 / 1137.95)
    assert sub["curve_id"].startswith("nirandjan_F2|williams_substation_max")


def test_no_zero_value(built: tuple[pd.DataFrame, dict]) -> None:
    frame = built[0]
    for column in ("value_low_usd_2026", "value_mid_usd_2026", "value_high_usd_2026"):
        assert not (frame[column] == 0).any()


def test_atomic_write(tmp_path, built, monkeypatch) -> None:
    frame = built[0]
    out = tmp_path / "exposures.csv"
    X.write_csv(frame, out)
    before = out.read_bytes()
    assert b",," in before  # unknowns are empty cells

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", broken)
    with pytest.raises(RuntimeError):
        X.write_csv(frame, out)
    assert out.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["exposures.csv"]


# --- the committed table -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def committed() -> pd.DataFrame:
    return pd.read_csv(EXPOSURES, dtype={"lot_bbl": str, "lot_base_bbl": str}, low_memory=False)


def test_committed_counts(committed: pd.DataFrame) -> None:
    b = committed[committed["asset_type"] == "building"]
    assert len(b) == 17_744 and b["LocNumber"].is_unique
    assert (committed["asset_type"] == "substation").sum() == 6
    routes = b["route"].value_counts().to_dict()
    assert routes["nsi"] == 11_902 and routes["nsi suffix"] == 426
    assert routes["pluto"] + routes["neighbour"] == 5_416
    assert b["gap_cause"].value_counts().to_dict() == {"B": 3_446, "A": 1_180, "C": 790}
    assert int(b["lot_shared_with_nsi"].sum()) == 1_180


def test_committed_substitutes(committed: pd.DataFrame) -> None:
    b = committed[committed["asset_type"] == "building"]
    unmatched = b[b["route"].isin(["pluto", "neighbour"])]
    assert unmatched["value_substitute"].all() and unmatched["occupancy_substitute"].all()
    assert not b.loc[b["route"] == "nsi", "occupancy_substitute"].any()
    assert (b.loc[b["route"] == "nsi suffix", "occupancy"] == "RES1").all()
    for column in ("value_low_usd_2026", "value_mid_usd_2026", "value_high_usd_2026"):
        assert not (committed[column] == 0).any()
    kinds = set(X.SUBSTITUTE_KINDS)
    for cell in b["asset_substitute_class"].fillna(""):
        assert set(filter(None, cell.split(";"))) <= kinds


def test_cached_pluto_classes_all_mapped() -> None:
    root = cache.root()
    if not (root / nyc_pluto.FOLDER / "query.json").exists():
        pytest.skip("PLUTO lots not in the cache")
    classes = set(nyc_pluto.read(root)["bldgclass"])
    assert classes - set(X.PLUTO_CLASS) == set()
