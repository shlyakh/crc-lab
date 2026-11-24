"""GHCNh as crc-sdk 1.0 delivers it. The only place that calls ``crc_sdk.GHCNh``.

What is read is the default output of an annual indicator: ``GHCNh(indicator=...)`` selected by
station and observation years, then ``read()``. Nothing is fitted; ``fit(...)`` is not called.
"""

from __future__ import annotations

import dataclasses
import json
import struct
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

INDICATORS = (
    "annual_maximum_daily_maximum_temperature",
    "annual_minimum_daily_minimum_temperature",
)
#: tries per station when the download fails part-way (crc-sdk does not retry; the files
#: already in its cache are kept, so a second try continues where the first stopped)
ATTEMPTS = 4


def _runtime(cache_dir: Path, *, live: bool) -> Any:
    from crc_sdk import Cache, Runtime

    cache_dir.mkdir(parents=True, exist_ok=True)
    return Runtime(cache=Cache.reuse(cache_dir) if live else Cache.offline(cache_dir))


def _recipe(indicator: str, fraction: float | None) -> Any:
    from crc_sdk import Coverage, GHCNh

    member = GHCNh.Indicator(indicator)
    if fraction is None:
        return GHCNh(indicator=member)
    return GHCNh(indicator=member, coverage=Coverage.minimum_fraction(fraction))


def defaults() -> dict[str, Any]:
    """The rule values crc-sdk holds, for the record (the reference keeps its own copy).

    The source lists and the licence text are private names in 1.0; a name that is gone is
    recorded as such instead of stopping the run.
    """
    from crc_sdk import Coverage

    found: dict[str, Any] = {"coverage_default": Coverage.complete().fraction}
    try:
        from crc_sdk import _observed_decoders as decoders
        from crc_sdk import _observed_sources as sources
    except ImportError as error:  # pragma: no cover - only if upstream renames the modules
        return found | {"private_names": f"not found: {error}"}
    for key, module, name in (
        ("quality_codes", decoders, "_GHCN_ACCEPTED"),
        ("sources_for_5", decoders, "_GHCN_ISD_SOURCES"),
        ("sources_for_1", decoders, "_GHCN_SOURCES"),
        ("licence", sources, "_NOAA_TERMS"),
        ("attribution", sources, "_NOAA_ATTRIBUTION"),
    ):
        value = getattr(module, name, None)
        found[key] = sorted(value) if isinstance(value, set | frozenset) else value
    return found


def catalogue(
    bounds: Sequence[float], years: tuple[int, int], cache_dir: Path, *, live: bool
) -> list[dict[str, Any]]:
    """Stations crc-sdk's inventory selects for a box (the station list only, no payload)."""
    from crc_sdk import Bounds, Period

    west, south, east, north = bounds
    inventory = (
        _recipe(INDICATORS[0], None)
        .select(
            area=Bounds(west=west, south=south, east=east, north=north),
            time=Period.window(*years),
        )
        .inspect(runtime=_runtime(cache_dir, live=live))
    )
    return [
        {
            "station": station.id,
            "name": station.label,
            "longitude": station.longitude,
            "latitude": station.latitude,
        }
        for station in inventory.stations
    ]


def _position(geometry: bytes) -> tuple[float, float]:
    """Longitude and latitude of a little-endian WKB point."""
    order, kind, lon, lat = struct.unpack("<BIdd", geometry)
    if (order, kind) != (1, 1):
        raise ValueError("support geometry is not a little-endian WKB point")
    return lon, lat


def _row(record: dict[str, Any]) -> dict[str, Any]:
    lon, lat = _position(record["geometry"])
    coverage = record["coverage"] or {}
    failure = record["failure"] or {}
    return {
        "station": record["station_id"],
        "year": int(record["time"]),
        "variable_id": record["variable_id"],
        "support_id": record["support_id"],
        "longitude": lon,
        "latitude": lat,
        "cell_id": int(record["cell_id"]),
        "valid_days": coverage.get("valid"),
        "expected_days": coverage.get("expected"),
        "minimum_fraction": coverage.get("minimum_fraction"),
        "value": record["value"],
        "failure": failure.get("code", ""),
    }


def _metadata(result: Any) -> dict[str, Any]:
    """What the output's metadata states about itself, from its JSON document."""
    document = json.loads(result.metadata.to_json())
    spec = document.get("spec", {})
    return {
        "kind": document.get("kind"),
        "variables": spec.get("variables"),
        "series": spec.get("series"),
        "sampling": document.get("sampling"),
        "provenance": document.get("provenance"),
        "source": {
            key: (document.get("source") or {}).get(key)
            for key in ("provider", "product", "release")
        },
    }


def _resources(result: Any) -> list[dict[str, Any]]:
    source = result.metadata.source
    return [
        {
            "uri": item.uri,
            "sha256": item.sha256,
            "license": item.license,
            "attribution": item.attribution,
            "retrieved_at": "" if item.retrieved_at is None else item.retrieved_at.isoformat(),
        }
        for item in ([] if source is None else source.resources)
    ]


def annual(
    indicator: str,
    stations: Sequence[str],
    years: tuple[int, int],
    cache_dir: Path,
    *,
    live: bool,
    fraction: float | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """crc-sdk's annual samples, one read per station; a station whose read raises is reported.

    ``fraction`` None is the default ``Coverage``; otherwise ``Coverage.minimum_fraction``.
    """
    from crc_sdk import Period, UnavailableStationYear

    runtime = _runtime(cache_dir, live=live)
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    unavailable: list[tuple[str, int]] = []
    counts: dict[str, int] = {}
    diagnostics: dict[str, int] = {}
    resources: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {}
    for station in stations:
        recipe = _recipe(indicator, fraction).select(stations=[station], time=Period.window(*years))
        for attempt in range(ATTEMPTS):
            try:
                result = recipe.read(runtime=runtime)
                break
            except ValueError as error:  # crc-sdk refuses the station's data
                result = None
                errors[station] = f"{type(error).__name__}: {error}"
                break
            except OSError as error:  # a reset or a timeout part-way through a download
                if not live or attempt == ATTEMPTS - 1:
                    raise
                log(f"crc-sdk: {station}: {error}; trying again")
                time.sleep(5 * (attempt + 1))
        if result is None:
            continue
        rows += [_row(record) for record in result.table.to_pylist()]
        for field in dataclasses.fields(result.report.counts):
            value = int(getattr(result.report.counts, field.name))
            counts[field.name] = counts.get(field.name, 0) + value
        for item in result.report.diagnostics:
            diagnostics[item.code] = diagnostics.get(item.code, 0) + 1
            if isinstance(item, UnavailableStationYear):
                unavailable.append((item.station_id, item.year))
        for item in _resources(result):
            resources[item["uri"]] = item
        metadata = metadata or _metadata(result)
    return {
        "rows": rows,
        "errors": errors,
        "unavailable": sorted(unavailable),
        "counts": counts,
        "diagnostics": dict(sorted(diagnostics.items())),
        "resources": [resources[uri] for uri in sorted(resources)],
        "metadata": metadata,
    }
