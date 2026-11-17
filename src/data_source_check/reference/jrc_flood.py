"""JRC flood hazard maps (GloFAS, EFAS) read from the publisher's GeoTIFF files.

This is the independent side of the comparison. It imports neither the framework under test
nor rasterio or GDAL, which the framework reads the same files with: the TIFF container is
parsed here with ``struct`` and its tiles are inflated with ``zlib``. numpy holds the arrays
and does the arithmetic; h3 and shapely are used for the cell rule only, by a different route
than the framework's (an overlap test of each pixel's box against the boundaries of nearby
cells, where the framework asks h3 to fill a polygon).

The rules applied to the values are fields of ``Rules`` so that a test can make one of them
deliberately wrong.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import time
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

USER_AGENT = "data-source-check"
ROOT = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata"

#: Where each dataset is published, and how its depth files are laid out.
DATASETS: dict[str, dict[str, str]] = {
    "glofas": {"base": f"{ROOT}/CEMS-GLOFAS/flood_hazard", "layout": "tiled"},
    "efas": {"base": f"{ROOT}/CEMS-EFAS/flood_hazard", "layout": "continental"},
}
Bounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class Rules:
    """The rules of the transformation statement, as the reference applies them."""

    nodata_is_missing: bool = True  # a pixel equal to the file's nodata value has no depth
    minimum_knots: int = 4  # depths needed for a curve
    touched_pixels: bool = True  # a window holds every pixel the bounds touch
    reduced_variate: bool = True  # the fit is linear in -ln(-ln(1 - 1/T))
    cells_overlapping: bool = True  # a pixel belongs to every cell its box overlaps
    edge_epsilon: float = 1e-9  # pixels; a bound this close to a pixel edge adds no pixel


# ---------------------------------------------------------------------------- downloads
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open(url: str, *, method: str = "GET", attempts: int = 4) -> Any:
    """Open ``url``; a request that times out or is cut is tried again after a pause."""
    for attempt in range(attempts):
        request = Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            return urlopen(request, timeout=120)  # noqa: S310
        except HTTPError:
            raise
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


def _get(url: str) -> Any:
    return _open(url)


def fetch(url: str, path: Path, *, live: bool) -> dict[str, Any]:
    """Download ``url`` whole (``live``, if not held) or reuse the copy; return its provenance.

    A copy is never downloaded twice: its checksum, size and the publisher's headers are kept
    in a file beside it and compared with the bytes on every use.
    """
    sidecar = path.with_name(path.name + ".json")
    if path.exists() and sidecar.exists():
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if path.stat().st_size != record["bytes"]:
            raise RuntimeError(f"the reference copy {path.name} has changed on disk")
        return record
    if not live:
        raise FileNotFoundError(f"no reference copy of {url}; run with --live")
    path.parent.mkdir(parents=True, exist_ok=True)
    headers: dict[str, str] = {}
    if not path.exists():
        temporary = path.with_name(path.name + ".part")
        with _get(url) as response, temporary.open("wb") as target:
            headers = {k.lower(): v for k, v in response.headers.items()}
            for chunk in iter(lambda: response.read(1 << 20), b""):
                target.write(chunk)
        os.replace(temporary, path)
        retrieved = datetime.now(UTC)
    else:  # fetched before its record was written: ask the publisher for the headers only
        with _open(url, method="HEAD") as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
        if int(headers.get("content-length", -1)) != path.stat().st_size:
            raise RuntimeError(f"{path.name} is not the size the publisher states")
        retrieved = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    record = {
        "url": url,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "retrieved_at": retrieved.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "last_modified": headers.get("last-modified", ""),
        "etag": headers.get("etag", ""),
    }
    temporary = sidecar.with_name(sidecar.name + ".tmp")
    temporary.write_text(json.dumps(record, indent=1), encoding="utf-8")
    os.replace(temporary, sidecar)
    return record


def listing(url: str) -> list[dict[str, str]]:
    """Names, dates and sizes in one of the publisher's directory pages."""
    with _get(url.rstrip("/") + "/") as response:
        html = response.read().decode("utf-8", "replace")
    rows = re.findall(
        r'href="([^"?/][^"]*)"[^<]*</a></td><td[^>]*>([^<]*)</td><td[^>]*>([^<]*)</td>', html
    )
    return [{"name": n, "modified": m.strip(), "size": s.strip()} for n, m, s in rows]


