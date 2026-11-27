"""F6 damage-curve readers (FR1-FR3): Nirandjan F2, Bor 2026, Hazus via SPHERE and FAST.

Offline. Fixtures are synthetic (they test the parsing, not the sources): the FAST ones are written
here, the SPHERE ones are in ``fixtures/f6_sphere``. Tests on the real files skip when the cache
does not hold them.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flood_lab import cache, paths
from flood_lab.curves import build as B
from flood_lab.curves import hazus as H
from flood_lab.curves import readers as R

CACHE = cache.root()
NIRANDJAN = (
    CACHE
    / "substation-curves-nirandjan"
    / "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx"
)
FAST = CACHE / "hazus-flood-functions" / "fast"
SPHERE = CACHE / "hazus-flood-functions" / "sphere"
SPHERE_FIXTURES = Path(__file__).parent / "fixtures" / "f6_sphere"
ASSETS = paths.ROOT / "site" / "flood" / "data" / "assets_oed.csv"


def _need(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"not in the cache: {path}")
    return path


# --- Nirandjan, fixture --------------------------------------------------------------------------


@pytest.fixture
def f2_workbook(tmp_path: Path) -> Path:
    """A tiny F_Vuln_Depth sheet: the F2 columns are not where v1.1.0 has them."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "F_Vuln_Depth"
    ids = ["ID number", "F1.1", "F2.3", "F2.1", "X9", "F2.2"]
    ws.append(ids)
    ws.append(["Infrastructure description"] + ["substation"] * 5)
    ws.append(["Additional characteristics"] + [""] * 5)
    ws.append([None] * 6)
    ws.append(["Depth (m)"] + ["Damage factor"] * 5)
    rows = [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3), (1.5, None), (2.0, None)]
    for depth, value in rows:
        ws.append([depth, 0.9 if value is not None else None, value, value, 1.0, value])
    path = tmp_path / "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx"
    wb.save(path)
    return path


def test_f2_fixture_columns_found_by_id_and_stops_at_last_value(f2_workbook: Path) -> None:
    curves = R._read_f2_sheet(f2_workbook)
    assert set(curves) == {"F2.1", "F2.2", "F2.3"}
    for cid, c in curves.items():
        assert c.id == f"nirandjan_{cid}"
        assert c.depth_m == (0.0, 0.5, 1.0)
        assert c.ratio == (0.0, 0.1, 0.3)
        assert c.tag == "S" and c.datum == "above ground"
    assert "column D" in curves["F2.1"].source and "column C" in curves["F2.3"].source


def test_f2_fixture_fails_the_checksum(f2_workbook: Path) -> None:
    with pytest.raises(ValueError, match="sha256"):
        R.read_nirandjan_f2(f2_workbook)


def test_f2_fixture_gap_is_an_error(f2_workbook: Path) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(f2_workbook)
    wb["F_Vuln_Depth"]["D7"] = None  # F2.1 at 0.5 m, between two values
    wb.save(f2_workbook)
    with pytest.raises(ValueError, match="empty"):
        R._read_f2_sheet(f2_workbook)


# --- Nirandjan, real file ------------------------------------------------------------------------


def test_nirandjan_f2_real_file() -> None:
    pytest.importorskip("openpyxl")
    curves, record = R.read_nirandjan_f2(_need(NIRANDJAN))
    assert record.sha256 == "a4d4cfe168f24ee3ad4fd802ee093da21d017a178f5345205e8723a3d2737f9c"
    a, b, c = curves["F2.1"], curves["F2.2"], curves["F2.3"]
    assert a.depth_m == b.depth_m == c.depth_m and a.ratio == b.ratio == c.ratio
    assert len(a.depth_m) == 62  # facts file: 0 to 3.05 m at 0.05 m steps
    assert a.depth_m[0] == 0.0 and a.ratio[0] == 0.0
    assert a.depth_m[-1] == 3.05 and a.ratio[-1] == 0.16
    assert all(y >= x for x, y in zip(a.ratio, a.ratio[1:], strict=False))
    # values the facts file records (f2_curves)
    at = dict(zip(a.depth_m, a.ratio, strict=True))
    assert round(at[0.05], 5) == 0.00328 and round(at[1.2], 4) == 0.0694
    assert round(at[3.0], 4) == 0.1569


