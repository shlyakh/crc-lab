"""tools/upstream.py: pins, PyPI filtering, each refusal of `bump`, edits on a copy (offline)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKSPACE_README = REPO.parent / "README.md"
FILES = [
    "pyproject.toml",
    "src/lab_common/__init__.py",
    "README.md",
    "AGENTS.md",
    "CHANGELOG-upstream.md",
    "uv.lock",
]

_spec = importlib.util.spec_from_file_location("upstream_tool", REPO / "tools" / "upstream.py")
assert _spec and _spec.loader
up = importlib.util.module_from_spec(_spec)
sys.modules["upstream_tool"] = up
_spec.loader.exec_module(up)

# Every version below is relative to the pins in the real files, so the tests survive each bump.
PINS = up.read_pins(REPO)
PIN = PINS["crc-sdk"]
FRAMEWORK = PINS["crc-framework"]
_M, _m, _u = (*up.Version(PIN).release, 0, 0)[:3]
OLDER = "0.0.1"  # a release older than the pin
NEXT = f"{_M}.{_m}.{_u + 1}"  # the next release: the bump target
PRE = f"{_M}.{_m}.{_u + 2}a1"  # pre-release
YANKED = f"{_M}.{_m}.{_u + 3}"  # yanked
AFTER = f"{_M}.{_m + 1}.0"  # the release after NEXT: bumping to it skips NEXT
EMPTY = f"{_M}.{_m + 1}.1"  # listed with no files
MISSING = f"{_M}.{_m + 2}.0"  # not on PyPI at all


def _file(time: str, yanked: bool = False) -> dict:
    return {"upload_time_iso_8601": time, "yanked": yanked}


PYPI = {
    "crc-sdk": {
        "releases": {
            OLDER: [_file("2026-08-01T10:00:00Z")],
            PIN: [_file("2026-11-04T22:12:36Z")],
            NEXT: [_file("2026-11-13T21:15:16Z"), _file("2026-11-13T21:14:00Z")],
            PRE: [_file("2026-11-14T10:00:00Z")],
            YANKED: [_file("2026-11-15T10:00:00Z", yanked=True)],
            AFTER: [_file("2026-11-20T10:00:00Z")],
            EMPTY: [],
        }
    },
    "crc-framework": {"releases": {FRAMEWORK: [_file("2026-11-04T10:00:00Z")]}},
}
NOTES = {
    "RiskThinking/crc-sdk": [
        {
            "tag_name": f"v{NEXT}",
            "body": "## What's Changed\n* fix a | b by @x in https://e.org/1\n",
        },
        {"tag_name": f"v{AFTER}", "body": "* bigger"},
    ],
    "RiskThinking/crc-framework-rs": [],
}


class World:
    """Stands in for PyPI, GitHub, git and uv; records every command."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.commands: list[tuple[list[str], Path]] = []
        self.clone_status = ""
        self.repo_status = ""
        self.github_down = False
        self.pypi_down = False
        self.tag = {"crc-sdk": f"v{PIN}", "crc-framework-rs": f"v{FRAMEWORK}"}

    def fetch_json(self, url: str, headers: dict | None = None) -> object:
        if url.startswith("https://pypi.org/"):
            if self.pypi_down:
                raise urllib.error.URLError("no route")
            return PYPI[url.split("/")[-2]]
        if self.github_down:
            raise urllib.error.URLError("rate limited")
        repo = url.split("/repos/")[1].split("/releases")[0]
        return NOTES[repo]

    def run(self, cmd: list[str], cwd: Path, capture: bool = True) -> subprocess.CompletedProcess:
        self.commands.append((cmd, cwd))
        out, code = "", 0
        if cmd[:2] == ["git", "describe"]:
            out = self.tag[cwd.name]
        elif cmd[:2] == ["git", "status"]:
            out = self.repo_status if cwd == self.root else self.clone_status
        return subprocess.CompletedProcess(cmd, code, out, "")

    def ran(self, *prefix: str) -> bool:
        return any(c[: len(prefix)] == list(prefix) for c, _ in self.commands)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    root = tmp_path / "crc-lab"
    for rel in FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    shutil.copy2(WORKSPACE_README, tmp_path / "README.md")
    for clone in ("crc-sdk", "crc-framework-rs"):
        (tmp_path / "upstream" / clone / ".git").mkdir(parents=True)
    w = World(root)
    monkeypatch.setattr(up, "fetch_json", w.fetch_json)
    monkeypatch.setattr(up, "run", w.run)
    monkeypatch.setattr(up, "today", lambda: up.dt.date(2026, 11, 23))
    return w


