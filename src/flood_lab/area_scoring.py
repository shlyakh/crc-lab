"""F0: score candidate study areas by what was observed in them (requirements D1, FD1).

A candidate is a square window slid over Brooklyn and Queens on the project's coordinate system
(UTM zone 18N). Each window gets counts of the things the later stages need: surveyed high-water
marks from Ida, flood sensors that recorded each storm, substations, deep flooding on the city's
map, and news-derived flood reports. Everything is counted on a grid of small bins first, so a
window's count is a sum of bins and every window is counted the same way.

No function here reads a file: the check script ``checks/f0_area.py`` does the reading.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CRS = "EPSG:32618"
#: Brooklyn and Queens, the box the F0 downloads used (longitude, latitude)
BOX_LONLAT = (-74.05, 40.55, -73.70, 40.80)


@dataclass(frozen=True)
class Grid:
    """Square bins in UTM metres; ``window`` bins on a side make one candidate area."""

    x0: float
    y0: float
    step: float
    nx: int
    ny: int
    window: int

    @property
    def window_km2(self) -> float:
        return (self.window * self.step) ** 2 / 1e6

    def count(self, x: np.ndarray, y: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
        """Points per bin, as an array [row from south, column from west]."""
        col = np.floor((np.asarray(x) - self.x0) / self.step).astype(int)
        row = np.floor((np.asarray(y) - self.y0) / self.step).astype(int)
        keep = (col >= 0) & (col < self.nx) & (row >= 0) & (row < self.ny)
        out = np.zeros((self.ny, self.nx))
        np.add.at(
            out, (row[keep], col[keep]), 1.0 if weights is None else np.asarray(weights)[keep]
        )
        return out

    def window_sums(self, bins: np.ndarray) -> np.ndarray:
        """Sum of every ``window`` x ``window`` block of bins, indexed by its south-west bin."""
        padded = np.zeros((self.ny + 1, self.nx + 1))
        padded[1:, 1:] = np.cumsum(np.cumsum(bins, axis=0), axis=1)
        w = self.window
        return padded[w:, w:] - padded[:-w, w:] - padded[w:, :-w] + padded[:-w, :-w]

    def window_bounds(self, row: int, col: int) -> tuple[float, float, float, float]:
        west, south = self.x0 + col * self.step, self.y0 + row * self.step
        return west, south, west + self.window * self.step, south + self.window * self.step


def fine_to_bins(fine_north_first: np.ndarray, grid: Grid, cell_m: float) -> np.ndarray:
    """Hectares per bin from a fine 0/1 raster whose row 0 is the north edge, as rasters are.

    The raster covers the grid exactly, ``grid.step / cell_m`` fine cells to a bin; the result is
    indexed like ``Grid.count``: [row from south, column from west].
    """
    fine = int(round(grid.step / cell_m))
    if abs(fine * cell_m - grid.step) > 1e-9:
        raise ValueError("the bin side must be a whole number of fine cells")
    if fine_north_first.shape != (grid.ny * fine, grid.nx * fine):
        raise ValueError("the fine raster must cover the grid exactly")
    south_first = fine_north_first[::-1]
    cells = south_first.reshape(grid.ny, fine, grid.nx, fine).sum(axis=(1, 3))
    return cells * cell_m**2 / 1e4


def make_grid(bounds_utm: tuple[float, float, float, float], *, step: float, side: float) -> Grid:
    west, south, east, north = bounds_utm
    x0, y0 = np.floor(west / step) * step, np.floor(south / step) * step
    nx, ny = int(np.ceil((east - x0) / step)), int(np.ceil((north - y0) / step))
    window = int(round(side / step))
    if abs(window * step - side) > 1e-9:
        raise ValueError("the window side must be a whole number of bins")
    return Grid(float(x0), float(y0), step, nx, ny, window)


def score(counts: dict[str, np.ndarray], thresholds: dict[str, float]) -> np.ndarray:
    """Sum over the criteria of count / threshold, each capped at 2.

    A criterion at its threshold adds 1; a criterion at twice its threshold or more adds 2, so no
    single plentiful source can carry a window.
    """
    total = np.zeros_like(next(iter(counts.values())), dtype=float)
    for name, threshold in thresholds.items():
        total += np.minimum(counts[name] / threshold, 2.0)
    return total


def passes(counts: dict[str, np.ndarray], rule: dict[str, float]) -> np.ndarray:
    ok = np.ones_like(next(iter(counts.values())), dtype=bool)
    for name, minimum in rule.items():
        ok &= counts[name] >= minimum
    return ok


def pick(scores: np.ndarray, grid: Grid, *, n: int, max_overlap: float) -> list[tuple[int, int]]:
    """The ``n`` best windows, best first, no two sharing more than ``max_overlap`` of their area.

    Ties go to the more southerly, then the more westerly window, so the result does not depend
    on the order of the input.
    """
    order = sorted(
        ((-scores[r, c], r, c) for r in range(scores.shape[0]) for c in range(scores.shape[1])),
    )
    chosen: list[tuple[int, int]] = []
    for _, row, col in order:
        if all(_overlap(row, col, r, c, grid.window) <= max_overlap for r, c in chosen):
            chosen.append((row, col))
            if len(chosen) == n:
                break
    return chosen


def _overlap(r1: int, c1: int, r2: int, c2: int, window: int) -> float:
    rows = max(0, window - abs(r1 - r2))
    cols = max(0, window - abs(c1 - c2))
    return rows * cols / window**2
