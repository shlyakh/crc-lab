"""Tests parked until their code is ported to crc-sdk 1.x.

crc-sdk 1.0 removed every module the 0.x code imported. The validation project is ported source by
source; the explorer and the hail project follow. A parked test is not collected, and every run
ends with the count of what is parked, so the list cannot be forgotten. Remove an entry when its
code runs on the pinned version.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).parent

#: whole test files whose subject still imports removed crc-sdk modules
PARKED_FILES = {
    "test_curves.py": "hail curves: crc_sdk.fitting, HazardDataset.from_table",
    "test_explorer.py": "explorer: crc_sdk.connectors, CRC Open through HazardDataset",
    "test_risk_layer.py": "hail risk layer: reaches crc_lab.curves.fit",
    "test_sources.py": "explorer sources: HazardDataset, IBTrACSPlan, NOAAExtremeWaterLevelPlan",
    "test_storm_events.py": "storm events: crc_sdk.geometry.vector.polyfill_wkb",
    "validation/test_data_source_check_era5.py": "draft assessment, not yet ported",
    "validation/test_data_source_check_ghcnh.py": "assessment not yet ported",
    "validation/test_data_source_check_ibtracs.py": "assessment not yet ported",
    "validation/test_data_source_check_jrc_flood_011.py": (
        "the 0.11 assessment (fitted curves), kept as the previous version"
    ),
    "validation/test_data_source_check_nex.py": "assessment not yet ported",
    "validation/test_data_source_check_noaa_water_levels.py": "draft assessment, not yet ported",
}
#: single tests in files that otherwise run
PARKED_TESTS = {
    "test_impacts.py::test_crc_expressions_match_the_callables": "crc_sdk.impacts.ImpactExpression",
    "test_impacts.py::test_plant_parameters_follow_year_and_mounting": "reaches crc_lab.curves.fit",
    "test_crc_surface.py::test_real_repository_uses_only_names_the_installed_upstream_has": (
        "true again when every project is ported"
    ),
}


def pytest_ignore_collect(collection_path: Path) -> bool | None:
    try:
        relative = collection_path.relative_to(HERE).as_posix()
    except ValueError:
        return None
    return True if relative in PARKED_FILES else None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        relative = Path(str(item.fspath)).relative_to(HERE).as_posix()
        reason = PARKED_TESTS.get(f"{relative}::{item.name.split('[')[0]}")
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"awaiting the 1.0 port: {reason}"))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    missing = [name for name in PARKED_FILES if not (HERE / name).exists()]
    terminalreporter.write_line(
        f"awaiting the 1.0 port: {len(PARKED_FILES)} test files and {len(PARKED_TESTS)} tests "
        "not run (tests/conftest.py)" + (f"; listed but absent: {missing}" if missing else "")
    )
