"""Source facts (requirements FS6, FS7): one TOML file per source in ``src/flood_lab/facts/``.

Each file names the source, the stage in which its facts were read from the primary source, the
level of check it gets, and one ``[[fact]]`` per fact with what the requirements claim, what the
primary source says, and an outcome. ``load`` reads one file and refuses a file that breaks a rule;
the data cards and the gallery are generated from what it returns.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .records import OUTCOMES

#: the facts every source must have (FS6), in the order the cards and the gallery show them
REQUIRED = (
    "identifier",
    "address",
    "licence",
    "fields",
    "coverage_space",
    "coverage_time",
    "release",
    "checksum",
)
LEVELS = ("facts", "facts and second reader")
#: how an outcome "confirmed" is worded when the requirements made no claim to confirm
READ = "read, no claim"
#: a second reader's record, once written: ``site/flood/tests/records/second-reader-<id>.json``
SECOND_READER_PREFIX = "second-reader-"

_SOURCE_KEYS = (
    "id",
    "title",
    "publisher",
    "checked_on",
    "stage",
    "level",
    "second_reader_stage",
    "used_for",
    "known_biases",
)
_FACT_KEYS = (
    "name",
    "claimed",
    "observed",
    "outcome",
    "source_url",
    "passage",
    "note",
    "verdict_note",
)
_FILE_KEYS = ("path", "url", "bytes", "sha256", "fetched_at")


@dataclass(frozen=True)
class Fact:
    name: str
    claimed: str
    observed: str
    outcome: str
    source_url: str
    passage: str
    note: str = ""
    verdict_note: str = ""

    @property
    def required(self) -> bool:
        return self.name in REQUIRED

    @property
    def shown(self) -> str:
        """The outcome as cards and the gallery word it.

        "confirmed" is kept for a claim of the requirements that the source bears out. A fact
        the requirements make no claim about was read from the source, not confirmed against
        anything, and is shown as ``READ``. The stored outcome stays one of the four.
        """
        if self.outcome == "confirmed" and not self.claimed.strip():
            return READ
        return self.outcome


@dataclass(frozen=True)
class File:
    """A file fetched from the source; ``path`` is relative to ``data/cache/flood/``."""

    path: str
    url: str
    bytes: int
    sha256: str
    fetched_at: str


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    publisher: str
    checked_on: str
    stage: str
    level: str
    second_reader_stage: str
    used_for: tuple[str, ...]
    known_biases: str
    facts: tuple[Fact, ...]
    files: tuple[File, ...] = ()

    def fact(self, name: str) -> Fact | None:
        return next((fact for fact in self.facts if fact.name == name), None)

    @property
    def further(self) -> tuple[Fact, ...]:
        """Facts beyond the required ones, in file order."""
        return tuple(fact for fact in self.facts if not fact.required)

    @property
    def differs(self) -> tuple[Fact, ...]:
        return tuple(fact for fact in self.facts if fact.outcome == "differs")


def _fault(path: Path, message: str) -> ValueError:
    return ValueError(f"{path.name}: {message}")


def _text(table: dict[str, Any], key: str, path: Path, where: str) -> str:
    value = table.get(key, "")
    if not isinstance(value, str):
        raise _fault(path, f"{where}: {key!r} must be text, got {type(value).__name__}")
    return value


def _unknown_keys(table: dict[str, Any], known: tuple[str, ...], path: Path, where: str) -> None:
    extra = sorted(set(table) - set(known))
    if extra:
        raise _fault(path, f"{where}: unknown key(s) {', '.join(extra)}")


def _fact(table: Any, path: Path, index: int) -> Fact:
    if not isinstance(table, dict):
        raise _fault(path, f"fact {index + 1} is not a table")
    name = _text(table, "name", path, f"fact {index + 1}").strip()
    if not name:
        raise _fault(path, f"fact {index + 1} has no name")
    where = f"fact {name!r}"
    _unknown_keys(table, _FACT_KEYS, path, where)
    fact = Fact(**{key: _text(table, key, path, where) for key in _FACT_KEYS} | {"name": name})
    if fact.outcome not in OUTCOMES:
        raise _fault(
            path, f"{where}: unknown outcome {fact.outcome!r}; use one of {', '.join(OUTCOMES)}"
        )
    if fact.outcome in ("confirmed", "differs"):
        if not fact.source_url.strip():
            raise _fault(path, f"{where}: outcome {fact.outcome!r} needs a source_url")
        if not fact.passage.strip():
            raise _fault(path, f"{where}: outcome {fact.outcome!r} needs a passage")
    if fact.outcome == "differs" and not fact.observed.strip():
        raise _fault(path, f"{where}: outcome 'differs' needs what was observed")
    return fact


def _file(table: Any, path: Path, index: int) -> File:
    where = f"file {index + 1}"
    if not isinstance(table, dict):
        raise _fault(path, f"{where} is not a table")
    _unknown_keys(table, _FILE_KEYS, path, where)
    size = table.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise _fault(path, f"{where}: 'bytes' must be a whole number of bytes")
    values = {key: _text(table, key, path, where) for key in _FILE_KEYS if key != "bytes"}
    if (
        not values["path"]
        or Path(values["path"]).is_absolute()
        or ".." in Path(values["path"]).parts
    ):
        raise _fault(path, f"{where}: 'path' must be relative to data/cache/flood/")
    return File(bytes=size, **values)


def load(path: Path) -> Source:
    """Read and check one facts file; a broken file raises ``ValueError`` naming file and fault."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise _fault(path, f"not valid TOML ({error})") from error
    _unknown_keys(data, (*_SOURCE_KEYS, "fact", "file"), path, "source")
    for key in ("id", "title", "publisher", "checked_on", "stage", "level"):
        if not _text(data, key, path, "source").strip():
            raise _fault(path, f"source: {key!r} is missing or empty")
    if data["id"] != path.stem:
        raise _fault(path, f"source: id {data['id']!r} does not match the file name")
    if data["level"] not in LEVELS:
        raise _fault(
            path, f"unknown level {data['level']!r}; use one of {', '.join(map(repr, LEVELS))}"
        )
    second = _text(data, "second_reader_stage", path, "source").strip()
    if data["level"] == "facts and second reader" and not second:
        raise _fault(path, "level 'facts and second reader' needs a second_reader_stage")
    used_for = data.get("used_for", [])
    if not isinstance(used_for, list) or not all(isinstance(item, str) for item in used_for):
        raise _fault(path, "source: 'used_for' must be a list of requirement ids")
    facts = tuple(_fact(table, path, i) for i, table in enumerate(data.get("fact", [])))
    names = [fact.name for fact in facts]
    twice = sorted({name for name in names if names.count(name) > 1})
    if twice:
        raise _fault(path, f"duplicate fact name(s): {', '.join(twice)}")
    missing = [name for name in REQUIRED if name not in names]
    if missing:
        raise _fault(path, f"required fact(s) missing: {', '.join(missing)}")
    files = tuple(_file(table, path, i) for i, table in enumerate(data.get("file", [])))
    return Source(
        id=data["id"],
        title=data["title"],
        publisher=data["publisher"],
        checked_on=data["checked_on"],
        stage=data["stage"],
        level=data["level"],
        second_reader_stage=second,
        used_for=tuple(used_for),
        known_biases=_text(data, "known_biases", path, "source"),
        facts=facts,
        files=files,
    )