# --- Bor et al. 2026 -----------------------------------------------------------------------------


def test_bor_states_are_the_stated_parameters() -> None:
    assert R.BOR_STATES == (
        ("slight", 0.50, 0.40, 0.05),
        ("moderate", 1.00, 0.40, 0.20),
        ("extensive", 1.50, 0.40, 0.50),
        ("complete", 3.00, 0.40, 1.00),
    )


def test_bor_expected_damage() -> None:
    assert R.bor_expected_damage(0.0) == 0.0
    d = np.linspace(0, 20, 4001)
    e = R.bor_expected_damage(d)
    assert np.all(np.diff(e) >= 0)
    assert np.all((e >= 0) & (e <= 1))
    # CH-27 (docs/flood/changes.md): 0.032/0.171/0.501/0.737 at 0.5/1/2/3 m
    got = np.round(R.bor_expected_damage([0.5, 1.0, 2.0, 3.0]), 3)
    assert got.tolist() == [0.032, 0.171, 0.501, 0.737]


def test_bor_rejects_negative_depth() -> None:
    with pytest.raises(ValueError):
        R.bor_expected_damage([-0.1])


def test_bor_curve_table_and_reported_error() -> None:
    c = R.bor_curve(5.0, 0.05)
    assert c.depth_m[0] == 0.0 and c.ratio[0] == 0.0
    assert len(c.depth_m) == 101 and abs(c.depth_m[-1] - 5.0) < 1e-12
    assert c.tag == "I" and c.datum == "above ground"
    err = R.bor_interpolation_error(5.0, 0.05)
    assert f"{err:.3g}" in c.note
    assert R.bor_interpolation_error(5.0, 0.01) < err
    with pytest.raises(ValueError, match="multiple"):
        R.bor_curve(5.0, 0.3)


# --- Hazus, fixtures -----------------------------------------------------------------------------

_DEPTHS = ",".join(H.DEPTH_COLUMNS)
_LIB_HEADER = f"BldgDmgFnID,Occupancy,Source,Description,{_DEPTHS},Comment"
_LUT_HEADER = (
    f"Occupancy,SpecificOccupId,Source,Description,Stories,Comment,{_DEPTHS},"
    "DDF_ID,Basement,HazardRiverine,HazardCV,HazardCA,SortOrder"
)
_RAMP = ",".join(str(i) for i in range(29))  # synthetic percentages 0..28
_FLAT = ",".join("5" for _ in range(29))


@pytest.fixture
def fast_files(tmp_path: Path) -> tuple[Path, Path]:
    lib = tmp_path / "flBldgStructDmgFn.csv"
    lib.write_text(
        f'{_LIB_HEADER}\n1,RES1,Test,"one, two",{_RAMP},NULL\n2,COM1,Test,flat,{_FLAT},NULL\n'
    )
    lut = tmp_path / "Building_DDF_Riverine_LUT_Hazus4p0.csv"
    lut.write_text(
        f"{_LUT_HEADER}\n"
        f'RES1,R11N,Test,"one, two",1 Story,,{_RAMP},1,,1,,,101\n'
        f"COM1,C1LN,Test,flat,Low Rise,,{_FLAT},2,,1,,,102\n"
        f"COM1,C1LB,Test,flat,Low Rise,,{_FLAT},2,1,1,,,103\n"
    )
    return lib, lut


def test_library_fixture(fast_files: tuple[Path, Path]) -> None:
    lib, _ = fast_files
    curves = H._parse_library(lib)
    assert set(curves) == {1, 2}
    c = curves[1]
    assert c.depth_ft == tuple(range(-4, 25)) and c.percent == tuple(float(i) for i in range(29))
    assert c.description == "one, two"
    p = c.to_points()
    assert p.id == "hazus_struct_1" and p.datum == "above first floor" and p.tag == "I"
    assert p.depth_m[0] == -4 * R.FOOT_M and p.ratio[-1] == 0.28
    assert "8e285a9" in p.source and "flBldgStructDmgFn.csv" in p.source and "row id 1" in p.source


