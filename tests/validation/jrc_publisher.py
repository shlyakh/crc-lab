"""A small publisher folder laid out as JRC's, for the offline tests of the JRC flood assessments.

Two GloFAS tiles that meet at a seam and one EFAS raster, with pixels placed on purpose: one with
three depths, one with four, one with equal depths, one whose depth decreases, one dry.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow  # noqa: F401  (before rasterio: a build against another GDAL breaks pyarrow)
import rasterio
from rasterio.transform import from_origin

FIXTURES = Path(__file__).parent / "fixtures"
VERSIONS = {"crc-sdk": "test"}
STEP = 1 / 1200  # three arc seconds, as the publisher's grids
NODATA = -9999.0
GLOFAS_PERIODS = (10, 20, 50, 75, 100, 200, 500)
EFAS_PERIODS = (10, 20, 30, 40, 50, 75, 100, 200, 500)
ROWS, COLUMNS = 40, 48
WEST, NORTH = -100.0, 31.0
SEAM = WEST + COLUMNS * STEP
# edges fall 0.6 of a pixel inside a pixel, so "touched" and "rounded" windows differ;
# the box crosses the seam between the two tiles
BOX = (WEST + 11.6 * STEP, NORTH - 30.6 * STEP, SEAM + 20.6 * STEP, NORTH - 4.4 * STEP)
FAR = (10.0, 10.0, 10.2, 10.2)
# (row, column) of pixels inside the box, in the first tile
THREE, FOUR, FLAT, DOWN, DRY = (10, 20), (10, 21), (12, 20), (12, 21), (14, 20)


def _stack(periods: tuple[int, ...], seed: int) -> np.ndarray:
    """Depths that increase with the return period; a third of the pixels start dry."""
    rng = np.random.default_rng(seed)
    steps = rng.uniform(0.05, 0.6, (len(periods), ROWS, COLUMNS))
    stack = (rng.uniform(0.1, 3.0, (ROWS, COLUMNS)) + np.cumsum(steps, axis=0)).astype("<f4")
    first_wet = rng.integers(0, len(periods), (ROWS, COLUMNS))
    first_wet[rng.random((ROWS, COLUMNS)) < 0.6] = 0
    for index in range(len(periods)):
        stack[index][first_wet > index] = NODATA
    stack[:, rng.random((ROWS, COLUMNS)) < 0.2] = NODATA  # never wet
    return stack


def _specials(stack: np.ndarray) -> None:
    count = stack.shape[0]
    rising = np.linspace(0.5, 2.0, count).astype("<f4")
    for (row, column), wet in ((THREE, 3), (FOUR, 4)):
        stack[:, row, column] = rising
        stack[: count - wet, row, column] = NODATA
    stack[:, FLAT[0], FLAT[1]] = 1.0
    stack[:, DOWN[0], DOWN[1]] = rising
    stack[3, DOWN[0], DOWN[1]] = 0.2
    stack[:, DRY[0], DRY[1]] = NODATA


def _write(path: Path, data: np.ndarray, west: float, north: float, **more: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {"driver": "GTiff", "dtype": data.dtype.name, "count": 1, "width": data.shape[1],
               "height": data.shape[0], "crs": "EPSG:4326", "nodata": NODATA,
               "transform": from_origin(west, north, STEP, STEP), "compress": "deflate",
               "tiled": True, "blockxsize": 16, "blockysize": 16, **more}  # fmt: skip
    with rasterio.open(path, "w", **profile) as target:
        target.write(data, 1)


def build_publisher(root: Path, flat_then_a_jump: bool = False) -> dict[str, Path]:
    glofas, efas = root / "glofas", root / "efas"
    tiles = {"ID1_N31_W100": WEST, "ID2_N31_W099": SEAM}
    for number, (tile, west) in enumerate(tiles.items()):
        stack = _stack(GLOFAS_PERIODS, seed=number + 1)
        if number == 0:
            _specials(stack)
            if flat_then_a_jump:  # the depths crc-framework's optimizer does not converge on
                stack[:, 16, 20] = (1.0, 1.0, 1.0, 1.0, 1.0, 1.016, 1.13)
        for index, period in enumerate(GLOFAS_PERIODS):
            _write(glofas / f"RP{period}" / f"{tile}_RP{period}_depth.tif", stack[index],
                   west, NORTH)  # fmt: skip
    features = [
        {"type": "Feature", "properties": {"id": int(tile[2]), "name": tile[4:]},
         "geometry": {"type": "Polygon", "coordinates": [[
             [west, NORTH], [west + COLUMNS * STEP, NORTH],
             [west + COLUMNS * STEP, NORTH - ROWS * STEP], [west, NORTH - ROWS * STEP],
             [west, NORTH]]]}}
        for tile, west in tiles.items()
    ]  # fmt: skip
    (glofas / "tile_extents.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    stack = _stack(EFAS_PERIODS, seed=7)
    _specials(stack)
    for index, period in enumerate(EFAS_PERIODS):
        _write(efas / f"Europe_RP{period}_filled_depth.tif", stack[index], 8.0, 50.0)
    for folder, release in ((glofas, "2.1.2"), (efas, "3.1.1")):
        (folder / "README.txt").write_text(
            f"GENERAL INFORMATION\n\nG01. Dataset version {release}\n"
            "D01. Horizontal coverage: constructed\n"
            "A02. License information, restrictions on use: "
            "Open Data Commons Open Database License v1.0\n",
            encoding="utf-8",
        )
        (folder / "copyright.txt").write_text("constructed", encoding="utf-8")
    return {"glofas": glofas, "efas": efas}
