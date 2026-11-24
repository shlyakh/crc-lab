"""Probes of crc-lab's findings against crc-sdk 1.0, in an environment of their own.

    just v1-probes 1.0.0a1 1.0.0a2 [--only <id> ...] [--list] [--offline]

The recipe runs this file with ``uv run --no-project`` and the 1.0 packages; it never uses the
project's environment, which stays on crc-sdk 0.11. Each probe runs in a child process with a
timeout; a probe that needs the network is tried once more if its first attempt does not
complete. One probe failing never stops the others.

Writes ``data/cache/validation/v1/<crc-sdk version>/probes.json`` (results of earlier runs of
other probes are kept, so ``--only`` adds to a run) and the generated report
``docs/reports/v1-probes-<crc-sdk version>.md``. Downloads made by crc-sdk go to
``data/cache/validation/v1/<crc-sdk version>/crc-sdk-cache/`` and are reused on a repeat.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # nothing is written next to the code

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
import traceback  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as c  # noqa: E402
import probes as p  # noqa: E402

FINDINGS = c.REPO / "src" / "data_source_check" / "sources" / "crc_sdk" / "findings.toml"


def cache_dir(version: str) -> Path:
    return c.REPO / "data" / "cache" / "validation" / "v1" / version


def folder_bytes(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


# ---------------------------------------------------------------------------- one probe, in a child
def child(probe_id: str, cache: Path, network: bool) -> None:
    """Run one probe and print its record as JSON on the last line of standard output."""
    probe = next(x for x in p.PROBES if x.id == probe_id)
    start = time.perf_counter()
    try:
        out = probe.run(p.Context(cache=cache, network=network))
        out["outcome"] = "completed"
    except Exception as error:  # an unexpected failure is recorded, not raised
        tail = traceback.format_exc().strip().splitlines()[-12:]
        out = {"ran": "", "observed": {"error": f"{type(error).__name__}: {error}",
                                       "traceback_tail": tail},
               "results": [p.result(f, p.COULD_NOT, f"the probe raised {type(error).__name__}: "
                                    f"{str(error)[:200]}") for f in probe.findings],
               "outcome": "raised"}  # fmt: skip
    out["seconds"] = round(time.perf_counter() - start, 1)
    out["peak_rss_mb"] = p._rss_mb()
    sys.stdout.flush()
    print("\n" + json.dumps(out, default=str))


def run_one(probe: p.Probe, cache: Path, network: bool) -> dict[str, Any]:
    base = {"id": probe.id, "title": probe.title, "findings": list(probe.findings),
            "network": probe.network}  # fmt: skip
    if probe.network and not network:
        return {**base, "ran": "", "observed": {}, "outcome": "skipped", "seconds": 0,
                "results": [p.result(f, p.COULD_NOT, "needs the network; run without --offline")
                            for f in probe.findings]}  # fmt: skip
    attempts = 2 if probe.network else 1
    before = folder_bytes(cache / "crc-sdk-cache")
    record: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        command = [sys.executable, str(HERE / "run.py"), "--child", probe.id, "--cache", str(cache)]
        if network:
            command.append("--network")
        started = time.perf_counter()
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=probe.timeout,
                                  env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})  # fmt: skip
            lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
            if lines:
                record = json.loads(lines[-1])
            else:
                record = {"ran": "", "outcome": "crashed", "observed": {
                    "exit_code": done.returncode,
                    "stderr_tail": done.stderr.strip().splitlines()[-12:]},
                    "results": [p.result(f, p.COULD_NOT, f"the child process ended with code "
                                         f"{done.returncode}") for f in probe.findings]}  # fmt: skip
        except subprocess.TimeoutExpired:
            record = {"ran": "", "outcome": "timed out", "observed": {"timeout_s": probe.timeout},
                      "results": [p.result(f, p.COULD_NOT, f"no answer within {probe.timeout} s")
                                  for f in probe.findings],
                      "seconds": round(time.perf_counter() - started, 1)}  # fmt: skip
        record["attempt"] = attempt
        if record.get("outcome") == "completed":
            break
    record["downloaded_bytes"] = folder_bytes(cache / "crc-sdk-cache") - before
    record["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return {**base, **record}


# ---------------------------------------------------------------------------- the report
def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _lines(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(item, dict | list) and item and not _flat(item):
                out.append(f"{pad}- {key}:")
                out.extend(_lines(item, indent + 1))
            else:
                out.append(f"{pad}- {key}: `{_inline(item)}`")
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict | list) and not _flat(item):
                out.append(f"{pad}-")
                out.extend(_lines(item, indent + 1))
            else:
                out.append(f"{pad}- `{_inline(item)}`")
        return out
    return [f"{pad}- `{_inline(value)}`"]


def _flat(item: Any) -> bool:
    if isinstance(item, dict):
        return all(not isinstance(v, dict | list) for v in item.values()) and len(item) <= 4
    return all(not isinstance(v, dict | list) for v in item) and len(item) <= 6


def _inline(item: Any) -> str:
    text = json.dumps(item, default=str) if isinstance(item, dict | list) else str(item)
    return text.replace("`", "'")


def report(state: dict[str, Any], version: str) -> str:
    findings = {f["id"]: f for f in tomllib.loads(FINDINGS.read_text(encoding="utf-8"))["finding"]}
    rows = [r for probe in state["probes"].values() for r in probe["results"]]
    order = {pr.id: i for i, pr in enumerate(p.PROBES)}
    probes = sorted(state["probes"].values(), key=lambda x: order.get(x["id"], 99))
    seconds = sum(x.get("seconds", 0) or 0 for x in probes)
    downloaded = sum(x.get("downloaded_bytes", 0) or 0 for x in probes)
    out = [
        f"# Probes of crc-lab's findings against crc-sdk {version}",
        "",
        "Generated by `tools/probes/v1/run.py` from "
        f"`data/cache/validation/v1/{version}/probes.json`; do not edit.",
        "",
        "| Package | Version |",
        "| --- | --- |",
        *[f"| {k} | {v} |" for k, v in state["versions"].items()],
        "",
        f"Last run: {state['last_run']}, {state.get('last_run_seconds', '-')} s in all. "
        f"Command: `{state['command']}`.",
        f"Probes: {len(probes)}; time in probes {seconds:.0f} s; downloaded through crc-sdk "
        f"{downloaded / (1 << 20):.1f} MB (into `data/cache/validation/v1/{version}/crc-sdk-cache/`).",
        "",
        "Verdicts: `not reproduced on 1.0`, `still reproduces`, `changed`, `new behaviour`, "
        "`could not run`. A verdict says what this run showed at these versions; it does not "
        "change the register (`findings.toml`), where status moves only after review.",
        "",
        "## Summary",
        "",
        "| Finding | Verdict | Observed | Probe |",
        "| --- | --- | --- | --- |",
    ]
    for probe in probes:
        for r in probe["results"]:
            out.append(f"| {_cell(r['finding'])} | {r['verdict']} | {_cell(r['note'])} | "
                       f"`{probe['id']}` |")  # fmt: skip
    out += ["", "## Not probed (state at 1.0 from code reading only)", ""]
    for fid in p.NOT_PROBED:
        title = findings.get(fid, {}).get("title", "")
        out.append(f"- {fid}: {title}. Not probed; code reading only.")
    out += ["", "## Probes", ""]
    for probe in probes:
        out += [
            f"### `{probe['id']}`: {probe['title']}",
            "",
            f"- Findings: {', '.join(probe['findings'])}",
            f"- Network: {'yes' if probe['network'] else 'no'}; outcome: {probe.get('outcome')}; "
            f"attempt {probe.get('attempt', '-')}; {probe.get('seconds', 0)} s; peak memory of the "
            f"probe's process {probe.get('peak_rss_mb', '-')} MB; downloaded "
            f"{(probe.get('downloaded_bytes') or 0) / (1 << 20):.1f} MB; finished "
            f"{probe.get('finished_at', '-')}",
            "",
            f"**Run.** {probe.get('ran') or '(see observed)'}",
            "",
            "**Observed.**",
            "",
            *_lines(probe.get("observed", {})),
            "",
            "**Verdicts.**",
            "",
            *[f"- {r['finding']}: {r['verdict']}. {r['note']}" for r in probe["results"]],
            "",
        ]
    del rows
    return "\n".join(out) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


#: text of a failed connection in a probe's note
NETWORK_FAILURE = re.compile(
    r"timed out|Connection reset|urlopen error|RemoteDisconnected|Name or service not known"
    r"|nodename nor servname|Connection refused|HTTP Error 5\d\d"
)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", action="append", default=[], help="probe id (repeatable)")
    parser.add_argument("--list", action="store_true", help="list the probes and stop")
    parser.add_argument("--offline", action="store_true",
                        help="run only the probes that need no network; record the others as not run")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--cache", help=argparse.SUPPRESS)
    parser.add_argument("--network", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.list:
        for probe in p.PROBES:
            print(f"{probe.id:20} {'network' if probe.network else 'offline':8} "
                  f"{', '.join(probe.findings)}: {probe.title}")  # fmt: skip
        return 0
    if args.child:
        child(args.child, Path(args.cache), args.network)
        return 0

    versions = c.versions()
    version = versions["crc-sdk"]
    if version == "not installed" or version.startswith("0."):
        print(f"crc-sdk {version} is installed; these probes need 1.0 (run through the recipe)")
        return 2
    unknown = [i for i in args.only if i not in {x.id for x in p.PROBES}]
    if unknown:
        print(f"unknown probe ids: {unknown}; --list shows them")
        return 2
    cache = cache_dir(version)
    cache.mkdir(parents=True, exist_ok=True)
    state_path = cache / "probes.json"
    state = (json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists()
             else {"probes": {}})  # fmt: skip
    if state.get("versions") and state["versions"].get("crc-framework") != versions["crc-framework"]:
        state["probes"] = {}  # results of another framework version are not mixed in
    state["versions"] = versions
    state["command"] = "just v1-probes " + " ".join(
        [version, versions["crc-framework"], *sys.argv[1:]])
    chosen = [x for x in p.PROBES if not args.only or x.id in args.only]
    started = time.perf_counter()
    for probe in chosen:
        print(f"{probe.id} ...", flush=True)
        record = run_one(probe, cache, network=not args.offline)
        for r in record["results"]:
            # a publisher that did not answer says nothing about the framework
            if r["verdict"] != "could not run" and NETWORK_FAILURE.search(r["note"]):
                r["verdict"], r["note"] = "could not run", "the publisher did not answer: " + r["note"]
        state["probes"][probe.id] = record
        state["last_run"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_atomic(state_path, json.dumps(state, indent=1, default=str))
        for r in record["results"]:
            print(f"  {r['finding']}: {r['verdict']}. {r['note'][:160]}", flush=True)
    state["last_run_seconds"] = round(time.perf_counter() - started, 1)
    write_atomic(state_path, json.dumps(state, indent=1, default=str))
    target = c.REPO / "docs" / "reports" / f"v1-probes-{version}.md"
    write_atomic(target, report(state, version))
    print(f"wrote {state_path.relative_to(c.REPO)} and {target.relative_to(c.REPO)} "
          f"({state['last_run_seconds']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
