"""NYC PLUTO (Department of City Planning): the tax lots of the study area's buildings (F6, CH-31).

Transformation statement:

1. The rows come from NYC Open Data ``64uk-42ks`` ("Primary Land Use Tax Lot Output (PLUTO)",
   version 26v3 when fetched) through its Socrata API, without a login. ``fetch`` asks only for
   the lots that the study area's building footprints lie on: every distinct ``mappluto_bbl``
   and ``base_bbl`` of the footprints of ``assets_oed.csv`` (the footprint layer's metadata names
   ``mappluto_bbl`` as the key to MapPLUTO; for a condominium it is the billing lot, while
   ``base_bbl`` is the lot the footprint stands on). The lots are asked ``CHUNK`` at a time with
   ``bbl in (...)`` and only the columns of ``COLUMNS``. Every answer is kept as returned under
   ``nyc-pluto/lots_<n>.json`` beside ``query.json`` (the addresses asked, the time, the size and
   sha256 of each file) and the dataset's metadata ``meta_64uk-42ks.json``. The data dictionary
   (``pluto_datadictionary.pdf``, November 2026, 26v3) is cached beside them
   by ``fetch_dictionary``.
2. ``read`` joins the pages into one frame, one row per lot, keyed by ``bbl`` as ten digits
   (the API writes ``3000030001.00000000``). Numbers stay as the table gives them; meanings are
   the dictionary's: ``numfloors`` is "for the tallest building on the tax lot" and empty means
   "not available" when the lot has buildings; ``bldgarea`` 0 means not available when
   ``numbldgs`` > 0; ``bsmtcode`` 5 means unknown.

PLUTO describes tax lots, not buildings. On a lot with several buildings its class, floors,
floor area and basement code are those of the lot (floors: of its tallest building).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.parse
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

DATASET = "64uk-42ks"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
METADATA = f"https://data.cityofnewyork.us/api/views/{DATASET}.json"
DICTIONARY = "https://s-media.nyc.gov/agencies/dcp/assets/files/pdf/data-tools/bytes/pluto_datadictionary.pdf"
FOLDER = "nyc-pluto"
CHUNK = 150
COLUMNS = (
    "bbl",
    "borough",
    "block",
    "lot",
    "address",
    "bldgclass",
    "landuse",
    "numbldgs",
    "numfloors",
    "bldgarea",
    "resarea",
    "comarea",
    "areasource",
    "unitsres",
    "unitstotal",
    "lotarea",
    "bsmtcode",
    "yearbuilt",
    "version",
)
NUMERIC = (
    "numbldgs",
    "numfloors",
    "bldgarea",
    "resarea",
    "comarea",
    "unitsres",
    "unitstotal",
    "lotarea",
    "yearbuilt",
)


def normal_bbl(value: Any) -> str:
    """A BBL as ten digits: ``3000030001.00000000``, ``3000030001`` and 3000030001.0 agree."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return ""


def _get(url: str) -> bytes:
    """One GET with curl (as ``sources.nyc_311``; Python's own TLS store fails here)."""
    for attempt in range(4):
        done = subprocess.run(  # noqa: S603
            ["curl", "-sS", "-L", "--fail", "--max-time", "180", "-A", "flood-lab/0.1", url],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if done.returncode == 0:
            return done.stdout
        if attempt == 3:
            raise OSError(f"curl {done.returncode}: {done.stderr.decode(errors='replace')}")
        time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_url(lots: list[str]) -> str:
    """The address asking for the given lots (ten-digit BBLs)."""
    where = "bbl in(" + ",".join(f"'{lot}.00000000'" for lot in lots) + ")"
    params = {"$select": ",".join(COLUMNS), "$where": where, "$limit": "50000"}
    return ENDPOINT + "?" + urllib.parse.urlencode(params)


def fetch(root: Path, lots: Iterable[str]) -> dict[str, Any]:
    """Statement step 1, over the network: the lots asked, the metadata; writes ``query.json``."""
    folder = Path(root) / FOLDER
    wanted = sorted({normal_bbl(lot) for lot in lots} - {""})
    files = []
    for n, start in enumerate(range(0, len(wanted), CHUNK), start=1):
        url = query_url(wanted[start : start + CHUNK])
        data = _get(url)
        json.loads(data)  # refuse anything that is not JSON
        name = f"lots_{n}.json"
        files.append(
            {
                "file": name,
                "url": url,
                "lots_asked": len(wanted[start : start + CHUNK]),
                "rows": len(json.loads(data)),
                "bytes": len(data),
                "sha256": _write(folder / name, data),
                "fetched_at": _now(),
            }
        )
    meta = _get(METADATA)
    meta_file = {
        "file": f"meta_{DATASET}.json",
        "url": METADATA,
        "bytes": len(meta),
        "sha256": _write(folder / f"meta_{DATASET}.json", meta),
        "fetched_at": _now(),
    }
    record = {
        "dataset": DATASET,
        "endpoint": ENDPOINT,
        "lots_asked": len(wanted),
        "rows": sum(f["rows"] for f in files),
        "files": files,
        "metadata": meta_file,
    }
    _write(folder / "query.json", json.dumps(record, indent=1).encode("utf-8"))
    return record


def fetch_dictionary(root: Path) -> dict[str, Any]:
    """Cache the PLUTO data dictionary PDF (statement step 1)."""
    data = _get(DICTIONARY)
    if not data.startswith(b"%PDF"):
        raise OSError(f"{DICTIONARY}: not a PDF")
    path = Path(root) / FOLDER / "pluto_datadictionary.pdf"
    return {"file": path.name, "url": DICTIONARY, "bytes": len(data), "sha256": _write(path, data)}


def read(root: Path) -> pd.DataFrame:
    """Statement step 2: one row per lot from the cached pages, ``bbl`` as ten digits."""
    folder = Path(root) / FOLDER
    record = json.loads((folder / "query.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for entry in record["files"]:
        rows += json.loads((folder / entry["file"]).read_text(encoding="utf-8"))
    return frame(rows)


def _cell(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Rows as the API returns them to a frame keyed by ten-digit ``bbl``; numbers as numbers."""
    table = pd.DataFrame(rows, columns=list(COLUMNS))
    table["bbl"] = table["bbl"].map(normal_bbl)
    for column in NUMERIC:
        table[column] = pd.to_numeric(table[column], errors="coerce").astype("Float64")
    for column in ("bldgclass", "landuse", "bsmtcode", "areasource", "version"):
        table[column] = [_cell(v) for v in table[column]]
    if table["bbl"].duplicated().any():
        raise ValueError("PLUTO: a lot appears twice")
    return table.set_index("bbl", drop=False)
