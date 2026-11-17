"""Downloads kept on disk with a record of where they came from (shared by the fetchers).

Every stored response ``name`` has a sidecar ``name.json`` holding its url, sha256, size and
retrieval time, as ``reference.jrc_flood.fetch`` does. A response is never downloaded twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "data-source-check/0.1"
Bounds = tuple[float, float, float, float]


def now() -> str:
    """The current time in UTC, to the second, as ISO 8601 with a Z."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def box_key(bounds: Bounds) -> str:
    """A folder name for a box: its west, south, east and north edges."""
    west, south, east, north = bounds
    return f"w{west:g}_s{south:g}_e{east:g}_n{north:g}"


def url_of(base: str, params: dict[str, Any] | None = None) -> str:
    """``base`` with ``params`` as a query string (commas kept readable)."""
    if not params:
        return base
    return f"{base}?{urlencode(params, safe=',')}"


def get(
    url: str, *, attempts: int = 3, timeout: float = 120, pause: float = 5
) -> tuple[bytes, dict[str, str]]:
    """Body and lower-cased headers of ``url``; a timed-out or cut request is tried again.

    An HTTP error status is raised at once (``urllib.error.HTTPError``), not retried.
    """
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.read(), headers
        except HTTPError:
            raise
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause * (attempt + 1))
    raise AssertionError("unreachable")


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to a temporary file beside ``path``, then move it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    write_atomic(path, json.dumps(payload, indent=1).encode("utf-8"))


def sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".json")


def stored(path: Path) -> dict[str, Any] | None:
    """The record of a stored response, or None when it is not held whole."""
    side = sidecar(path)
    if not (path.exists() and side.exists()):
        return None
    record = json.loads(side.read_text(encoding="utf-8"))
    if path.stat().st_size != record["bytes"]:
        raise RuntimeError(f"the stored copy {path.name} has changed on disk")
    return record


def store(
    url: str,
    path: Path,
    *,
    live: bool,
    check: Callable[[bytes], None] | None = None,
    attempts: int = 3,
    timeout: float = 120,
) -> dict[str, Any]:
    """Download ``url`` to ``path`` (``live``, if not held) or reuse the copy; return its record.

    ``check`` sees the body before it is kept and raises to refuse it (an error reply sent
    with status 200, for example); a refused body is not written.
    """
    record = stored(path)
    if record is not None:
        return record
    if not live:
        raise FileNotFoundError(f"no stored copy of {url}; run with --live")
    started = time.monotonic()
    body, headers = get(url, attempts=attempts, timeout=timeout)
    if check is not None:
        check(body)
    write_atomic(path, body)
    record = {
        "url": url,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "retrieved_at": now(),
        "seconds": round(time.monotonic() - started, 2),
        "last_modified": headers.get("last-modified", ""),
        "etag": headers.get("etag", ""),
    }
    write_json(sidecar(path), record)
    return record


def manifest(path: Path, *, live: bool) -> dict[str, Any] | None:
    """A finished fetch's manifest; None when a live run must (re)build it."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not live:
        raise FileNotFoundError(f"no stored fetch at {path.parent}; run with --live")
    return None