def test_library_id_column_detected(tmp_path: Path) -> None:
    path = tmp_path / "flBldgContDmgFn.csv"
    path.write_text(f"{_LIB_HEADER.replace('BldgDmgFnID', 'ContDmgFnId')}\n7,RES1,T,d,{_RAMP},\n")
    c = H._parse_library(path)[7]
    assert c.library == "flBldgContDmgFn.csv" and c.to_points().id == "hazus_cont_7"


def test_fixture_files_fail_the_checksum(fast_files: tuple[Path, Path]) -> None:
    lib, lut = fast_files
    with pytest.raises(ValueError, match="sha256"):
        H.read_library(lib)
    with pytest.raises(ValueError, match="sha256"):
        H.read_assignment(lut)


def test_lut_matches_library_fixture(fast_files: tuple[Path, Path]) -> None:
    lib, lut = fast_files
    table = H._parse_assignment(lut)
    assert H.lut_library_mismatches(table, H._parse_library(lib)) == []
    table.loc[0, "p3"] = 99
    assert H.lut_library_mismatches(table, H._parse_library(lib)) == [
        "R11N: values differ from library row 1"
    ]


def test_assignment_fixture(fast_files: tuple[Path, Path]) -> None:
    _, lut = fast_files
    table = H._parse_assignment(lut)
    assert H.assign_structure_curve(table, "RES1", 1, False) == 1
    assert H.assign_structure_curve(table, " COM1 ", 2, True) == 2
    assert H.assign_structure_curve(table, "RES1", 1, True) is None  # R11B not in the fixture


def test_specific_occupancy_id_follows_fast() -> None:
    # hazpy a207732 flood/modules/UDF.py lines 393-418
    soid = H.specific_occupancy_id
    assert soid("RES1", 1, False) == "R11N"
    assert soid("RES1", 7, True) == "R13B"  # RES1 capped at 3 stories
    assert soid("RES1", 1.5, False) == "R1SN"  # not an integer: split level
    assert soid("RES2", 2, False) == "R21N"
    assert soid("RES3B", 2, False) == "R3B1N"
    assert soid("RES3B", 3, False) == "R3B3N"
    assert soid("RES3B", 5, True) == "R3B5B"
    assert soid("COM10", 3, False) == "C10LN"
    assert soid("COM4", 4, False) == "C4MN"
    assert soid("COM4", 7, False) == "C4HN"
    assert soid("REL1", 1, False) == "RE1LN"
    assert soid("RES1-2SWB", 2, True) == "R1-2SWB2B"  # NSI occtype: no LUT row


# --- Hazus, real files ---------------------------------------------------------------------------


def test_every_library_curve_has_29_points_in_range() -> None:
    for name in ("flBldgStructDmgFn.csv", "flBldgContDmgFn.csv", "flBldgInvDmgFn.csv"):
        lib = H.read_library(_need(FAST / name))
        assert lib
        for c in lib.values():
            assert c.depth_ft == tuple(range(-4, 25))
            assert len(c.percent) == 29 and all(0 <= p <= 100 for p in c.percent)
            c.to_points()  # validates monotone depth and ratio in 0..1


@pytest.mark.parametrize(
    ("lut_name", "library_name", "rows"),
    [
        ("Building_DDF_Riverine_LUT_Hazus4p0.csv", "flBldgStructDmgFn.csv", 196),
        ("Building_DDF_CoastalA_LUT_Hazus4p0.csv", "flBldgStructDmgFn.csv", 64),
        ("Building_DDF_CoastalV_LUT_Hazus4p0.csv", "flBldgStructDmgFn.csv", 64),
    ],
)
def test_lut_rows_equal_library_rows(lut_name: str, library_name: str, rows: int) -> None:
    lut = H.read_assignment(_need(FAST / lut_name))
    lib = H.read_library(_need(FAST / library_name))
    assert len(lut) == rows  # facts file, fast_vs_hazus7
    assert H.lut_library_mismatches(lut, lib) == []


