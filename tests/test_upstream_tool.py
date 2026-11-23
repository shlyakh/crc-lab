"""tools/upstream.py: pins, PyPI filtering, each refusal of `bump`, edits on a copy (offline)."""

from __future__ import annotations

import copy
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
# A next major version that so far exists only as pre-releases (used with `major_world`).
A1, A2, A3_YANKED, RC1 = (f"{_M + 1}.0.0{s}" for s in ("a1", "a2", "a3", "rc1"))
MAJOR = f"{_M + 1}.0.0"


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
        self.tag: dict[str, str | None] = {
            "crc-sdk": f"v{PIN}",
            "crc-framework-rs": f"v{FRAMEWORK}",
        }  # the tag at HEAD, by clone
        self.local = {c: {t: f"{c}@{t}"} for c, t in self.tag.items()}  # tag -> commit
        self.spelling: dict[tuple[str, str], str] = {}  # (clone, version) -> tag name upstream
        self.extra_remote: dict[str, dict[str, str]] = {}  # more tags the fetch brings
        self.pypi = copy.deepcopy(PYPI)
        self.notes = copy.deepcopy(NOTES)
        self.requires: dict[tuple[str, str], list[str]] = {}  # (name, version) -> requires_dist

    def fetch_json(self, url: str, headers: dict | None = None) -> object:
        if url.startswith("https://pypi.org/"):
            if self.pypi_down:
                raise urllib.error.URLError("no route")
            parts = url.split("/pypi/")[1].split("/")[:-1]
            if len(parts) == 2:  # one version: its dependencies
                return {"info": {"requires_dist": self.requires.get(tuple(parts))}}
            return self.pypi[parts[0]]
        if self.github_down:
            raise urllib.error.URLError("rate limited")
        repo = url.split("/repos/")[1].split("/releases")[0]
        return self.notes[repo]

    def run(self, cmd: list[str], cwd: Path, capture: bool = True) -> subprocess.CompletedProcess:
        self.commands.append((cmd, cwd))
        out, code = "", 0
        clone = cwd.name
        if cmd[:2] == ["git", "describe"]:
            out, code = (self.tag[clone], 0) if self.tag[clone] else ("", 128)
        elif cmd[:2] == ["git", "fetch"]:
            package = "crc-sdk" if clone == "crc-sdk" else "crc-framework"
            for version in self.pypi[package]["releases"]:
                name = self.spelling.get((clone, version), f"v{version}")
                self.local[clone].setdefault(name, f"{clone}@{version}")
            self.local[clone].update(self.extra_remote.get(clone, {}))
        elif cmd[:3] == ["git", "tag", "--list"]:
            out = "\n".join(self.local[clone])
        elif cmd[:2] == ["git", "rev-parse"]:
            out = self.local[clone].get(cmd[-1].removesuffix("^{commit}"), "")
        elif cmd[:2] == ["git", "checkout"]:
            self.tag[clone] = cmd[-1]
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
        (["crc-sdk", PRE], "pre-release; released versions only, unless you pass --pre"),
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
    order = [x for x in order if x[0][:2] != ["git", "tag"]]
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


# --- pre-releases (opt-in with --pre) ---------------------------------------------------------


@pytest.fixture
def major_world(world: World) -> World:
    """After the pin come only pre-releases of the next major version, one of them yanked."""
    world.pypi["crc-sdk"]["releases"] = {
        PIN: [_file("2026-11-04T22:12:36Z")],
        A1: [_file("2026-11-20T10:00:00Z")],
        A2: [_file("2026-11-22T10:00:00Z")],
        A3_YANKED: [_file("2026-11-23T08:00:00Z", yanked=True)],
    }
    return world


def check(w: World, *args: str) -> int:
    return up.main(["check", *args, "--root", str(w.root)])


