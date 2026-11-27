"""Annual sums with weighted years, occurrence ties, the P-2 refusal, rates and brackets."""

from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from crc_event_loss import (
    AnnualLosses,
    AnnualMeasure,
    EventLossTable,
    EventSet,
    IndependenceMethod,
    YearWeights,
    annual_losses,
    brackets,
    occurrence_distribution,
    summary_inputs,
)


def _losses(events: EventSet, rows: list[tuple[str, str, float]]) -> EventLossTable:
    event_ids, component_ids, loss = zip(*rows, strict=True)
    return EventLossTable.from_losses(
        events,
        pa.table(
            {"event_id": list(event_ids), "component_id": list(component_ids), "loss": list(loss)}
        ),
        currency="USD",
        valuation_basis="v",
        label="l",
    )


def _stratified() -> EventLossTable:
    # Years y1, y2 stand for 6 of 10 years (0.3 each); y3 to y6 for 4 (0.1 each).
    years = YearWeights.stratified({"s1": (6, ["y1", "y2"]), "s2": (4, ["y3", "y4", "y5", "y6"])})
    events = EventSet.synthetic_years(
        {"e1": "y1", "e2": "y3", "e3": "y4", "e4": "y4"}, years=years, description="d"
    )
    return _losses(
        events,
        [
            ("e1", "a", 10.0),
            ("e2", "a", 50.0),
            ("e2", "b", 30.0),
            ("e3", "b", 100.0),
            ("e4", "a", 20.0),
        ],
    )


def test_weighted_years_worked_by_hand() -> None:
    annual = annual_losses(_stratified(), measure=AnnualMeasure.AGGREGATE)
    np.testing.assert_array_equal(annual.totals, [10, 0, 80, 120, 0, 0])
    np.testing.assert_array_equal(annual.components["a"], [10, 0, 50, 20, 0, 0])
    np.testing.assert_array_equal(annual.components["b"], [0, 0, 30, 100, 0, 0])
    assert '"kind":"discrete"' in annual.distribution().to_json()
    # Annual loss 0 (mass 0.5), 10 (0.3), 80 (0.1), 120 (0.1).
    level_85, level_60 = annual.risk([0.85, 0.6])
    # q = 0.85: VaR 80; CVaR over tail 0.15 = (120 * 0.1 + 80 * 0.05) / 0.15 = 106.67.
    assert level_85.value_at_risk == 80
    assert math.isclose(level_85.conditional_value_at_risk, 16 / 0.15, rel_tol=1e-12)
    shares = {s.id: s for s in level_85.attribution}
    # a: (20 * 0.1 + 50 * 0.05) / 0.15 = 30; b: (100 * 0.1 + 30 * 0.05) / 0.15 = 76.67
    assert math.isclose(shares["a"].conditional_value_at_risk, 30, rel_tol=1e-12)
    assert math.isclose(shares["b"].conditional_value_at_risk, 11.5 / 0.15, rel_tol=1e-12)
    assert (shares["a"].value_at_risk, shares["b"].value_at_risk) == (50, 30)
    # q = 0.6: VaR 10; CVaR = (12 + 8 + 10 * 0.2) / 0.4 = 55; a 22.5, b 32.5.
    assert level_60.value_at_risk == 10
    assert math.isclose(level_60.conditional_value_at_risk, 55, rel_tol=1e-12)
    shares = {s.id: s for s in level_60.attribution}
    assert math.isclose(shares["a"].conditional_value_at_risk, 22.5, rel_tol=1e-12)
    assert math.isclose(shares["b"].conditional_value_at_risk, 32.5, rel_tol=1e-12)
    assert (shares["a"].value_at_risk, shares["b"].value_at_risk) == (10, 0)
    with pytest.raises(ValueError, match="unequal weights"):
        summary_inputs(annual)


def test_weighted_occurrence() -> None:
    annual = annual_losses(_stratified(), measure=AnnualMeasure.OCCURRENCE)
    np.testing.assert_array_equal(annual.totals, [10, 0, 80, 100, 0, 0])
    np.testing.assert_array_equal(annual.components["a"], [10, 0, 50, 0, 0, 0])
    np.testing.assert_array_equal(annual.components["b"], [0, 0, 30, 100, 0, 0])


def test_level_beyond_the_years_is_refused() -> None:
    annual = annual_losses(_stratified(), measure=AnnualMeasure.AGGREGATE)
    # The smallest year mass is 0.1: tail mass 0.05 has no year to stand for it.
    with pytest.raises(ValueError, match=r"level 0\.95 .* smallest year mass 0\.1"):
        annual.risk([0.95])
    with pytest.raises(ValueError, match=r"level 0\.95"):
        brackets(
            annual, levels=[0.95], independence=IndependenceMethod.RESAMPLED, samples=10, seed=0
        )
    # 1 - 0.9 is 0.09999999999999998 in floating point; the level is still admitted.
    (level,) = annual.risk([0.9])
    assert level.value_at_risk == 80


