"""The flood lab's record format (requirement FG2).

Every check writes one JSON record: what went in (with checksums), the software that ran, the
parameters with their source tags, the numbers produced and whether each rule passed. Pages and
reports are generated from records and never typed.
"""

from __future__ import annotations

import hashlib
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from lab_common.io import write_json_atomic

SCHEMA = "flood_lab/0.1"
#: source tags of requirements section 4
TAGS = ("S", "I", "P", "V")
#: outcomes of a comparison or a fact, as in docs/validation/method.md
OUTCOMES = ("confirmed", "differs", "not checked", "not applicable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def software(*extra: str) -> dict[str, str]:
    """Versions of the pinned CRC packages, Python and any other distribution named."""
    found = {"python": platform.python_version()}
    for name in ("crc-sdk", "crc-framework", *extra):
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "not installed"
    return found


@dataclass(frozen=True)
class Input:
    path: str
    sha256: str
    bytes: int
    url: str = ""

    @classmethod
    def of(cls, path: Path, *, root: Path, url: str = "") -> Input:
        return cls(str(path.relative_to(root)), sha256_file(path), path.stat().st_size, url)


@dataclass(frozen=True)
class Parameter:
    name: str
    value: Any
    tag: str
    source: str = ""

    def __post_init__(self) -> None:
        if self.tag not in TAGS:
            raise ValueError(f"tag must be one of {TAGS}, got {self.tag!r}")
        if self.tag == "S" and not self.source:
            raise ValueError(f"parameter {self.name!r} is tagged [S] and names no source")


@dataclass(frozen=True)
class Check:
    """One rule with its verdict. ``proposed`` marks a threshold that is a starting value."""

    name: str
    rule: str
    passed: bool | None
    value: Any = None
    threshold: Any = None
    proposed: bool = False
    note: str = ""


@dataclass
class Record:
    id: str
    stage: str
    title: str
    inputs: list[Input] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, Any] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    software: dict[str, str] = field(default_factory=software)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool | None:
        """True when every rule passed; None when a rule could not be judged; else False."""
        verdicts = [check.passed for check in self.checks]
        if any(verdict is False for verdict in verdicts):
            return False
        if any(verdict is None for verdict in verdicts):
            return None
        return True

    def document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            **asdict(self),
            "passed": self.passed,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def write(self, folder: Path) -> Path:
        path = folder / f"{self.id}.json"
        write_json_atomic(path, self.document(), indent=1, sort_keys=True, default=str)
        return path
