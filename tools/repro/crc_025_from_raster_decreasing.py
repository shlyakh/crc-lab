# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "crc-sdk[raster]==1.0.0", "crc-framework==1.0.0",
#   "rasterio<1.5.2; sys_platform == 'darwin'",
# ]
# ///
"""Dataset.from_raster: one pixel whose value decreases fails the whole read, unnamed.

Expected (docs/datasets.md): each pixel keeps its footprint and quantile knots. Observed: a
3 x 3 pixel set of three rasters in which one pixel's value falls at a higher probability
gives no rows at all, and the error does not say which pixel. Input is constructed: the
rasters are written by the script to a temporary folder (depths in metres, as flood maps).

    uv run crc_025_from_raster_decreasing.py
"""

import tempfile
from importlib.metadata import version
from pathlib import Path

import numpy as np
import rasterio
from crc_framework import DepthAboveGround, LengthUnit, Tail
from crc_sdk import Bounds, Dataset, Probability, Variable
from rasterio.transform import from_origin

PERIODS = (10, 50, 100)  # return periods, years -> probabilities 1 - 1/T
BAD = (1, 2)  # row, column of the one pixel whose value decreases


def layers(decreasing: bool) -> dict[int, np.ndarray]:
    out = {t: np.full((3, 3), 0.5 * (i + 1), dtype="float32") for i, t in enumerate(PERIODS)}
    if decreasing:  # 1.0, 1.0, then 0.25 at 100 years
        for t, value in zip(PERIODS, (1.0, 1.0, 0.25), strict=True):
            out[t][BAD] = value
    return out


def read(folder: Path, decreasing: bool) -> str:
    files = {}
    for t, array in layers(decreasing).items():
        path = folder / f"{'bad' if decreasing else 'good'}_RP{t}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=3, height=3, count=1,
                           dtype="float32", crs="EPSG:4326",
                           transform=from_origin(10.0, 50.0, 0.01, 0.01)) as out:  # fmt: skip
            out.write(array, 1)
        files[1 - 1 / t] = path
    dataset = Dataset.from_raster(
        files,
        variable=Variable("example:depth", measurement=DepthAboveGround(unit=LengthUnit.METRE)),
        probability=Probability.annual(tail=Tail.UPPER),
    ).select(area=Bounds(west=10.0, south=49.97, east=10.03, north=50.0))
    try:
        result = dataset.read()
    except Exception as error:  # noqa: BLE001  the outcome is what is printed
        report = getattr(error, "report", None)
        counts = "" if report is None else (
            f"; counts requested={report.counts.requested} produced={report.counts.produced}; "
            f"diagnostic support_id={[d.support_id for d in report.diagnostics]}")  # fmt: skip
        return f"{type(error).__name__}: {error}{counts}"
    return f"{result.table.num_rows} rows"


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}, "
      f"rasterio {version('rasterio')}")  # fmt: skip
print(
    "call: Dataset.from_raster({1 - 1/T: file}, variable=..., "
    "probability=Probability.annual(tail=Tail.UPPER)).select(area=...).read()"
)
print(
    f"input: 3 x 3 pixels, T = {PERIODS}; pixel (row {BAD[0]}, column {BAD[1]}) "
    "is 1.0, 1.0, 0.25 m in the second set"
)
with tempfile.TemporaryDirectory() as tmp:
    good, bad = read(Path(tmp), False), read(Path(tmp), True)
print("expected: 9 rows for the first set; for the second, 8 rows, or an error naming the pixel")
print(f"observed, all pixels nondecreasing: {good}")
print(f"observed, one pixel decreasing:     {bad}")
named = "row" in bad.lower() and str(BAD[0]) in bad and str(BAD[1]) in bad
print(f"observed: the error names the pixel: {'yes' if named else 'no'}")
print("REPRODUCED" if good == "9 rows" and "rows" not in bad and not named else "NOT REPRODUCED")
