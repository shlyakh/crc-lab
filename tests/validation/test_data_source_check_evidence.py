"""Evidence fetchers: parsers on cut-down real replies, the FEMA class rule, offline contract."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from data_source_check.evidence import _store, fema_nfhl, usgs_peaks, usgs_stn

FIXTURES = Path(__file__).parent / "fixtures" / "evidence"
PACKAGE = Path(__file__).resolve().parents[2] / "src" / "data_source_check" / "evidence"
FORBIDDEN = {"crc_sdk", "crc_framework", "crc_lab", "crc_data_explorer", "lab_common"}
ALLOWED_THIRD_PARTY = {"numpy", "shapely", "h3", "data_source_check"}
HOUSTON = (-95.9, 29.3, -94.9, 30.2)


def text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- FEMA NFHL
@pytest.mark.parametrize(
    ("zone", "subtype", "sfha", "expected"),
    [
        ("AE", None, "T", ("1pct-riverine", False)),
        ("AE", "FLOODWAY", "T", ("1pct-riverine", True)),
        ("A", None, "T", ("1pct-riverine", False)),
        ("AH", None, "T", ("1pct-riverine", False)),
        ("AO", None, "T", ("1pct-riverine", False)),
        ("A99", None, "T", ("1pct-riverine", False)),
        ("AR", None, "T", ("1pct-riverine", False)),
        ("ae ", None, "t", ("1pct-riverine", False)),
        ("AE", None, "F", ("other", False)),
        ("VE", None, "T", ("1pct-coastal", False)),
        ("V", None, "T", ("1pct-coastal", False)),
        ("VE", "RIVERINE FLOODWAY SHOWN IN COASTAL ZONE", "T", ("1pct-coastal", True)),
        ("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD", "F", ("0.2pct", False)),
        ("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD IN COMBINED RIVERINE AND COASTAL ZONE", "F",
         ("0.2pct", False)),
        ("X", "1 PCT DEPTH LESS THAN 1 FOOT", "F", ("other", False)),
        ("X", "AREA OF MINIMAL FLOOD HAZARD", "F", ("other", False)),
        ("X", "AREA WITH REDUCED FLOOD RISK DUE TO LEVEE", "F", ("other", False)),
        ("D", None, "F", ("other", False)),
        ("OPEN WATER", None, "F", ("other", False)),
        (None, None, None, ("other", False)),
    ],
)  # fmt: skip
def test_zone_class_rule(zone: str, subtype: str, sfha: str, expected: tuple) -> None:
    properties = {"FLD_ZONE": zone, "ZONE_SUBTY": subtype, "SFHA_TF": sfha}
    assert fema_nfhl.zone_class(properties) == expected


def test_zones_parse_a_real_page_and_drop_repeats() -> None:
    page = text("fema_zones_page.geojson")
    rows = fema_nfhl.zones([page, json.loads(page)])  # the same page twice: kept once
    assert len(rows) == 6
    by_zone = {(r["zone"], r["subtype"]): r for r in rows}
    assert by_zone[("VE", None)]["class"] == "1pct-coastal"
    assert by_zone[("AE", "FLOODWAY")]["floodway"] is True
    assert by_zone[("AE", "FLOODWAY")]["class"] == "1pct-riverine"
    assert by_zone[("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD")]["class"] == "0.2pct"
    assert by_zone[("D", None)]["class"] == "other"
    for row in rows:
        assert row["geometry"].geom_type in ("Polygon", "MultiPolygon")
        assert -122.2 < row["geometry"].centroid.x < -121.8
        assert row["static_bfe"] is None or row["static_bfe"] > -9999
        assert isinstance(row["valid"], bool)


def test_panel_dates() -> None:
    dates = fema_nfhl.panel_dates([text("fema_panels.json")])
    assert dates and all(len(d) == 10 for days in dates.values() for d in days)
    assert dates == {"48071C": ["2015-05-04", "2018-01-19"]}  # 1430697600000, 1516320000000 ms


def test_fema_offline_without_copy(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--live"):
        fema_nfhl.fetch(HOUSTON, tmp_path, live=False)


def test_tile_quarters_cover_the_tile() -> None:
    quarters = fema_nfhl._quarters((0.0, 0.0, 2.0, 1.0))
    assert quarters[0] == (0.0, 0.0, 1.0, 0.5) and quarters[-1] == (1.0, 0.5, 2.0, 1.0)


# ---------------------------------------------------------------------------- USGS peaks
def test_sites_parser() -> None:
    rows = usgs_peaks.sites(text("usgs_sites.rdb"))
    assert [r["site_no"] for r in rows] == ["08105886", "0810588650", "08154510"]
    first = rows[0]
    assert first["name"] == "Lake Ck at Lake Ck Pkwy nr Austin, TX"
    assert first["lat"] == pytest.approx(30.46555556)
    assert first["lon"] == pytest.approx(-97.7878889)
    assert first["drainage_area_sqmi"] == 2.15
    assert first["gage_altitude_ft"] == 897.58 and first["gage_altitude_datum"] == "NAVD88"
    assert rows[2]["gage_altitude_datum"] == "NGVD29"


def test_peaks_parser() -> None:
    rows = usgs_peaks.peaks(text("usgs_peaks.rdb"))
    assert len(rows) == 4
    harvey = next(r for r in rows if r["date"] == "2017-08-28")
    assert harvey["water_year"] == 2017
    assert harvey["discharge_cfs"] == 32600 and harvey["gage_height_ft"] == 41.90
    assert harvey["discharge_codes"] == "6,9,C" and harvey["gage_height_codes"] == "R"
    december = next(r for r in rows if r["date"] == "1935-12-09")
    assert december["water_year"] == 1936  # October to September
    last = rows[-1]
    assert last["time"] == "22:45" and last["max_gage_height_ft"] == 15.65


def test_water_year_with_unknown_month() -> None:
    assert usgs_peaks.water_year("1935-00-00") is None
    assert usgs_peaks.water_year("2017-09-30") == 2017
    assert usgs_peaks.water_year("2017-10-01") == 2018


def test_flood_stage_parser() -> None:
    stage = usgs_peaks.flood_stage(text("nwps_gauge.json"))
    assert stage["lid"] == "BBST2" and stage["usgs_id"] == "08074000"
    assert (stage["action_stage"], stage["minor_stage"]) == (17, 28)
    assert (stage["moderate_stage"], stage["major_stage"]) == (29.5, 32)
    assert stage["minor_flow"] is None  # -9999 in the reply
    assert stage["stage_units"] == "ft" and "NAVD88" in stage["vertical_datums"]


def test_peaks_offline_without_copy(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--live"):
        usgs_peaks.fetch(HOUSTON, tmp_path, live=False)


# ---------------------------------------------------------------------------- USGS STN
def test_event_id() -> None:
    assert usgs_stn.event_id(text("stn_events.json")) == 180
    with pytest.raises(LookupError):
        usgs_stn.event_id(text("stn_events.json"), "no such event")


def test_marks_parser_joins_survey_details() -> None:
    rows = usgs_stn.marks(text("stn_hwms_filtered.json"), text("stn_hwms_event.json"))
    assert [r["id"] for r in rows] == [20748, 20777, 21049]
    coastal = rows[0]
    assert coastal["environment"] == "Coastal" and coastal["type"] == "Debris"
    assert coastal["elevation_ft"] == 9.727 and coastal["vertical_datum"] == "NAVD88"
    assert coastal["height_above_ground_ft"] == 3.85
    assert coastal["quality"] == "Good: +/- 0.10 ft"
    assert coastal["flag_date"] == "2017-09-02T05:00:00Z"
    assert coastal["survey_date"] is None  # not in the cut-down details reply
    assert rows[1]["height_above_ground_ft"] is None
    assert rows[1]["survey_date"] == "2017-09-04T05:00:00Z" and rows[1]["stillwater"] is True
    assert rows[2]["environment"] == "Riverine"
    west, south, east, north = HOUSTON
    assert west <= rows[2]["longitude"] <= east and south <= rows[2]["latitude"] <= north
    assert all("member" not in key for row in rows for key in row)


def test_stn_offline_without_copy(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--live"):
        usgs_stn.fetch(tmp_path, live=False)


# ---------------------------------------------------------------------------- caching contract
def test_stored_copy_is_reused_and_checked(tmp_path: Path) -> None:
    path = tmp_path / "reply.json"
    path.write_bytes(b"[]")
    _store.write_json(_store.sidecar(path), {"url": "u", "sha256": "", "bytes": 2,
                                              "retrieved_at": ""})  # fmt: skip
    assert _store.store("u", path, live=False)["url"] == "u"
    path.write_bytes(b"[1]")
    with pytest.raises(RuntimeError, match="changed on disk"):
        _store.store("u", path, live=False)


def test_stored_manifest_is_read_offline(tmp_path: Path) -> None:
    here = tmp_path / "usgs-stn" / "2017-Harvey-TX"
    _store.write_json(here / "manifest.json", {"marks": 3})
    assert usgs_stn.fetch(tmp_path, live=False)["marks"] == 3


# ---------------------------------------------------------------------------- independence
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {(n.module or "").split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.level == 0}  # fmt: skip
    names |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
              for a in n.names}  # fmt: skip
    return names


def test_package_imports_only_the_standard_library_and_allowed_packages() -> None:
    import sys

    files = sorted(PACKAGE.glob("*.py"))
    assert len(files) >= 4
    for path in files:
        names = _imports(path)
        assert not names & FORBIDDEN, f"{path.name} imports {names & FORBIDDEN}"
        other = names - set(sys.stdlib_module_names) - ALLOWED_THIRD_PARTY - {"__future__"}
        assert not other, f"{path.name} imports {other}"
