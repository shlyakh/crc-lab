"""Sums across components and events, annual distributions, attribution, brackets.

Every figure of a loss distribution (exceedance, VaR, CVaR, mean) is read from the CRC
``Distribution`` returned here; this module only adds losses.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

import crc_framework as cf
import numpy as np
import numpy.typing as npt

from ._events import Timeline, YearWeights
from ._format import (
    check_header,
    diagnostic_from_dict,
    diagnostic_to_dict,
    dumps,
    header,
    info,
    warning,
)
from ._table import EventLossTable, FailurePolicy

FloatArray = npt.NDArray[np.float64]

#: relative tolerance of the check that the CVaR shares add up to CRC's CVaR
_SHARE_TOLERANCE = 1e-9
#: relative slack of the P-2 check, so that 1 - 0.9 (0.09999999999999998) still admits a year
#: of mass 0.1; it is far below any difference between two year masses that matters
_LEVEL_SLACK = 1e-9


class AnnualMeasure(Enum):
    """Which annual loss of a year. A closed choice."""

    #: the sum of the losses of all events of the year
    AGGREGATE = "aggregate"
    #: the loss of the year's largest event
    OCCURRENCE = "occurrence"


def _frozen(values: Iterable[float]) -> FloatArray:
    array = np.array(values, dtype=np.float64)
    array.setflags(write=False)
    return array


def _law(values: FloatArray, weights: FloatArray | None) -> cf.Distribution:
    """``empirical`` for equal weights (None), ``discrete`` with the weights otherwise."""
    if weights is None:
        return cf.Distribution.empirical(values)
    return cf.Distribution.discrete(values, weights)


def _var_cvar(law: cf.Distribution, level: float) -> tuple[float, float]:
    var = float(law.quantile(float(level)))
    summary = law.statistics(metrics=[cf.Statistic.CVAR], level=float(level))
    cvar = summary.values[cf.Statistic.CVAR]
    if cvar.status is not cf.StatisticStatus.FINITE or cvar.value is None:
        raise ValueError(f"CRC gives no finite CVaR at level {level}: {cvar!r}")
    return var, float(cvar.value)


def _check_levels(levels: Sequence[float], smallest_mass: float, what: str) -> tuple[float, ...]:
    """P-2: a level whose tail mass is smaller than the smallest year mass is refused."""
    qs = tuple(float(q) for q in levels)
    if not qs:
        raise ValueError("at least one level is required")
    for q in qs:
        if not (math.isfinite(q) and 0 < q < 1):
            raise ValueError(f"level {q!r} must lie strictly between 0 and 1")
        if 1 - q < smallest_mass * (1 - _LEVEL_SLACK):
            raise ValueError(
                f"level {q!r} has tail mass {1 - q!r}, smaller than the smallest {what} mass "
                f"{smallest_mass!r}; the highest level these years support is "
                f"{1 - smallest_mass!r} (return period {1 / smallest_mass!r} years)"
            )
    return qs


def _shares(
    var: float,
    cvar: float,
    level: float,
    weights: FloatArray,
    totals: FloatArray,
    components: Iterable[tuple[str, FloatArray]],
) -> tuple[cf.RiskAttribution, ...]:
    """Each component's share of VaR and CVaR at ``level``.

    The CVaR share is the Euler allocation of expected shortfall (Tasche, "Capital allocation to
    business units and sub-portfolios: the Euler principle", arXiv:0708.2542): the component's
    weighted mean loss over the upper tail of mass 1 - level. Years above VaR count in full; the
    years whose total equals VaR fill what remains of the tail, each the same fraction of its
    mass, as ``compute_risk`` treats a tie. The VaR share is the component's weighted mean loss
    over the years whose total equals VaR.
    """
    tail = 1.0 - level
    above = totals > var
    at = totals == var
    mass_at = float(weights[at].sum())
    if mass_at <= 0:
        raise ValueError(f"CRC's VaR {var!r} is not the total of any year")
    remaining = tail - float(weights[above].sum())
    fraction = min(max(remaining / mass_at, 0.0), 1.0)
    w_above = weights * above
    w_at = weights * at
    result = []
    for component_id, losses in components:
        var_share = float(losses @ w_at) / mass_at
        cvar_share = (float(losses @ w_above) + fraction * float(losses @ w_at)) / tail
        result.append(cf.RiskAttribution(component_id, var_share, cvar_share))
    added = math.fsum(r.conditional_value_at_risk for r in result)
    if abs(added - cvar) > _SHARE_TOLERANCE * max(abs(cvar), abs(added)):
        raise ArithmeticError(f"CVaR shares add up to {added!r}, CRC's CVaR at {level} is {cvar!r}")
    return tuple(result)


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

    def __post_init__(self) -> None:
        n = len(self.years.year_ids)
        totals = _frozen(self.totals)
        components = {str(c): _frozen(v) for c, v in self.components.items()}
        for name, array in (("totals", totals), *components.items()):
            if array.shape != (n,):
                raise ValueError(f"{name}: {array.shape[0]} values for {n} years")
        object.__setattr__(self, "totals", totals)
        object.__setattr__(self, "components", MappingProxyType(components))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def _weights(self) -> FloatArray | None:
        return None if self.years.equal_weights else self.years._array()

    def distribution(self) -> cf.Distribution:
        """The portfolio's annual loss as a CRC distribution: ``Distribution.empirical`` when the
        years have equal weights, ``Distribution.discrete`` with the year weights otherwise."""
        return _law(self.totals, self._weights())

    def component_distribution(self, component_id: str) -> cf.Distribution:
        return _law(self.components[component_id], self._weights())

    def risk(self, levels: Sequence[float]) -> tuple[cf.RiskLevel, ...]:
        """VaR and CVaR from ``distribution()`` (CRC), with each component's share.

        A component's share of CVaR at level q is its weighted mean loss over the upper tail of
        mass 1 - q, with the year at the cutoff taken in part, as ``compute_risk`` treats a tie;
        the shares sum to CRC's CVaR (checked to 1e-9 relative). Its share of VaR is its weighted
        mean loss over the years whose total equals VaR. Returned as CRC's own ``RiskLevel`` and
        ``RiskAttribution``. A level whose tail mass 1 - q is smaller than the smallest year mass
        is refused with a ValueError, since no year stands for it.
        """
        qs = _check_levels(levels, min(self.years.weights), "year")
        law = self.distribution()
        weights = self.years._array()
        result = []
        for q in qs:
            var, cvar = _var_cvar(law, q)
            attribution = _shares(var, cvar, q, weights, self.totals, self.components.items())
            result.append(cf.RiskLevel(q, var, cvar, attribution))
        return tuple(result)

    def to_json(self) -> str:
        document: dict[str, Any] = header("annual_losses")
        document.update(
            measure=self.measure.value,
            years=self.years._to_dict(),
            totals=self.totals.tolist(),
            components={c: v.tolist() for c, v in self.components.items()},
            currency=self.currency,
            valuation_basis=self.valuation_basis,
            label=self.label,
            diagnostics=[diagnostic_to_dict(d) for d in self.diagnostics],
        )
        # Components keep their order: sort_keys would reorder them.
        document["component_order"] = list(self.components)
        return dumps(document)

    @classmethod
    def from_json(cls, text: str) -> AnnualLosses:
        document = json.loads(text)
        check_header(document, "annual_losses")
        return cls(
            measure=AnnualMeasure(document["measure"]),
            years=YearWeights._from_dict(document["years"]),
            totals=np.asarray(document["totals"], dtype=np.float64),
            components={
                c: np.asarray(document["components"][c], dtype=np.float64)
                for c in document["component_order"]
            },
            currency=document["currency"],
            valuation_basis=document["valuation_basis"],
            label=document["label"],
            diagnostics=tuple(diagnostic_from_dict(d) for d in document["diagnostics"]),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AnnualLosses):
            return NotImplemented
        return (
            self.measure is other.measure
            and self.years == other.years
            and np.array_equal(self.totals, other.totals)
            and list(self.components) == list(other.components)
            and all(np.array_equal(v, other.components[c]) for c, v in self.components.items())
            and self.currency == other.currency
            and self.valuation_basis == other.valuation_basis
            and self.label == other.label
            and self.diagnostics == other.diagnostics
        )


def _included(
    table: EventLossTable, failures: FailurePolicy
) -> tuple[tuple[str, ...], list[cf.Diagnostic]]:
    if not isinstance(failures, FailurePolicy):
        raise TypeError("failures must be a FailurePolicy")
    if table.failures and failures is FailurePolicy.REFUSE:
        raise ValueError(
            f"table {table.label!r} has {len(table.failures)} failure rows and the policy is "
            f"REFUSE; pass failures=FailurePolicy.EXCLUDE_COMPONENT to leave those components out"
        )
    failed = {f.component_id for f in table.failures}
    excluded = [c for c in table.component_ids if c in failed]
    diagnostics = []
    if failures is FailurePolicy.EXCLUDE_COMPONENT:
        diagnostics.append(
            (warning if excluded else info)(
                "components_excluded",
                "components left out of every sum because the impact refused a value of theirs",
                "/components",
                count=len(excluded),
                component_ids=excluded,
                failure_rows=len(table.failures),
            )
        )
    return tuple(c for c in table.component_ids if c not in failed), diagnostics


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
    if not isinstance(measure, AnnualMeasure):
        raise TypeError("measure must be an AnnualMeasure")
    events = table.events
    if events.timeline is not Timeline.SYNTHETIC_YEARS or events.years is None:
        raise ValueError(
            "annual losses need an event set of synthetic years; for annual rates use "
            "occurrence_distribution (the aggregate of a rate set is not in this version)"
        )
    years = events.years
    components, diagnostics = _included(table, failures)
    year_index = {y: i for i, y in enumerate(years.year_ids)}
    event_index = {e: i for i, e in enumerate(events.event_ids)}
    component_index = {c: i for i, c in enumerate(components)}
    year_of_event = np.array(
        [year_index[events._year_of(e)] for e in events.event_ids], dtype=np.int64
    )

    rows = table._rows
    row_components = rows.column("component_id").to_pylist()
    keep = np.array([c in component_index for c in row_components], dtype=bool)
    row_component = np.array([component_index.get(c, -1) for c in row_components], dtype=np.int64)[
        keep
    ]
    row_event = np.array(
        [event_index[e] for e in rows.column("event_id").to_pylist()], dtype=np.int64
    )[keep]
    row_loss = np.asarray(rows.column("loss").to_numpy(), dtype=np.float64)[keep]

    n_years, n_components = len(years.year_ids), len(components)
    matrix = np.zeros((n_components, n_years))
    if measure is AnnualMeasure.AGGREGATE:
        np.add.at(matrix, (row_component, year_of_event[row_event]), row_loss)
    else:
        event_total = np.bincount(row_event, weights=row_loss, minlength=len(event_index))
        # Largest total first within each year; a tie goes to the smaller event id.
        id_rank = np.empty(len(event_index), dtype=np.int64)
        id_rank[np.argsort(np.array(events.event_ids, dtype=object), kind="stable")] = np.arange(
            len(event_index)
        )
        order = np.lexsort((id_rank, -event_total, year_of_event))
        ordered_years = year_of_event[order]
        first = np.ones(len(order), dtype=bool)
        first[1:] = ordered_years[1:] != ordered_years[:-1]
        chosen = np.zeros(len(event_index), dtype=bool)
        chosen[order[first]] = True
        # A tie that decides something: a second event of the year with the same positive total.
        second = np.zeros(len(order), dtype=bool)
        second[1:] = ~first[1:] & first[:-1]
        tied_years = int(
            np.count_nonzero(
                second[1:]
                & (event_total[order[1:]] == event_total[order[:-1]])
                & (event_total[order[1:]] > 0)
            )
        )
        diagnostics.append(
            (warning if tied_years else info)(
                "occurrence_ties",
                "years whose largest event loss is shared by several events; the event with "
                "the smaller id was taken",
                "/components",
                count=tied_years,
            )
        )
        take = chosen[row_event]
        np.add.at(
            matrix,
            (row_component[take], year_of_event[row_event[take]]),
            row_loss[take],
        )
    totals = matrix.sum(axis=0)
    empty_years = n_years - len(np.unique(year_of_event))
    diagnostics.append(
        info(
            "years_without_events",
            "years of the set that hold no event; their annual loss is 0",
            "/years",
            count=int(empty_years),
        )
    )
    return AnnualLosses(
        measure=measure,
        years=years,
        totals=totals,
        components={c: matrix[i] for i, c in enumerate(components)},
        currency=table.currency,
        valuation_basis=table.valuation_basis,
        label=table.label,
        diagnostics=(*table.diagnostics, *diagnostics),
    )


def occurrence_distribution(table: EventLossTable) -> cf.Distribution:
    """For an event set of annual rates: the distribution of the largest event loss of a year.

    With independent Poisson events, P(largest <= x) = exp(-sum of rates of events with loss
    > x); returned as ``Distribution.discrete`` with atoms at the event losses and at 0. The
    aggregate annual loss of a rate set is left out of this version (see the design note).
    """
    events = table.events
    if events.timeline is not Timeline.ANNUAL_RATES:
        raise ValueError("occurrence_distribution needs an event set of annual rates")
    if table.failures:
        raise ValueError(
            f"table {table.label!r} has {len(table.failures)} failure rows; an event's loss is "
            f"not known while one of its values is refused"
        )
    event_index = {e: i for i, e in enumerate(events.event_ids)}
    rows = table._rows
    row_event = np.array(
        [event_index[e] for e in rows.column("event_id").to_pylist()], dtype=np.int64
    )
    row_loss = np.asarray(rows.column("loss").to_numpy(), dtype=np.float64)
    event_loss = np.bincount(row_event, weights=row_loss, minlength=len(event_index))
    rates = np.array([events.rate(e) for e in events.event_ids], dtype=np.float64)
    hit = (event_loss > 0) & (rates > 0)
    losses = np.unique(event_loss[hit])
    # rate of the events whose loss is exactly each atom, and of those above it
    at = np.array([rates[hit][event_loss[hit] == x].sum() for x in losses])
    above = np.concatenate([np.cumsum(at[::-1])[::-1][1:], [0.0]]) if losses.size else at
    total = float(at.sum())
    # P(largest = x_j) = exp(-rate above x_j) - exp(-rate at or above x_j)
    masses = np.exp(-above) * -np.expm1(-at)
    values = np.concatenate([[0.0], losses])
    probabilities = np.concatenate([[math.exp(-total)], masses])
    return cf.Distribution.discrete(values, probabilities)


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


def _comonotonic(annual: AnnualLosses, levels: tuple[float, ...]) -> list[cf.RiskLevel]:
    figures = {
        c: [_var_cvar(annual.component_distribution(c), q) for q in levels]
        for c in annual.components
    }
    result = []
    for i, q in enumerate(levels):
        parts = tuple(cf.RiskAttribution(c, f[i][0], f[i][1]) for c, f in figures.items())
        result.append(
            cf.RiskLevel(
                q,
                math.fsum(p.value_at_risk for p in parts),
                math.fsum(p.conditional_value_at_risk for p in parts),
                parts,
            )
        )
    return result


def _exact_two_state(
    annual: AnnualLosses, levels: tuple[float, ...]
) -> tuple[list[cf.RiskLevel], list[cf.Diagnostic]]:
    weights = annual.years._array()
    outcomes = []
    for c, losses in annual.components.items():
        states, inverse = np.unique(losses, return_inverse=True)
        if states.size > 2:
            raise ValueError(
                f"component {c!r} has {states.size} distinct annual losses; EXACT_TWO_STATE "
                f"needs at most two (use RESAMPLED)"
            )
        if states.size == 1:
            lower_mass, lower, upper = 1.0, float(states[0]), float(states[0])
        else:
            lower_mass = math.fsum(weights[inverse == 0])
            lower, upper = float(states[0]), float(states[1])
        outcomes.append(
            cf.BinaryOutcome(
                c,
                lower_rank_mass=lower_mass,
                lower_impact=lower,
                upper_rank_mass=1.0 - lower_mass,
                upper_impact=upper,
            )
        )
    result = cf.compute_risk(outcomes, levels=levels)
    diagnostics = [
        info(
            "independence_exact",
            "independence bracket by compute_risk over two-state components",
            "/independent",
            branch_count=result.branch_count,
        )
    ]
    return [result.at(q) for q in levels], diagnostics


def _resampled(
    annual: AnnualLosses, levels: tuple[float, ...], samples: int, seed: int
) -> tuple[list[cf.RiskLevel], list[cf.Diagnostic]]:
    _check_levels(levels, 1.0 / samples, "sample")
    weights = annual.years._array()
    n_years = len(weights)
    probabilities = weights / weights.sum()

    def draws() -> Iterable[tuple[str, FloatArray]]:
        # The same generator and order on every pass, so the draws repeat exactly.
        rng = np.random.default_rng(seed)
        for c, losses in annual.components.items():
            yield c, losses[rng.choice(n_years, size=samples, p=probabilities)]

    totals = np.zeros(samples)
    for _, drawn in draws():
        totals += drawn
    law = cf.Distribution.empirical(totals)
    equal = np.full(samples, 1.0 / samples)
    result = []
    for q in levels:
        var, cvar = _var_cvar(law, q)
        result.append(cf.RiskLevel(q, var, cvar, _shares(var, cvar, q, equal, totals, draws())))
    diagnostics = [
        info(
            "independence_resampled",
            "independence bracket from years drawn independently for each component by their "
            "weights; its figures carry sampling error",
            "/independent",
            samples=samples,
            seed=seed,
        )
    ]
    return result, diagnostics


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
    if not isinstance(independence, IndependenceMethod):
        raise TypeError("independence must be an IndependenceMethod")
    if not annual.components:
        raise ValueError("brackets need at least one component")
    qs = _check_levels(levels, min(annual.years.weights), "year")
    if independence is IndependenceMethod.RESAMPLED:
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise ValueError("RESAMPLED needs samples, a positive integer")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("RESAMPLED needs seed, an integer")
        independent, diagnostics = _resampled(annual, qs, samples, seed)
    else:
        if samples is not None or seed is not None:
            raise ValueError("EXACT_TWO_STATE takes no samples or seed")
        independent, diagnostics = _exact_two_state(annual, qs)
    comonotonic = _comonotonic(annual, qs)
    from_events = annual.risk(qs)
    return tuple(
        Bracket(
            level=q,
            comonotonic=comonotonic[i],
            independent=independent[i],
            from_events=from_events[i],
            independence_method=independence,
            samples=samples,
            seed=seed,
            diagnostics=tuple(diagnostics),
        )
        for i, q in enumerate(qs)
    )


def summary_inputs(annual: AnnualLosses) -> Mapping[str, object]:
    """``totals`` and ``components`` in the form ``summarize_annual_losses`` of crc-framework-rs
    pull request #27 takes them. Only for equal year weights: that summary has no year weights,
    and unequal weights are an error here rather than a silent expansion."""
    if not annual.years.equal_weights:
        raise ValueError(
            "summarize_annual_losses has no year weights; these years have unequal weights "
            "and are not expanded to equal-weight trials"
        )
    return {
        "totals": annual.totals.copy(),
        "components": {c: v.copy() for c, v in annual.components.items()},
    }
