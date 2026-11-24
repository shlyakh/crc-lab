"""NEX-GDDP-CMIP6 as crc-sdk 1.0 delivers it. The only place that calls ``crc_sdk.NEX``.

Each request runs in its own process, so that the same code can be pointed at another copy of
crc-sdk (a clone with a fix, through ``PYTHONPATH``) without touching the installed one, and
so that several requests can run side by side. crc-sdk 1.0 keeps its own cache of what it
acquired (``Cache.reuse``): the listing pages, the file header and the window it cut from each
file. The rows it returned are also stored by the caller.

crc-sdk reads a box from NASA's file by HTTP range requests of 1 MiB. NASA's files are stored
in chunks of one day by the whole globe, so a box of any size reads every chunk of the file:
about 240 requests per file. crc-sdk does not try a request again, and one dropped connection
ends the read. This process therefore tries each single HTTP request again on a connection
error (never on an answer from the server, such as a 404 or 412), up to ``ATTEMPTS`` times, and
counts the retries in the answer. crc-sdk's own checks on each range (status 206, the exact
``Content-Range``, ``If-Match`` on the ETag) are untouched.

    python -m data_source_check.adapters.crc.nex '<request as JSON>' <output file>
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import subprocess
import sys
import time
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

ATTEMPTS = 5
#: indicator name in crc-sdk 1.0 -> the recipe name crc-lab and crc-sdk 0.11 used
INDICATORS = {
    "annual_maximum_daily_precipitation": "rx1day",
    "annual_maximum_five_day_precipitation": "rx5day",
    "annual_maximum_daily_maximum_temperature": "txx",
    "annual_minimum_daily_minimum_temperature": "tnn",
}


def plain(value: Any, depth: int = 0) -> Any:
    """A crc-sdk object as JSON: dataclasses by field, enums by value, others as text."""
    if depth > 12:
        return repr(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [plain(v, depth + 1) for v in value]
    if hasattr(value, "to_json") and not isinstance(value, type):  # crc-framework objects
        try:
            return json.loads(value.to_json())
        except (TypeError, ValueError):
            return repr(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {"type": type(value).__name__}
        for field in dataclasses.fields(value):
            if not field.name.startswith("_"):
                out[field.name] = plain(getattr(value, field.name), depth + 1)
        return out
    slots = [s for s in getattr(type(value), "__slots__", ()) if not s.startswith("_")]
    if slots:
        return {"type": type(value).__name__} | {
            s: plain(getattr(value, s, None), depth + 1) for s in slots
        }
    return repr(value)


class _Buffered:
    """A response whose body was read whole, so that a reset can be retried."""

    def __init__(self, response: Any, body: bytes) -> None:
        self.status, self.headers, self.url = response.status, response.headers, response.url
        self.code = self.status
        self._body, self._at = body, 0

    def read(self, size: int = -1) -> bytes:
        end = len(self._body) if size is None or size < 0 else self._at + size
        chunk = self._body[self._at : end]
        self._at += len(chunk)
        return chunk

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        pass

    def __enter__(self) -> _Buffered:
        return self

    def __exit__(self, *_: object) -> None:
        pass


def _retrying(counter: dict[str, int]) -> Any:
    import http.client
    import urllib.error
    import urllib.request

    original = urllib.request.urlopen

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                with original(request, *args, **kwargs) as response:
                    return _Buffered(response, response.read())
            except urllib.error.HTTPError:
                raise  # an answer from the server is the result
            except (OSError, http.client.HTTPException):
                if attempt == ATTEMPTS:
                    raise
                counter["retries"] = counter.get("retries", 0) + 1
                time.sleep(2.0 * attempt)
        raise AssertionError("unreachable")

    urllib.request.urlopen = urlopen
    return original


def _rows(table: Any) -> list[dict[str, Any]]:
    from shapely import wkb

    out = []
    for row in table.to_pylist():
        geometry = row.pop("geometry", None)
        failure = row.pop("failure", None) or {}
        coverage = row.pop("coverage", None) or {}
        west, south, east, north = wkb.loads(geometry).bounds if geometry else (None,) * 4
        out.append(
            {k: plain(v) for k, v in row.items()}
            | {"west": west, "south": south, "east": east, "north": north,
               "failure_code": failure.get("code"), "failure_message": failure.get("message"),
               "valid": coverage.get("valid"), "expected": coverage.get("expected"),
               "minimum_fraction": coverage.get("minimum_fraction")}
        )  # fmt: skip
    return out


def _labels(result: Any) -> dict[str, Any]:
    """What the result says about itself, read from crc-sdk's metadata and report."""
    metadata = result.metadata
    variable = metadata.spec.variables[0] if metadata.spec.variables else None
    series = metadata.spec.series[0] if metadata.spec.series else None
    source = metadata.source
    out: dict[str, Any] = {
        "variable_id": None if variable is None else variable.id,
        "unit": None if variable is None else variable.measurement.unit.value,
        "measurement": None if variable is None else plain(variable.measurement),
        "scenario": None if series is None or series.scenario is None else series.scenario.id,
        "calendar": None if metadata.sampling is None else plain(metadata.sampling.calendar),
        "model": None if source is None else source.model,
        "member": None if source is None else source.member,
        "release_id": None if source is None or source.release is None else source.release.id,
        "unit_conversion": None,
        "reductions": [],
        "resources": [],
    }
    for item in metadata.provenance:
        name = type(item).__name__
        if name == "UnitConversion":
            fields = ("source_unit", "target_unit", "scale", "offset")
            out["unit_conversion"] = {k: plain(getattr(item, k, None)) for k in fields}
        elif name == "TemporalReduction":
            window = getattr(item, "window", None)
            out["reductions"].append({
                "operation": plain(item.operation), "coverage_fraction": item.coverage.fraction,
                "window": None if window is None else plain(window),
            })  # fmt: skip
    for resource in () if source is None else source.resources:
        fields = ("uri", "sha256", "license", "attribution", "retrieved_at")
        out["resources"].append({k: plain(getattr(resource, k, None)) for k in fields})
    report = result.report
    out["counts"] = plain(getattr(report, "counts", None))
    out["diagnostics"] = [d.code for d in getattr(report, "diagnostics", ())]
    return out


