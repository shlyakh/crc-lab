"""The event-loss table."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import crc_framework as cf
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ._events import EventSet
from ._format import (
    check_header,
    diagnostic_from_dict,
    diagnostic_to_dict,
    dumps,
    header,
    info,
    warning,
)

_METADATA_KEY = b"crc_event_loss"

_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("component_id", pa.string(), nullable=False),
        pa.field("intensity", pa.float64()),
        pa.field("damage_ratio", pa.float64()),
        pa.field("loss", pa.float64(), nullable=False),
    ]
)


class MissingIntensity(Enum):
    """What an (event, component) pair absent from the intensity table means. A closed choice."""

    #: the event does not reach the component: loss 0, counted in the diagnostics
    NO_LOSS = "no_loss"
    #: every pair must be present; an absent pair is an error
    ERROR = "error"


class FailurePolicy(Enum):
    """What aggregation does with rows the impact refused (``ImpactError``). A closed choice."""

    #: aggregation is refused while any failure row exists
    REFUSE = "refuse"
    #: the components with any failure are left out of every sum, and named in the diagnostics
    EXCLUDE_COMPONENT = "exclude_component"


@dataclass(frozen=True)
class Exposure:
    """One component (an asset or any other unit of loss) and what its loss is measured against.

    ``value`` is the amount a damage ratio of 1 corresponds to, in the table's currency and
    valuation basis. ``impact`` names an entry of the impacts given to ``from_intensities``.
    """

    component_id: str
    value: float
    impact: str


@dataclass(frozen=True)
class Failure:
    """One row the impact refused: event, component, the intensity, and CRC's error code."""

    event_id: str
    component_id: str
    intensity: float
    code: str
    message: str


def _string_column(table: pa.Table, name: str) -> list[str]:
    if name not in table.column_names:
        raise ValueError(f"column {name!r} is missing; found {table.column_names}")
    column = table.column(name)
    if not (pa.types.is_string(column.type) or pa.types.is_large_string(column.type)):
        raise ValueError(f"column {name!r} must be strings, found {column.type}")
    if column.null_count:
        raise ValueError(f"column {name!r} has {column.null_count} nulls")
    values = column.to_pylist()
    empty = sum(1 for v in values if not v)
    if empty:
        raise ValueError(f"column {name!r} has {empty} empty strings")
    return values


def _float_column(table: pa.Table, name: str) -> np.ndarray:
    if name not in table.column_names:
        raise ValueError(f"column {name!r} is missing; found {table.column_names}")
    column = table.column(name)
    if not pa.types.is_floating(column.type):
        raise ValueError(f"column {name!r} must be float64, found {column.type}")
    if column.null_count:
        raise ValueError(f"column {name!r} has {column.null_count} nulls")
    return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)


def _check_ids(
    events: EventSet, event_ids: list[str], component_ids: list[str], known_components: set[str]
) -> None:
    known_events = set(events.event_ids)
    unknown_events = sorted({e for e in event_ids if e not in known_events})
    if unknown_events:
        raise ValueError(
            f"{len(unknown_events)} event ids are not in the event set: {unknown_events[:5]}"
        )
    unknown = sorted({c for c in component_ids if c not in known_components})
    if unknown:
        raise ValueError(f"{len(unknown)} component ids have no exposure: {unknown[:5]}")
    pairs = Counter(zip(event_ids, component_ids, strict=True))
    repeated = [pair for pair, n in pairs.items() if n > 1]
    if repeated:
        raise ValueError(f"{len(repeated)} (event, component) pairs repeat: {repeated[:5]}")


def _ratio_scale(name: str, impact: cf.Impact, intensity: cf.Measurement) -> float:
    if impact.input != intensity:
        raise ValueError(
            f"impact {name!r} takes {impact.input!r}, but the intensities are {intensity!r}"
        )
    output = impact.output
    if not isinstance(output, cf.Ratio):
        raise ValueError(f"impact {name!r} gives {output!r}, not a cf.Ratio")
    return 0.01 if output.unit is cf.RatioUnit.PERCENT else 1.0


