"""FG1: inside flood_lab only sources/ and risk/ may import crc-sdk or crc-framework."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "flood_lab"
MAY_IMPORT_CRC = {"sources", "risk"}
CRC = {"crc_sdk", "crc_framework"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    names |= {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    return names


def test_only_sources_and_risk_import_crc() -> None:
    for path in PACKAGE.rglob("*.py"):
        folder = path.relative_to(PACKAGE).parts[0]
        if folder in MAY_IMPORT_CRC:
            continue
        assert not _imports(path) & CRC, f"{path} imports {_imports(path) & CRC}"


def test_reference_and_crosscheck_share_nothing_with_the_loaders() -> None:
    for name in ("reference", "crosscheck"):
        for path in (PACKAGE / name).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "flood_lab.sources" not in text and "flood_lab.risk" not in text, path
