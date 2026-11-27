"""Format name and version, and the JSON form of CRC diagnostics, shared by the documents."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import crc_framework as cf

FORMAT = "crc-event-loss"
FORMAT_VERSION = "0.1"


def header(kind: str) -> dict[str, str]:
    return {"format": FORMAT, "version": FORMAT_VERSION, "object": kind}


def check_header(document: Mapping[str, Any], kind: str) -> None:
    found = (document.get("format"), document.get("version"), document.get("object"))
    if found != (FORMAT, FORMAT_VERSION, kind):
        raise ValueError(f"expected a {FORMAT} {FORMAT_VERSION} {kind!r} document, found {found!r}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_plain(v) for v in value]
    return value


def diagnostic_to_dict(diagnostic: cf.Diagnostic) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "severity": diagnostic.severity.value,
        "path": diagnostic.path,
        "details": _plain(diagnostic.details),
    }


def diagnostic_from_dict(document: Mapping[str, Any]) -> cf.Diagnostic:
    return cf.Diagnostic(
        document["code"],
        document["message"],
        cf.DiagnosticSeverity(document["severity"]),
        document["path"],
        document["details"],
    )


def dumps(document: Mapping[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def info(code: str, message: str, path: str, **details: Any) -> cf.Diagnostic:
    return cf.Diagnostic(code, message, cf.DiagnosticSeverity.INFO, path, details)


def warning(code: str, message: str, path: str, **details: Any) -> cf.Diagnostic:
    return cf.Diagnostic(code, message, cf.DiagnosticSeverity.WARNING, path, details)
