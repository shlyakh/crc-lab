"""F4: a solver queue from RainyDay scenarios (FH5). Standard library only; the forcing is built in
the builder's environment, as F3 built its replays.

    python3 tools/flood/f4_queue.py <selection.json> <queue.json>

``selection.json`` is a JSON list ``[{"label": "cat_r0001", "scenario": "<scenario_*.nc>",
"weight": 1.0, ...}]``. For each item the rain is built once to
``data/cache/flood/f4/forcing/<label>.nc`` with ``sfincs_model.py scenario-forcing`` (its record
beside it as ``<label>.json``; an item whose forcing and record exist is not built again), and a
queue entry for ``tools/flood/f3_batch.py`` is written::

    {"label", "qinf": 30, "netampr", "tref", "rain_h", "after_h": 1, "weight", "scenario", ...}

``tref`` is the start of the scenario's first hour (a scenario keeps its parent storm's dates),
``rain_h`` the scenario's length in hours (its rain plus RainyDay's ``PADSCENARIOS`` hours). Every
other key of a selection item is passed through; an item may set its own ``qinf`` or ``after_h``.
An item whose forcing cannot be built is left out of the queue and named on stderr, and the exit
code is 1. The queue is written atomically.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORCING = ROOT / "data" / "cache" / "flood" / "f4" / "forcing"
QINF = 30  # mm/h, frozen at the F3 stop (requirements §16, CH-16)
AFTER_H = 1
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
FIXED = ("label", "qinf", "netampr", "tref", "rain_h", "after_h", "weight", "scenario")


def entry(item: dict, record: dict, forcing: Path) -> dict:
    """The queue entry for one selection item and its forcing record."""
    out = {
        "label": item["label"],
        "qinf": item.get("qinf", QINF),
        "netampr": str(forcing),
        "tref": record["tref"],
        "rain_h": int(record["hours"]),
        "after_h": item.get("after_h", AFTER_H),
        "weight": item.get("weight", 1.0),
        "scenario": item["scenario"],
    }
    for k, v in item.items():
        if k not in FIXED:
            out[k] = v
    return out


def build(item: dict, forcing_dir: Path = FORCING, builder: list[str] | None = None) -> dict:
    """The forcing record for one item, building the forcing if it is not there yet."""
    forcing = forcing_dir / f"{item['label']}.nc"
    record = forcing.with_suffix(".json")
    if forcing.exists() and record.exists():
        return json.loads(record.read_text())
    forcing_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        *(builder or BUILDER),
        "scenario-forcing",
        str(Path(item["scenario"]).resolve()),
        str(forcing),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0 or not record.exists():
        raise RuntimeError(proc.stderr[-800:] or f"no record written for {item['label']}")
    return json.loads(record.read_text())


def make_queue(selection: list[dict], forcing_dir: Path = FORCING, builder=None):
    labels = [x["label"] for x in selection]
    if len(set(labels)) != len(labels):
        raise ValueError("labels in the selection are not unique")
    queue, failed = [], []
    for item in selection:
        try:
            rec = build(item, forcing_dir, builder)
        except Exception as error:  # report and go on; a rerun resumes
            failed.append((item["label"], str(error)))
            continue
        queue.append(entry(item, rec, forcing_dir / f"{item['label']}.nc"))
    return queue, failed


def main() -> None:
    selection = json.loads(Path(sys.argv[1]).read_text())
    dest = Path(sys.argv[2])
    queue, failed = make_queue(selection)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(queue, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    print(f"{len(queue)} entries written to {dest}")
    for label, error in failed:
        print(f"{label}: forcing failed: {error}", file=sys.stderr)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
