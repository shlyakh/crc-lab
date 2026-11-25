# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "crc-sdk[raster]==1.0.0", "crc-framework==1.0.0",
#   "rasterio<1.5.2; sys_platform == 'darwin'",
# ]
# ///
"""JRC GloFAS: for a file read by window, the recorded SHA-256 is not the publisher file's.

Expected (docs/data-licences.md): "A `ResourceIdentity` carries its URI and full content SHA-256
identity." Observed: two boxes inside the same publisher GeoTIFF get two different checksums for
that file, and neither equals the SHA-256 of the file as the publisher serves it. A file read
whole (tile_extents.geojson) is shown as a control. Real requests to the JRC server; the RP10 file
(~3.5 MB) is downloaded once to <temp dir>/glofas-repro.

    uv run crc_027_window_checksum.py
"""

import hashlib
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

from crc_sdk import JRC, Bounds

BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard"
FILE = "RP10/ID18_N40_W130_RP10_depth.tif"  # one GloFAS tile, return period 10 years
BOXES = (  # two small boxes near Fremont, California, both inside that tile
    dict(west=-122.10, south=37.50, east=-122.08, north=37.52),
    dict(west=-122.00, south=37.50, east=-121.98, north=37.52),
)
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


def sha256_of(name: str) -> str:
    path = CACHE / Path(name).name
    if not path.exists():
        headers = {"User-Agent": "repro-script/1.0"}
        request = urllib.request.Request(f"{BASE}/{name}", headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            data = response.read()
        CACHE.mkdir(exist_ok=True)
        path.with_suffix(".part").write_bytes(data)
        path.with_suffix(".part").replace(path)
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def recorded(box: dict) -> dict[str, str]:
    result = JRC(product=JRC.Product.GLOFAS).select(area=Bounds(**box)).read()
    return {r.uri.removeprefix(BASE + "/"): r.sha256 for r in result.metadata.source.resources}


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print("call: JRC(product=JRC.Product.GLOFAS).select(area=Bounds(**box)).read(), two boxes;")
print("      result.metadata.source.resources[*].uri and .sha256")
reads = [tries(f"crc-sdk read {i + 1}", lambda b=b: recorded(b)) for i, b in enumerate(BOXES)]
publisher = tries(FILE, lambda: sha256_of(FILE))
index = tries("tile_extents.geojson", lambda: sha256_of("tile_extents.geojson"))
window = [next((uri, sha) for uri, sha in r.items() if uri.startswith(FILE + "#")) for r in reads]
rows = [
    *window,
    (f"{FILE} (publisher's file, whole)", publisher),
    ("tile_extents.geojson (recorded by read 1)", reads[0]["tile_extents.geojson"]),
    ("tile_extents.geojson (publisher's file, whole)", index),
]
print("sha256 (first 16 hex)      resource")
for uri, sha in rows:
    print(f"{sha[:23]}...  {uri}")
print("expected: the SHA-256 recorded for the depth file is the publisher file's, in both reads")
same = window[0][1] == window[1][1]
hits = [sha == publisher for _, sha in window]
print(
    f"observed: the two reads record {'the same' if same else 'different'} checksums for "
    f"{FILE}; equal to the publisher file's: {hits}"
)
print(
    f"observed (control, file read whole): recorded == publisher: "
    f"{reads[0]['tile_extents.geojson'] == index}"
)
print("REPRODUCED" if not same and not any(hits) else "NOT REPRODUCED")
