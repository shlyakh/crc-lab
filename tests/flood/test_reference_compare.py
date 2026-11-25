"""FS4: the comparisons themselves, and the import rule of ``reference/`` (FG1)."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import shapely

from flood_lab.reference.compare import compare_grids, compare_tables, outcome

REFERENCE = Path(__file__).resolve().parents[2] / "src" / "flood_lab" / "reference"
ALLOWED_FLOOD_LAB = {"domain", "cache", "paths"}
FORBIDDEN = {"crc_sdk", "crc_framework", "pandas"}


def test_equal_grids_are_confirmed() -> None:
    a = np.arange(12, dtype=np.uint8).reshape(3, 4)
    result = compare_grids(a, a.copy())
    assert result["differing_cells"] == 0 and outcome(result) == "confirmed"


def test_differing_cells_are_counted_and_located() -> None:
    a = np.zeros((3, 4), dtype=np.uint8)
    b = a.copy()
    b[2, 1] = 1
    b[0, 3] = 2
    result = compare_grids(a, b)
    assert result["differing_cells"] == 2
    assert result["first"] == [(0, 3), (2, 1)]
    assert outcome(result) == "differs"


def test_grids_of_other_shapes_differ() -> None:
    result = compare_grids(np.zeros((2, 2)), np.zeros((2, 3)))
    assert result["same_shape"] is False and outcome(result) == "differs"


def test_nan_cells_are_equal() -> None:
    a = np.array([[np.nan, 1.0]])
    assert outcome(compare_grids(a, a.copy())) == "confirmed"


def test_repeated_keys_differ() -> None:
    a = [{"k": 1, "v": 1}]
    b = [{"k": 1, "v": 1}, {"k": 1, "v": 1}]
    result = compare_tables(a, b, "k", exact=("v",))
    assert result["repeated_keys_b"] == 1 and outcome(result) == "differs"


def test_missing_values_equal_only_missing_values() -> None:
    a = [{"k": 1, "x": None, "y": math.nan, "g": None}]
    b = [{"k": 1, "x": None, "y": math.nan, "g": None}]
    assert outcome(compare_tables(a, b, "k", ("x",), {"y": 0.1}, ("g",))) == "confirmed"
    c = [{"k": 1, "x": 0, "y": 0.0, "g": shapely.to_wkb(shapely.Point(0, 0))}]
    result = compare_tables(a, c, "k", ("x",), {"y": 0.1}, ("g",))
    assert {name: col["differ"] for name, col in result["columns"].items()} == {
        "x": 1,
        "y": 1,
        "g": 1,
    }


def test_a_close_column_uses_its_own_tolerance() -> None:
    a = [{"k": "a", "d": 1.0, "e": 1.0}]
    b = [{"k": "a", "d": 1.0005, "e": 1.0005}]
    result = compare_tables(a, b, "k", close={"d": 0.001, "e": 0.0001})
    assert result["columns"]["d"]["differ"] == 0 and result["columns"]["e"]["differ"] == 1


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0:
                names.add(module)
            elif node.level == 1:
                names |= {f"flood_lab.reference.{module or a.name}" for a in node.names}
            else:
                names |= (
                    {f"flood_lab.{module}"}
                    if module
                    else {f"flood_lab.{a.name}" for a in node.names}
                )
    return names


def test_reference_imports_only_what_the_brief_allows() -> None:
    faults = []
    for path in sorted(REFERENCE.glob("*.py")):
        for name in _imports(path):
            top = name.split(".")[0]
            if top in FORBIDDEN:
                faults.append(f"{path.name}: {name}")
            if top == "flood_lab":
                sub = name.split(".")[1]
                if sub != "reference" and sub not in ALLOWED_FLOOD_LAB:
                    faults.append(f"{path.name}: {name}")
    assert faults == []