def test_pre_releases_are_read_only_on_request(world: World) -> None:
    assert PRE not in [str(r.version) for r in up.pypi_releases("crc-sdk")]
    versions = [str(r.version) for r in up.pypi_releases("crc-sdk", pre=True)]
    assert versions == [OLDER, PIN, NEXT, PRE, AFTER]  # the yanked one stays out


def test_check_counts_pre_releases_without_listing_them(world: World, capsys) -> None:
    assert check(world) == 0
    out = capsys.readouterr().out
    assert "- 1 pre-release(s) newer than the pin, not listed; use --pre" in out
    assert PRE not in out
    assert check(world, "--pre") == 0
    out = capsys.readouterr().out
    assert f"#### crc-sdk {PRE} (pre-release), released 2026-11-14" in out
    assert f"#### crc-sdk {NEXT}, released" in out and "use --pre" not in out
    assert "of which 1 pre-release(s)" in out
    assert (
        out.index(f"crc-sdk {AFTER},")
        < out.index(f"crc-sdk {PRE} ")
        < out.index(f"crc-sdk {NEXT},")
    )  # newest first, pre-releases in their place


def test_check_exit_code_counts_pre_releases_only_with_pre(major_world: World, capsys) -> None:
    assert check(major_world, "--exit-code") == 0
    out = capsys.readouterr().out
    assert "Up to date" in out and "- 2 pre-release(s) newer than the pin" in out
    assert check(major_world, "--exit-code", "--pre") == 1
    out = capsys.readouterr().out
    assert f"- Latest pre-release on PyPI: {A2}" in out and A3_YANKED not in out
    assert f"`just upstream-bump crc-sdk {A1} --pre`" in out


def test_bump_to_a_pre_release_needs_pre(major_world: World, capsys) -> None:
    assert bump(major_world, "crc-sdk", A2, "--dry-run") == 2
    assert "--pre" in capsys.readouterr().err


def test_pre_releases_between_do_not_count_as_skipped(major_world: World, capsys) -> None:
    assert bump(major_world, "crc-sdk", A2, "--pre", "--dry-run") == 0
    assert "| To be filled in" in capsys.readouterr().out


def test_final_releases_between_still_count_with_pre(world: World, capsys) -> None:
    assert bump(world, "crc-sdk", PRE, "--pre", "--dry-run") == 2
    assert f"skips {NEXT}" in capsys.readouterr().err


def test_yanked_pre_release_is_refused(major_world: World, capsys) -> None:
    assert bump(major_world, "crc-sdk", A3_YANKED, "--pre", "--dry-run") == 2
    assert "not a release on PyPI" in capsys.readouterr().err


def _holds(w: World, version: str) -> None:
    """Every hand-written location names `version`, and the old pin's texts are gone."""
    ws = w.root.parent
    for path, text in [
        (w.root / "pyproject.toml", f'"crc-sdk[geometry,zarr,raster,netcdf]=={version}",'),
        (w.root / up.PINS_FILE, f'"crc-sdk": "{version}"'),
        (w.root / "README.md", f"`crc-sdk=={version}`"),
        (w.root / "AGENTS.md", f"`../upstream/crc-sdk/` (v{version})"),
        (ws / "README.md", f"`crc-sdk/` at tag v{version}"),
    ]:
        assert path.read_text().count(text) == 1, (path, text)
    assert up.read_pins(w.root)["crc-sdk"] == version


