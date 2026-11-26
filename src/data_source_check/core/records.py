"""The record format: sources, transformation steps, check records and findings.

Everything the page and the reports show is generated from these records. The vocabulary
is fixed here and explained in ``docs/validation/method.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

SCHEMA = "data_source_check/0.1"

#: What a source hands to its user.
SOURCE_KINDS = (
    "pass-through",  # the publisher's records, reformatted only
    "annual samples",  # reduced to annual values, no fit
    "fitted curves",  # reduced and fitted by the framework
    "pre-fitted release",  # curves fitted elsewhere and published by the framework's owner
    "user data",  # not an upstream source
)
TIERS = (1, 2, 3)
#: Outcome of one transformation step or one check.
OUTCOMES = ("confirmed", "differs", "not checked", "not applicable")
#: Progress of each assessment tier for a source.
TIER_STATUS = ("not assessed", "in progress", "assessed", "not possible")
ASSESSMENT_TIERS = ("exploration", "verification", "validation")
#: Check categories, after the Copernicus C3S quality assessments.
CATEGORIES = (
    "completeness",
    "consistency",
    "extremes",
    "resolution",
    "timeliness",
    "uncertainty",
    "validation",
    "fidelity",  # agreement with the publisher's original (tier 2); not a C3S category
)
FINDING_KINDS = ("defect", "doc-code difference", "observation")
#: "fixed": a run on ``fixed_in`` shows the behaviour gone. "no longer applies": the feature the
#: finding is about was removed in ``closed_in``. "superseded": the issue changed shape in
#: ``closed_in`` and continues as the finding ``superseded_by``.
FINDING_STATUS = (
    "open",
    "reported upstream",
    "fixed",
    "by design",
    "no longer applies",
    "superseded",
)
#: statuses that end a finding; it stays in the register and on the page
CLOSED_STATUS = ("fixed", "by design", "no longer applies", "superseded")
#: How a finding is known.
BASIS = ("reproduced", "code reading")


class RecordError(ValueError):
    """A record does not follow the format."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def _one_of(value: Any, allowed: tuple[Any, ...], name: str) -> None:
    _require(value in allowed, f"{name} must be one of {allowed}, got {value!r}")


