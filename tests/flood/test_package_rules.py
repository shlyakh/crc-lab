"""FG1: inside flood_lab only sources/ and risk/ may import crc-sdk or crc-framework."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "flood_lab"
MAY_IMPORT_CRC = {"sources", "risk"}
CRC = {"crc_sdk", "crc_framework"}
LOADERS = {"sources", "risk"}
INDEPENDENT = ("reference", "crosscheck")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    """Top-level names of the absolute imports in a file."""
    tree = _tree(path)
    names = {
        (n.module or "").split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.level == 0
    }
    names |= {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    return names


def _package_modules(path: Path, package: Path) -> set[str]:
    """The flood_lab subpackages a file imports, absolute (``flood_lab.x``) or relative."""
    found = set()
    here = path.relative_to(package).parts[:-1]
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            parts_list = [a.name.split(".") for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            parts_list = [(node.module or "").split(".")]
        elif isinstance(node, ast.ImportFrom):
            base = list(here[: len(here) - (node.level - 1)]) if node.level - 1 <= len(here) else []
            module = (node.module or "").split(".") if node.module else []
            targets = [base + module] if module else [base + [a.name] for a in node.names]
            found |= {t[0] for t in targets if t}
            continue
        else:
            continue
        found |= {p[1] for p in parts_list if len(p) > 1 and p[0] == package.name}
    return found


def crc_import_faults(package: Path) -> list[str]:
    """Files outside sources/ and risk/ that import crc-sdk or crc-framework."""
    faults = []
    for path in sorted(package.rglob("*.py")):
        if path.relative_to(package).parts[0] in MAY_IMPORT_CRC:
            continue
        if bad := _imports(path) & CRC:
            faults.append(f"{path.relative_to(package)} imports {', '.join(sorted(bad))}")
    return faults


def loader_sharing_faults(package: Path) -> list[str]:
    """Files in reference/ or crosscheck/ that import the loaders in sources/ or risk/."""
    faults = []
    for name in INDEPENDENT:
        for path in sorted((package / name).rglob("*.py")):
            if bad := _package_modules(path, package) & LOADERS:
                faults.append(f"{path.relative_to(package)} imports {', '.join(sorted(bad))}")
    return faults


def test_only_sources_and_risk_import_crc() -> None:
    assert crc_import_faults(PACKAGE) == []


def test_reference_and_crosscheck_share_nothing_with_the_loaders() -> None:
    # passes trivially while reference/ and crosscheck/ do not exist yet; the test below shows
    # that the rule finds a fault when one is there
    assert loader_sharing_faults(PACKAGE) == []


def test_the_rules_report_a_fake_package_that_breaks_them(tmp_path: Path) -> None:
    package = tmp_path / "flood_lab"
    files = {
        "__init__.py": "",
        "sources/loader.py": "import crc_sdk\n",
        "risk/engine.py": "from crc_framework import Distribution\n",
        "reference/x.py": "import crc_sdk.io\n",
        "reference/ok.py": "import numpy\nfrom . import x\n",
        "crosscheck/a.py": "from flood_lab.sources import loader\n",
        "crosscheck/b.py": "from ..risk import engine\n",
        "crosscheck/c.py": "from .. import sources\n",
    }
    for name, text in files.items():
        (package / name).parent.mkdir(parents=True, exist_ok=True)
        (package / name).write_text(text)
    assert crc_import_faults(package) == ["reference/x.py imports crc_sdk"]
    assert loader_sharing_faults(package) == [
        "crosscheck/a.py imports sources",
        "crosscheck/b.py imports risk",
        "crosscheck/c.py imports sources",
    ]