def test_moving_through_pre_releases_to_the_final(major_world: World, capsys) -> None:
    w = major_world
    assert bump(w, "crc-sdk", A1, "--pre") == 0
    _holds(w, A1)
    w.pypi["crc-sdk"]["releases"][RC1] = [_file("2026-11-24T10:00:00Z")]
    w.pypi["crc-sdk"]["releases"][MAJOR] = [_file("2026-11-25T10:00:00Z")]
    assert bump(w, "crc-sdk", A1, "--pre") == 2  # not newer than itself
    assert bump(w, "crc-sdk", A2, "--pre") == 0  # pinned pre-release -> later pre-release
    _holds(w, A2)
    assert check(w, "--pre") == 0
    out = capsys.readouterr().out
    assert f"- Pinned: {A2} (pre-release)" in out
    assert f"`just upstream-bump crc-sdk {MAJOR}`" in out
    assert bump(w, "crc-sdk", A1, "--pre") == 2  # an earlier pre-release is not newer
    assert bump(w, "crc-sdk", MAJOR) == 0  # pinned pre-release -> the final, no --pre needed
    _holds(w, MAJOR)
    log = (w.root / "CHANGELOG-upstream.md").read_text().splitlines()
    rule = log.index(up.CHANGELOG_RULE)
    assert [row.split(" | ")[2] for row in log[rule + 1 : rule + 4]] == [
        MAJOR,
        f"{A2} (pre-release)",
        f"{A1} (pre-release)",
    ]
    checkouts = [c[-1] for c, _ in w.commands if c[:2] == ["git", "checkout"]]
    assert checkouts == [f"v{A1}", f"v{A2}", f"v{MAJOR}"]


# --- the two pins have to resolve together -----------------------------------------------------


def test_bump_refuses_a_target_that_needs_another_framework(major_world: World, capsys) -> None:
    w = major_world
    w.requires[("crc-sdk", A1)] = ["numpy>=1.23", f"crc-framework<{_M + 2},>={A1}"]
    before = snapshot(w.root.parent)
    assert bump(w, "crc-sdk", A1, "--pre") == 2
    err = capsys.readouterr().err
    assert f"crc-sdk {A1} requires crc-framework<{_M + 2},>={A1}" in err
    assert f"excludes crc-framework {FRAMEWORK}" in err and "Move both in one step" in err
    assert snapshot(w.root.parent) == before and not w.ran("git", "fetch")


def test_bump_refuses_when_the_other_pin_excludes_the_target(world: World, capsys) -> None:
    world.requires[("crc-framework", FRAMEWORK)] = [f"crc-sdk<{NEXT}; extra == 'x'"]
    assert bump(world, "crc-sdk", NEXT, "--dry-run") == 2
    assert f"crc-framework {FRAMEWORK} requires crc-sdk<{NEXT}" in capsys.readouterr().err


def test_bump_accepts_compatible_requirements(world: World) -> None:
    world.requires[("crc-sdk", NEXT)] = [f"crc-framework>={FRAMEWORK}", "not a requirement !"]
    world.requires[("crc-framework", FRAMEWORK)] = ["numpy>=1.23"]
    assert bump(world, "crc-sdk", NEXT, "--dry-run") == 0


def test_release_notes_are_found_under_semver_style_tags(major_world: World, capsys) -> None:
    major_world.notes["RiskThinking/crc-sdk"] = [
        {"tag_name": f"v{_M + 1}.0.0-alpha.2", "body": "* alpha two"}
    ]
    assert check(major_world, "--pre") == 0
    out = capsys.readouterr().out
    assert "> * alpha two" in out and f"No GitHub release found for tag v{A1}." in out


# --- a pair that requires each other moves in one step (--with) ---------------------------------

_FM, _fm, _fu = (*up.Version(FRAMEWORK).release, 0, 0)[:3]
FW_A1, FW_A2 = f"{_FM + 1}.0.0a1", f"{_FM + 1}.0.0a2"
FW_FINAL = f"{_FM + 1}.0.0"
FW_TAG_A1, FW_TAG_A2 = f"v{_FM + 1}.0.0-alpha.1", f"v{_FM + 1}.0.0-alpha.2"  # semver spelling
FW_TAG_FINAL = f"v{FW_FINAL}"


