"""Watch and move the crc-sdk and crc-framework pins, one released version at a time.

    uv run python tools/upstream.py check [--exit-code] [--pre]
    uv run python tools/upstream.py bump <package> <version> [--dry-run] [--allow-skip]
                                         [--allow-dirty] [--pre]

Pre-releases are ignored unless `--pre` is given: `check --pre` lists them too (marked), and
`bump --pre` accepts one as the target (the skip rule then counts final releases only).

`check` only reads: the pins in `src/lab_common/__init__.py`, PyPI, GitHub release notes and the
reference clones. Its output is Markdown (it is appended to the monitor workflow's step summary).

`bump` moves one pin to one newer release: it checks everything first, then moves the reference
clone's tag, replaces the version in each hand-written location, adds a row to
`CHANGELOG-upstream.md` and runs `uv lock` and `uv sync`. It never commits or pushes. The steps
after it are in `docs/upstream-updates.md`.

Standard library plus `packaging` (already in the locked environment). `--root` points the tool at
another copy of the repository (the workspace root is its parent) so tests can run on a copy.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PINS_FILE = "src/lab_common/__init__.py"
CHANGELOG = "CHANGELOG-upstream.md"
CHANGELOG_RULE = "| --- | --- | --- | --- | --- |"
EFFECT_PLACEHOLDER = "To be filled in after the re-runs"
GUIDE = "docs/upstream-updates.md"
TIMEOUT = 30


@dataclass(frozen=True)
class Package:
    name: str  # PyPI name and key in PINNED
    repo: str  # GitHub owner/name
    clone: str  # directory under <workspace>/upstream/
    pyproject: str  # the requirement as written in pyproject.toml, with {v}


PACKAGES = {
    "crc-sdk": Package(
        "crc-sdk",
        "RiskThinking/crc-sdk",
        "crc-sdk",
        '"crc-sdk[zarr,raster,netcdf]=={v}",',
    ),
    "crc-framework": Package(
        "crc-framework",
        "RiskThinking/crc-framework-rs",
        "crc-framework-rs",
        '"crc-framework=={v}",',
    ),
}


class UpstreamError(Exception):
    """A refusal or failure, with a message for the person running the tool."""


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def workspace(self) -> Path:
        return self.root.parent

    def clone(self, pkg: Package) -> Path:
        return self.workspace / "upstream" / pkg.clone


@dataclass(frozen=True)
class Location:
    path: Path
    old: str
    new: str


@dataclass(frozen=True)
class Release:
    version: Version
    date: str  # YYYY-MM-DD of the first non-yanked file

    @property
    def pre(self) -> bool:
        return self.version.is_prerelease  # includes dev releases


def _mark(version: Version) -> str:
    return f"{version} (pre-release)" if version.is_prerelease else str(version)


# --- outside world (stubbed in tests) -------------------------------------------------------


def fetch_json(url: str, headers: dict[str, str] | None = None) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": "crc-lab-upstream", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def run(cmd: list[str], cwd: Path, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, check=False)


def today() -> dt.date:
    return dt.date.today()


# --- reading ---------------------------------------------------------------------------------


def read_pins(root: Path) -> dict[str, str]:
    """`PINNED` from the shared package, parsed (crc packages are never imported)."""
    path = root / PINS_FILE
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if any(isinstance(t, ast.Name) and t.id == "PINNED" for t in targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict) and all(isinstance(v, str) for v in value.values()):
                return value
    raise UpstreamError(f"{path}: no PINNED = {{...}} dictionary of strings found")


def pypi_releases(name: str, pre: bool = False) -> list[Release]:
    """Versions on PyPI, oldest first; yanked ones left out, and pre-releases unless `pre`."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        data = fetch_json(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamError(f"PyPI could not be reached for {name} ({url}): {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("releases"), dict):
        raise UpstreamError(f"PyPI answered for {name} without a 'releases' table ({url})")
    out = []
    for text, files in data["releases"].items():
        try:
            version = Version(text)
        except InvalidVersion:
            continue
        if version.is_prerelease and not pre:
            continue
        live = [f for f in files if not f.get("yanked")]
        if not live:  # yanked, or no files at all
            continue
        date = min(f.get("upload_time_iso_8601") or f.get("upload_time") or "" for f in live)
        out.append(Release(version, date[:10]))
    if not out:
        raise UpstreamError(f"PyPI lists no released version of {name} ({url})")
    return sorted(out, key=lambda r: r.version)


