# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "crc-sdk[raster]==1.0.0", "crc-framework==1.0.0",
#   "rasterio<1.5.2; sys_platform == 'darwin'",
# ]
# ///
"""JRC GloFAS: dry pixels and flooded pixels that are left out share one skipped count.

Expected (docs/sources.md: "original pixels and quantile knots"): every flooded pixel in the box
becomes a row, or the read says which flooded pixels it left out and why. Observed: pixels with
one depth, and pixels whose depth is lower at a longer return period, are dropped; the only trace
is one count that also holds every dry pixel. The publisher's seven GeoTIFFs of the tile (~28 MB)
are downloaded once to <temp dir>/glofas-repro and counted with rasterio, as crc-sdk reads them.

    uv run crc_023_jrc_skipped_pixels.py
"""

import math
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

import numpy as np
import rasterio
from crc_sdk import JRC, Bounds

BOX = dict(west=-122.15, south=37.42, east=-121.85, north=37.62)  # Fremont, California
BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard"
TILE = "ID18_N40_W130"  # the GloFAS tile that holds the box
PERIODS = (10, 20, 50, 75, 100, 200, 500)
CACHE = Path(tempfile.gettempdir()) / "glofas-repro"


def tries(what, call):
    """Three tries with a growing pause on connection errors; exit 2 if all fail."""
    for attempt in range(1, 4):
        try:
            return call()
        except OSError as error:
            print(f"  ({what}: try {attempt} failed: {type(error).__name__}: {error})")
            if attempt < 3:
                time.sleep(10 * attempt)
    print(f"COULD NOT RUN: the publisher did not answer for {what} after three tries")
    sys.exit(2)


def download(period: int) -> Path:
    path = CACHE / f"{TILE}_RP{period}_depth.tif"
    if not path.exists():
        request = urllib.request.Request(f"{BASE}/RP{period}/{path.name}",
                                         headers={"User-Agent": "repro-script/1.0"})  # fmt: skip
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            data = response.read()
        CACHE.mkdir(exist_ok=True)
        path.with_suffix(".part").write_bytes(data)
        path.with_suffix(".part").replace(path)
    return path


def publisher_window(path: Path) -> np.ma.MaskedArray:
    """The pixels touched by the box, as crc-sdk selects them (floor/ceil of the edges)."""
    with rasterio.open(path) as source:
        inverse = ~source.transform
        c0, r0 = inverse * (BOX["west"], BOX["north"])
        c1, r1 = inverse * (BOX["east"], BOX["south"])
        window = rasterio.windows.Window.from_slices(
            (math.floor(r0), math.ceil(r1)), (math.floor(c0), math.ceil(c1))
        )
        return source.read(1, window=window, masked=True)


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}, "
      f"rasterio {version('rasterio')}")  # fmt: skip
print(f"box: {BOX}; publisher files: {BASE}/RP<T>/{TILE}_RP<T>_depth.tif (cache: {CACHE})")
files = [tries(f"RP{t} file", lambda t=t: download(t)) for t in PERIODS]
stack = np.ma.stack([publisher_window(f) for f in files])  # [period, row, column]
valid = ~np.ma.getmaskarray(stack) & np.isfinite(stack.filled(np.nan))
depth = np.where(valid, stack.filled(np.nan), np.nan)
knots = valid.sum(axis=0)
decreasing = np.zeros(knots.shape, dtype=bool)
last = np.full(knots.shape, -np.inf)
for layer in range(len(PERIODS)):
    decreasing |= valid[layer] & (depth[layer] < last)
    last = np.where(valid[layer], depth[layer], last)
dry, one = int((knots == 0).sum()), int((knots == 1).sum())
down = int(((knots >= 2) & decreasing).sum())
curves = int(((knots >= 2) & ~decreasing).sum())
flooded = knots.size - dry

print("call: JRC(product=JRC.Product.GLOFAS).select(area=Bounds(**BOX)).read()")
result = tries("crc-sdk read", lambda: JRC(product=JRC.Product.GLOFAS)
               .select(area=Bounds(**BOX)).read())  # fmt: skip
counts = result.report.counts
tiles = {s.split(":")[2] for s in result.table["support_id"].to_pylist()}
print("publisher's files, pixels touched by the box:")
print(f"  {'all':<44}{knots.size:>8}")
print(f"  {'dry (no depth at any return period)':<44}{dry:>8}")
print(f"  {'flooded, one depth only':<44}{one:>8}")
print(f"  {'flooded, depth lower at a longer period':<44}{down:>8}")
print(f"  {'flooded, a nondecreasing curve':<44}{curves:>8}")
print(
    f"crc-sdk: requested {counts.requested}, produced {counts.produced}, rows "
    f"{result.table.num_rows}, skipped {counts.skipped}; rows' tiles {sorted(tiles)}"
)
for d in result.report.diagnostics:
    print(f"  diagnostic {d.code} support_id={d.support_id}: {d.message}")
left_out = one + down
print(
    f"expected: {flooded} rows (every flooded pixel), or the {left_out} flooded pixels "
    "left out reported apart from the dry ones"
)
print(
    f"observed: {result.table.num_rows} rows; skipped {counts.skipped} = {dry} dry + {one} "
    f"one depth + {down} decreasing: {counts.skipped == dry + one + down}"
)
print(
    f"observed: flooded pixels left out: {left_out} of {flooded} "
    f"({100 * left_out / flooded:.1f}%), not named in the report"
)
ok = (
    counts.skipped == dry + one + down
    and result.table.num_rows == curves
    and left_out > 0
    and all(d.support_id is None for d in result.report.diagnostics)
)
print("REPRODUCED" if ok else "NOT REPRODUCED")