@pytest.fixture
def pair_world(major_world: World) -> World:
    """crc-sdk's next major needs crc-framework's next major, and its pin the framework's pin."""
    w = major_world
    w.pypi["crc-framework"]["releases"].update(
        {FW_A1: [_file("2026-11-21T10:00:00Z")], FW_A2: [_file("2026-11-22T10:00:00Z")]}
    )
    w.requires[("crc-sdk", PIN)] = [f"crc-framework<{_FM}.{_fm + 1},>={FRAMEWORK}"]
    for version in (A1, A2):
        w.requires[("crc-sdk", version)] = [f"crc-framework<{_FM + 2},>={FW_A1}"]
    w.spelling[("crc-framework-rs", FW_A1)] = FW_TAG_A1
    w.spelling[("crc-framework-rs", FW_A2)] = FW_TAG_A2
    w.notes["RiskThinking/crc-framework-rs"] = [{"tag_name": FW_TAG_A2, "body": "* fw two"}]
    return w


def test_single_move_refusal_names_the_joint_command(pair_world: World, capsys) -> None:
    before = snapshot(pair_world.root.parent)
    assert bump(pair_world, "crc-sdk", A1, "--pre") == 2
    err = capsys.readouterr().err
    assert f"`just upstream-bump crc-sdk {A1} --pre --with crc-framework={FW_A1}`" in err
    assert bump(pair_world, "crc-framework", FW_A1, "--pre") == 2  # the other way round
    err = capsys.readouterr().err
    assert f"`just upstream-bump crc-framework {FW_A1} --pre --with crc-sdk={A1}`" in err
    assert snapshot(pair_world.root.parent) == before and not pair_world.ran("git", "fetch")


def test_refusal_without_a_known_partner_gives_the_form(pair_world: World, capsys) -> None:
    pair_world.requires[("crc-sdk", A1)] = [f"crc-framework>={_FM + 9}"]
    assert bump(pair_world, "crc-sdk", A1, "--pre") == 2
    assert "--with crc-framework=<version>`" in capsys.readouterr().err


def test_joint_move_changes_both_pins_in_one_step(pair_world: World, capsys) -> None:
    w, ws = pair_world, pair_world.root.parent
    before = snapshot(ws)
    assert bump(w, "crc-sdk", A1, "--pre", "--with", f"crc-framework={FW_A2}") == 0
    after = snapshot(ws)
    changed = {p.relative_to(ws).as_posix() for p in before if before[p] != after.get(p)}
    assert changed == {
        "crc-lab/pyproject.toml",
        "crc-lab/src/lab_common/__init__.py",
        "crc-lab/README.md",
        "crc-lab/AGENTS.md",
        "crc-lab/CHANGELOG-upstream.md",
        "README.md",
    }
    _holds(w, A1)
    for path, text in [
        (w.root / "pyproject.toml", f'"crc-framework=={FW_A2}",'),
        (w.root / up.PINS_FILE, f'"crc-framework": "{FW_A2}"'),
        (w.root / "README.md", f"`crc-framework=={FW_A2}`"),
        (w.root / "AGENTS.md", f"`../upstream/crc-framework-rs/` ({FW_TAG_A2})"),
        (ws / "README.md", f"`crc-framework-rs/` at tag {FW_TAG_A2}"),
    ]:
        assert path.read_text().count(text) == 1, (path, text)
    log = (w.root / "CHANGELOG-upstream.md").read_text().splitlines()
    rule = log.index(up.CHANGELOG_RULE)
    assert log[rule + 1].startswith(f"| 2026-11-23 | crc-sdk | {A1} (pre-release) | ")
    assert log[rule + 2] == (
        f"| 2026-11-23 | crc-framework | {FW_A2} (pre-release) | fw two "
        "| To be filled in after the re-runs |"
    )
    sdk, fw = ws / "upstream" / "crc-sdk", ws / "upstream" / "crc-framework-rs"
    acts = [
        (c, cwd)
        for c, cwd in w.commands
        if c[:2] in (["git", "fetch"], ["git", "checkout"]) or c[0] == "uv"
    ]
    assert acts == [
        (["git", "fetch", "--tags"], sdk),
        (["git", "fetch", "--tags"], fw),
        (["git", "checkout", "--quiet", "--detach", f"v{A1}"], sdk),
        (["git", "checkout", "--quiet", "--detach", FW_TAG_A2], fw),
        (["uv", "lock"], w.root),
        (["uv", "sync", "--all-extras", "--group", "dev"], w.root),
    ]
    assert "- [ ] fill in 'Effect on crc-lab' for crc-sdk" in capsys.readouterr().out


