"""IBTrACS as crc-sdk 1.0 delivers it. The only place that calls ``crc_sdk.IBTrACS``."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: crc-sdk's cache modes, by the names this project uses
MODES = ("refresh", "reuse", "offline")


@dataclass
class Reading:
    """What one complete read gave: its columns, the rows (consumed once), and, after the
    rows are exhausted, the metadata and report crc-sdk attached."""

    columns: list[str]
    types: list[str]
    rows: Iterator[dict[str, Any]]
    after: dict[str, Any] = field(default_factory=dict)


def _runtime(cache_dir: Path, mode: str) -> Any:
    from crc_sdk import Cache, Runtime

    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    return Runtime(cache=getattr(Cache, mode)(cache_dir))


def _identity(source: Any) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "provider": source.provider,
        "product": source.product,
        "member": source.member,
        "release_id": None if source.release is None else source.release.id,
        "release_sha256": None if source.release is None else source.release.sha256,
        "resources": [
            {
                "uri": resource.uri,
                "sha256": resource.sha256,
                "license": resource.license,
                "attribution": resource.attribution,
                "retrieved_at": None
                if resource.retrieved_at is None
                else resource.retrieved_at.isoformat(),
                "retrieved_at_has_zone": resource.retrieved_at is not None
                and resource.retrieved_at.utcoffset() is not None,
            }
            for resource in source.resources
        ],
    }


def _variables(metadata: Any) -> list[dict[str, Any]]:
    out = []
    for variable in metadata.spec.variables:
        measurement = variable.measurement
        out.append(
            {
                "id": variable.id,
                "quantity": getattr(measurement, "quantity", None),
                "unit": str(getattr(measurement, "unit", "")),
                "fields": dict(getattr(measurement, "fields", None) or {}),
                "label": variable.label,
            }
        )
    return out


def _batch_provenance(schema: Any) -> dict[str, Any]:
    """What a batch's own schema metadata says about the source, read as JSON."""
    raw = dict(schema.metadata or {})
    keys = sorted(key.decode() for key in raw)
    text = raw.get(b"crc.evidence", b"").decode()
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "uri" in value and "sha256" in value:
                found.append({k: value.get(k) for k in ("uri", "sha256", "license", "attribution")})
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    if text:
        walk(json.loads(text))
    unique = [dict(t) for t in {tuple(sorted(r.items())) for r in found}]
    return {"schema_metadata_keys": keys, "resources_in_batch_metadata": unique}


def read(
    agency: str,
    cache_dir: Path,
    *,
    mode: str,
    consume: Callable[[Reading], Any],
) -> tuple[Any, dict[str, Any]]:
    """Read every row crc-sdk gives for one agency, by default (no selection), and hand
    them to ``consume``. Returns what ``consume`` returned and what crc-sdk attached."""
    from crc_sdk import IBTrACS

    recipe = IBTrACS(agency=IBTrACS.Agency(agency))
    with recipe.batches(runtime=_runtime(cache_dir, mode)) as stream:
        batches = iter(stream)
        first = next(batches, None)
        schema = [] if first is None else list(first.schema)
        names = [f.name for f in schema]
        types = [str(f.type) for f in schema]
        first_batch = {} if first is None else _batch_provenance(first.schema)

        def rows() -> Iterator[dict[str, Any]]:
            if first is None:
                return
            yield from first.to_pylist()
            for batch in batches:
                yield from batch.to_pylist()

        reading = Reading(names, types, rows())
        result = consume(reading)
        for _ in reading.rows:  # whatever consume left unread
            pass
    metadata, report = stream.metadata, stream.report
    after = {
        "source": _identity(metadata.source),
        "report_sources": [_identity(s) for s in report.source_identities],
        "variables": _variables(metadata),
        "report": {
            "complete": report.complete,
            "valid": report.valid,
            "produced": report.counts.produced,
            "no_data": report.counts.no_data,
            "diagnostics": [str(d) for d in report.diagnostics],
        },
        "first_batch": first_batch,
    }
    return result, after
