"""F0 solver timing: the record and figures from the toy-model runs (plan F0 step 7; FH2, FH5, FH8).

Reads only the JSON files that ``hazard/toy_model.py`` and ``hazard/run_sfincs.py`` wrote beside
each model folder; HydroMT is not imported here (FG4).

    uv run python -m flood_lab.checks.f0_solver_timing [--models <folder>]

Writes ``site/flood/tests/records/f0-solver-timing.json`` and
``docs/flood/figures/f0/solver_timing.html`` and ``toy_max_depth.html`` (no PNG: the repository
has no image exporter for plotly, and none is added).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from flood_lab.paths import CACHE, FIGURES, RECORDS
from flood_lab.records import Check, Input, Parameter, Record
from lab_common.io import write_text_atomic

MODELS = CACHE / "f0" / "solver" / "models"
#: the full area: 15 km2 of 5 m cells (plan F0 step 7; requirements section 5)
TARGET_CELLS = 600_000
BUDGET_S = 12 * 3600
BALANCE_LIMIT = 0.01  # FH8
#: plan F0 step 7: 150 runs if one takes under 10 minutes, about 100 otherwise
CATALOGUE_SWITCH_S = 600
#: share of the Docker VM's memory left to the solver when counting parallel runs [P]
MEMORY_SHARE = 0.75


def water_balance(rain: float, infiltrated: float, stored: float, out: float) -> dict[str, float]:
    """rain = infiltrated + stored + out; the residual and its share of rain."""
    residual = rain - infiltrated - stored - out
    return {
        "rain_m3": rain,
        "infiltrated_m3": infiltrated,
        "stored_m3": stored,
        "out_m3": out,
        "residual_m3": residual,
        "residual_share": residual / rain if rain else math.nan,
    }


def power_fit(cells: list[float], seconds: list[float]) -> tuple[float, float]:
    """Least squares of log(seconds) on log(cells): seconds = a * cells ** b. Returns (a, b)."""
    xs = [math.log(c) for c in cells]
    ys = [math.log(s) for s in seconds]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum(
        (x - mx) ** 2 for x in xs
    )
    return math.exp(my - b * mx), b


def extrapolate(sizes: dict[int, list[float]], target: int = TARGET_CELLS) -> dict[str, Any]:
    """Two estimates of one run at ``target`` cells, with the arithmetic as text."""
    cells = [c for c, walls in sizes.items() for _ in walls]
    walls = [w for ws in sizes.values() for w in ws]
    a, b = power_fit(cells, walls)
    fitted = a * target**b
    largest = max(sizes)
    mean_largest = sum(sizes[largest]) / len(sizes[largest])
    linear = mean_largest * target / largest
    return {
        "power_a": a,
        "power_b": b,
        "fitted_s": fitted,
        "linear_from_largest_s": linear,
        "planning_s": max(fitted, linear),
        "arithmetic": [
            f"fit of log(wall) on log(cells) over {len(walls)} runs: "
            f"wall = {a:.4g} * cells^{b:.3f}",
            f"fitted: {a:.4g} * {target}^{b:.3f} = {fitted:.1f} s",
            f"linear from {largest} cells: {mean_largest:.1f} s * {target} / {largest} "
            f"= {linear:.1f} s",
            f"planning value: the larger, {max(fitted, linear):.1f} s",
        ],
    }


def runs_in_budget(seconds_per_run: float, budget: float = BUDGET_S) -> int:
    return int(budget // seconds_per_run)


def inp_value(path: Path, key: str) -> str | None:
    """The value of ``key`` in a SFINCS ``sfincs.inp`` (``key = value`` lines); None if absent."""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip().lower() == key.lower():
            return value.strip()
    return None


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _platform(image_platform: str, runs: list[dict[str, Any]]) -> str:
    """The image platform and the host architecture Docker reported, as the runner wrote them."""
    host = next((r["docker_host"] for r in runs if r.get("docker_host")), {})
    arch = host.get("architecture", "")
    if image_platform == "linux/amd64" and arch in ("aarch64", "arm64"):
        return "linux/amd64 image on an arm64 host, emulated by Docker Desktop"
    return f"{image_platform} image on a host Docker reports as {arch or 'unknown'}"


def collect(models: Path) -> dict[str, Any]:
    folders = sorted(p for p in models.iterdir() if (p / "toy_model.json").exists())
    found: dict[str, Any] = {"folders": {}, "inputs": []}
    for folder in folders:
        entry = {"toy": _load(folder / "toy_model.json"), "runs": [], "analysis": None}
        found["inputs"].append(folder / "toy_model.json")
        for run in sorted(folder.glob("run_*.json")):
            entry["runs"].append(_load(run))
            found["inputs"].append(run)
        if (folder / "analysis.json").exists():
            entry["analysis"] = _load(folder / "analysis.json")
            found["inputs"].append(folder / "analysis.json")
        found["folders"][folder.name] = entry
    return found


def _fig_timing(
    sizes: dict[int, list[float]],
    ext: dict[str, Any],
    parallel: dict[int, list[float]],
    path: Path,
) -> None:
    import plotly.graph_objects as go

    fig = go.Figure()
    xs = [c for c, ws in sizes.items() for _ in ws]
    ys = [w for ws in sizes.values() for w in ws]
    fig.add_trace(
        go.Scatter(x=xs, y=ys, mode="markers", name="measured, one run at a time", marker_size=9)
    )
    for n, walls in sorted(parallel.items()):
        largest = max(sizes)
        fig.add_trace(
            go.Scatter(
                x=[largest] * len(walls),
                y=walls,
                mode="markers",
                marker_symbol="diamond",
                marker_size=8,
                name=f"measured, {n} runs at once (each run's wall time)",
            )
        )
    grid = [min(sizes) * (TARGET_CELLS / min(sizes)) ** (i / 40) for i in range(41)]
    fig.add_trace(
        go.Scatter(
            x=grid,
            y=[ext["power_a"] * c ** ext["power_b"] for c in grid],
            mode="lines",
            line_dash="dot",
            name=f"fit wall = a * cells^{ext['power_b']:.2f}",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[TARGET_CELLS],
            y=[ext["planning_s"]],
            mode="markers+text",
            marker_symbol="circle-open",
            marker_size=14,
            text=["extrapolated, not measured"],
            textposition="top left",
            name=f"extrapolation to {TARGET_CELLS:,} cells (15 km2 at 5 m)",
        )
    )
    fig.update_layout(
        title="SFINCS v2.5.0 wall time for a two-hour storm (3 h simulated), toy model",
        xaxis_title="cells (5 m)",
        yaxis_title="wall time (s)",
        template="plotly_white",
    )
    write_text_atomic(
        path, fig.to_html(include_plotlyjs="cdn", full_html=True, div_id="f0-solver-timing")
    )


def _fig_depth(grid: dict[str, Any], path: Path) -> None:
    import plotly.graph_objects as go

    values = grid["values_mm"]
    n = len(values)
    cell = grid["cell_m"]
    coords = [(i + 0.5) * cell for i in range(n)]
    fig = go.Figure(
        go.Heatmap(
            z=[[v / 1000 for v in row] for row in values],
            x=coords,
            y=coords,
            colorscale="Blues",
            colorbar_title="m",
        )
    )
    fig.update_layout(
        title="Toy model, 1 km2: maximum depth on the 5 m grid (zsmax minus the cell's lowest "
        "sub-grid level), 50 mm/h for 2 h; placeholder terrain",
        xaxis_title=f"m east of {grid['x0']:.0f} (EPSG:32618)",
        yaxis_title=f"m north of {grid['y0']:.0f}",
        yaxis_scaleanchor="x",
        template="plotly_white",
    )
    write_text_atomic(
        path, fig.to_html(include_plotlyjs="cdn", full_html=True, div_id="f0-toy-max-depth")
    )


def build(models: Path = MODELS, records: Path = RECORDS, figures: Path = FIGURES / "f0") -> Record:
    found = collect(models)
    folders = found["folders"]
    record = Record(
        id="f0-solver-timing",
        stage="F0",
        title="SFINCS and HydroMT-SFINCS stood up; toy model timed at three sizes",
    )
    record.inputs = [Input.of(p, root=models.parent) for p in found["inputs"]]

    sequential: dict[int, list[float]] = defaultdict(list)
    memory: dict[int, list[int]] = defaultdict(list)
    parallel: dict[int, list[float]] = defaultdict(list)
    runs_table = []
    all_runs = []
    for name, entry in folders.items():
        cells = entry["toy"]["cells"]
        for run in entry["runs"]:
            all_runs.append(run)
            label = run["label"]
            row = {
                "folder": name,
                "label": label,
                "cells": cells,
                "rain_mm_per_h": entry["toy"]["rain_mm_per_h"],
                "wall_time_s": run["wall_time_s"],
                "solver_total_time_s": run["parsed"].get("total_time_s"),
                "peak_memory_bytes": run["peak_memory_bytes"],
                "exit_code": run["exit_code"],
            }
            runs_table.append(row)
            if label.startswith("par"):
                parallel[int(label[3:].split("-")[0])].append(run["wall_time_s"])
            elif entry["toy"]["rain_mm_per_h"] == 50:
                sequential[cells].append(run["wall_time_s"])
            if run["peak_memory_bytes"]:
                memory[cells].append(run["peak_memory_bytes"])
    record.tables["runs"] = runs_table

    first = all_runs[0]
    toy = next(iter(folders.values()))["toy"]
    record.software.update(
        {
            "sfincs": first["parsed"].get("sfincs_revision", "unknown"),
            "sfincs_build_date": first["parsed"].get("sfincs_build_date", "unknown"),
            "sfincs_image": first["image"],
            "sfincs_image_digest": first["image_digest"],
            "sfincs_platform": _platform(first["platform"], all_runs),
            **{f"builder:{k}": v for k, v in toy["builder"].items()},
        }
    )
    for key, value in toy["parameters"].items():
        record.parameters.append(Parameter(f"toy.{key}", value, "P", "made-up toy value"))
    record.parameters += [
        Parameter("target_cells", TARGET_CELLS, "P", "plan F0: 15 km2 of 5 m cells"),
        Parameter("budget_s", BUDGET_S, "P", "12 hours of machine time, from the brief"),
        Parameter("memory_share", MEMORY_SHARE, "P", "share of the VM's memory given to runs"),
        Parameter("balance_limit", BALANCE_LIMIT, "S", "requirements FH8"),
        Parameter("catalogue_switch_s", CATALOGUE_SWITCH_S, "S", "plan F0 step 7"),
    ]

    sizes = {c: ws for c, ws in sorted(sequential.items())}
    ext = extrapolate(sizes) if len(sizes) >= 2 else None
    host = next((r["docker_host"] for r in all_runs if r.get("docker_host")), {})
    numbers: dict[str, Any] = {
        "wall_time_s_by_cells": {str(c): ws for c, ws in sizes.items()},
        "peak_memory_bytes_by_cells": {str(c): ms for c, ms in sorted(memory.items())},
        "docker_host": host,
    }
    if ext:
        numbers["extrapolation"] = ext
        numbers["runs_in_12h_sequential"] = runs_in_budget(ext["planning_s"])
        target_runs = 150 if ext["planning_s"] < CATALOGUE_SWITCH_S else 100
        numbers["catalogue_target_runs"] = target_runs
        numbers["catalogue_hours_at_target_sequential"] = round(
            target_runs * ext["planning_s"] / 3600, 1
        )
        largest = max(sizes)
        mem_largest = max(memory.get(largest, [0])) or None
        if mem_largest and host:
            mem_target = mem_largest * TARGET_CELLS / largest
            by_memory = int(host["mem_total_bytes"] * MEMORY_SHARE // mem_target)
            numbers["memory_per_run_at_target_bytes_linear"] = mem_target
            numbers["parallel_runs_memory_allows"] = by_memory
        if parallel:
            seq_mean = sum(sizes[largest]) / len(sizes[largest])
            speedups = {}
            for n, walls in sorted(parallel.items()):
                batch = max(walls)
                speedups[str(n)] = {
                    "runs": n,
                    "batch_wall_s": batch,
                    "throughput_vs_sequential": n * seq_mean / batch,
                    "runs_in_12h_at_target": int(
                        BUDGET_S // (ext["planning_s"] * batch / (n * seq_mean))
                    ),
                }
            numbers["parallel"] = speedups
    record.numbers = numbers

    # checks
    completed = [
        r["exit_code"] == 0 and r["parsed"].get("finished") and not r["timed_out"] for r in all_runs
    ]
    record.checks.append(
        Check(
            "runs_completed",
            "every run exits 0, prints 'Simulation finished' and stays under 20 minutes",
            all(completed),
            f"{sum(completed)} of {len(completed)}",
            len(completed),
        )
    )
    balances = {}
    for name, entry in folders.items():
        if entry["analysis"]:
            t = entry["analysis"]["water_balance"]
            balances[name] = water_balance(
                t["rain_m3"], t["infiltrated_m3"], t["stored_m3"], t["out_m3"]
            )
    record.tables["water_balance"] = balances
    worst = max((abs(b["residual_share"]) for b in balances.values()), default=None)
    record.checks.append(
        Check(
            "water_balance",
            "|rain - infiltrated - stored - out| / rain within 1% in every analysed run (FH8)",
            None if worst is None else worst <= BALANCE_LIMIT,
            worst,
            BALANCE_LIMIT,
        )
    )
    thresholds = {
        name: inp_value(models / name / "sfincs.inp", "huthresh")
        for name in folders
        if (models / name / "sfincs.inp").exists()
    }
    record.inputs += [
        Input.of(models / name / "sfincs.inp", root=models.parent) for name in thresholds
    ]
    read = sorted({v for v in thresholds.values() if v is not None})
    if len(read) == 1 and None not in thresholds.values():
        huthresh = f"the solver's dry threshold huthresh = {read[0]} m (read from sfincs.inp)"
    elif not read:
        huthresh = "the solver's default dry threshold (huthresh is not set in sfincs.inp)"
    else:
        huthresh = (
            "the solver's dry threshold huthresh, which differs between the models' sfincs.inp: "
            + ", ".join(f"{k} {v or 'default'}" for k, v in sorted(thresholds.items()))
        )
    compare = next(
        (
            e["analysis"]["compare_to"]
            for e in folders.values()
            if (e["analysis"] or {}).get("compare_to")
        ),
        None,
    )
    record.checks.append(
        Check(
            "monotone_in_rainfall",
            "25 mm/h gives depth no greater than 50 mm/h in every 5 m cell (FH8)",
            None if compare is None else compare["max_depth_minus_other_m"] <= 0.0,
            None if compare is None else compare["max_depth_minus_other_m"],
            0.0,
            note=""
            if compare is None
            else (
                f"{compare['cells_deeper_than_other']} of {compare['cells']} cells deeper at "
                f"25 mm/h, all with depths of "
                + ", ".join(f"{c['depth_m']:.4f}" for c in compare.get("deeper_cells", []))
                + f" m, at {huthresh}; among cells wet "
                "(0.05 m or more) in either run the largest difference is "
                f"{compare.get('max_depth_minus_other_where_either_wet_m')} m. The rule is "
                "kept strict as written; whether to judge it on wet cells only is for review."
            ),
        )
    )
    record.tables["monotone"] = compare
    one_km = next(
        (
            e["analysis"]
            for e in folders.values()
            if (e["analysis"] or {}).get("depth_5m_grid") and e["toy"]["rain_mm_per_h"] == 50
        ),
        None,
    )
    if one_km:
        d = one_km["depth"]
        record.numbers["depth_1km_50mm"] = d
        record.checks.append(
            Check(
                "deeper_in_depressions",
                "mean maximum depth in the depressions exceeds the 95th percentile on the slope",
                d["subgrid_1m_depressions_mean_m"] > d["subgrid_1m_slope_p95_m"],
                d["subgrid_1m_depressions_mean_m"],
                d["subgrid_1m_slope_p95_m"],
            )
        )

    figures.mkdir(parents=True, exist_ok=True)
    if ext:
        _fig_timing(sizes, ext, parallel, figures / "solver_timing.html")
        record.figures.append("docs/flood/figures/f0/solver_timing.html")
    if one_km:
        _fig_depth(one_km["depth_5m_grid"], figures / "toy_max_depth.html")
        record.figures.append("docs/flood/figures/f0/toy_max_depth.html")
    record.notes += [
        "The image tag is built for linux/amd64 only; every run here is a "
        f"{record.software['sfincs_platform']}.",
        "Wall time is measured around 'docker run' and includes container start.",
        "Parallel batches: the runs start together; batch wall time is the longest run.",
        "Every toy value is a placeholder [P]; the toy exists to time the solver.",
    ]
    if ext and "catalogue_hours_at_target_sequential" in numbers:
        par = numbers.get("parallel", {})
        ratios = "; ".join(
            f"{v['runs']} runs at once gave {v['throughput_vs_sequential']:.2f} times the "
            "throughput of runs one after another"
            for v in par.values()
        )
        record.notes.append(
            f"Catalogue size: plan F0's rule sets {numbers['catalogue_target_runs']} runs, since "
            f"one run at {TARGET_CELLS:,} cells is estimated at {ext['planning_s']:.0f} s, "
            + ("under" if ext["planning_s"] < CATALOGUE_SWITCH_S else "not under")
            + f" {CATALOGUE_SWITCH_S} s. Those {numbers['catalogue_target_runs']} runs take about "
            f"{numbers['catalogue_hours_at_target_sequential']} hours of solver time one after "
            "another on this machine, "
            + (
                "more"
                if numbers["catalogue_hours_at_target_sequential"] > BUDGET_S / 3600
                else "not more"
            )
            + " than the 12 hours used as a yardstick (about "
            f"{numbers['runs_in_12h_sequential']} runs fit in 12 hours). "
            + (
                f"Running in parallel does not shorten it: {ratios}."
                if par and max(v["throughput_vs_sequential"] for v in par.values()) <= 1
                else f"Runs in parallel were measured as follows: {ratios or 'not measured'}."
            )
            + " Real terrain with buildings may need a smaller time step than the toy, which "
            "would make each run longer."
        )
    record.write(records)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", type=Path, default=MODELS)
    args = parser.parse_args()
    record = build(args.models)
    print(json.dumps({"passed": record.passed, **{c.name: c.passed for c in record.checks}}))


if __name__ == "__main__":
    main()