@pytest.mark.parametrize(
    ("occupancy", "stories", "basement", "ddf_id"),
    [
        # facts file (building_function_sources, fast_vs_hazus7) and the riverine LUT
        ("RES1", 1, False, 129),
        ("RES1", 1, True, 704),
        ("RES1", 2, False, 107),
        ("RES1", 3, True, 110),
        ("RES1", 5, False, 109),  # capped at 3 stories (UDF.py line 407)
        ("RES2", 1, True, 189),
        ("RES3B", 4, False, 204),
        ("RES3B", 8, True, 205),
        ("COM1", 1, False, 217),
        ("COM4", 12, True, 431),
        ("EDU1", 2, False, 643),
        # cases FAST's rule does not assign
        ("RES1", 0, False, None),  # SOID R10N: no row
        ("RES1-2SWB", 2, True, None),  # NSI occtype suffix
        ("RES1-3SNB", 3, False, None),
        ("RES1-1SNB", 1, False, None),
        ("RES1", None, False, None),  # FAST skips a record with an empty field
        ("RES1", 1, None, None),
        ("", 1, False, None),
    ],
)
def test_assign_structure_curve_real_lut(
    occupancy: str, stories: int | None, basement: bool | None, ddf_id: int | None
) -> None:
    lut = H.read_assignment(_need(FAST / "Building_DDF_Riverine_LUT_Hazus4p0.csv"))
    assert H.assign_structure_curve(lut, occupancy, stories, basement) == ddf_id


# --- SPHERE, fixtures ----------------------------------------------------------------------------


def test_sphere_depth_columns() -> None:
    assert H.SPHERE_DEPTH_COLUMNS[:5] == ("ft04m", "ft03m", "ft02m", "ft01m", "ft00")
    assert H.SPHERE_DEPTH_COLUMNS[-1] == "ft24" and len(H.SPHERE_DEPTH_COLUMNS) == 29


def test_sphere_library_fixture() -> None:
    curves = H._parse_sphere_library(SPHERE_FIXTURES / "flBldgDmgFn.csv")  # UTF-8 with BOM
    assert set(curves) == {1, 2, 3}
    c = curves[1]
    assert c.depth_ft == tuple(range(-4, 25)) and c.percent == tuple(float(i) for i in range(29))
    assert c.source == "Test" and c.description == "synthetic, ramp" and c.origin == "sphere"
    p = c.to_points()
    assert p.id == "hazus_struct_1" and p.datum == "above first floor" and p.tag == "I"
    assert p.depth_m[0] == -4 * R.FOOT_M and p.ratio[-1] == 0.28
    for words in ("SPHERE", "2967fe6", "flBldgDmgFn.csv", "row id 1", "MIT", "FEMA Hazus data"):
        assert words in p.source
    assert "FAST" not in p.source


def test_sphere_library_trailing_blanks_stop_the_curve() -> None:
    c = H._parse_sphere_library(SPHERE_FIXTURES / "flBldgDmgFn.csv")[3]
    assert c.depth_ft == tuple(range(-4, 17)) and c.percent[-1] == 20.5


def test_sphere_library_gap_is_an_error(tmp_path: Path) -> None:
    text = (SPHERE_FIXTURES / "flBldgDmgFn.csv").read_text(encoding="utf-8-sig")
    path = tmp_path / "flBldgDmgFn.csv"
    path.write_text(text.replace("2,Test,5,5,5", "2,Test,5,,5"), encoding="utf-8-sig")
    with pytest.raises(ValueError, match="empty depth cell"):
        H._parse_sphere_library(path)


def test_sphere_library_kind_from_name(tmp_path: Path) -> None:
    text = (SPHERE_FIXTURES / "flBldgDmgFn.csv").read_text(encoding="utf-8-sig")
    path = tmp_path / "flContDmgFn.csv"
    path.write_text(text.replace("BldgDmgFnId", "ContDmgFnId"), encoding="utf-8-sig")
    assert H._parse_sphere_library(path)[1].to_points().id == "hazus_cont_1"
    with pytest.raises(ValueError, match="not a SPHERE library"):
        H._parse_sphere_library(tmp_path / "other.csv")


