"""Shared helpers of the crc-sdk 1.0 probes: paths, versions, and the publisher's JRC depths.

The publisher's side is read with crc-lab's independent reader
(``data_source_check.reference.jrc_flood``), which imports neither crc-sdk nor rasterio, from the
copies the 0.11 assessment holds under ``data/cache/validation/jrc-flood/original/``. Nothing here
imports crc-lab code that imports crc-sdk 0.x.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from data_source_check.reference import jrc_flood as ref  # noqa: E402  (numpy only)

ORIGINAL = REPO / "data" / "cache" / "validation" / "jrc-flood" / "original"
Box = tuple[float, float, float, float]  # west, south, east, north

# The areas of the 0.11 assessment (src/data_source_check/assessments/jrc_flood.py).
FREMONT: Box = (-122.15, 37.42, -121.85, 37.62)
HOUSTON: Box = (-95.9, 29.3, -94.9, 30.2)
AUSTIN: Box = (-98.0, 30.0, -97.5, 30.5)


def versions() -> dict[str, str]:
    out = {}
    for name in ("crc-sdk", "crc-framework", "rasterio", "numpy", "pyarrow"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out


def bounds(box: Box) -> Any:
    from crc_sdk import Bounds

    west, south, east, north = box
    return Bounds(west=west, south=south, east=east, north=north)


# ---------------------------------------------------------------------------- publisher depths
@dataclass
class Window:
    """The publisher's depths of one tile inside a box: one layer per return period."""

    dataset: str
    tile: str  # "" for EFAS's continental files
    periods: list[int]
    column: int  # first column of the window in the publisher's file
    row: int
    left: float  # west edge of the file, degrees
    top: float
    dx: float
    dy: float
    depths: np.ndarray  # [period, row, column], float64, NaN where no depth
    files: dict[int, str]  # period -> local file

    def edges(self, row: int, column: int) -> Box:
        """West, south, east, north of a pixel given in file coordinates."""
        west = self.left + column * self.dx
        north = self.top - row * self.dy
        return west, north - self.dy, west + self.dx, north

    def at(self, row: int, column: int) -> np.ndarray:
        return self.depths[:, row - self.row, column - self.column]


def _periods(folder: Path, layout: str) -> list[int]:
    if layout == "tiled":
        return sorted(int(p.name[2:]) for p in folder.iterdir() if re.fullmatch(r"RP\d+", p.name))
    return sorted(
        int(m.group(1))
        for p in folder.iterdir()
        if (m := re.fullmatch(r"Europe_RP(\d+)_filled_depth\.tif", p.name))
    )


def publisher_windows(dataset: str, box: Box) -> list[Window]:
    """The publisher's depths in ``box``, from the copies the 0.11 assessment downloaded.

    Raises FileNotFoundError when a file is not held; the probes do not download these.
    """
    folder = ORIGINAL / dataset
    layout = ref.DATASETS[dataset]["layout"]
    if not folder.is_dir():
        raise FileNotFoundError(f"no copy of the publisher's {dataset} files under {folder}")
    periods = _periods(folder, layout)
    if layout == "tiled":
        index = json.loads((folder / "tile_extents.geojson").read_text(encoding="utf-8"))
        tiles = ref.tiles_for(index, box)
    else:
        tiles = [""]
    out = []
    for tile in tiles:
        files = {p: folder / ref.depth_name(layout, p, tile) for p in periods}
        missing = [str(f) for f in files.values() if not f.exists()]
        if missing:
            raise FileNotFoundError(f"publisher copies not held: {missing[:3]}")
        layers, window = [], None
        for period in periods:
            with ref.Tiff(files[period]) as tiff:
                window = window or tiff.window(box)
                if window is None:
                    break
                layers.append(ref.depths(tiff.read(window), tiff.nodata))
                meta = (tiff.left, tiff.top, tiff.dx, tiff.dy)
        if window is None:
            continue
        c0, r0, _, _ = window
        out.append(Window(dataset, tile, periods, c0, r0, *meta, np.stack(layers),
                          {p: str(f) for p, f in files.items()}))  # fmt: skip
    return out


