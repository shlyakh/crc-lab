"""Watch and move the crc-sdk and crc-framework pins, one released version at a time.

    uv run python tools/upstream.py check [--exit-code]
    uv run python tools/upstream.py bump <package> <version> [--dry-run] [--allow-skip]
                                         [--allow-dirty]

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
        '"crc-sdk[geometry,zarr,raster,netcdf]=={v}",',
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


def pypi_releases(name: str) -> list[Release]:
    """Released versions on PyPI, oldest first; pre-releases and yanked versions left out."""
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
        if version.is_prerelease or version.is_devrelease:
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
    return {r.get("tag_name", ""): (r.get("body") or "").strip() for r in data}


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


def check(paths: Paths) -> tuple[str, bool]:
    """The Markdown report and whether anything newer than a pin exists."""
    pins = read_pins(paths.root)
    lines = [f"## Upstream releases (checked {today().isoformat()})", ""]
    nexts = []
    for name, pkg in PACKAGES.items():
        if name not in pins:
            raise UpstreamError(f"{PINS_FILE} has no pin for {name}")
        pinned = Version(pins[name])
        releases = pypi_releases(name)
        newer = [r for r in releases if r.version > pinned]
        lines += [
            f"### {name}",
            "",
            f"- Pinned: {pinned}",
            f"- Latest release on PyPI: {releases[-1].version}",
        ]
        try:
            tag, changes = clone_state(pkg, paths)
            where = f"at {tag}" if tag else "not at a tag"
            match = "matches the pin" if tag == f"v{pinned}" else f"**expected v{pinned}**"
            dirty = "; **has local changes**" if changes else ""
            lines.append(f"- Reference clone `upstream/{pkg.clone}`: {where} ({match}){dirty}")
        except UpstreamError as exc:
            lines.append(f"- Reference clone `upstream/{pkg.clone}`: not checked ({exc})")
        if not newer:
            lines += ["- Up to date: no release newer than the pin.", ""]
            continue
        nexts.append(f"{name} {newer[0].version}")
        lines += [f"- Newer than the pin: {len(newer)} release(s)", ""]
        try:
            notes: dict[str, str] | None = github_notes(pkg)
        except UpstreamError as exc:
            notes = None
            lines += [f"{exc}; release notes not shown.", ""]
        for r in reversed(newer):
            lines += [f"#### {name} {r.version}, released {r.date}", ""]
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
        bumps = ", ".join(f"`just upstream-bump {n}`" for n in nexts)
        lines.append(f"Next step, one release at a time: {bumps} (see `{GUIDE}`).")
    else:
        lines.append("All pins are at the latest release.")
    return "\n".join(lines) + "\n", bool(nexts)


# --- bump ------------------------------------------------------------------------------------


def locations(pkg: Package, old: str, new: str, paths: Paths) -> list[Location]:
    """Every hand-written place that names the pin, with the exact text before and after."""
    root, ws = paths.root, paths.workspace
    templates = [
        (root / "pyproject.toml", pkg.pyproject),
        (root / PINS_FILE, f'"{pkg.name}": "{{v}}"'),
        (root / "README.md", f"`{pkg.name}=={{v}}`"),
        (root / "AGENTS.md", f"`../upstream/{pkg.clone}/` (v{{v}})"),
        (ws / "README.md", f"`{pkg.clone}/` at tag v{{v}}"),
    ]
    return [Location(p, t.format(v=old), t.format(v=new)) for p, t in templates]


def dirty_files(root: Path, files: list[Path]) -> list[str]:
    inside = [str(f.relative_to(root)) for f in files if f.is_relative_to(root)]
    result = run(["git", "status", "--porcelain", "--", *inside], root)
    if result.returncode != 0:
        raise UpstreamError(f"git status failed in {root}: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def plan_edits(locs: list[Location], row: str, paths: Paths) -> dict[Path, tuple[str, str]]:
    """{file: (text now, text after)}; raises before anything is written if a text has drifted."""
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
        lines.insert(rules[0] + 1, row + "\n")
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


def checklist(pkg: Package, version: str) -> str:
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
        f"fill in 'Effect on crc-lab' for {pkg.name} {version} in {CHANGELOG}",
    ]
    return "\n".join(
        [
            "",
            "Remaining steps (nothing is committed):",
            *[f"- [ ] {s}" for s in steps],
            f"See {GUIDE}.",
        ]
    )


def bump(
    paths: Paths,
    name: str,
    target_text: str,
    *,
    dry_run: bool = False,
    allow_skip: bool = False,
    allow_dirty: bool = False,
) -> str:
    out: list[str] = []
    if name not in PACKAGES:
        raise UpstreamError(f"unknown package {name!r}; known: {', '.join(PACKAGES)}")
    pkg = PACKAGES[name]
    pins = read_pins(paths.root)
    if name not in pins:
        raise UpstreamError(f"{PINS_FILE} has no pin for {name}")
    old_text = pins[name]
    try:
        target, pinned = Version(target_text), Version(old_text)
    except InvalidVersion as exc:
        raise UpstreamError(f"not a version: {exc}") from exc
    target_text = str(target)  # "v0.11.2" and "0.11.2" both mean 0.11.2
    releases = {r.version: r for r in pypi_releases(name)}
    if target not in releases:
        known = ", ".join(str(v) for v in sorted(releases)[-5:])
        raise UpstreamError(
            f"{name} {target_text} is not a release on PyPI (pre-releases and yanked versions "
            f"do not count); latest releases: {known}"
        )
    if target <= pinned:
        raise UpstreamError(f"{name} {target_text} is not newer than the pin {old_text}")
    skipped = sorted(v for v in releases if pinned < v < target)
    if skipped and not allow_skip:
        raise UpstreamError(
            f"{name} {target_text} skips {', '.join(map(str, skipped))}; "
            f"move one release at a time (next: {skipped[0]}) or pass --allow-skip"
        )
    clone = paths.clone(pkg)
    _, changes = clone_state(pkg, paths)
    if changes:
        raise UpstreamError(f"reference clone {clone} has local changes:\n{changes}")
    try:
        notes = github_notes(pkg).get(f"v{target_text}")
        if notes is None:
            out.append(f"warning: no GitHub release for v{target_text}; the changelog row says so.")
            notes = f"No GitHub release found for v{target_text}"
    except UpstreamError as exc:
        out.append(f"warning: {exc}; the changelog row says so.")
        notes = "Release notes not fetched (GitHub unreachable)"
    cells = [today().isoformat(), name, target_text, condense(notes), EFFECT_PLACEHOLDER]
    row = "| " + " | ".join(cells) + " |"
    edits = plan_edits(locations(pkg, old_text, target_text, paths), row, paths)
    files = [*edits, paths.root / "uv.lock"]
    dirty = dirty_files(paths.root, files)
    if dirty and not allow_dirty:
        raise UpstreamError(
            "uncommitted changes in files this would edit (pass --allow-dirty to go on):\n"
            + "\n".join(dirty)
        )
    outside = [f for f in edits if not f.is_relative_to(paths.root)]
    for f in outside:
        out.append(f"note: {f} is outside the repository; git cannot show or undo its change.")
    commands = [
        (["git", "fetch", "--tags"], clone),
        (["git", "checkout", "--quiet", "--detach", f"v{target_text}"], clone),
        (["uv", "lock"], paths.root),
        (["uv", "sync", "--all-extras", "--group", "dev"], paths.root),
    ]
    if dry_run:
        out.append(f"Dry run: {name} {old_text} -> {target_text}. Nothing is changed.\n")
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
        out += [f"  (cd {cwd} && {' '.join(cmd)})" for cmd, cwd in commands]
        out.append(checklist(pkg, target_text))
        return "\n".join(out)
    must(*commands[0])
    if run(
        ["git", "rev-parse", "--verify", "--quiet", f"v{target_text}^{{commit}}"], clone
    ).returncode:
        raise UpstreamError(
            f"tag v{target_text} not found in {clone} after fetching; nothing changed"
        )
    must(*commands[1])
    out.append(f"{clone}: at v{target_text}")
    for path, (_, after) in edits.items():
        write_atomic(path, after)
        out.append(f"edited {path}")
    print("\n".join(out), flush=True)
    out = []
    for cmd, cwd in commands[2:]:
        print(f"$ {' '.join(cmd)}", flush=True)
        must(cmd, cwd, capture=False)
    out.append(f"{name} moved from {old_text} to {target_text}.")
    out.append(checklist(pkg, target_text))
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
    p_bump = sub.add_parser("bump", parents=[common], help="move one pin to one newer release")
    p_bump.add_argument("package", help=", ".join(PACKAGES))
    p_bump.add_argument("version")
    p_bump.add_argument("--dry-run", action="store_true", help="show the diffs and commands only")
    p_bump.add_argument("--allow-skip", action="store_true", help="allow skipping releases")
    p_bump.add_argument("--allow-dirty", action="store_true", help="allow uncommitted changes")
    args = parser.parse_args(argv)
    paths = Paths(args.root.resolve())
    try:
        if args.command == "check":
            report, newer = check(paths)
            print(report, end="")
            return 1 if newer and args.exit_code else 0
        print(
            bump(
                paths,
                args.package,
                args.version,
                dry_run=args.dry_run,
                allow_skip=args.allow_skip,
                allow_dirty=args.allow_dirty,
            )
        )
        return 0
    except UpstreamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