def _iso_date(value: str, name: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise RecordError(f"{name} must be an ISO date, got {value!r}") from error


#: keys of a source's ``[monitoring]`` table
MONITORING_KEYS = ("rewritten_in_place", "reason", "rerun_after_days")


def _validate_monitoring(table: dict[str, Any], name: str) -> None:
    """``rewritten_in_place`` (file names or glob patterns, matched against the last part of
    each address), ``reason`` (why, in a sentence) and optionally ``rerun_after_days``."""
    extra = sorted(set(table) - set(MONITORING_KEYS))
    _require(not extra, f"{name}: unknown keys {extra}; allowed {MONITORING_KEYS}")
    files = table.get("rewritten_in_place")
    _require(
        isinstance(files, list | tuple) and bool(files)
        and all(isinstance(item, str) and item and "/" not in item for item in files),
        f"{name}.rewritten_in_place must be a non-empty list of file names or patterns",
    )  # fmt: skip
    reason = table.get("reason")
    _require(isinstance(reason, str) and bool(reason.strip()), f"{name}.reason is empty")
    days = table.get("rerun_after_days")
    _require(
        days is None or (type(days) is int and days > 0),
        f"{name}.rerun_after_days must be a positive whole number of days, got {days!r}",
    )


@dataclass(frozen=True)
class Step:
    """One thing the framework does between the publisher's bytes and its output."""

    id: str
    text: str
    code_ref: str = ""
    outcome: str = "not checked"
    note: str = ""  # why a step is not checked, or what the outcome does not cover

    def validate(self) -> None:
        _require(bool(self.id and self.text), "a step needs an id and a text")
        _one_of(self.outcome, OUTCOMES, "step outcome")


@dataclass(frozen=True)
class Source:
    """One entry of the inventory."""

    id: str
    framework: str
    title: str
    kind: str
    publisher: str
    original: str
    purpose: str
    tier: int | None
    tier_reason: str
    entry_points: tuple[str, ...]
    symbols: tuple[str, ...] = ()
    #: the framework version that removed this source; it then has no entry point
    removed_in: str = ""
    options: dict[str, tuple[str, ...]] = field(default_factory=dict)
    assessed_options: dict[str, tuple[str, ...]] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    statement: tuple[Step, ...] = ()
    notes: str = ""
    #: address of a view of this source in a data explorer, relative to the page; empty if none
    explorer: str = ""
    #: for the summary of an assessment: what the framework's output holds that the publisher's
    #: data do not, and how the assessment compares the two (plain sentences, written by hand)
    adds: str = ""
    compared: str = ""
    #: who or what wrote the draft, e.g. "agent (draft-source-assessment skill), 2026-11-12"
    drafted_by: str = ""
    reviewed_by: str = ""
    reviewed_on: str = ""
    #: set by a person: files the publisher rewrites in place at the same address (the
    #: ``[monitoring]`` table). A new copy of such a file is reported, not failed on.
    monitoring: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("id", "framework", "title", "publisher", "original", "purpose"):
            _require(bool(getattr(self, name)), f"source {self.id!r}: {name} is empty")
        _one_of(self.kind, SOURCE_KINDS, f"source {self.id!r}: kind")
        if self.kind == "user data":
            _require(self.tier is None, f"source {self.id!r}: user data has no tier")
        else:
            _one_of(self.tier, TIERS, f"source {self.id!r}: tier")
            _require(bool(self.tier_reason), f"source {self.id!r}: tier_reason is empty")
        _require(
            bool(self.entry_points) != bool(self.removed_in),
            f"source {self.id!r}: an entry point, or the version that removed the source",
        )
        _require(
            set(self.status) == set(ASSESSMENT_TIERS),
            f"source {self.id!r}: status needs exactly {ASSESSMENT_TIERS}",
        )
        for tier, value in self.status.items():
            _one_of(value, TIER_STATUS, f"source {self.id!r}: status.{tier}")
        for name, values in self.assessed_options.items():
            extra = set(values) - set(self.options.get(name, ()))
            _require(not extra, f"source {self.id!r}: assessed {name} {sorted(extra)} not offered")
        for step in self.statement:
            step.validate()
        _require(
            bool(self.reviewed_by) == bool(self.reviewed_on),
            f"source {self.id!r}: reviewed_by and reviewed_on go together",
        )
        if self.reviewed_on:
            _iso_date(self.reviewed_on, f"source {self.id!r}: reviewed_on")
        if self.monitoring:
            _validate_monitoring(self.monitoring, f"source {self.id!r}: monitoring")

    @property
    def is_draft(self) -> bool:
        return not self.reviewed_by

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["draft"] = self.is_draft
        return out


@dataclass(frozen=True)
class Finding:
    """Something the framework does that its user should know, worded neutrally."""

    id: str
    source: str
    kind: str
    title: str
    documented: str  # what the documentation says, with its reference ("" if silent)
    observed: str  # what the code or the data shows
    evidence: tuple[str, ...]  # file:line references or record ids
    basis: str
    status: str
    found_on: str
    framework_version: str
    consequence: str = ""
    upstream_ref: str = ""  # issue or pull request, once reported
    fixed_in: str = ""
    closed_in: str = ""  # version from which the finding no longer applies or is superseded
    superseded_by: str = ""  # id of the finding that continues this one
    note: str = ""  # how the status was established (the run, the probe)

    @property
    def status_text(self) -> str:
        if self.status == "fixed":
            return f"fixed in {self.fixed_in}"
        if self.status == "no longer applies":
            return f"no longer applies from {self.closed_in}"
        if self.status == "superseded":
            return f"superseded by {self.superseded_by} from {self.closed_in}"
        return self.status

    def validate(self) -> None:
        _require(bool(self.id and self.source and self.title), "a finding needs id, source, title")
        _one_of(self.kind, FINDING_KINDS, f"finding {self.id}: kind")
        _one_of(self.basis, BASIS, f"finding {self.id}: basis")
        _one_of(self.status, FINDING_STATUS, f"finding {self.id}: status")
        _require(bool(self.observed), f"finding {self.id}: observed is empty")
        _require(bool(self.evidence), f"finding {self.id}: no evidence")
        _iso_date(self.found_on, f"finding {self.id}: found_on")
        if self.kind == "doc-code difference":
            _require(bool(self.documented), f"finding {self.id}: documented is empty")
        if self.status == "reported upstream":
            _require(bool(self.upstream_ref), f"finding {self.id}: reported without a reference")
        if self.status == "fixed":
            _require(bool(self.fixed_in), f"finding {self.id}: fixed without a version")
        if self.status in ("no longer applies", "superseded"):
            _require(bool(self.closed_in), f"finding {self.id}: {self.status} without a version")
        _require(
            (self.status == "superseded") == bool(self.superseded_by),
            f"finding {self.id}: superseded_by goes with the status superseded, and only with it",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"status_text": self.status_text}


@dataclass(frozen=True)
class CheckRecord:
    """The result of running one check once. Written by code, never by hand."""

    source: str
    check: str
    tier: str
    category: str
    method: str
    outcome: str
    run_at: str  # ISO timestamp, UTC
    versions: dict[str, str]
    inputs: tuple[dict[str, Any], ...] = ()  # url, sha256, retrieved_at of every file read
    sample: dict[str, Any] = field(default_factory=dict)  # what was compared, and the seed
    tolerance: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    steps: tuple[str, ...] = ()  # statement step ids this check bears on
    note: str = ""
    summary: str = ""  # one line of numbers for people, written by the assessment from the result
    schema: str = SCHEMA

    def validate(self) -> None:
        _require(
            bool(self.source and self.check and self.method), "a check needs source, id, method"
        )
        _one_of(self.tier, ASSESSMENT_TIERS, f"check {self.check}: tier")
        _one_of(self.category, CATEGORIES, f"check {self.check}: category")
        _one_of(self.outcome, OUTCOMES, f"check {self.check}: outcome")
        _require(bool(self.versions), f"check {self.check}: versions are missing")
        _require(self.run_at.endswith(("Z", "+00:00")), f"check {self.check}: run_at must be UTC")
        if self.outcome in ("confirmed", "differs"):
            _require(bool(self.result), f"check {self.check}: an outcome needs a result")
        if self.outcome == "not checked":
            _require(bool(self.note), f"check {self.check}: say why it was not checked")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