def github_notes(pkg: Package) -> dict[str, str]:
    """Release notes by tag name from GitHub's public API; raises UpstreamError if unreachable."""
    url = f"https://api.github.com/repos/{pkg.repo}/releases?per_page=100"
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    try:
        data = fetch_json(url, headers)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamError(f"GitHub could not be reached ({url}): {exc}") from exc
    if not isinstance(data, list):
        raise UpstreamError(f"GitHub answered without a list of releases ({url}): {data!r:.200}")
    notes = {}
    for r in data:
        tag, body = r.get("tag_name") or "", (r.get("body") or "").strip()
        notes[tag] = body
        try:  # also under v<normalised version>: v1.0.0-alpha.2 is found as v1.0.0a2
            notes.setdefault(f"v{Version(tag.removeprefix('v'))}", body)
        except InvalidVersion:
            pass
    return notes


def requires(name: str, version: str) -> list[Requirement]:
    """The dependencies PyPI lists for one version (all of them, extras included)."""
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        data = fetch_json(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamError(
            f"PyPI could not be reached for {name} {version} ({url}): {exc}"
        ) from exc
    info = data.get("info") if isinstance(data, dict) else None
    out = []
    for text in (info or {}).get("requires_dist") or []:
        try:
            out.append(Requirement(text))
        except InvalidRequirement:
            continue
    return out


def conflicts(after: dict[str, str]) -> list[str]:
    """Where the pins, as they would be after a move, exclude each other (both directions)."""
    problems = []
    for owner in PACKAGES:
        for dep in PACKAGES:
            if owner == dep or owner not in after or dep not in after:
                continue
            for req in requires(owner, after[owner]):
                if canonicalize_name(req.name) != canonicalize_name(dep):
                    continue
                if not req.specifier.contains(after[dep], prereleases=True):
                    problems.append(
                        f"{owner} {after[owner]} requires {req}, which excludes {dep} {after[dep]}"
                    )
    return problems


def joint_command(name: str, target: str, pins: dict[str, str]) -> str:
    """The `--with` form that fixes a single move the other pin rules out.

    Names the lowest version of the other package that the target accepts and that accepts the
    target, if PyPI says so within a few lookups; otherwise only the form."""
    other = next(o for o in PACKAGES if o != name)
    pre = " --pre" if Version(target).is_prerelease else ""
    generic = f"`just upstream-bump {name} {target}{pre} --with {other}=<version>`"
    try:
        wanted = [r for r in requires(name, target) if _same(r.name, other)]
        candidates = [
            r.version
            for r in pypi_releases(other, pre=True)
            if all(q.specifier.contains(r.version, prereleases=True) for q in wanted)
        ]
        for version in candidates[:10]:
            back = [r for r in requires(other, str(version)) if _same(r.name, name)]
            if all(q.specifier.contains(target, prereleases=True) for q in back):
                pre = " --pre" if Version(target).is_prerelease or version.is_prerelease else ""
                return f"`just upstream-bump {name} {target}{pre} --with {other}={version}`"
    except UpstreamError:
        pass
    return generic


def _same(a: str, b: str) -> bool:
    return canonicalize_name(a) == canonicalize_name(b)


def clone_state(pkg: Package, paths: Paths) -> tuple[str | None, str]:
    """(tag at HEAD or None, local changes as `git status --porcelain` text)."""
    clone = paths.clone(pkg)
    if not (clone / ".git").exists():
        raise UpstreamError(f"reference clone not found: {clone}")
    tag = run(["git", "describe", "--tags", "--exact-match", "HEAD"], clone)
    status = run(["git", "status", "--porcelain"], clone)
    if status.returncode != 0:
        raise UpstreamError(f"git status failed in {clone}: {status.stderr.strip()}")
    return (tag.stdout.strip() or None) if tag.returncode == 0 else None, status.stdout.strip()


def condense(notes: str) -> str:
    """Release notes as one Markdown table cell: headings dropped, lines joined, pipes escaped."""
    notes = re.sub(r"<!--.*?-->", "", notes, flags=re.S)
    parts = []
    for line in notes.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts.append(re.sub(r"^[*+-]\s+", "", line))
    return "; ".join(parts).replace("|", r"\|") or "No release notes"


# --- check -----------------------------------------------------------------------------------


def check(paths: Paths, pre: bool = False) -> tuple[str, bool]:
    """The Markdown report and whether anything listed is newer than a pin.

    Pre-releases newer than a pin are listed only with `pre`; without it they are counted."""
    pins = read_pins(paths.root)
    lines = [f"## Upstream releases (checked {today().isoformat()})", ""]
    nexts: dict[str, Version] = {}
    for name, pkg in PACKAGES.items():
        if name not in pins:
            raise UpstreamError(f"{PINS_FILE} has no pin for {name}")
        pinned = Version(pins[name])
        everything = pypi_releases(name, pre=True)
        finals = [r for r in everything if not r.pre]
        newer_pre = [r for r in everything if r.pre and r.version > pinned]
        newer = [r for r in everything if r.version > pinned and (pre or not r.pre)]
        latest = str(finals[-1].version) if finals else "none (pre-releases only)"
        lines += [
            f"### {name}",
            "",
            f"- Pinned: {_mark(pinned)}",
            f"- Latest release on PyPI: {latest}",
        ]
        if pre and newer_pre:
            lines.append(f"- Latest pre-release on PyPI: {newer_pre[-1].version}")
        try:
            tag, changes = clone_state(pkg, paths)
            where = f"at {tag}" if tag else "not at a tag"
            ok = tag is not None and _tag_version(tag) == pinned
            match = "matches the pin" if ok else f"**expected the tag of {pinned}**"
            dirty = "; **has local changes**" if changes else ""
            lines.append(f"- Reference clone `upstream/{pkg.clone}`: {where} ({match}){dirty}")
        except UpstreamError as exc:
            lines.append(f"- Reference clone `upstream/{pkg.clone}`: not checked ({exc})")
        if newer_pre and not pre:
            lines.append(
                f"- {len(newer_pre)} pre-release(s) newer than the pin, not listed; use --pre"
            )
        if not newer:
            lines += ["- Up to date: no release newer than the pin.", ""]
            continue
        next_final = [r for r in newer if not r.pre]
        nexts[name] = (next_final or newer)[0].version
        count = f"{len(newer)} release(s)"
        if pre and newer_pre:
            count += f", of which {len(newer_pre)} pre-release(s)"
        lines += [f"- Newer than the pin: {count}", ""]
        try:
            notes: dict[str, str] | None = github_notes(pkg)
        except UpstreamError as exc:
            notes = None
            lines += [f"{exc}; release notes not shown.", ""]
        for r in reversed(newer):
            lines += [f"#### {name} {_mark(r.version)}, released {r.date}", ""]
            if notes is not None:
                body = notes.get(f"v{r.version}")
                if body is None:
                    lines += [f"No GitHub release found for tag v{r.version}.", ""]
                else:
                    lines += [
                        ("> " + s).rstrip() for s in (body or "No release notes").splitlines()
                    ]
                    lines.append("")
    if nexts:
        lines.append(
            f"Next step, one release at a time: {next_steps(nexts, pins)} (see `{GUIDE}`)."
        )
    else:
        lines.append("All pins are at the latest release.")
    return "\n".join(lines) + "\n", bool(nexts)


# --- tags in the reference clones ---------------------------------------------------------------


def _tag_version(tag: str) -> Version | None:
    try:
        return Version(tag.removeprefix("v"))
    except InvalidVersion:
        return None


def resolve_tag(clone: Path, version: Version, required: bool) -> str | None:
    """The tag in `clone` that names `version` (v1.0.0-alpha.2 names 1.0.0a2).

    None if no tag matches and `required` is false; refused if none matches and it is required,
    or if tags naming the version point at different commits."""
    listed = run(["git", "tag", "--list"], clone)
    names = listed.stdout.split() if listed.returncode == 0 else []
    matches = [n for n in names if _tag_version(n) == version]
    if not matches:
        if not required:
            return None
        near = sorted(
            (n for n in names if (v := _tag_version(n)) and v.release[:2] == version.release[:2]),
            key=_tag_version,
        )
        raise UpstreamError(
            f"no tag in {clone} names version {version}; tags near it: "
            + (", ".join(near) or "none")
        )
    commits: dict[str, list[str]] = {}
    for n in matches:
        sha = run(["git", "rev-parse", "--verify", "--quiet", f"{n}^{{commit}}"], clone)
        commits.setdefault(sha.stdout.strip(), []).append(n)
    if len(commits) > 1:
        raise UpstreamError(
            f"tags {', '.join(sorted(matches))} in {clone} all name version {version} "
            "but point at different commits; nothing changed"
        )
    standard = f"v{version}"
    return standard if standard in matches else sorted(matches)[0]


def pinned_tag(tag_at_head: str | None, pinned: str) -> str:
    """The tag the hand-written texts name now: the clone's own, if it is the pin's, else v<pin>."""
    if tag_at_head and _tag_version(tag_at_head) == Version(pinned):
        return tag_at_head
    return f"v{pinned}"


def next_steps(nexts: dict[str, Version], pins: dict[str, str]) -> str:
    """The commands for the next releases: one joint command when they only move together."""
    singles = []
    for name, version in nexts.items():
        pre = " --pre" if version.is_prerelease else ""
        singles.append(f"`just upstream-bump {name} {version}{pre}`")
    if len(nexts) == 2:
        (a, va), (b, vb) = nexts.items()
        try:
            alone = [conflicts({**pins, a: str(va)}), conflicts({**pins, b: str(vb)})]
            together = conflicts({**pins, a: str(va), b: str(vb)})
        except UpstreamError:
            return ", ".join(singles)
        if all(alone) and not together:
            pre = " --pre" if va.is_prerelease or vb.is_prerelease else ""
            return f"`just upstream-bump {a} {va}{pre} --with {b}={vb}` (the two move together)"
    return ", ".join(singles)


# --- bump ------------------------------------------------------------------------------------


@dataclass
class Move:
    pkg: Package
    old: str  # the pinned version as written in PINNED
    target: Version
    old_tag: str = ""
    new_tag: str | None = None  # None until resolved

    @property
    def text(self) -> str:
        return str(self.target)

    @property
    def tag(self) -> str:
        return self.new_tag or f"v{self.text}"


def locations(move: Move, paths: Paths) -> list[Location]:
    """Every hand-written place that names the pin, with the exact text before and after."""
    pkg, root, ws = move.pkg, paths.root, paths.workspace
    templates = [
        (root / "pyproject.toml", pkg.pyproject),
        (root / PINS_FILE, f'"{pkg.name}": "{{v}}"'),
        (root / "README.md", f"`{pkg.name}=={{v}}`"),
        (root / "AGENTS.md", f"`../upstream/{pkg.clone}/` ({{tag}})"),
        (ws / "README.md", f"`{pkg.clone}/` at tag {{tag}}"),
    ]
    return [
        Location(
            p,
            t.format(v=move.old, tag=move.old_tag),
            t.format(v=move.text, tag=move.tag),
        )
        for p, t in templates
    ]


def dirty_files(root: Path, files: list[Path]) -> list[str]:
    inside = [str(f.relative_to(root)) for f in files if f.is_relative_to(root)]
    result = run(["git", "status", "--porcelain", "--", *inside], root)
    if result.returncode != 0:
        raise UpstreamError(f"git status failed in {root}: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def plan_edits(locs: list[Location], rows: list[str], paths: Paths) -> dict[Path, tuple[str, str]]:
    """{file: (text now, text after)}; raises before anything is written if a text has drifted.

    `rows` go to the top of the changelog table in the order given."""
    edits: dict[Path, tuple[str, str]] = {}
    problems = []
    for loc in locs:
        if not loc.path.exists():
            problems.append(f"{loc.path}: file not found (expected {loc.old!r})")
            continue
        before, current = edits.get(loc.path, (None, None))
        text = current if current is not None else loc.path.read_text(encoding="utf-8")
        count = text.count(loc.old)
        if count != 1:
            problems.append(f"{loc.path}: expected {loc.old!r} exactly once, found {count}")
            continue
        edits[loc.path] = (before if before is not None else text, text.replace(loc.old, loc.new))
    log = paths.root / CHANGELOG
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    lines = text.splitlines(keepends=True)
    rules = [i for i, line in enumerate(lines) if line.rstrip("\n") == CHANGELOG_RULE]
    if len(rules) != 1:
        problems.append(
            f"{log}: expected the table rule {CHANGELOG_RULE!r} exactly once, found {len(rules)}"
        )
    else:
        lines[rules[0] + 1 : rules[0] + 1] = [row + "\n" for row in rows]
        edits[log] = (text, "".join(lines))
    if problems:
        raise UpstreamError(
            "nothing changed; the text expected is not there:\n  " + "\n  ".join(problems)
        )
    return edits


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def must(cmd: list[str], cwd: Path, capture: bool = True) -> None:
    result = run(cmd, cwd, capture)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise UpstreamError(
            f"`{' '.join(cmd)}` failed in {cwd} (exit {result.returncode}) {detail}"
        )


def checklist(moved: list[str]) -> str:
    steps = [
        "just test",
        "just lint",
        "just validation-monitor-rerun",
        "read docs/validation/monitoring.md",
        "just validation-accept <id>, once per source re-run",
        "re-check the open findings in src/data_source_check/sources/crc_sdk/findings.toml",
        "review the hand-written 'about' line in site/sources.json (it names the crc-sdk version)",
        "just validation",
        "just site",
        f"fill in 'Effect on crc-lab' for {' and '.join(moved)} in {CHANGELOG}",
    ]
    return "\n".join(
        [
            "",
            "Remaining steps (nothing is committed):",
            *[f"- [ ] {s}" for s in steps],
            f"See {GUIDE}.",
        ]
    )


def parse_with(value: str) -> tuple[str, str]:
    """`crc-framework=1.0.0a2` (or `==`) -> (package, version)."""
    match = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==?\s*(\S+)\s*", value)
    if not match:
        raise UpstreamError(f"--with {value!r}: expected <package>=<version>")
    return match.group(1), match.group(2)


def plan_move(
    pins: dict[str, str], name: str, target_text: str, *, pre: bool, allow_skip: bool
) -> Move:
    """One package's move, after every refusal that concerns that package alone."""
    if name not in PACKAGES:
        raise UpstreamError(f"unknown package {name!r}; known: {', '.join(PACKAGES)}")
    if name not in pins:
        raise UpstreamError(f"{PINS_FILE} has no pin for {name}")
    old_text = pins[name]
    try:
        target, pinned = Version(target_text), Version(old_text)
    except InvalidVersion as exc:
        raise UpstreamError(f"not a version: {exc}") from exc
    target_text = str(target)  # "v0.11.2" and "0.11.2" both mean 0.11.2
    if target.is_prerelease and not pre:
        raise UpstreamError(
            f"{name} {target_text} is a pre-release; released versions only, unless you pass --pre"
        )
    releases = {r.version: r for r in pypi_releases(name, pre=pre)}
    if target not in releases:
        known = ", ".join(str(v) for v in sorted(releases)[-5:])
        kinds = "yanked versions do not count" + ("" if pre else ", nor pre-releases without --pre")
        raise UpstreamError(
            f"{name} {target_text} is not a release on PyPI ({kinds}); latest: {known}"
        )
    if target <= pinned:
        raise UpstreamError(f"{name} {target_text} is not newer than the pin {old_text}")
    # Only final releases count as skipped: 0.11.2 -> 1.0.0a2 does not skip 1.0.0a1.
    skipped = sorted(v for v in releases if pinned < v < target and not v.is_prerelease)
    if skipped and not allow_skip:
        raise UpstreamError(
            f"{name} {target_text} skips {', '.join(map(str, skipped))}; "
            f"move one release at a time (next: {skipped[0]}) or pass --allow-skip"
        )
    return Move(PACKAGES[name], old_text, target)


def bump(
    paths: Paths,
    name: str,
    target_text: str,
    *,
    with_: str | None = None,
    dry_run: bool = False,
    allow_skip: bool = False,
    allow_dirty: bool = False,
    pre: bool = False,
) -> str:
    """Move one pin, or with `with_` a pair that require each other, in one step."""
    out: list[str] = []
    pins = read_pins(paths.root)
    wanted = [(name, target_text)]
    if with_ is not None:
        other, other_version = parse_with(with_)
        if other not in PACKAGES:
            raise UpstreamError(f"--with: unknown package {other!r}; known: {', '.join(PACKAGES)}")
        if _same(other, name):
            raise UpstreamError(f"--with names {other}, the package being moved; name the other")
        wanted.append((other, other_version))
    moves = [plan_move(pins, n, t, pre=pre, allow_skip=allow_skip) for n, t in wanted]
    problems = conflicts({**pins, **{m.pkg.name: m.text for m in moves}})
    if problems and len(moves) == 1:
        raise UpstreamError(
            "the pins would not resolve together: "
            + "; ".join(problems)
            + ". Move both in one step: "
            + joint_command(name, moves[0].text, pins)
        )
    if problems:
        raise UpstreamError("the two targets would not resolve together: " + "; ".join(problems))
    for m in moves:
        clone = paths.clone(m.pkg)
        tag_at_head, changes = clone_state(m.pkg, paths)
        if changes:
            raise UpstreamError(f"reference clone {clone} has local changes:\n{changes}")
        m.old_tag = pinned_tag(tag_at_head, m.old)
        m.new_tag = resolve_tag(clone, m.target, required=False)  # the fetch may change it
    rows = []
    for m in moves:
        try:
            notes = github_notes(m.pkg).get(f"v{m.text}")
            if notes is None:
                out.append(
                    f"warning: no GitHub release for {m.pkg.name} {m.text}; "
                    "the changelog row says so."
                )
                notes = f"No GitHub release found for {m.text}"
        except UpstreamError as exc:
            out.append(f"warning: {exc}; the changelog row says so.")
            notes = "Release notes not fetched (GitHub unreachable)"
        cells = [today().isoformat(), m.pkg.name, _mark(m.target), condense(notes)]
        rows.append("| " + " | ".join([*cells, EFFECT_PLACEHOLDER]) + " |")

    def plan() -> dict[Path, tuple[str, str]]:
        return plan_edits([loc for m in moves for loc in locations(m, paths)], rows, paths)

    edits = plan()
    dirty = dirty_files(paths.root, [*edits, paths.root / "uv.lock"])
    if dirty and not allow_dirty:
        raise UpstreamError(
            "uncommitted changes in files this would edit (pass --allow-dirty to go on):\n"
            + "\n".join(dirty)
        )
    for f in edits:
        if not f.is_relative_to(paths.root):
            out.append(f"note: {f} is outside the repository; git cannot show or undo its change.")
    lock = [
        (["uv", "lock"], paths.root),
        (["uv", "sync", "--all-extras", "--group", "dev"], paths.root),
    ]
    summary = ", ".join(f"{m.pkg.name} {m.old} -> {m.text}" for m in moves)
    moved = [f"{m.pkg.name} {m.text}" for m in moves]
    if dry_run:
        out.append(f"Dry run: {summary}. Nothing is changed.\n")
        for m in moves:
            if m.new_tag is None:
                out.append(
                    f"provisional: no tag in {paths.clone(m.pkg)} names {m.text} yet; the texts "
                    f"below say {m.tag}, and the tag is resolved after the fetch "
                    "(a tag such as v1.0.0-alpha.1 would be written as it is)."
                )
        for path, (before, after) in edits.items():
            out.append(
                "".join(
                    difflib.unified_diff(
                        before.splitlines(keepends=True),
                        after.splitlines(keepends=True),
                        fromfile=f"{path} (now)",
                        tofile=f"{path} (after)",
                    )
                )
            )
        out.append("Commands it would run:")
        for m in moves:
            out.append(f"  (cd {paths.clone(m.pkg)} && git fetch --tags)")
        for m in moves:
            mark = "" if m.new_tag else "   # provisional: the tag naming the version, after fetch"
            out.append(
                f"  (cd {paths.clone(m.pkg)} && git checkout --quiet --detach {m.tag}){mark}"
            )
        out += [f"  (cd {cwd} && {' '.join(cmd)})" for cmd, cwd in lock]
        out.append(checklist(moved))
        return "\n".join(out)
    for m in moves:
        must(["git", "fetch", "--tags"], paths.clone(m.pkg))
    for m in moves:
        m.new_tag = resolve_tag(paths.clone(m.pkg), m.target, required=True)
    edits = plan()  # again, with the tags as fetched
    for m in moves:
        must(["git", "checkout", "--quiet", "--detach", m.tag], paths.clone(m.pkg))
        out.append(f"{paths.clone(m.pkg)}: at {m.tag}")
    for path, (_, after) in edits.items():
        write_atomic(path, after)
        out.append(f"edited {path}")
    print("\n".join(out), flush=True)
    out = []
    for cmd, cwd in lock:
        print(f"$ {' '.join(cmd)}", flush=True)
        must(cmd, cwd, capture=False)
    out.append(f"Moved: {summary}.")
    out.append(checklist(moved))
    return "\n".join(out)


# --- command line ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="the crc-lab repository")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", parents=[common], help="report releases newer than the pins")
    p_check.add_argument(
        "--exit-code", action="store_true", help="exit 1 if a newer release exists"
    )
    p_check.add_argument("--pre", action="store_true", help="also list newer pre-releases")
    p_bump = sub.add_parser("bump", parents=[common], help="move one pin to one newer release")
    p_bump.add_argument("package", help=", ".join(PACKAGES))
    p_bump.add_argument("version")
    p_bump.add_argument("--dry-run", action="store_true", help="show the diffs and commands only")
    p_bump.add_argument("--allow-skip", action="store_true", help="allow skipping releases")
    p_bump.add_argument("--allow-dirty", action="store_true", help="allow uncommitted changes")
    p_bump.add_argument("--pre", action="store_true", help="allow a pre-release as the target")
    p_bump.add_argument(
        "--with",
        dest="with_",
        metavar="PACKAGE=VERSION",
        help="move the other package in the same step (a pair that require each other)",
    )
    args = parser.parse_args(argv)
    paths = Paths(args.root.resolve())
    try:
        if args.command == "check":
            report, newer = check(paths, pre=args.pre)
            print(report, end="")
            return 1 if newer and args.exit_code else 0
        print(
            bump(
                paths,
                args.package,
                args.version,
                with_=args.with_,
                dry_run=args.dry_run,
                allow_skip=args.allow_skip,
                allow_dirty=args.allow_dirty,
                pre=args.pre,
            )
        )
        return 0
    except UpstreamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
