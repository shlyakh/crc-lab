"""Second readers of the flood lab's sources (requirement FS4).

Each module here recomputes, by a route of its own, the values a loader under ``sources/``
produces, so that an error in either shows up as a difference when ``compare`` puts the two side
by side. The modules share no code with the loaders and never import crc-sdk, crc-framework or any
``flood_lab`` subpackage other than ``domain``, ``cache`` and ``paths`` (FG1).

* ``nyc_flood_maps``: the city's stormwater flood maps, polygon by polygon, and their depth
  classes on the project grid by point-in-polygon tests of the cell centres (no rasteriser);
* ``floodnet``: the FloodNet event and sensor tables with the standard library's ``csv``,
  ``datetime`` and ``zoneinfo`` (no pandas);
* ``groundsource``: the Groundsource Parquet file through DuckDB with its GeoParquet
  interpretation switched off, then exact intersection with shapely;
* ``mrms``: one event window of the MRMS radar rainfall, decoded from the GRIB2 files with
  ecCodes (no GDAL) and compared cell by cell with the loaded NetCDF;
* ``compare``: pure comparisons of grids and tables, and the outcome of FS4.

Every reader module has a ``main`` that runs it on the cached publisher's files and writes its
output under ``$FLOOD_CACHE/f2/reference-scratch/``:

    FLOOD_CACHE=... uv run python -m flood_lab.reference.nyc_flood_maps
"""

from __future__ import annotations

import json
import os
import resource
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import cache

SCRATCH = ("f2", "reference-scratch")


def scratch_dir() -> Path:
    """``$FLOOD_CACHE/f2/reference-scratch/``, the only place in the cache these readers write."""
    path = cache.root().joinpath(*SCRATCH)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_atomic(path: Path, write: Callable[[Path], None]) -> None:
    """Call ``write`` on a temporary file beside ``path``, then move it into place.

    The temporary file keeps the destination's suffix, so that writers which choose a format by
    the name (numpy's ``savez``) write the right one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    try:
        write(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, value: Any) -> None:
    """Write ``value`` as indented JSON, atomically."""

    def _write(tmp: Path) -> None:
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")

    write_atomic(path, _write)


def write_json_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write one JSON object per line, atomically; bytes are written as hexadecimal text."""

    def _default(value: Any) -> Any:
        if isinstance(value, bytes | bytearray):
            return value.hex()
        return str(value)

    def _write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, default=_default) + "\n")

    write_atomic(path, _write)


def peak_memory_bytes() -> int:
    """Peak resident memory of this process so far (``ru_maxrss``: bytes on macOS, KiB on Linux)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)
