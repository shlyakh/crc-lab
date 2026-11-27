"""FR9: crc_event_loss imports crc_framework, numpy, pyarrow and the standard library only."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "crc_event_loss"
ALLOWED = {"crc_framework", "numpy", "pyarrow", "crc_event_loss"}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        (n.module or "").split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.level == 0
    }
    names |= {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    return names


def test_imports_only_what_it_may() -> None:
    files = sorted(PACKAGE.rglob("*.py"))
    assert files
    for path in files:
        others = _top_level_imports(path) - ALLOWED - set(sys.stdlib_module_names)
        assert not others, f"{path.name} imports {sorted(others)}"


def test_names_no_hazard_place_or_asset_type() -> None:
    """Nor any file of this repository: upstream code does not point at outside documents."""
    words = (
        "flood",
        "substation",
        "building",
        "storm",
        "rain",
        "williamsburg",
        "new york",
        "docs/",
    )
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        found = [w for w in words if re.search(rf"\b{w}", text)]
        assert not found, f"{path.name} names {found}"
