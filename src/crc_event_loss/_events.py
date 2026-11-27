"""Event sets: which events can happen, and how often."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt

from ._format import check_header, dumps, header

FloatArray = npt.NDArray[np.float64]

_WEIGHT_SUM_TOLERANCE = 1e-12


def _identity(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    return value


class Timeline(Enum):
    """How the events of a set are placed in time. A closed choice."""

    #: every event belongs to one synthetic year; years carry probability weights
    SYNTHETIC_YEARS = "synthetic_years"
    #: every event has its own annual rate and occurs as an independent Poisson process
    ANNUAL_RATES = "annual_rates"


@dataclass(frozen=True)
class YearWeights:
    """The probability mass of each synthetic year.

    Equal weights are the ordinary case of a simulated catalogue (each of n years has mass 1/n).
    Unequal weights arise when the years were sampled by stratum and each one stands for the years
    of its stratum that were not run. Weights are positive and sum to 1 within 1e-12.
    """

    year_ids: tuple[str, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        ids = tuple(_identity(y, "year id") for y in self.year_ids)
        weights = tuple(float(w) for w in self.weights)
        if not ids:
            raise ValueError("at least one year is required")
        if len(ids) != len(weights):
            raise ValueError(f"{len(ids)} year ids but {len(weights)} weights")
        if len(set(ids)) != len(ids):
            raise ValueError("year ids must be unique")
        bad = [
            (y, w) for y, w in zip(ids, weights, strict=True) if not (math.isfinite(w) and w > 0)
        ]
        if bad:
            raise ValueError(f"year weights must be positive and finite: {bad[:5]}")
        total = math.fsum(weights)
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"year weights sum to {total!r}, not 1 within 1e-12")
        object.__setattr__(self, "year_ids", ids)
        object.__setattr__(self, "weights", weights)

    @classmethod
    def equal(cls, year_ids: Sequence[str]) -> YearWeights:
        """Mass 1/n for each of n years."""
        ids = tuple(year_ids)
        if not ids:
            raise ValueError("at least one year is required")
        return cls(ids, (1.0 / len(ids),) * len(ids))

    @classmethod
    def stratified(cls, strata: Mapping[str, tuple[int, Sequence[str]]]) -> YearWeights:
        """Weights from strata: ``{stratum: (years the stratum stands for, years run in it)}``.

        A year run in a stratum of N years of which n were run has mass N / (n * total years).
        """
        if not strata:
            raise ValueError("at least one stratum is required")
        parts: list[tuple[str, int, tuple[str, ...]]] = []
        for name, (stands_for, run) in strata.items():
            _identity(name, "stratum")
            if isinstance(stands_for, bool) or not isinstance(stands_for, int | np.integer):
                raise ValueError(f"stratum {name!r}: the years it stands for must be an integer")
            run_ids = tuple(run)
            if not run_ids:
                raise ValueError(f"stratum {name!r} has no year run")
            if int(stands_for) < len(run_ids):
                raise ValueError(
                    f"stratum {name!r} stands for {stands_for} years but {len(run_ids)} were run"
                )
            parts.append((name, int(stands_for), run_ids))
        total = sum(n for _, n, _ in parts)
        ids: list[str] = []
        weights: list[float] = []
        for _, stands_for, run_ids in parts:
            # One division, correctly rounded, so that equal masses give equal floats.
            mass = stands_for / (len(run_ids) * total)
            ids.extend(run_ids)
            weights.extend([mass] * len(run_ids))
        return cls(tuple(ids), tuple(weights))

    @property
    def equal_weights(self) -> bool:
        return all(w == self.weights[0] for w in self.weights)

    def _array(self) -> FloatArray:
        return np.asarray(self.weights, dtype=np.float64)

    def _to_dict(self) -> dict[str, Any]:
        return {"year_ids": list(self.year_ids), "weights": list(self.weights)}

    @classmethod
    def _from_dict(cls, document: Mapping[str, Any]) -> YearWeights:
        return cls(tuple(document["year_ids"]), tuple(document["weights"]))


class EventSet:
    """Event identities with their place in time and a statement of what the set represents.

    Built with ``synthetic_years`` or ``annual_rates``; the constructor itself is not public.
    ``description`` and ``provenance`` are open strings carried into every document written from
    the set (for example the generator, its version and settings, and the number of years).
    """

    timeline: Timeline
    event_ids: tuple[str, ...]
    description: str
    provenance: Mapping[str, str]

    __slots__ = ("timeline", "event_ids", "description", "provenance", "_years", "_place")

    def __init__(self) -> None:
        raise TypeError("use EventSet.synthetic_years or EventSet.annual_rates")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("EventSet is immutable")

    @classmethod
    def _make(
        cls,
        timeline: Timeline,
        place: Mapping[str, Any],
        years: YearWeights | None,
        description: str,
        provenance: Mapping[str, str] | None,
    ) -> EventSet:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        prov = dict(provenance or {})
        for key, value in prov.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"provenance must map strings to strings: {key!r}: {value!r}")
        self = object.__new__(cls)
        set_ = object.__setattr__
        set_(self, "timeline", timeline)
        set_(self, "event_ids", tuple(place))
        set_(self, "description", description)
        set_(self, "provenance", MappingProxyType(prov))
        set_(self, "_years", years)
        set_(self, "_place", MappingProxyType(dict(place)))
        return self

    @classmethod
    def synthetic_years(
        cls,
        event_years: Mapping[str, str],
        *,
        years: YearWeights,
        description: str,
        provenance: Mapping[str, str] | None = None,
    ) -> EventSet:
        """Events placed in synthetic years: ``{event_id: year_id}``.

        Every year of ``years`` is part of the set, including years that hold no event: they are
        years without loss and keep their mass. An event whose year is not in ``years`` is an
        error.
        """
        if not isinstance(years, YearWeights):
            raise TypeError("years must be YearWeights")
        known = set(years.year_ids)
        place: dict[str, str] = {}
        for event, year in event_years.items():
            _identity(event, "event id")
            _identity(year, "year id")
            if year not in known:
                raise ValueError(f"event {event!r} is placed in year {year!r}, not in years")
            place[event] = year
        return cls._make(Timeline.SYNTHETIC_YEARS, place, years, description, provenance)

    @classmethod
    def annual_rates(
        cls,
        rates: Mapping[str, float],
        *,
        description: str,
        provenance: Mapping[str, str] | None = None,
    ) -> EventSet:
        """Events with annual occurrence rates (per year, finite, non-negative)."""
        place: dict[str, float] = {}
        for event, rate in rates.items():
            _identity(event, "event id")
            value = float(rate)
            if not (math.isfinite(value) and value >= 0):
                raise ValueError(f"event {event!r}: rate must be finite and non-negative")
            place[event] = value
        return cls._make(Timeline.ANNUAL_RATES, place, None, description, provenance)

    @property
    def years(self) -> YearWeights | None:
        """The synthetic years, or None for a set of annual rates."""
        return self._years

    def rate(self, event_id: str) -> float:
        """Annual rate of an event. For synthetic years: the mass of its year (one occurrence a
        year at most per event)."""
        if event_id not in self._place:
            raise KeyError(event_id)
        if self.timeline is Timeline.ANNUAL_RATES:
            return float(self._place[event_id])
        assert self._years is not None
        index = self._years.year_ids.index(self._place[event_id])
        return self._years.weights[index]

    def _year_of(self, event_id: str) -> str:
        if self.timeline is not Timeline.SYNTHETIC_YEARS:
            raise ValueError("an event set of annual rates has no years")
        return str(self._place[event_id])

    def to_json(self) -> str:
        """A document with a format name and version that ``from_json`` reads back equal."""
        document: dict[str, Any] = header("event_set")
        document.update(
            timeline=self.timeline.value,
            description=self.description,
            provenance=dict(self.provenance),
            events=[[event, self._place[event]] for event in self.event_ids],
            years=None if self._years is None else self._years._to_dict(),
        )
        return dumps(document)

    @classmethod
    def from_json(cls, text: str) -> EventSet:
        document = json.loads(text)
        check_header(document, "event_set")
        timeline = Timeline(document["timeline"])
        place = {event: where for event, where in document["events"]}
        if timeline is Timeline.SYNTHETIC_YEARS:
            return cls.synthetic_years(
                place,
                years=YearWeights._from_dict(document["years"]),
                description=document["description"],
                provenance=document["provenance"],
            )
        return cls.annual_rates(
            place, description=document["description"], provenance=document["provenance"]
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EventSet):
            return NotImplemented
        return (
            self.timeline is other.timeline
            and self.event_ids == other.event_ids
            and self.description == other.description
            and dict(self.provenance) == dict(other.provenance)
            and self._years == other._years
            and dict(self._place) == dict(other._place)
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (
            f"EventSet({self.timeline.value}, {len(self.event_ids)} events, "
            f"description={self.description!r})"
        )
