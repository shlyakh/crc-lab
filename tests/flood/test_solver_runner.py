"""F0 solver runner and timing check, offline and without Docker (FH2, FH8)."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from flood_lab.checks.f0_solver_timing import (
    extrapolate,
    power_fit,
    runs_in_budget,
    water_balance,
)
from flood_lab.hazard.run_sfincs import IMAGE, docker_command, parse_log, parse_memory

LOG = Path(__file__).resolve().parents[1] / "fixtures" / "flood" / "sfincs_v2.5.0_run.log"
HAZARD = Path(__file__).resolve().parents[2] / "src" / "flood_lab" / "hazard"


def test_docker_command_mounts_the_folder_as_data(tmp_path: Path) -> None:
    command = docker_command(tmp_path, "sfincs-x")
    assert command[:3] == ["docker", "run", "--rm"]
    assert command[command.index("--name") + 1] == "sfincs-x"
    assert command[command.index("--platform") + 1] == "linux/amd64"
    assert command[command.index("-v") + 1] == f"{tmp_path.resolve()}:/data"
    assert command[-1] == IMAGE == "deltares/sfincs-cpu:sfincs-v2.5.0-Hautacam"


def test_parse_log_on_a_saved_v2_5_0_run() -> None:
    found = parse_log(LOG.read_text(encoding="utf-8"))
    assert found["sfincs_revision"] == "v2.5.0 Hautacam Release 2026.02"
    assert found["sfincs_build_date"] == "2026-10-30"
    assert found["total_time_s"] == pytest.approx(17.347)
    assert found["time_in_simulation_s"] == pytest.approx(17.231)
    assert found["average_time_step_s"] == pytest.approx(0.842)
    assert found["threads"] == 8 and found["active_cells"] == 40000
    assert found["finished"] is True and found["stopped_with_error"] is False


def test_parse_log_flags_a_failed_run() -> None:
    text = 'Error   : SFINCS input file "sfincs.inp" not found! SFINCS has stopped!\nSTOP 2\n'
    found = parse_log(text)
    assert found["finished"] is False and found["stopped_with_error"] is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("45.06MiB / 7.748GiB", int(45.06 * 1024**2)),
        ("1.5GiB / 7.7GiB", int(1.5 * 1024**3)),
        ("812KiB / 7.7GiB", 812 * 1024),
        ("--", None),
    ],
)
def test_parse_memory(text: str, expected: int | None) -> None:
    assert parse_memory(text) == expected


def test_water_balance_arithmetic_on_made_up_numbers() -> None:
    terms = water_balance(rain=1000.0, infiltrated=200.0, stored=300.0, out=495.0)
    assert terms["residual_m3"] == pytest.approx(5.0)
    assert terms["residual_share"] == pytest.approx(0.005)
    assert math.isnan(water_balance(0.0, 0.0, 0.0, 0.0)["residual_share"])


def test_power_fit_and_extrapolation_recover_a_known_law() -> None:
    sizes = {c: [2.0 * c**0.9, 2.0 * c**0.9] for c in (40_000, 160_000, 360_000)}
    a, b = power_fit([c for c in sizes for _ in sizes[c]], [w for ws in sizes.values() for w in ws])
    assert a == pytest.approx(2.0) and b == pytest.approx(0.9)
    ext = extrapolate(sizes, target=600_000)
    assert ext["fitted_s"] == pytest.approx(2.0 * 600_000**0.9)
    assert ext["linear_from_largest_s"] == pytest.approx(2.0 * 360_000**0.9 * 600_000 / 360_000)
    assert ext["planning_s"] == max(ext["fitted_s"], ext["linear_from_largest_s"])
    assert runs_in_budget(100.0, budget=43_200) == 432


def test_runner_uses_the_standard_library_only() -> None:
    tree = ast.parse((HAZARD / "run_sfincs.py").read_text(encoding="utf-8"))
    names = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names |= {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert names <= {
        "__future__",
        "argparse",
        "json",
        "os",
        "re",
        "subprocess",
        "threading",
        "time",
        "datetime",
        "pathlib",
    }
