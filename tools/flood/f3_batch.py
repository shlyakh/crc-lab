"""Run a queue of SFINCS runs one after another, resumably (FG10). Standard library only.

    caffeinate -i python3 tools/flood/f3_batch.py <queue.json>

The queue is a JSON list of runs: ``{"label", "qinf", "rain"?, "rain_h"?, "after_h"?,
"netampr"?, "tref"?, "level"?, "base"?}``. Each goes to ``data/cache/flood/f3/runs/<label>/``. A run
with a ``balance.json`` is done and skipped; a folder without one (a run that was stopped) is
moved aside to ``<label>.stopped-<n>`` and started again. After the solver, the run's output is
analysed in the builder's environment (``sfincs_model.py analyse``) and the large map file is
kept. One line per run goes to ``data/cache/flood/f3/runs/batch.log``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "flood_lab" / "hazard"))
import run_sfincs  # noqa: E402
import sfincs_model  # noqa: E402

CACHE = ROOT / "data" / "cache" / "flood"
RUNS = CACHE / "f3" / "runs"
BASE = CACHE / "f3" / "model" / "base"
BUILDER = [
    "uv",
    "run",
    "--no-project",
    "--python",
    "3.12",
    "--with",
    "hydromt-sfincs==2.0.0",
    "--with",
    "rasterio<1.5.2; sys_platform == 'darwin'",
    "--with",
    "scipy",
    "python",
    str(ROOT / "src" / "flood_lab" / "hazard" / "sfincs_model.py"),
]


def log(line: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with (RUNS / "batch.log").open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
    print(stamp, line, flush=True)


def one(item: dict) -> None:
    folder = RUNS / item["label"]
    if (folder / "balance.json").exists():
        log(f"{item['label']} done before, skipped")
        return
    if folder.exists():
        n = 1
        while (RUNS / f"{item['label']}.stopped-{n}").exists():
            n += 1
        folder.rename(RUNS / f"{item['label']}.stopped-{n}")
    netampr = Path(item["netampr"]) if item.get("netampr") else None
    sfincs_model.make_run(
        Path(item.get("base", BASE)),
        folder,
        float(item["qinf"]),
        item.get("rain"),
        float(item.get("rain_h", 1.0)),
        float(item.get("after_h", 1.0)),
        netampr,
        item.get("level"),
        extra=item.get("extra"),
        tref=item.get("tref", sfincs_model.TREF),
    )
    record = run_sfincs.run(folder, "run", timeout=float(item.get("timeout", 4 * 3600)))
    finished = record["parsed"].get("finished")
    ok = record["exit_code"] == 0 and finished
    log(
        f"{item['label']} solver exit {record['exit_code']} finished {finished} "
        f"wall {record['wall_time_s']} s dt {record['parsed'].get('average_time_step_s')}"
    )
    if not ok:
        return
    out = subprocess.run(
        [*BUILDER, "analyse", str(folder)], capture_output=True, text=True, cwd=ROOT
    )
    if out.returncode != 0:
        log(f"{item['label']} analyse failed: {out.stderr[-400:]}")
        return
    bal = json.loads((folder / "balance.json").read_text())
    log(f"{item['label']} balance residual {bal['residual_share_of_rain']:.5f} of rain")


def main() -> None:
    queue = json.loads(Path(sys.argv[1]).read_text())
    RUNS.mkdir(parents=True, exist_ok=True)
    for item in queue:
        one(item)


if __name__ == "__main__":
    main()
