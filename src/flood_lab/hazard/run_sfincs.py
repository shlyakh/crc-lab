"""Run SFINCS in Docker on one model folder and record the run (FH2, FG4). Standard library only.

    python src/flood_lab/hazard/run_sfincs.py <model folder> --label run1

The solver writes its outputs into the folder; this script adds ``run_<label>.log`` (everything
the solver printed) and ``run_<label>.json``: image, digest, platform, command, wall time, peak
memory of the container (sampled with ``docker stats``), exit code and the figures parsed from
the log.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

IMAGE = "deltares/sfincs-cpu:sfincs-v2.5.0-Hautacam"
#: the tag is built for linux/amd64 only (Docker Hub, 2026-11-25); on Apple Silicon it runs under
#: Docker Desktop's Rosetta emulation
PLATFORM = "linux/amd64"
#: a run that takes longer than this is stopped (seconds)
TIMEOUT = 20 * 60
_UNITS = {
    "B": 1,
    "KB": 1e3,
    "MB": 1e6,
    "GB": 1e9,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
}


def docker_command(
    folder: Path, name: str, image: str = IMAGE, platform: str = PLATFORM
) -> list[str]:
    """The ``docker run`` line: the model folder is mounted as the image's working folder /data."""
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--platform",
        platform,
        "-v",
        f"{folder.resolve()}:/data",
        image,
    ]


def parse_memory(text: str) -> int | None:
    """Bytes in use from a ``docker stats`` MemUsage field such as ``123.4MiB / 7.6GiB``."""
    match = re.match(r"\s*([\d.]+)\s*([KMG]?i?B)", text, re.IGNORECASE)
    if not match:
        return None
    return int(float(match.group(1)) * _UNITS[match.group(2).upper()])


def parse_log(text: str) -> dict[str, object]:
    """Version, timings and the end state from what SFINCS printed."""
    found: dict[str, object] = {}
    if m := re.search(r"Build-Revision:\s*\$Rev:\s*(.+?)\s*\$?\s*$", text, re.MULTILINE):
        found["sfincs_revision"] = m.group(1).strip()
    if m := re.search(r"Build-Date:\s*\$Date:\s*(.+?)\s*\$?\s*$", text, re.MULTILINE):
        found["sfincs_build_date"] = m.group(1).strip()
    for key, label in (
        ("total_time_s", r"Total time"),
        ("time_in_simulation_s", r"Time in simulation"),
        ("time_in_momentum_s", r"Time in momentum"),
        ("average_time_step_s", r"Average time step \(s\)"),
    ):
        if m := re.search(rf"^\s*{label}\s*:\s*([\d.Ee+-]+)", text, re.MULTILINE):
            found[key] = float(m.group(1))
    if m := re.search(r"Using (\d+) of (\d+) available threads", text):
        found["threads"] = int(m.group(1))
        found["threads_available"] = int(m.group(2))
    if m := re.search(r"Number of active z points\s*:\s*(\d+)", text):
        found["active_cells"] = int(m.group(1))
    found["finished"] = "Simulation finished" in text
    found["stopped_with_error"] = bool(re.search(r"^\s*(Error|STOP [1-9])", text, re.MULTILINE))
    return found


def image_digest(image: str = IMAGE) -> str:
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip()


def docker_host() -> dict[str, object]:
    """Memory and CPUs of the Docker VM, and the host architecture Docker reports."""
    out = subprocess.run(
        ["docker", "info", "--format", "{{.MemTotal}} {{.NCPU}} {{.Architecture}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    parts = out.stdout.split()
    if len(parts) != 3:
        return {}
    return {"mem_total_bytes": int(parts[0]), "ncpu": int(parts[1]), "architecture": parts[2]}


class _MemorySampler(threading.Thread):
    def __init__(self, name: str, every: float = 1.0) -> None:
        super().__init__(daemon=True)
        self.name_ = name
        self.every = every
        self.peak: int | None = None
        self.samples = 0
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.name_],
                capture_output=True,
                text=True,
                check=False,
            )
            used = parse_memory(out.stdout) if out.returncode == 0 else None
            if used is not None:
                self.samples += 1
                self.peak = used if self.peak is None else max(self.peak, used)
            self.stop.wait(self.every)


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def run(folder: Path, label: str, timeout: float = TIMEOUT) -> dict:
    name = f"sfincs-{folder.name}-{label}-{os.getpid()}"
    command = docker_command(folder, name)
    sampler = _MemorySampler(name)
    started = datetime.now(UTC)
    t0 = time.monotonic()
    log_path = folder / f"run_{label}.log"
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, text=True)
        sampler.start()
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
            code = proc.wait()
    wall = time.monotonic() - t0
    sampler.stop.set()
    sampler.join(timeout=10)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    record = {
        "folder": folder.name,
        "label": label,
        "image": IMAGE,
        "image_digest": image_digest(),
        "platform": PLATFORM,
        "docker_host": docker_host(),
        "command": command,
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wall_time_s": round(wall, 2),
        "timed_out": timed_out,
        "timeout_s": timeout,
        "exit_code": code,
        "peak_memory_bytes": sampler.peak,
        "memory_samples": sampler.samples,
        "memory_method": "docker stats --no-stream MemUsage, sampled about once a second",
        "log": log_path.name,
        "parsed": parse_log(text),
    }
    _write_json(folder / f"run_{label}.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--label", default="run1")
    parser.add_argument("--timeout", type=float, default=TIMEOUT)
    args = parser.parse_args()
    record = run(args.folder, args.label, args.timeout)
    print(json.dumps({k: record[k] for k in ("folder", "label", "wall_time_s", "exit_code")}))
    print(json.dumps(record["parsed"]))


if __name__ == "__main__":
    main()