def test_sphere_fixture_files_fail_the_checksum() -> None:
    with pytest.raises(ValueError, match="sha256"):
        H.read_sphere_library(SPHERE_FIXTURES / "flBldgDmgFn.csv")
    with pytest.raises(ValueError, match="sha256"):
        H.read_sphere_xref(SPHERE_FIXTURES / "flDmgXRef.csv")


def test_sphere_xref_fixture() -> None:
    xref = H._parse_sphere_xref(SPHERE_FIXTURES / "flDmgXRef.csv")
    m, c = H.sphere_structure_matches, H.sphere_structure_curve
    assert c(xref, "RES1", 1, False) == 1
    assert m(xref, "RES1", 1.5, False) == [1, 3]  # overlapping rows, first in file order
    assert c(xref, "RES1", 1.5, False) == 1
    assert c(xref, "RES1", 2, False) == 2  # StoriesMax is exclusive
    assert c(xref, "RES1", 1000, False) is None
    assert c(xref, "RES1", 0, False) is None
    assert c(xref, "RES1", 3, True) == 2
    assert c(xref, "COM1", 1, False) is None  # HazardR = 0
    assert m(xref, "COM1", 1, False, hazard="CA") == [3]
    assert c(xref, " RES1", 1, False) is None  # SPHERE does not strip
    assert c(xref, "RES1", None, False) is None and c(xref, "RES1", 1, None) is None


def test_building_curves_stop_when_fast_differs(fast_files: tuple[Path, Path]) -> None:
    lib, lut = fast_files
    fast = H._parse_library(lib)
    sphere = H._parse_sphere_library(SPHERE_FIXTURES / "flBldgDmgFn.csv")
    table = H._parse_assignment(lut)
    got = B.building_curves(table, sphere, fast)  # ids 1 and 2: same values in both fixtures
    assert [c.ddf_id for c in got] == [1, 2] and all(c.origin == "sphere" for c in got)
    table.loc[0, "DDF_ID"] = 3  # SPHERE has 3, FAST does not
    with pytest.raises(ValueError, match=r"\[3\]"):
        B.building_curves(table, sphere, fast)


# --- SPHERE, real files --------------------------------------------------------------------------


def _sphere_entries() -> list[dict]:
    with open(paths.FACTS / H.SPHERE_FACTS, "rb") as f:
        return tomllib.load(f)["file"]


@pytest.mark.parametrize("entry", _sphere_entries(), ids=lambda e: Path(e["path"]).name)
def test_sphere_file_checksum(entry: dict) -> None:
    path = _need(CACHE / entry["path"])
    got = R.verified(path, H.SPHERE_FACTS)
    assert got.sha256 == entry["sha256"] and got.bytes == entry["bytes"]
    assert H.SPHERE_COMMIT_FULL in entry["url"]


def test_sphere_libraries_equal_fast_rows() -> None:
    # facts file, equal_to_fast: 597, 507 and 116 FAST rows, all identical in SPHERE
    pairs = [
        ("flBldgDmgFn.csv", "flBldgStructDmgFn.csv", 597),
        ("flContDmgFn.csv", "flBldgContDmgFn.csv", 507),
        ("flInvDmgFn.csv", "flBldgInvDmgFn.csv", 116),
    ]
    for sphere_name, fast_name, rows in pairs:
        sphere = H.read_sphere_library(_need(SPHERE / sphere_name))
        fast = H.read_library(_need(FAST / fast_name))
        assert len(fast) == rows
        for i, c in fast.items():
            assert (sphere[i].depth_ft, sphere[i].percent) == (c.depth_ft, c.percent), i


