# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk[raster]==1.1.0", "crc-framework==1.1.0", "rasterio<1.5.2; sys_platform == 'darwin'"]
# ///
"""Does GDAL_HTTP_MAX_RETRY / GDAL_HTTP_RETRY_DELAY make a remote raster read survive a dropped
connection or a 503? Offline: a local HTTP server with range support serves a constructed GeoTIFF
and fails chosen request numbers, either by closing the connection without an answer ("drop") or
by answering 503. Each trial uses a fresh URL path so GDAL's cache does not help.
Options as crc-sdk 1.1.0 passes them (crc_sdk/_climate_io.py _gdal_options) with and without the two
retry options.
"""

import http.server
import itertools
import socket
import sys
import tempfile
import threading
from importlib.metadata import version
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

DATA = Path(tempfile.mkdtemp(prefix="gdal-retry-")) / "x.tif"
profile = dict(driver="GTiff", width=2048, height=2048, count=1, dtype="float32", crs="EPSG:4326",
               transform=from_origin(-100, 40, 0.001, 0.001), tiled=True, blockxsize=256, blockysize=256)
with rasterio.open(DATA, "w", **profile) as dst:
    dst.write(np.arange(2048 * 2048, dtype="float32").reshape(1, 2048, 2048))
BYTES = DATA.read_bytes()
STATE = {"n": 0, "fail": set(), "mode": "drop", "log": []}
LOCK = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _serve(self, body: bool):
        with LOCK:
            STATE["n"] += 1
            n = STATE["n"]
        failing = n in STATE["fail"]
        STATE["log"].append((n, self.command, self.headers.get("Range"), "FAIL" if failing else "ok"))
        if failing and STATE["mode"] == "drop":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        if failing:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng:
            a, b = rng.removeprefix("bytes=").split("-")
            a, b = int(a), min(int(b), len(BYTES) - 1)
            chunk = BYTES[a:b + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(BYTES)}")
        else:
            chunk = BYTES
            self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        if body:
            self.wfile.write(chunk)

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]
counter = itertools.count()
BASE = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
RETRY = {"GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_RETRY_DELAY": "0.2"}


def trial(mode: str, fail: set[int], options: dict) -> str:
    STATE.update(n=0, fail=fail, mode=mode, log=[])
    url = f"/vsicurl/http://127.0.0.1:{PORT}/t{next(counter)}/x.tif"
    try:
        with rasterio.Env(**options), rasterio.open(url) as src:
            a = src.read(1, window=Window(512, 512, 512, 512))
        ok = bool(np.array_equal(a, np.arange(2048 * 2048, dtype="float32").reshape(2048, 2048)[512:1024, 512:1024]))
        return f"read OK (values correct: {ok}), requests: {STATE['n']}"
    except Exception as error:  # noqa: BLE001
        return f"FAILED {type(error).__name__}: {str(error)[:110]}, requests: {STATE['n']}"


print(f"crc-sdk {version('crc-sdk')}, rasterio {rasterio.__version__}, GDAL {rasterio.__gdal_version__}")
print("control, no failure:", trial("drop", set(), BASE), STATE["log"])
print("drop first, crc-sdk options:", trial("drop", {1}, BASE), STATE["log"])
print("drop third, crc-sdk options:", trial("drop", {3}, BASE), STATE["log"])
print("503 third, crc-sdk options:", trial("503", {3}, BASE), STATE["log"])
for mode in ("drop", "503"):
    for fail, where in (({1}, "first request"), ({2}, "second request (first data range)"), ({3}, "third request")):
        for name, opts in (("crc-sdk options", BASE), ("+ MAX_RETRY=3, RETRY_DELAY=0.2", {**BASE, **RETRY})):
            print(f"{mode:4} at {where:34} {name:32} -> {trial(mode, fail, opts)}")
server.shutdown()
sys.exit(0)