class EventLossTable:
    """Loss per event and component, with its measurement, currency and valuation basis.

    Rows hold event id, component id, intensity (when built from intensities), damage ratio and
    loss. Pairs with no loss need not be stored. Failure rows are kept apart, never dropped, and
    every count of what was left out travels in ``diagnostics``. ``label`` is an open string
    naming the choice behind the table (for example which of several damage curves was used),
    so several tables over one event set can stand side by side.
    """

    events: EventSet
    currency: str
    valuation_basis: str
    label: str
    loss: cf.Measurement
    failures: tuple[Failure, ...]
    diagnostics: tuple[cf.Diagnostic, ...]

    __slots__ = (
        "events",
        "currency",
        "valuation_basis",
        "label",
        "loss",
        "failures",
        "diagnostics",
        "_rows",
        "_component_ids",
        "_intensity",
    )

    def __init__(self) -> None:
        raise TypeError("use EventLossTable.from_intensities, from_losses or read")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("EventLossTable is immutable")

    @classmethod
    def _make(
        cls,
        *,
        events: EventSet,
        rows: pa.Table,
        component_ids: tuple[str, ...],
        intensity: cf.Measurement | None,
        currency: str,
        valuation_basis: str,
        label: str,
        failures: tuple[Failure, ...],
        diagnostics: tuple[cf.Diagnostic, ...],
    ) -> EventLossTable:
        for what, text in (
            ("currency", currency),
            ("valuation_basis", valuation_basis),
            ("label", label),
        ):
            if not isinstance(text, str) or not text:
                raise ValueError(f"{what} must be a non-empty string")
        self = object.__new__(cls)
        set_ = object.__setattr__
        set_(self, "events", events)
        set_(self, "currency", currency)
        set_(self, "valuation_basis", valuation_basis)
        set_(self, "label", label)
        set_(self, "loss", cf.Measurement(quantity="loss", unit=currency))
        set_(self, "failures", tuple(failures))
        set_(self, "diagnostics", tuple(diagnostics))
        set_(self, "_rows", rows.cast(_SCHEMA).replace_schema_metadata(None))
        set_(self, "_component_ids", tuple(component_ids))
        set_(self, "_intensity", intensity)
        return self

    @classmethod
    def from_intensities(
        cls,
        events: EventSet,
        intensities: pa.Table,
        *,
        intensity: cf.Measurement,
        exposures: tuple[Exposure, ...],
        impacts: Mapping[str, cf.Impact],
        currency: str,
        valuation_basis: str,
        label: str,
        missing: MissingIntensity = MissingIntensity.NO_LOSS,
    ) -> EventLossTable:
        """Damage ratios from CRC, ``impact.evaluate``, times each component's value.

        ``intensities`` has the columns ``event_id`` (string), ``component_id`` (string) and
        ``value`` (float64), in the measurement ``intensity``, which must equal the ``input`` of
        every impact used; every impact's ``output`` must be a ``cf.Ratio``. An event or
        component not in ``events`` or ``exposures`` is an error. A value the impact refuses
        becomes a ``Failure`` with CRC's error code; the other rows of the same impact are still
        evaluated.
        """
        if not isinstance(events, EventSet):
            raise TypeError("events must be an EventSet")
        if not isinstance(missing, MissingIntensity):
            raise TypeError("missing must be a MissingIntensity")
        by_component: dict[str, Exposure] = {}
        for exposure in exposures:
            if not isinstance(exposure, Exposure):
                raise TypeError("exposures must be Exposure objects")
            if not isinstance(exposure.component_id, str) or not exposure.component_id:
                raise ValueError("component ids must be non-empty strings")
            if exposure.component_id in by_component:
                raise ValueError(f"component {exposure.component_id!r} has two exposures")
            if not (math.isfinite(exposure.value) and exposure.value >= 0):
                raise ValueError(
                    f"component {exposure.component_id!r}: value must be finite and non-negative"
                )
            if exposure.impact not in impacts:
                raise ValueError(
                    f"component {exposure.component_id!r} names impact {exposure.impact!r}, "
                    f"which is not among the impacts given"
                )
            by_component[exposure.component_id] = exposure
        scales = {
            name: _ratio_scale(name, impacts[name], intensity)
            for name in sorted({e.impact for e in by_component.values()})
        }

        event_ids = _string_column(intensities, "event_id")
        component_ids = _string_column(intensities, "component_id")
        values = _float_column(intensities, "value")
        _check_ids(events, event_ids, component_ids, set(by_component))

        n = len(values)
        ratios = np.full(n, np.nan)
        refused = np.zeros(n, dtype=bool)
        failures: list[Failure] = []
        impact_of_row = np.array([by_component[c].impact for c in component_ids], dtype=object)
        for name, scale in scales.items():
            rows = np.flatnonzero(impact_of_row == name)
            if rows.size == 0:
                continue
            impact = impacts[name]
            try:
                ratios[rows] = np.asarray(impact.evaluate(values[rows]), dtype=np.float64) * scale
            except cf.ImpactError:
                # CRC refuses the whole array for one bad value: evaluate value by value so
                # that only the refused rows become failures.
                for row in rows:
                    try:
                        ratio = impact.evaluate(np.array([values[row]]))
                    except cf.ImpactError as error:
                        refused[row] = True
                        failures.append(
                            Failure(
                                event_ids[row],
                                component_ids[row],
                                float(values[row]),
                                error.code,
                                error.message,
                            )
                        )
                    else:
                        ratios[row] = float(np.asarray(ratio)[0]) * scale
        kept = ~refused
        exposure_values = np.array([by_component[c].value for c in component_ids], dtype=float)
        losses = ratios * exposure_values
        bad = kept & ~np.isfinite(losses)
        if bad.any():
            row = int(np.flatnonzero(bad)[0])
            raise ValueError(
                f"loss is not finite for event {event_ids[row]!r}, component "
                f"{component_ids[row]!r} (damage ratio {ratios[row]!r})"
            )

        absent = len(events.event_ids) * len(by_component) - n
        if absent and missing is MissingIntensity.ERROR:
            raise ValueError(
                f"{absent} (event, component) pairs have no intensity and missing is ERROR"
            )
        diagnostics = [
            info(
                "pairs_absent_as_no_loss",
                "(event, component) pairs absent from the intensities, taken as no loss",
                "/intensities",
                count=absent,
                missing=missing.value,
            ),
            (warning if failures else info)(
                "impact_refused_values",
                "intensity values the impact refused, kept apart as failures",
                "/failures",
                count=len(failures),
                codes=dict(sorted(Counter(f.code for f in failures).items())),
            ),
        ]
        keep = np.flatnonzero(kept)
        rows_table = pa.table(
            {
                "event_id": pa.array([event_ids[i] for i in keep], pa.string()),
                "component_id": pa.array([component_ids[i] for i in keep], pa.string()),
                "intensity": pa.array(values[keep], pa.float64()),
                "damage_ratio": pa.array(ratios[keep], pa.float64()),
                "loss": pa.array(losses[keep], pa.float64()),
            },
            schema=_SCHEMA,
        )
        return cls._make(
            events=events,
            rows=rows_table,
            component_ids=tuple(by_component),
            intensity=intensity,
            currency=currency,
            valuation_basis=valuation_basis,
            label=label,
            failures=tuple(failures),
            diagnostics=tuple(diagnostics),
        )

    @classmethod
    def from_losses(
        cls,
        events: EventSet,
        losses: pa.Table,
        *,
        currency: str,
        valuation_basis: str,
        label: str,
    ) -> EventLossTable:
        """A table of losses computed elsewhere: columns ``event_id``, ``component_id``,
        ``loss`` (float64, finite, non-negative)."""
        if not isinstance(events, EventSet):
            raise TypeError("events must be an EventSet")
        event_ids = _string_column(losses, "event_id")
        component_ids = _string_column(losses, "component_id")
        loss = _float_column(losses, "loss")
        if not (np.isfinite(loss).all() and (loss >= 0).all()):
            raise ValueError("losses must be finite and non-negative")
        components = tuple(dict.fromkeys(component_ids))
        _check_ids(events, event_ids, component_ids, set(components))
        n = len(loss)
        rows_table = pa.table(
            {
                "event_id": pa.array(event_ids, pa.string()),
                "component_id": pa.array(component_ids, pa.string()),
                "intensity": pa.nulls(n, pa.float64()),
                "damage_ratio": pa.nulls(n, pa.float64()),
                "loss": pa.array(loss, pa.float64()),
            },
            schema=_SCHEMA,
        )
        return cls._make(
            events=events,
            rows=rows_table,
            component_ids=components,
            intensity=None,
            currency=currency,
            valuation_basis=valuation_basis,
            label=label,
            failures=(),
            diagnostics=(),
        )

    @property
    def component_ids(self) -> tuple[str, ...]:
        return self._component_ids

    def _metadata(self) -> dict[str, Any]:
        document: dict[str, Any] = header("event_loss_table")
        document.update(
            events=self.events.to_json(),
            loss=self.loss.to_json(),
            intensity=None if self._intensity is None else self._intensity.to_json(),
            currency=self.currency,
            valuation_basis=self.valuation_basis,
            label=self.label,
            component_ids=list(self._component_ids),
            failures=[asdict(f) for f in self.failures],
            diagnostics=[diagnostic_to_dict(d) for d in self.diagnostics],
        )
        return document

    def to_arrow(self) -> pa.Table:
        """The rows, with the table's metadata in the schema metadata."""
        return self._rows.replace_schema_metadata({_METADATA_KEY: dumps(self._metadata())})

    def write(self, path: Path, *, overwrite: bool = False) -> Path:
        """Parquet, written atomically; an existing file is kept unless ``overwrite``.

        The event set, measurement, currency, label, failures and diagnostics are stored in the
        file's metadata with a format name and version, so that ``read`` gives back an equal table.
        """
        target = Path(path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"{target} exists; pass overwrite=True to replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        os.close(handle)
        try:
            pq.write_table(self.to_arrow(), temporary)
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target

    @classmethod
    def read(cls, path: Path) -> EventLossTable:
        table = pq.read_table(Path(path))
        metadata = table.schema.metadata or {}
        if _METADATA_KEY not in metadata:
            raise ValueError(f"{path} has no {_METADATA_KEY.decode()} metadata")
        document = json.loads(metadata[_METADATA_KEY])
        check_header(document, "event_loss_table")
        events = EventSet.from_json(document["events"])
        loss = cf.Measurement.from_json(document["loss"])
        result = cls._make(
            events=events,
            rows=table.select(_SCHEMA.names),
            component_ids=tuple(document["component_ids"]),
            intensity=(
                None
                if document["intensity"] is None
                else cf.Measurement.from_json(document["intensity"])
            ),
            currency=document["currency"],
            valuation_basis=document["valuation_basis"],
            label=document["label"],
            failures=tuple(Failure(**f) for f in document["failures"]),
            diagnostics=tuple(diagnostic_from_dict(d) for d in document["diagnostics"]),
        )
        if result.loss != loss:
            raise ValueError(f"stored loss measurement {loss!r} does not match the currency")
        return result

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EventLossTable):
            return NotImplemented
        return (
            self.events == other.events
            and self.currency == other.currency
            and self.valuation_basis == other.valuation_basis
            and self.label == other.label
            and self.loss == other.loss
            and self._intensity == other._intensity
            and self._component_ids == other._component_ids
            and self.failures == other.failures
            and self.diagnostics == other.diagnostics
            and self._rows.equals(other._rows)
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (
            f"EventLossTable(label={self.label!r}, {self._rows.num_rows} rows, "
            f"{len(self._component_ids)} components, {len(self.failures)} failures)"
        )