def load_all(folder: Path = paths.FACTS) -> list[Source]:
    """Every facts file in the folder, sorted by id; an absent folder has none."""
    if not folder.is_dir():
        return []
    return [load(path) for path in sorted(folder.glob("*.toml"))]


def summary(source: Source) -> dict[str, int]:
    """How many facts have each outcome, every outcome named (zero included)."""
    counts = dict.fromkeys(OUTCOMES, 0)
    for fact in source.facts:
        counts[fact.outcome] += 1
    return counts


def read_without_claim(source: Source) -> int:
    """How many facts count as confirmed but had no claim in the requirements to confirm."""
    return sum(1 for fact in source.facts if fact.shown == READ)


def second_reader(source: Source, records: Path = paths.RECORDS) -> dict[str, Any] | None:
    """The second reader's record for this source (FS4), when one has been written."""
    path = records / f"{SECOND_READER_PREFIX}{source.id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def facts_words(source: Source) -> str:
    """The facts' outcomes in words: "facts confirmed" only when none differs or is unread."""
    counts = summary(source)
    read = read_without_claim(source)
    if counts["differs"] == 0 and counts["not checked"] == 0:
        return "facts confirmed" + (f" ({read} read with no claim)" if read else "")
    numbers = (
        (counts["confirmed"] - read, "confirmed"),
        (read, "read with no claim"),
        (counts["differs"], "differ"),
        (counts["not checked"], "not checked"),
    )
    parts = [f"{number} {word}" for number, word in numbers if number]
    return "facts checked: " + ", ".join(parts)


def level_words(source: Source, records: Path = paths.RECORDS) -> str:
    """The level named in the words of FS7, with the facts' outcomes."""
    words = facts_words(source)
    if source.level == "facts":
        return words
    record = second_reader(source, records)
    if record is None:
        return (
            f"{words}; values to be recomputed by a second reader in {source.second_reader_stage}"
        )
    verdict = {True: "passed", False: "failed", None: "not judged"}[record.get("passed")]
    return f"{words}; values recomputed by a second reader in {record['stage']} ({verdict})"