def test_follow_on_bump_finds_a_non_standard_tag_spelling(pair_world: World) -> None:
    w, ws = pair_world, pair_world.root.parent
    assert bump(w, "crc-sdk", A1, "--pre", "--with", f"crc-framework={FW_A1}") == 0
    assert f"({FW_TAG_A1})" in (w.root / "AGENTS.md").read_text()
    w.pypi["crc-framework"]["releases"][FW_FINAL] = [_file("2026-11-24T10:00:00Z")]
    assert bump(w, "crc-framework", FW_A2, "--pre") == 0  # old text built from v...-alpha.1
    assert f"({FW_TAG_A2})" in (w.root / "AGENTS.md").read_text()
    assert bump(w, "crc-framework", FW_FINAL) == 0
    assert f"`crc-framework-rs/` at tag {FW_TAG_FINAL}" in (ws / "README.md").read_text()
    assert f"({FW_TAG_FINAL})" in (w.root / "AGENTS.md").read_text()
    assert up.read_pins(w.root)["crc-framework"] == FW_FINAL


def test_old_tag_falls_back_to_v_pin_when_the_clone_says_nothing(world: World) -> None:
    world.tag["crc-sdk"] = None  # not at a tag: the texts are taken to say v<pin>
    assert bump(world, "crc-sdk", NEXT) == 0
    _holds(world, NEXT)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (f"crc-sdk={NEXT}", "the package being moved"),
        (f"crc-docs={NEXT}", "unknown package 'crc-docs'"),
        ("crc-framework", "expected <package>=<version>"),
        ("=1.0", "expected <package>=<version>"),
    ],
)
def test_with_is_refused_when_malformed(world: World, capsys, value: str, message: str) -> None:
    assert bump(world, "crc-sdk", NEXT, "--with", value, "--dry-run") == 2
    assert message in capsys.readouterr().err


def test_with_package_meets_the_same_refusals(pair_world: World, capsys) -> None:
    w = pair_world
    assert bump(w, "crc-sdk", A1, "--pre", "--with", f"crc-framework={FRAMEWORK}") == 2
    assert f"crc-framework {FRAMEWORK} is not newer than the pin" in capsys.readouterr().err
    w.pypi["crc-sdk"]["releases"][A1] = [_file("2026-11-20T10:00:00Z")]
    assert bump(w, "crc-sdk", A1, "--with", f"crc-framework={FW_A1}") == 2
    assert "unless you pass --pre" in capsys.readouterr().err
    w.clone_status = " M src/lib.rs"
    assert bump(w, "crc-sdk", A1, "--pre", "--with", f"crc-framework={FW_A1}") == 2
    assert "has local changes" in capsys.readouterr().err
    assert not w.ran("git", "fetch")


def test_pair_that_does_not_resolve_is_refused(pair_world: World, capsys) -> None:
    pair_world.requires[("crc-framework", FW_A1)] = [f"crc-sdk>={A2}"]
    before = snapshot(pair_world.root.parent)
    assert bump(pair_world, "crc-sdk", A1, "--pre", "--with", f"crc-framework={FW_A1}") == 2
    err = capsys.readouterr().err
    assert "the two targets would not resolve together" in err
    assert f"crc-framework {FW_A1} requires crc-sdk>={A2}, which excludes crc-sdk {A1}" in err
    assert snapshot(pair_world.root.parent) == before and not pair_world.ran("git", "fetch")


