"""Which calendar does each NEX-GDDP-CMIP6 model declare for its ``time`` coordinate?

crc-sdk 1.0.0 refuses a NEX source whose file calendar is not Gregorian
(``_climate_sampling.py`` ``_nex_source``, ~line 1815). This probe lists the models in the public
bucket, picks one file per model (historical, first member, ``tasmax``, year 2000, highest file
version), reads only the ``calendar`` and ``units`` attributes of ``time`` through HTTP range
requests (no whole-file download), decides accepted/refused with crc-sdk's own
``calendar_name`` rule, and runs two real crc-sdk reads on a tiny box to confirm the mapping.

    uv run --project /Users/yuri/work/crc/crc-lab python tools/probes/nex_calendars.py

No extra packages: ``h5py`` reads a small file object that fetches 1 MiB blocks by ranged GET with
``urllib`` (``fsspec``'s HTTP filesystem would need ``aiohttp``, which is not installed).
Only anonymous GET/HEAD requests go to the NASA bucket, with a generic User-Agent.
Output: data/cache/validation/probes/nex-calendars.json (git-ignored).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

BUCKET = "https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com"
ROOT = "NEX-GDDP-CMIP6/"
UA = "nex-calendar-probe/1.0"
BLOCK = 1 << 20
OUT = Path("/Users/yuri/work/crc/crc-lab/data/cache/validation/probes/nex-calendars.json")
SOURCE_REF = "crc_sdk/_climate_sampling.py:1815-1817 (_nex_source); mapping in _climate_grid.py:83"
FILE_RE = re.compile(r"_(\d{4})(?:_v(\d+(?:\.\d+)*))?\.nc$")
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def request(url: str, headers: dict[str, str] | None = None, method: str = "GET") -> Any:
    """One request with three tries and a growing pause; returns (body, response headers)."""
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url, method=method, headers={"User-Agent": UA} | (headers or {})
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as error:
            last = error
            if error.code in (403, 404):
                break
        except (OSError, TimeoutError) as error:
            last = error
        time.sleep(2.0 * attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def list_dir(prefix: str) -> tuple[list[str], list[str]]:
    """(sub-prefixes, keys) directly under prefix, following continuation tokens."""
    prefixes: list[str] = []
    keys: list[str] = []
    token = None
    while True:
        query = {"list-type": "2", "prefix": prefix, "delimiter": "/"}
        if token:
            query["continuation-token"] = token
        body, _ = request(f"{BUCKET}/?{urllib.parse.urlencode(query)}")
        root = ET.fromstring(body)
        prefixes += [e.text or "" for e in root.findall("s:CommonPrefixes/s:Prefix", NS)]
        keys += [e.text or "" for e in root.findall("s:Contents/s:Key", NS)]
        if root.findtext("s:IsTruncated", namespaces=NS) != "true":
            return sorted(prefixes), sorted(keys)
        token = root.findtext("s:NextContinuationToken", namespaces=NS)


class RangeFile:
    """Read-only seekable file over HTTP range requests, with a block cache."""

    def __init__(self, url: str) -> None:
        self.url, self.pos, self.blocks = url, 0, {}
        _, headers = request(url, method="HEAD")
        self.size = int(headers["Content-Length"])

    def _block(self, index: int) -> bytes:
        if index not in self.blocks:
            start = index * BLOCK
            end = min(start + BLOCK, self.size) - 1
            self.blocks[index], _ = request(self.url, {"Range": f"bytes={start}-{end}"})
        return self.blocks[index]

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = (offset, self.pos + offset, self.size + offset)[whence]
        return self.pos

    def read(self, size: int = -1) -> bytes:
        end = self.size if size is None or size < 0 else min(self.pos + size, self.size)
        out = bytearray()
        while self.pos < end:
            index, inner = divmod(self.pos, BLOCK)
            chunk = self._block(index)[inner : inner + end - self.pos]
            out += chunk
            self.pos += len(chunk)
        return bytes(out)

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        pass


def attr_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def pick(model: str) -> dict[str, Any]:
    """Choose the file for one model and read its time attributes."""
    row: dict[str, Any] = {"model": model}
    try:
        members, _ = list_dir(f"{ROOT}{model}/historical/")
        if not members:
            raise RuntimeError("no historical scenario or no member")
        member_prefix = members[0]
        row["member"] = member_prefix.rstrip("/").rsplit("/", 1)[-1]
        variables, _ = list_dir(member_prefix)
        names = [v.rstrip("/").rsplit("/", 1)[-1] for v in variables]
        variable = "tasmax" if "tasmax" in names else names[0]
        row["variable"] = variable
        _, keys = list_dir(f"{member_prefix}{variable}/")
        files: dict[int, list[tuple[tuple[int, ...], str]]] = {}
        for key in keys:
            match = FILE_RE.search(key)
            if match:
                ver = tuple(int(p) for p in (match.group(2) or "0").split("."))
                files.setdefault(int(match.group(1)), []).append((ver, key))
        if not files:
            raise RuntimeError("no annual files")
        year = 2000 if 2000 in files else min(files)
        key = max(files[year])[1]
        row["year"] = year
        row["file"] = key.rsplit("/", 1)[-1]
        row["url"] = f"{BUCKET}/{key}"
    except Exception as error:
        row["status"] = f"could not read: {error}"
        return row
    try:
        import h5py

        with h5py.File(RangeFile(row["url"]), "r") as handle:
            attrs = handle["time"].attrs
            row["calendar"] = attr_text(attrs.get("calendar"))
            row["units"] = attr_text(attrs.get("units"))
        row["status"] = "read"
    except Exception as error:
        row["status"] = f"could not read: {type(error).__name__}: {error}"
    return row


def decide(row: dict[str, Any]) -> bool | None:
    """True/False by crc-sdk's own rule; None when the file was not read."""
    if row["status"] != "read":
        return None
    from crc_sdk._climate_grid import calendar_name
    from crc_sdk._declarations import Calendar

    try:
        return calendar_name(row["calendar"]) in {Calendar.GREGORIAN, Calendar.PROLEPTIC_GREGORIAN}
    except ValueError:  # an unknown label is refused too (with a different message)
        return False