class Copy:
    """The publisher's files of one dataset, held whole in a folder with their checksums."""

    def __init__(
        self, dataset: str, cache: Path, *, live: bool, folder: Path | None = None
    ) -> None:
        """``folder``: a local folder laid out as the publisher's, read in place (tests)."""
        self.dataset, self.live, self.local = dataset, live, folder is not None
        self.base = folder.resolve().as_uri() if folder else DATASETS[dataset]["base"]
        self.layout = DATASETS[dataset]["layout"]
        self.root = folder if folder else cache / "original" / dataset
        self.used: dict[str, dict[str, Any]] = {}

    def file(self, name: str) -> Path:
        """The local path of ``name`` (relative to the dataset's address), fetched if needed."""
        path = self.root / name
        if self.local:
            if name not in self.used:
                moment = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                self.used[name] = {
                    "url": f"{self.base}/{name}", "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                    "retrieved_at": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
                }  # fmt: skip
            return path
        self.used[name] = fetch(f"{self.base}/{name}", path, live=self.live)
        return path

    def text(self, name: str) -> str:
        return self.file(name).read_text(encoding="utf-8", errors="replace")

    def index(self) -> dict[str, Any]:
        """The publisher's directory page, kept so that a run without the network repeats."""
        if self.local:

            def rows(folder: Path) -> list[dict[str, str]]:
                return [{"name": p.name + ("/" if p.is_dir() else ""), "modified": "", "size": ""}
                        for p in sorted(folder.iterdir())]  # fmt: skip

            top = rows(self.root)
            folders = {row["name"].rstrip("/"): rows(self.root / row["name"])
                       for row in top if re.fullmatch(r"RP\d+/", row["name"])}  # fmt: skip
            return {"retrieved_at": "", "top": top, "folders": folders}
        path = self.root / "listing.json"
        if self.live:
            top = listing(self.base)
            folders = {
                row["name"].rstrip("/"): listing(f"{self.base}/{row['name']}")
                for row in top
                if re.fullmatch(r"RP\d+/", row["name"])
            }
            payload = {
                "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "top": top,
                "folders": folders,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, path)
        elif not path.exists():
            raise FileNotFoundError(f"no stored directory page of {self.dataset}; run with --live")
        return json.loads(path.read_text(encoding="utf-8"))

    def provenance(self, names: Iterable[str] | None = None) -> dict[str, Any]:
        """Address, combined checksum and size of the files used (or of ``names``)."""
        chosen = sorted(self.used if names is None else names)
        digest = hashlib.sha256()
        for name in chosen:
            digest.update(f"{name}\0{self.used[name]['sha256']}\n".encode())
        times = [self.used[name]["retrieved_at"] for name in chosen]
        return {
            "url": self.base,
            "files": len(chosen),
            "bytes": sum(self.used[name]["bytes"] for name in chosen),
            "sha256": digest.hexdigest() if chosen else "",
            "sha256_of": "the list of file names and their sha256",
            "retrieved_at": max(times, default=""),
        }


# ---------------------------------------------------------------------------- what is published
def version(readme: str) -> str:
    """The release the publisher's README states ("G01. Dataset version X")."""
    found = re.search(r"^G01\.\s*Dataset version\s+([0-9][0-9.]*[0-9])", readme, re.MULTILINE)
    return found.group(1) if found else ""


def stated(readme: str) -> dict[str, str]:
    """The README's own statements that the assessment quotes."""
    out = {}
    for key, name in (("A02", "licence"), ("D01", "coverage"), ("D02", "resolution"),
                      ("D10", "units"), ("D12", "projection"), ("A01", "citation")):  # fmt: skip
        found = re.search(rf"^{key}\.[^:]*:\s*(.*)$", readme, re.MULTILINE)
        out[name] = found.group(1).strip() if found else ""
    return out