def classify(depths: np.ndarray) -> dict[str, np.ndarray]:
    """Per pixel, by crc-sdk 1.0's rule for raster knots (crc_sdk/_climate_io.py:167-178).

    A pixel with fewer than two finite depths is skipped; one whose finite depths ever decrease
    with return period cannot be made into a ``QuantileCurve`` (values must be nondecreasing).
    """
    held = np.isfinite(depths)
    knots = held.sum(axis=0)
    decreasing = np.zeros(depths.shape[1:], dtype=bool)
    last = np.full(depths.shape[1:], -np.inf)
    for layer in range(depths.shape[0]):
        here = held[layer]
        decreasing |= here & (depths[layer] < last)
        last = np.where(here, depths[layer], last)
    return {
        "wet": knots >= 1,
        "skipped": (knots >= 1) & (knots < 2),
        "decreasing": (knots >= 2) & decreasing,
        "curve": (knots >= 2) & ~decreasing,
        "knots": knots,
    }


def clean_region(window: Window, rows: int, columns: int) -> tuple[int, int] | None:
    """Top-left (file row, column) of the ``rows`` x ``columns`` block of the window that has no
    decreasing pixel and the most pixels that become curves; None if there is none."""
    kinds = classify(window.depths)
    bad = kinds["decreasing"].astype(np.int64)
    good = kinds["curve"].astype(np.int64)
    height, width = bad.shape
    if height < rows or width < columns:
        return None

    def sums(a: np.ndarray) -> np.ndarray:
        s = np.zeros((height + 1, width + 1), dtype=np.int64)
        s[1:, 1:] = a.cumsum(0).cumsum(1)
        return s[rows:, columns:] - s[:-rows, columns:] - s[rows:, :-columns] + s[:-rows, :-columns]

    bad_sum, good_sum = sums(bad), sums(good)
    score = np.where(bad_sum == 0, good_sum, -1)
    r, c = np.unravel_index(int(np.argmax(score)), score.shape)
    if score[r, c] <= 0:
        return None
    return window.row + int(r), window.column + int(c)


def inner_box(window: Window, row: int, column: int, rows: int, columns: int) -> Box:
    """A box that holds exactly the pixels of the block: its edges sit a quarter pixel inside the
    block, so no neighbouring pixel is touched."""
    west, _, _, north = window.edges(row, column)
    _, south, east, _ = window.edges(row + rows - 1, column + columns - 1)
    qx, qy = window.dx / 4, window.dy / 4
    return (west + qx, south + qy, east - qx, north - qy)


def first_decreasing(window: Window, margin: int = 2) -> tuple[int, int] | None:
    """File row and column of the first decreasing pixel at least ``margin`` pixels inside the
    window, so that a box around it stays in the same file."""
    kinds = classify(window.depths)
    height, width = kinds["decreasing"].shape
    for r, c in np.argwhere(kinds["decreasing"]):
        if margin <= r < height - margin and margin <= c < width - margin:
            return window.row + int(r), window.column + int(c)
    return None


def stats(values: Sequence[float] | np.ndarray) -> dict[str, Any]:
    a = np.asarray(values, dtype=np.float64)
    a = a[np.isfinite(a)]
    if not len(a):
        return {"n": 0}
    return {
        "n": int(len(a)),
        "median": round(float(np.median(a)), 4),
        "p90": round(float(np.quantile(a, 0.9)), 4),
        "largest": round(float(a.max()), 4),
    }


def log_period_interpolation(periods: Sequence[float], values: Sequence[float], at: float) -> float:
    """Depth at return period ``at`` by straight lines in ln(T) between the bracketing knots
    (crc-framework 0.6's ``TabulatedDistribution.from_return_periods``)."""
    t = np.asarray(periods, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)
    if not (t[0] <= at <= t[-1]):
        return math.nan
    return float(np.interp(math.log(at), np.log(t), v))