def test_occurrence_and_aggregate_with_ties() -> None:
    years = YearWeights.equal(["y0", "y1", "y2"])
    events = EventSet.synthetic_years(
        {"e2": "y0", "e1": "y0", "e3": "y1", "e4": "y1", "e5": "y2", "e6": "y2"},
        years=years,
        description="d",
    )
    table = _losses(
        events,
        [
            ("e2", "a", 30.0),  # y0: e1 and e2 both lose 30; e1 has the smaller id
            ("e1", "b", 30.0),
            ("e3", "a", 10.0),  # y1: e4 is larger
            ("e4", "a", 5.0),
            ("e4", "b", 15.0),
            ("e5", "a", 0.0),  # y2: two events of loss 0, a tie that decides nothing
            ("e6", "b", 0.0),
        ],
    )
    occurrence = annual_losses(table, measure=AnnualMeasure.OCCURRENCE)
    np.testing.assert_array_equal(occurrence.totals, [30, 20, 0])
    np.testing.assert_array_equal(occurrence.components["a"], [0, 5, 0])
    np.testing.assert_array_equal(occurrence.components["b"], [30, 15, 0])
    ties = {d.code: d for d in occurrence.diagnostics}["occurrence_ties"]
    assert ties.details["count"] == 1
    aggregate = annual_losses(table, measure=AnnualMeasure.AGGREGATE)
    np.testing.assert_array_equal(aggregate.totals, [60, 30, 0])
    np.testing.assert_array_equal(aggregate.components["a"], [30, 15, 0])
    inputs = summary_inputs(aggregate)
    np.testing.assert_array_equal(inputs["totals"], [60, 30, 0])
    assert AnnualLosses.from_json(occurrence.to_json()) == occurrence


def test_occurrence_distribution_of_rates() -> None:
    events = EventSet.annual_rates({"e1": 0.1, "e2": 0.2, "e3": 0.05, "e4": 0.3}, description="r")
    table = _losses(
        events,
        [("e1", "a", 100.0), ("e2", "a", 50.0), ("e3", "a", 60.0), ("e3", "b", 40.0)],
    )  # e4 reaches nothing
    law = occurrence_distribution(table)
    # P(max = 0) = exp(-0.35); P(max = 50) = exp(-0.15) - exp(-0.35); P(max = 100) = 1 - exp(-0.15)
    masses = law.mass([0.0, 50.0, 100.0])
    expected = [math.exp(-0.35), math.exp(-0.15) - math.exp(-0.35), 1 - math.exp(-0.15)]
    np.testing.assert_allclose(masses, expected, rtol=1e-12)
    with pytest.raises(ValueError, match="synthetic years"):
        annual_losses(table, measure=AnnualMeasure.AGGREGATE)


def test_exact_two_state_against_resampled() -> None:
    years = YearWeights.equal([f"y{i}" for i in range(10)])
    events = EventSet.synthetic_years(
        {"e0": "y0", "e1": "y1", "e2": "y2"}, years=years, description="d"
    )
    table = _losses(
        events,
        [("e0", "a", 100.0), ("e1", "a", 100.0), ("e2", "b", 50.0), ("e0", "c", 200.0)],
    )
    annual = annual_losses(table, measure=AnnualMeasure.AGGREGATE)
    # Under independence P(total <= 50) = 0.72 and P(total <= 100) = 0.882: VaR at 0.85 is 100,
    # away from a step, so that sampling error cannot move it.
    (exact,) = brackets(annual, levels=[0.85], independence=IndependenceMethod.EXACT_TWO_STATE)
    (sampled,) = brackets(
        annual, levels=[0.85], independence=IndependenceMethod.RESAMPLED, samples=200_000, seed=7
    )
    assert exact.samples is None and exact.seed is None
    assert exact.comonotonic == sampled.comonotonic
    assert exact.independent.value_at_risk == sampled.independent.value_at_risk == 100
    assert math.isclose(
        exact.independent.conditional_value_at_risk,
        sampled.independent.conditional_value_at_risk,
        rel_tol=0.02,
    )
    for e, s in zip(exact.independent.attribution, sampled.independent.attribution, strict=True):
        assert e.id == s.id
        assert math.isclose(e.conditional_value_at_risk, s.conditional_value_at_risk, rel_tol=0.05)
    with pytest.raises(ValueError, match="needs samples"):
        brackets(annual, levels=[0.9], independence=IndependenceMethod.RESAMPLED)

    three_states = _losses(events, [("e0", "a", 100.0), ("e1", "a", 50.0)])
    many = annual_losses(three_states, measure=AnnualMeasure.AGGREGATE)
    with pytest.raises(ValueError, match="'a' has 3 distinct"):
        brackets(many, levels=[0.9], independence=IndependenceMethod.EXACT_TWO_STATE)


def test_shares_sum_to_cvar() -> None:
    rng = np.random.default_rng(3)
    n = 40
    years = YearWeights.equal([f"y{i}" for i in range(n)])
    year_of = {f"e{i}": f"y{rng.integers(n)}" for i in range(120)}
    events = EventSet.synthetic_years(year_of, years=years, description="d")
    rows = [
        (e, c, float(rng.integers(0, 4) * 10))
        for e in year_of
        for c in ("a", "b", "c")
        if rng.random() < 0.5
    ]
    annual = annual_losses(_losses(events, rows), measure=AnnualMeasure.AGGREGATE)
    for level in annual.risk([0.5, 0.8, 0.9, 0.95, 0.975]):
        added = math.fsum(s.conditional_value_at_risk for s in level.attribution)
        assert math.isclose(added, level.conditional_value_at_risk, rel_tol=1e-9)
        added = math.fsum(s.value_at_risk for s in level.attribution)
        assert math.isclose(added, level.value_at_risk, rel_tol=1e-9)
