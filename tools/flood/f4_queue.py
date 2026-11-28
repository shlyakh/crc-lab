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

    python3 tools/flood/f4_queue.py <selection.json> <queue.json> --cover <forcing dir>

``--cover`` (CH-26): RainyDay's scenario holds only the pixels whose centres lie in the study box,
and SFINCS puts no rain on cells beyond the outermost pixel centres of a ``netamprfile``, so the
square's north and east strips (28.5% of it) got no rain. With ``--cover`` each scenario is first
rebuilt over the square with one pixel to spare on each side (``sfincs_ring.py rebuild-scenario
--box square``: the parent storm moved by the scenario's shift, proved equal to the scenario on its
own pixels); the item's existing forcing (``data/cache/flood/f4/forcing/<label>.nc``) keeps every
pixel as it is and is extended to cover the square with one pixel to spare, the added pixels
taking the rebuilt scenario's nearest cell (``sfincs_ring.py aligned-forcing --box square``), into
``<forcing dir>``. The record is the existing one with ``cover`` added.
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


RING_TOOL = str(ROOT / "src" / "flood_lab" / "hazard" / "sfincs_ring.py")


def _run_dir(scenario: Path) -> Path:
    """The RainyDay output folder of a scenario (the one holding ``scenarios.csv``)."""
    for parent in scenario.parents:
        if (parent / "scenarios.csv").exists():
            return parent
    raise FileNotFoundError(f"no scenarios.csv above {scenario}")


def build(
    item: dict, forcing_dir: Path = FORCING, builder: list[str] | None = None, cover: bool = False
) -> dict:
    """The forcing record for one item, building the forcing if it is not there yet."""
    forcing = forcing_dir / f"{item['label']}.nc"
    record = forcing.with_suffix(".json")
    if forcing.exists() and record.exists():
        return json.loads(record.read_text())
    forcing_dir.mkdir(parents=True, exist_ok=True)
    scenario = Path(item["scenario"]).resolve()
    tool = builder or BUILDER
    if cover:
        base = build(item, FORCING, builder)
        rebuilt = forcing_dir / f"rebuilt_{item['label']}.nc"
        cmd = [*tool[:-1], RING_TOOL, "rebuild-scenario", str(scenario), str(rebuilt)]
        cmd += ["--run-dir", str(_run_dir(scenario)), "--box", "square"]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        proof = rebuilt.with_suffix(".json")
        if proc.returncode != 0 or not proof.exists():
            raise RuntimeError(proc.stderr[-800:] or f"no rebuilt scenario for {item['label']}")
        if not json.loads(proof.read_text())["proof"]["equal"]:
            raise RuntimeError(f"{item['label']}: rebuilt scenario differs from RainyDay's")
        aligned = forcing_dir / f"aligned_{item['label']}.nc"
        cmd = [*tool[:-1], RING_TOOL, "aligned-forcing", str(FORCING / f"{item['label']}.nc")]
        cmd += [str(rebuilt), str(aligned), "--box", "square"]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        arec = aligned.with_suffix(".json")
        if proc.returncode != 0 or not arec.exists():
            raise RuntimeError(proc.stderr[-800:] or f"no aligned forcing for {item['label']}")
        rec = {**base, "cover": json.loads(arec.read_text())}
        tmp = record.with_name(record.name + ".tmp")
        tmp.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        os.replace(aligned, forcing)
        os.replace(tmp, record)
        return rec
    cmd = [
        *tool,
        "scenario-forcing",
        str(scenario),
        str(forcing),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0 or not record.exists():
        raise RuntimeError(proc.stderr[-800:] or f"no record written for {item['label']}")
    return json.loads(record.read_text())


def make_queue(selection: list[dict], forcing_dir: Path = FORCING, builder=None, cover=False):
    labels = [x["label"] for x in selection]
    if len(set(labels)) != len(labels):
        raise ValueError("labels in the selection are not unique")
    queue, failed = [], []
    for item in selection:
        try:
            rec = build(item, forcing_dir, builder, cover)
        except Exception as error:  # report and go on; a rerun resumes
            failed.append((item["label"], str(error)))
            continue
        queue.append(entry(item, rec, forcing_dir / f"{item['label']}.nc"))
    return queue, failed


def main() -> None:
    selection = json.loads(Path(sys.argv[1]).read_text())
    dest = Path(sys.argv[2])
    cover = "--cover" in sys.argv
    forcing_dir = Path(sys.argv[sys.argv.index("--cover") + 1]).resolve() if cover else FORCING
    queue, failed = make_queue(selection, forcing_dir, cover=cover)
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