def test_every_used_structure_curve_is_identical_in_sphere_and_fast() -> None:
    lut = H.read_assignment(_need(FAST / "Building_DDF_Riverine_LUT_Hazus4p0.csv"))
    sphere = H.read_sphere_library(_need(SPHERE / "flBldgDmgFn.csv"))
    fast = H.read_library(_need(FAST / "flBldgStructDmgFn.csv"))
    used = B.building_curves(lut, sphere, fast)
    assert len(used) == 36
    for c in used:
        f = fast[c.ddf_id]
        assert c.percent == f.percent and c.depth_ft == f.depth_ft == H.DEPTH_FT
        assert c.to_points().id == f.to_points().id
        assert c.to_points().ratio == f.to_points().ratio


def test_curves_yaml_building_curves_come_from_sphere() -> None:
    from flood_lab.risk import crc_adapter

    curves = crc_adapter.load()
    assert len(curves["building_curves"]) == 36
    for e in curves["building_curves"]:
        assert e["source"].startswith(
            "SPHERE (NiyamIT, MIT licence; FEMA Hazus data), commit 2967fe6"
        )
        assert "FAST" in e["note"]
    licences = [s.get("licence", "") for s in curves["sources"]]
    assert any(s.startswith("MIT (SPHERE") for s in licences)
    assert any(s.startswith("GPL-3.0 (FEMA FAST") for s in licences)


@pytest.mark.parametrize(
    ("occupancy", "stories", "basement", "fast_id", "sphere_ids"),
    [
        # facts file, assignment_vs_fast
        ("RES1", 1, False, 129, [129]),
        ("RES1", 3, True, 110, [110]),
        ("RES3B", 8, True, 205, [205]),
        ("COM4", 12, True, 431, [431]),
        ("EDU2", 1900, False, 652, []),  # the one building where they differ
        ("RES1", 1.5, False, 111, [129, 111]),
        ("RES2", 2, False, 189, []),
        ("COM1", 0, False, 217, []),
        ("RES1-2SWB", 2, True, None, []),
    ],
)
def test_sphere_xref_against_fast_rule(
    occupancy: str, stories: float, basement: bool, fast_id: int | None, sphere_ids: list[int]
) -> None:
    xref = H.read_sphere_xref(_need(SPHERE / "flDmgXRef.csv"))
    lut = H.read_assignment(_need(FAST / "Building_DDF_Riverine_LUT_Hazus4p0.csv"))
    assert H.assign_structure_curve(lut, occupancy, stories, basement) == fast_id
    assert H.sphere_structure_matches(xref, occupancy, stories, basement) == sphere_ids


def _basement(row: pd.Series) -> bool | None:
    """The flag floors_values.py chooses: the city's subgrade flag, else NSI found_type."""
    if row["lab_subgrade"] in ("Y", "N"):
        return row["lab_subgrade"] == "Y"
    if row["lab_foundation_type"]:
        return row["lab_foundation_type"] == "B"
    return None


def test_assignment_comparison_on_the_asset_table() -> None:
    """Facts file, assignment_vs_fast: one building of 17,744 differs, so FAST's rule is kept."""
    xref = H.read_sphere_xref(_need(SPHERE / "flDmgXRef.csv"))
    lut = H.read_assignment(_need(FAST / "Building_DDF_Riverine_LUT_Hazus4p0.csv"))
    assets = pd.read_csv(_need(ASSETS), dtype=str, keep_default_na=False)
    buildings = assets[assets["lab_asset_type"] == "building"]
    combos = (
        buildings.assign(
            stories=[float(s) if s else None for s in buildings["NumberOfStoreys"]],
            basement=[_basement(r) for _, r in buildings.iterrows()],
        )
        .groupby(["lab_occupancy_hazus", "stories", "basement"], dropna=False)
        .size()
    )
    differ = {}
    for (oc, st, bs), n in combos.items():
        st = None if pd.isna(st) else st
        bs = None if pd.isna(bs) else bool(bs)
        fast = H.assign_structure_curve(lut, oc, st, bs)
        sphere = H.sphere_structure_curve(xref, oc, st, bs)
        if fast != sphere:
            differ[(oc, st, bs)] = (fast, sphere, n)
    assert len(buildings) == 17744
    assert differ == {("EDU2", 1900.0, False): (652, None, 1)}
