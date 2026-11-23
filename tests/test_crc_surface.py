"""tools/crc_surface.py: the collector on constructed snippets, `check` on a fake package, and the
real repository against the installed crc-sdk (offline).

Most snippets use a made-up package ``upkg`` so that no upstream-looking string in this file is
itself collected by the real-repository test.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("crc_surface", REPO / "tools" / "crc_surface.py")
assert _spec and _spec.loader
cs = importlib.util.module_from_spec(_spec)
sys.modules["crc_surface"] = cs
_spec.loader.exec_module(cs)

PKG = ("upkg",)


def _collect(tmp_path: Path, source: str, packages: tuple[str, ...] = PKG):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "mod.py").write_text(textwrap.dedent(source))
    return cs.collect(tmp_path, dirs=("src",), packages=packages)


def _lines(surface, name: str) -> list[int]:
    return sorted(int(u.rsplit(":", 1)[1]) for u in surface.names[name])


def test_imports_module_and_from_with_alias_and_inside_functions(tmp_path: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        import upkg.sub
        from upkg.sub import a, b as bee
        import numpy as np

        def f():
            from upkg import other as o
            return o.VALUE, bee, np.zeros
        """,
    )
    assert set(s.names) == {
        "upkg.sub",
        "upkg.sub.a",
        "upkg.sub.b",
        "upkg.other.VALUE",
        "upkg.other",
    }
    assert _lines(s, "upkg.sub.b") == [2, 7]
    assert _lines(s, "upkg.other.VALUE") == [7]
    assert not any(n.startswith("numpy") for n in s.names)


def test_attribute_chains_on_modules_and_imported_classes(tmp_path: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        import upkg
        import upkg.deep.mod
        from upkg.providers import era5 as provider
        from upkg.workflows import HazardDataset

        upkg.__version__
        upkg.deep.mod.THING
        provider.ERA5_STORES
        HazardDataset.crc_open("x")
        """,
    )
    for name in (
        "upkg.__version__",
        "upkg.deep.mod.THING",
        "upkg.providers.era5.ERA5_STORES",
        "upkg.workflows.HazardDataset.crc_open",
    ):
        assert name in s.names, name
    assert s.module_of("upkg.workflows.HazardDataset.crc_open") == "upkg.workflows"
    assert s.module_of("upkg.providers.era5.ERA5_STORES") == "upkg.providers.era5"


def test_import_module_literal_binds_an_alias(tmp_path: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        import importlib
        workflows = importlib.import_module("upkg.workflows")
        workflows.Plan
        for name in workflows.__all__:
            name.endswith("Plan")
        """,
    )
    assert "upkg.workflows.Plan" in s.names
    assert "upkg.workflows.__all__" in s.names
    assert not any("endswith" in n for n in s.names)  # an item of __all__ is a value, not a name


def test_private_names_are_marked_and_dunders_are_not() -> None:
    assert cs.is_private("upkg.workflows._remote.file_checksum")
    assert cs.is_private("upkg.workflows.ibtracs._SUBSETS")
    assert not cs.is_private("upkg.__version__")
    assert not cs.is_private("upkg.workflows.HazardDataset")


def test_string_targets_and_option_table(tmp_path: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        def test_x(monkeypatch):
            monkeypatch.setattr("upkg.workflows.ibtracs._urlopen", None)
            "upkg is a package"
            "upkg.not a path"

        OPTION_TABLES: dict = {
            "era5": {"store": ("upkg.providers.era5", "ERA5_STORES")},
            "ibtracs": {"subset": ("upkg.workflows.ibtracs", "_SUBSETS")},
        }
        """,
    )
    assert _lines(s, "upkg.workflows.ibtracs._urlopen") == [2]
    assert _lines(s, "upkg.providers.era5.ERA5_STORES") == [7]
    assert _lines(s, "upkg.workflows.ibtracs._SUBSETS") == [8]
    assert not any(" " in n for n in s.names)
    md = cs.as_markdown(s, PKG)
    assert "| `upkg.workflows.ibtracs._SUBSETS` | private |" in md
    assert "## `upkg.workflows.ibtracs`" in md


def test_chains_on_returned_values_are_counted_not_named(tmp_path: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        from upkg.workflows import IBTrACSPlan, HazardDataset

        plan = IBTrACSPlan()
        plan.for_area("tx").years(2020)
        HazardDataset.local("p").for_assets

        def f(ds: HazardDataset):
            return ds.curves
        """,
    )
    assert set(s.names) == {
        "upkg.workflows.IBTrACSPlan",
        "upkg.workflows.HazardDataset",
        "upkg.workflows.HazardDataset.local",
    }
    # .for_area, .years, .for_assets, .curves
    assert len(s.unresolved) == 4
    assert cs.as_json(s, PKG)["unresolved_attribute_accesses"] == 4


def test_scopes_keep_function_imports_local(tmp_path: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        def f():
            from upkg import era5
            return era5.X

        def g(era5):
            return era5.Y
        """,
    )
    assert "upkg.era5.X" in s.names and "upkg.era5.Y" not in s.names


@pytest.fixture
def fake_package(tmp_path: Path):
    root = tmp_path / "pkgroot"
    (root / "upkg" / "sub").mkdir(parents=True)
    (root / "upkg" / "__init__.py").write_text("PRESENT = 1\n_HIDDEN = 2\n")
    (root / "upkg" / "sub" / "__init__.py").write_text("class Klass:\n    method = 1\n")
    sys.path.insert(0, str(root))
    yield root
    sys.path.remove(str(root))
    for name in [m for m in sys.modules if m == "upkg" or m.startswith("upkg.")]:
        del sys.modules[name]


def test_check_reports_missing_names_private_first(tmp_path: Path, fake_package: Path) -> None:
    s = _collect(
        tmp_path,
        """\
        import upkg
        from upkg.sub import Klass
        from upkg.gone import thing

        upkg.PRESENT, upkg._HIDDEN, upkg._LOST, upkg.LOST
        Klass.method, Klass.renamed
        """,
    )
    out = io.StringIO()
    assert cs.check(s, PKG, out=out) == 1
    text = out.getvalue()
    missing = [
        line.split()[1].rstrip(":") for line in text.splitlines() if line.startswith("MISSING")
    ]
    assert missing == ["upkg._LOST", "upkg.LOST", "upkg.gone.thing", "upkg.sub.Klass.renamed"]
    assert "src/mod.py:5" in text and "src/mod.py:3" in text
    assert "upkg not installed" in text

    ok = _collect(tmp_path, "import upkg\nupkg.PRESENT\nfrom upkg.sub import Klass\nKlass.method\n")
    assert cs.check(ok, PKG, out=io.StringIO()) == 0


def test_real_repository_uses_only_names_the_installed_upstream_has() -> None:
    """Fails right after a pin move if crc-sdk or crc-framework dropped a name crc-lab uses."""
    surface = cs.collect()
    assert len(surface.names) > 50  # the collector found the real uses
    out = io.StringIO()
    code = cs.check(surface, out=out)
    assert code == 0, out.getvalue()