def snapshot(base: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in base.rglob("*") if p.is_file()}


def bump(w: World, *args: str) -> int:
    return up.main(["bump", *args, "--root", str(w.root)])


def test_pinned_is_parsed_without_importing(tmp_path: Path) -> None:
    from lab_common import PINNED

    assert up.read_pins(REPO) == PINNED
    (tmp_path / "src/lab_common").mkdir(parents=True)
    (tmp_path / up.PINS_FILE).write_text('"""Doc."""\n\nX = 1\nPINNED = {"a": "1.0"}\n')
    assert up.read_pins(tmp_path) == {"a": "1.0"}
    (tmp_path / up.PINS_FILE).write_text("PINS = {}\n")
    with pytest.raises(up.UpstreamError, match="no PINNED"):
        up.read_pins(tmp_path)


def test_prereleases_yanked_and_empty_versions_are_ignored(world: World) -> None:
    releases = up.pypi_releases("crc-sdk")
    assert [str(r.version) for r in releases] == [OLDER, PIN, NEXT, AFTER]
    assert releases[2].date == "2026-11-13"  # the first file's day


def test_condense_keeps_links_and_escapes_pipes() -> None:
    cell = up.condense(
        "## What's Changed\n<!-- x -->\n* a | b in https://e.org/1\n\n- [c](https://e.org/2)\n"
    )
    assert cell == r"a \| b in https://e.org/1; [c](https://e.org/2)"
    assert up.condense("") == "No release notes"


def test_check_reports_newer_releases_and_exit_code(world: World, capsys) -> None:
    assert up.main(["check", "--root", str(world.root)]) == 0
    out = capsys.readouterr().out
    assert f"- Pinned: {PIN}" in out and f"- Latest release on PyPI: {AFTER}" in out
    assert f"#### crc-sdk {NEXT}, released 2026-11-13" in out and "> * bigger" in out
    assert PRE not in out and YANKED not in out and EMPTY not in out
    assert f"`upstream/crc-sdk`: at v{PIN} (matches the pin)" in out
    assert "### crc-framework" in out and "Up to date" in out
    assert f"`just upstream-bump crc-sdk {NEXT}`" in out
    assert up.main(["check", "--exit-code", "--root", str(world.root)]) == 1


def test_check_without_github_still_prints_pypi(world: World, capsys) -> None:
    world.github_down = True
    assert up.main(["check", "--root", str(world.root)]) == 0
    out = capsys.readouterr().out
    assert "GitHub could not be reached" in out and f"#### crc-sdk {AFTER}" in out


def test_check_without_pypi_is_an_error(world: World, capsys) -> None:
    world.pypi_down = True
    assert up.main(["check", "--exit-code", "--root", str(world.root)]) == 2
    captured = capsys.readouterr()
    assert "PyPI could not be reached" in captured.err and "Up to date" not in captured.out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["crc-docs", "1.0"], "unknown package"),
        (["crc-sdk", MISSING], "not a release on PyPI"),
        (["crc-sdk", PRE], "not a release on PyPI"),
        (["crc-sdk", YANKED], "not a release on PyPI"),
        (["crc-sdk", EMPTY], "not a release on PyPI"),
        (["crc-sdk", PIN], "not newer than the pin"),
        (["crc-sdk", OLDER], "not newer than the pin"),
        (["crc-sdk", AFTER], f"skips {NEXT}"),
    ],
)
def test_bump_refuses(world: World, capsys, args: list[str], message: str) -> None:
    before = snapshot(world.root.parent)
    assert bump(world, *args) == 2
    assert message in capsys.readouterr().err
    assert snapshot(world.root.parent) == before
    assert not world.ran("git", "fetch") and not world.ran("uv")


def test_bump_refuses_a_dirty_clone(world: World, capsys) -> None:
    world.clone_status = " M crc_sdk/__init__.py"
    assert bump(world, "crc-sdk", NEXT) == 2
    assert "has local changes" in capsys.readouterr().err
    assert not world.ran("git", "fetch")