def periods(index: dict[str, Any], layout: str) -> list[int]:
    """The return periods the publisher's directory holds depth files for."""
    if layout == "tiled":
        return sorted(int(name[2:]) for name in index["folders"])
    names = [row["name"] for row in index["top"]]
    return sorted(
        int(m.group(1))
        for n in names
        if (m := re.fullmatch(r"Europe_RP(\d+)_filled_depth\.tif", n))
    )


def depth_name(layout: str, period: int, tile: str = "") -> str:
    if layout == "tiled":
        return f"RP{period}/{tile}_RP{period}_depth.tif"
    return f"Europe_RP{period}_filled_depth.tif"


def tiles_for(index_geojson: dict[str, Any], bounds: Sequence[float]) -> list[str]:
    """Tiles of the publisher's tile index whose extent meets the box (touching counts)."""
    west, south, east, north = bounds
    out = []
    for feature in index_geojson["features"]:
        ring = feature["geometry"]["coordinates"][0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        if min(xs) <= east and max(xs) >= west and min(ys) <= north and max(ys) >= south:
            properties = feature["properties"]
            out.append(f"ID{properties['id']}_{properties['name']}")
    return out


# ---------------------------------------------------------------------------- the TIFF container
_TYPES = {1: "B", 2: "c", 3: "H", 4: "I", 5: "II", 6: "b", 7: "B", 8: "h", 9: "i", 10: "ii",
          11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}  # fmt: skip
_TAGS = {256: "width", 257: "height", 258: "bits", 259: "compression", 262: "photometric",
         273: "strip_offsets", 277: "samples", 278: "rows_per_strip", 279: "strip_counts",
         284: "planar", 317: "predictor", 322: "tile_width", 323: "tile_height",
         324: "tile_offsets", 325: "tile_counts", 339: "sample_format", 33550: "pixel_scale",
         33922: "tiepoint", 34264: "transformation", 34735: "geo_keys", 34737: "geo_ascii",
         42113: "nodata"}  # fmt: skip


class TiffError(ValueError):
    """The file is not a TIFF this reader understands; nothing is guessed."""


def decode_block(
    raw: bytes, compression: int, dtype: np.dtype, rows: int, width: int
) -> np.ndarray:
    """One tile or strip of a TIFF as an array: inflated if deflated, then read as numbers."""
    if compression != 1:
        raw = zlib.decompress(raw)
    return np.frombuffer(raw, dtype=dtype, count=rows * width).reshape(rows, width)


class Tiff:
    """One single-band GeoTIFF: classic or BigTIFF, tiles or strips, deflate or plain."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("rb")
        head = self._file.read(16)
        if head[:2] not in (b"II", b"MM"):
            raise TiffError(f"{path.name}: not a TIFF")
        self.order = "<" if head[:2] == b"II" else ">"
        magic = struct.unpack(self.order + "H", head[2:4])[0]
        if magic == 42:
            self.big, first = False, struct.unpack(self.order + "I", head[4:8])[0]
        elif magic == 43:
            self.big, first = True, struct.unpack(self.order + "Q", head[8:16])[0]
        else:
            raise TiffError(f"{path.name}: unknown TIFF version {magic}")
        self.tags = self._directory(first)
        self._check()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Tiff:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _directory(self, offset: int) -> dict[str, Any]:
        count_format, entry_size, inline = ("Q", 20, 8) if self.big else ("H", 12, 4)
        self._file.seek(offset)
        size = struct.calcsize(count_format)
        count = struct.unpack(self.order + count_format, self._file.read(size))[0]
        block = self._file.read(count * entry_size)
        tags: dict[str, Any] = {}
        for at in range(0, len(block), entry_size):
            tag, kind = struct.unpack(self.order + "HH", block[at : at + 4])
            if tag not in _TAGS:
                continue
            if kind not in _TYPES:
                raise TiffError(f"{self.path.name}: tag {tag} has unknown type {kind}")
            number = struct.unpack(
                self.order + ("Q" if self.big else "I"), block[at + 4 : at + 4 + inline]
            )[0]
            unit = _TYPES[kind]
            width = struct.calcsize("=" + unit) * number
            raw = block[at + 4 + inline : at + 4 + 2 * inline]
            if width > inline:
                where = struct.unpack(self.order + ("Q" if self.big else "I"), raw)[0]
                self._file.seek(where)
                raw = self._file.read(width)
            if kind == 2:
                tags[_TAGS[tag]] = raw[:width].split(b"\0", 1)[0].decode("ascii", "replace")
            else:
                dtype = np.dtype(self.order + {"II": "u4", "ii": "i4"}.get(unit, unit))
                values = np.frombuffer(raw[:width], dtype=dtype)
                tags[_TAGS[tag]] = values[0].item() if len(values) == 1 else values
        return tags

    def _check(self) -> None:
        tags = self.tags
        name = self.path.name
        if tags.get("samples", 1) != 1:
            raise TiffError(f"{name}: more than one band")
        if tags.get("compression", 1) not in (1, 8, 32946):
            raise TiffError(f"{name}: compression {tags.get('compression')} is not handled")
        if tags.get("predictor", 1) != 1:
            raise TiffError(f"{name}: predictor {tags.get('predictor')} is not handled")
        kind = {(3, 32): "f4", (3, 64): "f8", (1, 8): "u1", (1, 16): "u2", (2, 16): "i2",
                (2, 32): "i4", (1, 32): "u4"}.get(
            (tags.get("sample_format", 1), tags.get("bits")))  # fmt: skip
        if kind is None:
            raise TiffError(f"{name}: sample format is not handled")
        self.dtype = np.dtype(self.order + kind)
        self.width, self.height = int(tags["width"]), int(tags["height"])
        if "tile_offsets" in tags:
            self.block_width, self.block_height = int(tags["tile_width"]), int(tags["tile_height"])
            self._offsets, self._counts = tags["tile_offsets"], tags["tile_counts"]
        elif "strip_offsets" in tags:
            self.block_width = self.width
            self.block_height = min(int(tags.get("rows_per_strip", self.height)), self.height)
            self._offsets, self._counts = tags["strip_offsets"], tags["strip_counts"]
        else:
            raise TiffError(f"{name}: neither tiles nor strips")
        self._offsets = np.atleast_1d(self._offsets)
        self._counts = np.atleast_1d(self._counts)
        self.tiled = "tile_offsets" in tags
        self.across = math.ceil(self.width / self.block_width)
        if "pixel_scale" not in tags or "tiepoint" not in tags:
            raise TiffError(f"{name}: no pixel scale and tie point")
        scale, tie = tags["pixel_scale"], tags["tiepoint"]
        if len(tie) != 6 or tie[0] != 0 or tie[1] != 0:
            raise TiffError(f"{name}: the tie point is not the upper-left corner")
        #: x of the left edge, width of a pixel, y of the top edge, height of a pixel (degrees)
        self.left, self.dx = float(tie[3]), float(scale[0])
        self.top, self.dy = float(tie[4]), float(scale[1])
        text = str(tags.get("nodata", "")).strip()
        self.nodata: float | None = float(text) if text else None
        self.geographic = self._geographic()

    def _geographic(self) -> dict[str, Any]:
        """Model type and geographic code from the GeoKey directory (1024 and 2048)."""
        keys = self.tags.get("geo_keys")
        out: dict[str, Any] = {}
        if keys is None:
            return out
        for at in range(4, len(keys), 4):
            key, location, _, value = (int(v) for v in keys[at : at + 4])
            if location == 0 and key in (1024, 1025, 2048, 3072):
                out[{1024: "model", 1025: "raster", 2048: "geographic", 3072: "projected"}[key]] = (
                    value
                )
        return out

    @property
    def bounds(self) -> Bounds:
        """West, south, east, north edges of the grid."""
        return (self.left, self.top - self.height * self.dy,
                self.left + self.width * self.dx, self.top)  # fmt: skip

    def _block(self, number: int) -> np.ndarray:
        rows = self.block_height
        if not self.tiled:  # the last strip may be short
            rows = min(self.block_height, self.height - number * self.block_height)
        count = int(self._counts[number])
        if count == 0:  # a block that was never written holds nodata
            fill = self.nodata if self.nodata is not None else 0
            return np.full((rows, self.block_width), fill, dtype=self.dtype)
        self._file.seek(int(self._offsets[number]))
        raw = self._file.read(count)
        return decode_block(
            raw, int(self.tags.get("compression", 1)), self.dtype, rows, self.block_width
        )

    def block_bytes(self, number: int) -> bytes:
        """One tile or strip as stored in the file (compressed)."""
        self._file.seek(int(self._offsets[number]))
        return self._file.read(int(self._counts[number]))

    def read(self, window: tuple[int, int, int, int] | None = None) -> np.ndarray:
        """Pixels of ``window`` (first column, first row, end column, end row), as stored."""
        c0, r0, c1, r1 = window or (0, 0, self.width, self.height)
        if not (0 <= c0 < c1 <= self.width and 0 <= r0 < r1 <= self.height):
            raise ValueError(f"window {window} is outside {self.path.name}")
        out = np.empty((r1 - r0, c1 - c0), dtype=self.dtype)
        for block_row in range(r0 // self.block_height, (r1 - 1) // self.block_height + 1):
            top = block_row * self.block_height
            for block_col in range(c0 // self.block_width, (c1 - 1) // self.block_width + 1):
                left = block_col * self.block_width
                block = self._block(block_row * self.across + block_col)
                rows = slice(max(r0, top), min(r1, top + block.shape[0]))
                cols = slice(max(c0, left), min(c1, left + block.shape[1]))
                out[rows.start - r0 : rows.stop - r0, cols.start - c0 : cols.stop - c0] = block[
                    rows.start - top : rows.stop - top, cols.start - left : cols.stop - left
                ]
        return out

    def window(
        self, bounds: Sequence[float], rules: Rules | None = None
    ) -> tuple[int, int, int, int] | None:
        """The pixel window of a WGS84 box, or None where the box misses the grid."""
        rules = rules or Rules()
        west, south, east, north = bounds
        c0, c1 = (west - self.left) / self.dx, (east - self.left) / self.dx
        r0, r1 = (self.top - north) / self.dy, (self.top - south) / self.dy
        if rules.touched_pixels:
            e = rules.edge_epsilon
            first_col, first_row = math.floor(c0 + e), math.floor(r0 + e)
            end_col = max(first_col + 1, math.ceil(c1 - e))
            end_row = max(first_row + 1, math.ceil(r1 - e))
        else:  # the wrong rule: pixels whose centre is inside the box
            first_col, first_row = round(c0), round(r0)
            end_col, end_row = round(c1), round(r1)
        first_col, first_row = max(0, first_col), max(0, first_row)
        end_col, end_row = min(self.width, end_col), min(self.height, end_row)
        if first_col >= end_col or first_row >= end_row:
            return None
        return first_col, first_row, end_col, end_row

    def describe(self) -> dict[str, Any]:
        return {
            "width": self.width, "height": self.height, "dtype": self.dtype.str,
            "tiled": self.tiled, "block": [self.block_width, self.block_height],
            "compression": int(self.tags.get("compression", 1)),
            "nodata": self.nodata, "pixel_degrees": [self.dx, self.dy],
            "bounds": list(self.bounds), "geographic": self.geographic,
            "big_tiff": self.big,
        }  # fmt: skip


# ---------------------------------------------------------------------------- depths and curves
def depths(stack: np.ndarray, nodata: float | None, rules: Rules | None = None) -> np.ndarray:
    """Depths as float64 with NaN where the publisher gives none."""
    rules = rules or Rules()
    out = stack.astype(np.float64)
    missing = ~np.isfinite(out)
    if nodata is not None and rules.nodata_is_missing:
        missing |= stack == np.asarray(nodata, dtype=stack.dtype)
    out[missing] = np.nan
    return out


def reduced_variate(return_periods: Sequence[float], rules: Rules | None = None) -> np.ndarray:
    """The Gumbel reduced variate of each return period: -ln(-ln(1 - 1/T))."""
    rules = rules or Rules()
    periods_ = np.asarray(return_periods, dtype=np.float64)
    if not rules.reduced_variate:  # the wrong rule: linear in ln(T)
        return np.log(periods_)
    return -np.log(-np.log(1.0 - 1.0 / periods_))


def fit(
    return_periods: Sequence[float], values: np.ndarray, rules: Rules | None = None
) -> dict[str, np.ndarray]:
    """Least-squares Gumbel curve per pixel through its depths at the source return periods.

    ``values`` has one row per return period and one column per pixel, NaN where there is no
    depth. A Gumbel quantile is ``location + scale * y`` with ``y`` the reduced variate, so
    the least-squares fit is a straight line through (y, depth). A pixel gets a curve when it
    has at least ``minimum_knots`` depths and they are not all equal.
    """
    rules = rules or Rules()
    y = reduced_variate(return_periods, rules)[:, None]
    held = np.isfinite(values)
    knots = held.sum(axis=0)
    v = np.where(held, values, 0.0)
    yy = np.where(held, y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_y, mean_v = yy.sum(axis=0) / knots, v.sum(axis=0) / knots
        dy_ = np.where(held, y - mean_y, 0.0)
        dv = np.where(held, values - mean_v, 0.0)
        scale = (dy_ * dv).sum(axis=0) / (dy_ * dy_).sum(axis=0)
        location = mean_v - scale * mean_y
    low = np.where(held, values, np.inf).min(axis=0)
    high = np.where(held, values, -np.inf).max(axis=0)
    increasing = np.ones(values.shape[1], dtype=bool)
    last = np.full(values.shape[1], -np.inf)
    for row in range(values.shape[0]):
        here = held[row]
        increasing &= ~here | (values[row] >= last)
        last = np.where(here, values[row], last)
    return {
        "knots": knots,
        "enough": knots >= rules.minimum_knots,
        "constant": (knots > 0) & (low == high),
        "lowest": low,
        "increasing": increasing,
        "location": location,
        "scale": scale,
    }


def quantile(location: np.ndarray, scale: np.ndarray, return_period: float) -> np.ndarray:
    """Depth of the fitted curve at a return period."""
    return location + scale * float(-math.log(-math.log(1.0 - 1.0 / return_period)))


# ---------------------------------------------------------------------------- cells
def pixel_box(tiff: Tiff, row: int, column: int) -> Bounds:
    west = tiff.left + column * tiff.dx
    north = tiff.top - row * tiff.dy
    return west, north - tiff.dy, west + tiff.dx, north


def cells_of_box(box: Sequence[float], resolution: int, rules: Rules | None = None) -> list[int]:
    """H3 cells a pixel belongs to: every cell whose boundary overlaps the pixel's box.

    Candidates are the cells of the box's corners, edge midpoints and centre and their
    neighbours within two rings; each is kept when its boundary polygon and the box share
    area (longitude and latitude taken as plane coordinates).
    """
    import h3
    from shapely.geometry import Polygon
    from shapely.geometry import box as rectangle

    rules = rules or Rules()
    west, south, east, north = box
    mid_x, mid_y = (west + east) / 2, (south + north) / 2
    if not rules.cells_overlapping:  # the wrong rule: the cell of the pixel's centre only
        return [h3.str_to_int(h3.latlng_to_cell(mid_y, mid_x, resolution))]
    points = [(x, y) for x in (west, mid_x, east) for y in (south, mid_y, north)]
    candidates: set[str] = set()
    for x, y in points:
        candidates.update(h3.grid_disk(h3.latlng_to_cell(y, x, resolution), 2))
    pixel = rectangle(west, south, east, north)
    out = []
    for cell in candidates:
        boundary = Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)])
        if boundary.intersection(pixel).area > 0:
            out.append(h3.str_to_int(cell))
    return sorted(out)
