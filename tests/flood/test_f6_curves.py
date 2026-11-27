"""F6 damage-curve readers (FR1-FR3): Nirandjan F2, Bor 2026, Hazus via FAST.

Offline. Fixtures are written here with synthetic values (they test the parsing, not the
sources); tests on the real files skip when the cache does not hold them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flood_lab import cache
from flood_lab.curves import hazus as H
from flood_lab.curves import readers as R

CACHE = cache.root()
NIRANDJAN = (
    CACHE
    / "substation-curves-nirandjan"
    / "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx"
)
FAST = CACHE / "hazus-flood-functions" / "fast"


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
