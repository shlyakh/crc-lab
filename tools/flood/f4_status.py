"""Status of the F4 catalogue batch. Standard library only; reads files, changes nothing.

    python3 tools/flood/f4_status.py            # once
    python3 tools/flood/f4_status.py --watch 60 # refresh every 60 s (Ctrl-C to stop)

Shows runs finished per stratum with a bar, the run in progress and its time so far, solver time
per run, the largest water-balance residual, failed runs, the estimated finish, and free disk.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
F4 = ROOT / "data" / "cache" / "flood" / "f4"
RUNS = F4 / "runs"
LINE = re.compile(r"^(\S+) (\S+) solver exit (\S+) finished (\S+) wall ([\d.]+) s")


def bar(done: int, total: int, width: int = 30) -> str:
    n = round(width * done / total) if total else 0
    return "#" * n + "." * (width - n)


def status() -> str:
    sel = json.loads((F4 / "selection.json").read_text())
    labels = {x["label"]: x for x in sel}
    walls, failed = {}, []
    log = RUNS / "batch.log"
    for line in log.read_text().splitlines() if log.exists() else []:
        m = LINE.match(line)
        if m and m.group(2) in labels:
            if m.group(3) == "0" and m.group(4) == "True":
                walls[m.group(2)] = float(m.group(5))
            else:
                failed.append(m.group(2))
    done = {lab for lab in labels if (RUNS / lab / "balance.json").exists()}
    residual = max(
        (
            abs(json.loads((RUNS / lab / "balance.json").read_text())["residual_share_of_rain"])
            for lab in done
        ),
        default=0.0,
    )
    running = None
    for x in sorted(sel, key=lambda x: x["order"]):
        folder = RUNS / x["label"]
        if x["label"] not in done and folder.exists():
            running = (x, time.time() - folder.stat().st_mtime)
            break
    out = [f"F4 catalogue batch, {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    for s in ("T1", "T2", "T3"):
        mine = [x for x in sel if x["stratum"] == s]
        d = sum(x["label"] in done for x in mine)
        out.append(f"  {s}  [{bar(d, len(mine))}] {d:3d} / {len(mine)}")
    out.append(
        f"  all [{bar(len(done), len(sel))}] {len(done):3d} / {len(sel)}"
        "  (60 needed before 1 December)"
    )
    out.append("")
    if running:
        x, age = running
        out.append(
            f"  running: {x['label']} (order {x['order']}, {x['stratum']}, rank {x['rank']}, "
            f"box {x['box_total_mm']:.0f} mm in 3 h), started about {age / 60:.0f} min ago"
        )
    else:
        out.append("  running: none")
    alive = subprocess.run(
        ["pgrep", "-f", "f3_batch.py"], capture_output=True, text=True
    ).stdout.strip()
    restart = "just flood-f4-batch data/cache/flood/f4/queue_catalogue.json"
    out.append(f"  batch process: {'alive' if alive else 'NOT RUNNING (restart: ' + restart + ')'}")
    if walls:
        recent = list(walls.values())[-10:]
        mean = sum(recent) / len(recent)
        left = len(sel) - len(done)
        eta = datetime.now() + timedelta(seconds=left * mean)
        out.append(
            f"  solver time per run: mean of last {len(recent)} {mean / 60:.1f} min; "
            f"{left} left, finish about {eta:%a %H:%M}"
        )
    out.append(f"  largest water-balance residual: {residual * 100:.3f}% of rain (rule 1%)")
    out.append(f"  failed runs: {', '.join(failed) if failed else 'none'}")
    free = shutil.disk_usage(ROOT).free / 1e9
    out.append(f"  free disk: {free:.1f} GB")
    out.append("")
    out.append(
        "  figures (rebuilt by the check): docs/flood/figures/f4/progress.png; "
        "gallery: site/flood/tests/index.html"
    )
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--watch", type=int, default=0, help="refresh every N seconds")
    a = p.parse_args()
    while True:
        text = status()
        if a.watch:
            os.system("clear")
        print(text, flush=True)
        if not a.watch:
            return
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