def test_bump_refuses_dirty_files_unless_allowed(world: World, capsys) -> None:
    world.repo_status = " M README.md"
    assert bump(world, "crc-sdk", NEXT, "--dry-run") == 2
    assert "uncommitted changes" in capsys.readouterr().err
    status = [c for c, cwd in world.commands if cwd == world.root and c[:2] == ["git", "status"]]
    assert {"pyproject.toml", "README.md", "AGENTS.md", "uv.lock"} <= set(status[0])
    assert bump(world, "crc-sdk", NEXT, "--dry-run", "--allow-dirty") == 0


def test_allow_skip_lets_a_bump_jump(world: World) -> None:
    assert bump(world, "crc-sdk", AFTER, "--dry-run", "--allow-skip") == 0


def test_dry_run_changes_nothing(world: World, capsys) -> None:
    before = snapshot(world.root.parent)
    assert bump(world, "crc-sdk", NEXT, "--dry-run") == 0
    out = capsys.readouterr().out
    assert snapshot(world.root.parent) == before
    assert not world.ran("git", "fetch") and not world.ran("git", "checkout")
    assert not world.ran("uv")
    assert f'+    "crc-sdk[geometry,zarr,raster,netcdf]=={NEXT}",' in out
    assert "git fetch --tags" in out and "uv sync --all-extras --group dev" in out
    assert up.GUIDE in out


def test_bump_changes_exactly_the_listed_locations(world: World, capsys) -> None:
    ws = world.root.parent
    before = snapshot(ws)
    assert bump(world, "crc-sdk", NEXT) == 0
    after = snapshot(ws)
    changed = {p.relative_to(ws).as_posix() for p in before if before[p] != after.get(p)}
    assert set(after) == set(before)
    assert changed == {
        "crc-lab/pyproject.toml",
        "crc-lab/src/lab_common/__init__.py",
        "crc-lab/README.md",
        "crc-lab/AGENTS.md",
        "crc-lab/CHANGELOG-upstream.md",
        "README.md",
    }
    expected = {
        "crc-lab/pyproject.toml": '"crc-sdk[geometry,zarr,raster,netcdf]=={v}",',
        "crc-lab/src/lab_common/__init__.py": '"crc-sdk": "{v}"',
        "crc-lab/README.md": "`crc-sdk=={v}`",
        "crc-lab/AGENTS.md": "`../upstream/crc-sdk/` (v{v})",
        "README.md": "`crc-sdk/` at tag v{v}",
    }
    for rel, template in expected.items():
        old, new = template.format(v=PIN), template.format(v=NEXT)
        text = before[ws / rel].decode()
        assert text.count(old) == 1, f"{rel} no longer holds {old!r}"
        assert after[ws / rel].decode() == text.replace(old, new)
    log_before = before[world.root / "CHANGELOG-upstream.md"].decode().splitlines()
    log_after = after[world.root / "CHANGELOG-upstream.md"].decode().splitlines()
    rule = log_before.index(up.CHANGELOG_RULE)
    assert log_after[: rule + 1] + log_after[rule + 2 :] == log_before
    assert log_after[rule + 1] == (
        f"| 2026-11-23 | crc-sdk | {NEXT} | fix a \\| b by @x in https://e.org/1 "
        "| To be filled in after the re-runs |"
    )
    assert up.read_pins(world.root) == {"crc-sdk": NEXT, "crc-framework": FRAMEWORK}
    clone = ws / "upstream" / "crc-sdk"
    order = [(c, cwd) for c, cwd in world.commands if c[:2] != ["git", "status"]]
    order = [x for x in order if x[0][:2] not in (["git", "describe"], ["git", "rev-parse"])]
    assert order == [
        (["git", "fetch", "--tags"], clone),
        (["git", "checkout", "--quiet", "--detach", f"v{NEXT}"], clone),
        (["uv", "lock"], world.root),
        (["uv", "sync", "--all-extras", "--group", "dev"], world.root),
    ]
    assert not world.ran("git", "commit") and not world.ran("git", "push")
    out = capsys.readouterr().out
    assert "- [ ] just validation-monitor-rerun" in out and up.GUIDE in out


def test_drifted_text_stops_before_any_write(world: World, capsys) -> None:
    agents = world.root / "AGENTS.md"
    agents.write_text(agents.read_text().replace(f"(v{PIN})", f"({PIN})"))
    before = snapshot(world.root.parent)
    assert bump(world, "crc-sdk", NEXT) == 2
    err = capsys.readouterr().err
    assert str(agents) in err and f"`../upstream/crc-sdk/` (v{PIN})" in err
    assert snapshot(world.root.parent) == before
    assert not world.ran("git", "fetch") and not world.ran("uv")