def sdk_read(row: dict[str, Any]) -> dict[str, Any]:
    """One real crc-sdk read of a 1 degree box for the model's file year."""
    from data_source_check.adapters.crc.nex import _run

    begin = time.monotonic()
    result = _run(
        {
            "bounds": [10.0, 45.0, 11.0, 46.0],
            "indicator": "annual_maximum_daily_maximum_temperature",
            "model": row["model"],
            "scenario": "historical",
            "member": row["member"],
            "year": row["year"],
        }
    )
    return {
        "model": row["model"],
        "calendar": row.get("calendar"),
        "predicted_accepted": row["accepted"],
        "error_type": result["error_type"],
        "error": result["error"][:300],
        "rows": len(result["rows"]),
        "seconds": round(time.monotonic() - begin, 1),
        "transport_retries": result["transport_retries"],
    }


def main() -> None:
    begin = time.monotonic()
    prefixes, _ = list_dir(ROOT)
    models = [p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(pick, models))
    for row in rows:
        row["accepted"] = decide(row)

    reads: list[dict[str, Any]] = []
    for want in (False, True):
        candidates = [r for r in rows if r["accepted"] is want and r.get("calendar")]
        if candidates:
            try:
                reads.append(sdk_read(candidates[0]))
            except Exception as error:
                reads.append({"model": candidates[0]["model"], "error": f"{error}"})

    totals = {
        "models_listed": len(rows),
        "read": sum(r["status"] == "read" for r in rows),
        "accepted": sum(r["accepted"] is True for r in rows),
        "refused": sum(r["accepted"] is False for r in rows),
        "could_not_read": sum(r["accepted"] is None for r in rows),
    }
    document = {
        "retrieved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "crc_sdk_version": version("crc-sdk"),
        "accepted_calendar_strings": ["standard", "gregorian", "proleptic_gregorian", None],
        "accepted_note": "a missing calendar attribute counts as 'standard' (CF default)",
        "source_reference": SOURCE_REF,
        "selection": "historical, first member, tasmax, year 2000, highest file version",
        "totals": totals,
        "sdk_confirmation_reads": reads,
        "models": [
            {
                "model": r["model"],
                "member": r.get("member"),
                "variable": r.get("variable"),
                "file": r.get("file"),
                "url": r.get("url"),
                "calendar": r.get("calendar"),
                "time_units": r.get("units"),
                "accepted": r["accepted"],
                "status": r["status"],
            }
            for r in rows
        ],
        "seconds": round(time.monotonic() - begin, 1),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    os.replace(temporary, OUT)

    print("| model | member | var | file | calendar | units | accepted |")
    print("|---|---|---|---|---|---|---|")
    for m in document["models"]:
        shown = m["calendar"] if m["status"] == "read" else m["status"]
        print(
            f"| {m['model']} | {m['member']} | {m['variable']} | {m['file']} | {shown} "
            f"| {m['time_units']} | {m['accepted']} |"
        )
    print(totals)
    for read in reads:
        print("sdk read:", read)
    print(f"seconds: {document['seconds']}", file=sys.stderr)


if __name__ == "__main__":
    main()