def test_dry_run_without_a_local_tag_is_provisional(pair_world: World, capsys) -> None:
    before = snapshot(pair_world.root.parent)
    args = ("crc-sdk", A1, "--pre", "--with", f"crc-framework={FW_A2}", "--dry-run")
    assert bump(pair_world, *args) == 0
    out = capsys.readouterr().out
    assert snapshot(pair_world.root.parent) == before
    assert not pair_world.ran("git", "fetch") and not pair_world.ran("git", "checkout")
    assert (
        f"provisional: no tag in {pair_world.root.parent / 'upstream' / 'crc-framework-rs'}" in out
    )
    assert f"+  - `crc-framework-rs/` at tag v{FW_A2}" in out
    assert f"git checkout --quiet --detach v{FW_A2})   # provisional" in out
    # once the tag is in the clone, the dry run names it as it is spelled
    pair_world.local["crc-framework-rs"][FW_TAG_A2] = "fw@a2"
    pair_world.local["crc-sdk"][f"v{A1}"] = "sdk@a1"
    assert bump(pair_world, *args) == 0
    out = capsys.readouterr().out
    assert "provisional" not in out and f"at tag {FW_TAG_A2}" in out


def test_tag_resolution_reads_semver_spellings(world: World) -> None:
    clone = world.root.parent / "upstream" / "crc-sdk"
    world.local["crc-sdk"] = {"v1.0.0-alpha.2": "a", "v1.0.0a1": "b", "v1.0.0": "c", "x": "d"}
    resolve = up.resolve_tag
    assert resolve(clone, up.Version("1.0.0a2"), True) == "v1.0.0-alpha.2"
    assert resolve(clone, up.Version("1.0.0a1"), True) == "v1.0.0a1"
    assert resolve(clone, up.Version("1.0.0"), True) == "v1.0.0"
    assert resolve(clone, up.Version("1.0.0rc1"), False) is None
    with pytest.raises(up.UpstreamError, match="tags near it: v1.0.0a1, v1.0.0-alpha.2, v1.0.0"):
        resolve(clone, up.Version("1.0.0rc1"), True)
    world.local["crc-sdk"]["1.0.0"] = "c"  # a second name for the same commit is fine
    assert resolve(clone, up.Version("1.0.0"), True) == "v1.0.0"


def test_ambiguous_tags_stop_the_bump_before_any_write(world: World, capsys) -> None:
    world.extra_remote["crc-sdk"] = {NEXT: "another commit"}  # "0.11.3" next to "v0.11.3"
    before = snapshot(world.root.parent)
    assert bump(world, "crc-sdk", NEXT) == 2
    err = capsys.readouterr().err
    assert "point at different commits" in err and f"v{NEXT}" in err
    assert snapshot(world.root.parent) == before
    assert not world.ran("git", "checkout") and not world.ran("uv")


def test_missing_tag_after_fetch_stops_before_any_write(world: World, capsys) -> None:
    world.spelling[("crc-sdk", NEXT)] = "release-candidate"  # names no version
    before = snapshot(world.root.parent)
    assert bump(world, "crc-sdk", NEXT) == 2
    assert f"names version {NEXT}; tags near it: v{PIN}" in capsys.readouterr().err
    assert snapshot(world.root.parent) == before and not world.ran("git", "checkout")


def test_check_gives_the_joint_command_and_reads_tag_spellings(pair_world: World, capsys) -> None:
    pair_world.tag["crc-framework-rs"] = FRAMEWORK  # the pin's tag without the "v"
    assert check(pair_world, "--pre") == 0
    out = capsys.readouterr().out
    assert (
        f"`just upstream-bump crc-sdk {A1} --pre --with crc-framework={FW_A1}` "
        "(the two move together)"
    ) in out
    assert f"`upstream/crc-framework-rs`: at {FRAMEWORK} (matches the pin)" in out
    assert "> * fw two" in out  # notes under the semver tag
