"""Event sets: which events can happen, and how often (interface draft, not implemented)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


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

    @classmethod
    def equal(cls, year_ids: Sequence[str]) -> YearWeights:
        """Mass 1/n for each of n years."""
        raise NotImplementedError

    @classmethod
    def stratified(cls, strata: Mapping[str, tuple[int, Sequence[str]]]) -> YearWeights:
        """Weights from strata: ``{stratum: (years the stratum stands for, years run in it)}``.

        A year run in a stratum of N years of which n were run has mass N / (n * total years).
        """
        raise NotImplementedError

    @property
    def equal_weights(self) -> bool:
        raise NotImplementedError


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
        raise NotImplementedError

    @classmethod
    def annual_rates(
        cls,
        rates: Mapping[str, float],
        *,
        description: str,
        provenance: Mapping[str, str] | None = None,
    ) -> EventSet:
        """Events with annual occurrence rates (per year, finite, non-negative)."""
        raise NotImplementedError

    @property
    def years(self) -> YearWeights | None:
        """The synthetic years, or None for a set of annual rates."""
        raise NotImplementedError

    def rate(self, event_id: str) -> float:
        """Annual rate of an event. For synthetic years: the mass of its year (one occurrence a
        year at most per event)."""
        raise NotImplementedError

    def to_json(self) -> str:
        """A document with a format name and version that ``from_json`` reads back equal."""
        raise NotImplementedError

    @classmethod
    def from_json(cls, text: str) -> EventSet:
        raise NotImplementedError
