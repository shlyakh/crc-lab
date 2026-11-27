"""Sums across components and events, annual distributions, attribution, brackets.

Interface draft, not implemented. Every figure of a loss distribution (exceedance, VaR,
CVaR, mean) is read from the CRC ``Distribution`` returned here; this module only adds losses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

import crc_framework as cf
import numpy as np
import numpy.typing as npt

from ._events import YearWeights
from ._table import EventLossTable, FailurePolicy

FloatArray = npt.NDArray[np.float64]


class AnnualMeasure(Enum):
    """Which annual loss of a year. A closed choice."""

    #: the sum of the losses of all events of the year
    AGGREGATE = "aggregate"
    #: the loss of the year's largest event
    OCCURRENCE = "occurrence"


@dataclass(frozen=True)
class AnnualLosses:
    """Annual losses per synthetic year, for the portfolio and for each component.

    ``totals[i]`` and ``components[c][i]`` belong to year ``years.year_ids[i]``; years without an
    event hold 0. For ``AGGREGATE``, the component arrays sum to ``totals``. For ``OCCURRENCE``
    the components hold their loss in the year's largest event (the event of largest total loss;
    a tie between events is broken by event id, and counted in the diagnostics), so they too sum
    to ``totals``. The field names follow the annual-loss arrays of crc-framework-rs pull
    request #27 (``totals``, ``components``), which are aligned the same way.
    """

    measure: AnnualMeasure
    years: YearWeights
    totals: FloatArray
    components: Mapping[str, FloatArray]
    currency: str
    valuation_basis: str
    label: str
    diagnostics: tuple[cf.Diagnostic, ...]

    def distribution(self) -> cf.Distribution:
        """The portfolio's annual loss as a CRC distribution: ``Distribution.empirical`` when the
        years have equal weights, ``Distribution.discrete`` with the year weights otherwise."""
        raise NotImplementedError

    def component_distribution(self, component_id: str) -> cf.Distribution:
        raise NotImplementedError

    def risk(self, levels: Sequence[float]) -> tuple[cf.RiskLevel, ...]:
        """VaR and CVaR from ``distribution()`` (CRC), with each component's share.

        A component's share of CVaR at level q is its weighted mean loss over the upper tail of
        mass 1 - q, with the year at the cutoff taken in part, as ``compute_risk`` treats a tie;
        the shares sum to CRC's CVaR (checked to 1e-9 relative). Its share of VaR is its weighted
        mean loss over the years whose total equals VaR. Returned as CRC's own ``RiskLevel`` and
        ``RiskAttribution``.
        """
        raise NotImplementedError

    def to_json(self) -> str:
        raise NotImplementedError

    @classmethod
    def from_json(cls, text: str) -> AnnualLosses:
        raise NotImplementedError


def annual_losses(
    table: EventLossTable,
    *,
    measure: AnnualMeasure,
    failures: FailurePolicy = FailurePolicy.REFUSE,
) -> AnnualLosses:
    """Add losses across components within each event, then across or over events in a year.

    Needs an event set of synthetic years. Dependence between components is whatever the events
    carry: components lose together when one event reaches them. Nothing is assumed or fitted.
    """
    raise NotImplementedError


def occurrence_distribution(table: EventLossTable) -> cf.Distribution:
    """For an event set of annual rates: the distribution of the largest event loss of a year.

    With independent Poisson events, P(largest <= x) = exp(-sum of rates of events with loss
    > x); returned as ``Distribution.discrete`` with atoms at the event losses and at 0. The
    aggregate annual loss of a rate set is left out of this version (see the design note).
    """
    raise NotImplementedError


class IndependenceMethod(Enum):
    """How the independence bracket is computed. A closed choice."""

    #: exact, by ``compute_risk``; only when every component has at most two annual loss values
    EXACT_TWO_STATE = "exact_two_state"
    #: years drawn independently for each component, with a stated seed and sample count
    RESAMPLED = "resampled"


@dataclass(frozen=True)
class Bracket:
    """Portfolio VaR and CVaR at one level under an assumed dependence, beside the events'."""

    level: float
    comonotonic: cf.RiskLevel
    independent: cf.RiskLevel
    from_events: cf.RiskLevel
    independence_method: IndependenceMethod
    samples: int | None
    seed: int | None
    diagnostics: tuple[cf.Diagnostic, ...]


def brackets(
    annual: AnnualLosses,
    *,
    levels: Sequence[float],
    independence: IndependenceMethod,
    samples: int | None = None,
    seed: int | None = None,
) -> tuple[Bracket, ...]:
    """The same components added under full dependence and under independence.

    Full dependence (comonotonic): VaR and CVaR at q are the sums of the components' VaR and CVaR
    at q, each read from CRC on the component's own distribution. Independence: ``compute_risk``
    on each component's two states when ``EXACT_TWO_STATE`` applies (else an error), or the
    portfolio distribution of independently resampled years under ``RESAMPLED`` (``samples`` and
    ``seed`` required), whose figures again come from CRC.
    """
    raise NotImplementedError


def summary_inputs(annual: AnnualLosses) -> Mapping[str, object]:
    """``totals`` and ``components`` in the form ``summarize_annual_losses`` of crc-framework-rs
    pull request #27 takes them. Only for equal year weights: that summary has no year weights,
    and unequal weights are an error here rather than a silent expansion."""
    raise NotImplementedError
