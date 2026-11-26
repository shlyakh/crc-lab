"""The hazard interface (FH1): ``depth(scenario)`` gives a raster in metres on the project grid.

Three implementations are registered. A licensed model would be one more class with the same two
methods.

* ``city-map``: the city's stormwater flood maps (F2). They hold classes, not depths, so the raster
  is the **lower bound** of each cell's class (0.1016 m or 0.3048 m, else 0) and the record says so.
* ``solver``: a SFINCS run of F3 (``f3/runs/<label>/``): peak depth at each cell's centre pixel, as
  ``calibration.run_depth`` defines it.
* ``emulator``: the neural-network emulator of F9. Not built yet; asking it for a depth raises.

Each ``depth`` returns ``(raster, record)``: rows from the north on ``domain.GRID``, and a dict
naming the implementation, the scenario, the inputs and what the values mean.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from flood_lab import paths
from flood_lab.hazard import calibration


class HazardSource(Protocol):
    name: str

    def scenarios(self) -> list[str]: ...

    def depth(self, scenario: str) -> tuple[np.ndarray, dict]: ...


class CityMapHazard:
    name = "city-map"
    folder = paths.SITE / "data" / "city_flood_maps"

    def scenarios(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.tif") if not p.stem.endswith("-tidal"))

    def depth(self, scenario: str) -> tuple[np.ndarray, dict]:
        classes = calibration.city_class(scenario)
        lower = np.select(
            [classes == 2, classes == 1], [calibration.DEEP_M, calibration.SHALLOW_M], 0.0
        )
        return lower, {
            "implementation": self.name,
            "scenario": scenario,
            "input": str((self.folder / f"{scenario}.tif").relative_to(paths.ROOT)),
            "values": "lower bound of the city's depth class (0, 0.1016 or 0.3048 m); not a depth",
        }


class SolverHazard:
    name = "solver"

    def __init__(self, runs: Path | None = None, cache: Path | None = None) -> None:
        self.cache = cache or paths.CACHE
        self.runs = runs or self.cache / "f3" / "runs"
        self._frame: calibration.Frame | None = None

    def scenarios(self) -> list[str]:
        return sorted(p.parent.name for p in self.runs.glob("*/zsmax.tif"))

    def depth(self, scenario: str) -> tuple[np.ndarray, dict]:
        folder = self.runs / scenario
        if not (folder / "zsmax.tif").exists():
            raise FileNotFoundError(f"no finished solver run {scenario!r} in {self.runs}")
        if self._frame is None:
            self._frame = calibration.Frame.load(
                self.cache, paths.SITE / "data" / "study_area.geojson"
            )
        return calibration.run_depth(folder, self._frame), {
            "implementation": self.name,
            "scenario": scenario,
            "input": str(folder),
            "values": "peak depth at the cell's centre pixel above the model terrain, m",
        }


class EmulatorHazard:
    name = "emulator"

    def scenarios(self) -> list[str]:
        return []

    def depth(self, scenario: str) -> tuple[np.ndarray, dict]:
        raise NotImplementedError("the emulator is built in F9")


REGISTRY: dict[str, type] = {
    CityMapHazard.name: CityMapHazard,
    SolverHazard.name: SolverHazard,
    EmulatorHazard.name: EmulatorHazard,
}


def get(name: str, **kwargs) -> HazardSource:
    return REGISTRY[name](**kwargs)