def _run(request: dict[str, Any], *, retry: bool = True) -> dict[str, Any]:
    """crc-sdk's answer for one request, in this process. Errors are recorded, not raised."""
    from importlib.metadata import version

    import crc_sdk
    from crc_sdk import NEX, Bounds, Cache, Period, Runtime

    out: dict[str, Any] = {
        "request": request,
        "crc_sdk_path": str(Path(crc_sdk.__file__).parent),
        "crc_sdk_version": version("crc-sdk"),
        "columns": [],
        "rows": [],
        "labels": {},
        "metadata": {},
        "report": {},
        "files_read": [],
        "error": "",
        "error_type": "",
        "warnings": [],
        "transport_retries": 0,
    }
    counter: dict[str, int] = {}
    original = _retrying(counter) if retry else None
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            west, south, east, north = request["bounds"]
            recipe = NEX(
                indicator=NEX.Indicator(request["indicator"]),
                model=request["model"],
                scenario=request["scenario"],
                member=request["member"],
            ).select(
                area=Bounds(west=west, south=south, east=east, north=north),
                time=Period.window(request["year"], request["year"]),
            )
            cache = request.get("cache")
            runtime = Runtime(cache=Cache.reuse(cache) if cache else Cache.ephemeral())
            result = recipe.read(runtime=runtime)
            out["columns"] = list(result.table.schema.names)
            out["rows"] = _rows(result.table)
            out["labels"] = _labels(result)
            out["metadata"] = plain(result.metadata)
            out["report"] = plain(result.report)
            source = result.metadata.source
            resources = () if source is None else source.resources
            out["files_read"] = sorted(
                {r.uri.split("#", 1)[0] for r in resources if "#crc-variable=" in r.uri}
            )
        out["warnings"] = sorted({f"{w.category.__name__}: {w.message}" for w in caught})
    except Exception as error:  # the error is the result: it is recorded, not hidden
        out["error"], out["error_type"] = str(error)[:4000], type(error).__name__
    finally:
        if original is not None:
            import urllib.request

            urllib.request.urlopen = original
        out["transport_retries"] = counter.get("retries", 0)
    return out


def annual(request: dict[str, Any], output: Path, *, crc_sdk_source: Path | None = None) -> None:
    """Run one request in a new process and write crc-sdk's answer to ``output``."""
    env = dict(os.environ)
    if crc_sdk_source is not None:
        env["PYTHONPATH"] = f"{crc_sdk_source}{os.pathsep}{env.get('PYTHONPATH', '')}"
    output.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [sys.executable, "-m", "data_source_check.adapters.crc.nex", json.dumps(request),
         str(output)],
        env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise RuntimeError(f"crc-sdk request failed to run: {done.stderr[-2000:]}")


if __name__ == "__main__":
    result = _run(json.loads(sys.argv[1]))
    temporary = Path(sys.argv[2] + ".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    os.replace(temporary, sys.argv[2])
