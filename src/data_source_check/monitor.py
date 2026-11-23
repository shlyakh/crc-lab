"""Monitoring run: is every assessment still current?

    python -m data_source_check.monitor              # ask the publishers (HEAD), compare, report
    python -m data_source_check.monitor --rerun      # also re-run stale sources (staged)
    python -m data_source_check.monitor --rerun --only ID [--only ID]   # these sources only
    python -m data_source_check.monitor --rerun --profile quick   # small areas; cannot be accepted
    python -m data_source_check.monitor --rerun --again           # ignore re-runs already staged
    python -m data_source_check.monitor --accept ID  # publish a staged re-run after review

A re-run is staged source by source and the report is written after each one, so a source that
fails (a publisher that does not answer, an upstream name that is gone) is reported as failed
and the others still run. A source already staged at the installed versions is not run again.

Writes ``docs/validation/monitoring.md`` and ``site/validation/data/monitor.json``. Exits 1
when something needs attention, so that a scheduled run is noticed. It never replaces the
published records: a re-run is staged, and a person accepts it.
"""

from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import build
from .adapters.crc import enumerate as crc
from .core import compare, inventory, monitoring
from .core.io import write_json_atomic, write_text_atomic

STAGING = build.CACHE / "staging"
USER_AGENT = "data-source-check"
#: folders of a source's cache that hold material which does not pass through the framework
#: (outside evidence, administrative boundaries). A re-run reuses the copies held, each with
#: its own retrieval date, instead of asking those services again.
HELD = {"jrc-flood": ("evidence", "boundaries")}


def seed(source_id: str, staging_cache: Path, cache: Path) -> int:
    """Copy held material into the staging cache where it is absent; the number of files."""
    copied = 0
    for folder in HELD.get(source_id, ()):
        origin = cache / source_id / folder
        for path in sorted(origin.rglob("*")) if origin.is_dir() else ():
            target = staging_cache / source_id / folder / path.relative_to(origin)
            if path.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied += 1
    return copied


def head(url: str) -> dict[str, Any]:
    request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=60) as response:
            return {"status": int(response.status), "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified")}  # fmt: skip
    except HTTPError as error:
        return {"status": int(error.code)}
    except (URLError, TimeoutError, ConnectionError) as error:
        return {"status": None, "error": str(error)}


def run(*, rerun: bool = False, page_data: Path = build.PAGE_DATA, docs: Path = build.DOCS,
        ask: Any = head, only: tuple[str, ...] = (), profile: str = "full",
        again: bool = False) -> dict[str, Any]:  # fmt: skip
    sources = inventory.load_sources("crc_sdk")
    offered = crc.offered()
    gaps = inventory.unassessed(sources, offered)
    records = {s.id: build.load_records(s.id, page_data) for s in sources}
    records = {name: value for name, value in records.items() if value}
    urls = sorted({item["url"] for value in records.values()
                   for item in monitoring.recorded_inputs(value)})  # fmt: skip
    print(f"asking the publishers about {len(urls)} files")
    with ThreadPoolExecutor(max_workers=16) as pool:
        heads = dict(zip(urls, pool.map(ask, urls), strict=True))
    states = [monitoring.source_state(value, heads, offered["versions"])
              for value in records.values()]  # fmt: skip
    report: dict[str, Any] = {
        "run_at": compare.now(),
        "installed": offered["versions"],
        "sources": states,
        "gaps": {key: gaps[key] for key in ("unclaimed_symbols", "new_options")},
        "needs_attention": monitoring.needs_attention(states, gaps),
        "reruns": [],
    }

    def write() -> None:
        write_json_atomic(page_data / "monitor.json", report)
        write_text_atomic(docs / "monitoring.md", monitoring.markdown(report))

    unknown = sorted(set(only) - records.keys())
    if unknown:
        raise SystemExit(f"no assessed source named {', '.join(unknown)}")
    if rerun:
        staged = STAGING / "page-data"
        for state in states:
            name = state["source"]
            if name not in only if only else not state["stale"]:
                continue
            where = str(staged / "records" / f"{name}.json")
            entry: dict[str, Any] = {"source": name, "profile": "full", "staged": where}
            try:
                held = None if again else build.load_records(name, staged)
                if (
                    held
                    and held.get("versions") == offered["versions"]
                    and held["run_at"] > records[name]["run_at"]
                    and held.get("profile", "full") in ("full", profile)
                ):
                    print(f"{name}: already staged at the installed versions ({held['run_at']})")
                    fresh, entry["reused"] = held, True
                else:
                    print(f"re-running {name} into the staging folder")
                    seed(name, STAGING / "cache", build.CACHE)
                    more = {} if profile == "full" else {"profile": profile}
                    fresh = build.assess_source(name, live=True, page_data=staged,
                                                cache=STAGING / "cache", **more)  # fmt: skip
                entry["profile"] = fresh.get("profile", "full")
                entry |= monitoring.diff_records(records[name], fresh)
            except Exception as error:  # noqa: BLE001  one source failing must not lose the others
                print(f"{name}: the re-run failed: {type(error).__name__}: {error}")
                entry["failed"] = f"{type(error).__name__}: {error}"[:400]
            report["reruns"].append(entry)
            write()
    write()
    return report


def accept(source_id: str) -> None:
    """Publish a staged re-run: a person runs this after reading the monitoring report."""
    staged = STAGING / "page-data" / "records" / f"{source_id}.json"
    if not staged.exists():
        raise SystemExit(f"nothing is staged for {source_id!r}")
    profile = build.load_records(source_id, STAGING / "page-data").get("profile", "full")
    if profile != "full":
        raise SystemExit(
            f"the staged re-run of {source_id!r} used the {profile} profile and covers less than "
            "the published records; run it in full before accepting"
        )
    shutil.copyfile(staged, build.PAGE_DATA / "records" / f"{source_id}.json")
    build.build_inventory()
    print(f"{source_id}: staged records published; the assessment is a draft until signed again")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rerun", action="store_true", help="re-run stale sources (staged)")
    parser.add_argument("--accept", metavar="ID", help="publish a staged re-run")
    parser.add_argument("--only", metavar="ID", action="append", default=[],
                        help="re-run this source, stale or not (repeatable)")  # fmt: skip
    parser.add_argument("--profile", choices=build.PROFILES, default="full",
                        help="quick: small areas only; cannot be accepted")  # fmt: skip
    parser.add_argument("--again", action="store_true",
                        help="re-run even where one is already staged")  # fmt: skip
    args = parser.parse_args()
    if args.accept:
        accept(args.accept)
        return
    report = run(rerun=args.rerun or bool(args.only), only=tuple(args.only),
                 profile=args.profile, again=args.again)  # fmt: skip
    for entry in report["reruns"]:
        if "failed" in entry:
            print(f"{entry['source']}: re-run FAILED: {entry['failed']}")
    for state in report["sources"]:
        print(f"{state['source']}: " + ("stale: " + "; ".join(state["reasons"])
                                        if state["stale"] else "current"))  # fmt: skip
    raise SystemExit(1 if report["needs_attention"] else 0)


if __name__ == "__main__":
    main()
