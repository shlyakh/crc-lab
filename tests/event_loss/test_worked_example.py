"""The worked example of the design note (event-loss-extension.md, section 3), by hand."""

from __future__ import annotations

import math

import numpy as np

from crc_event_loss import AnnualMeasure, IndependenceMethod, annual_losses, brackets


def test_totals_and_components(table) -> None:
    annual = annual_losses(table, measure=AnnualMeasure.AGGREGATE)
    np.testing.assert_array_equal(annual.totals, [175, 0, 200, 0])
    np.testing.assert_array_equal(annual.components["a"], [75, 0, 0, 0])
    np.testing.assert_array_equal(annual.components["b"], [100, 0, 200, 0])


def test_var_cvar_and_shares(table) -> None:
    annual = annual_losses(table, measure=AnnualMeasure.AGGREGATE)
    (level,) = annual.risk([0.75])
    assert level.value_at_risk == 175
    assert level.conditional_value_at_risk == 200
    shares = {a.id: a for a in level.attribution}
    assert shares["a"].conditional_value_at_risk == 0
    assert shares["b"].conditional_value_at_risk == 200
    assert shares["a"].value_at_risk == 75
    assert shares["b"].value_at_risk == 100
    # The same figures straight from the CRC distribution.
    law = annual.distribution()
    assert float(law.quantile(0.75)) == 175


def test_comonotonic_bracket(table) -> None:
    annual = annual_losses(table, measure=AnnualMeasure.AGGREGATE)
    (bracket,) = brackets(
        annual, levels=[0.75], independence=IndependenceMethod.RESAMPLED, samples=100_000, seed=1
    )
    assert bracket.comonotonic.value_at_risk == 100
    assert bracket.comonotonic.conditional_value_at_risk == 275
    assert bracket.from_events.value_at_risk == 175
    assert bracket.from_events.conditional_value_at_risk == 200
    # Full dependence bounds CVaR from above, not VaR.
    assert bracket.from_events.conditional_value_at_risk <= 275
    assert bracket.samples == 100_000 and bracket.seed == 1
    cvar = bracket.independent.conditional_value_at_risk
    added = math.fsum(a.conditional_value_at_risk for a in bracket.independent.attribution)
    assert math.isclose(added, cvar, rel_tol=1e-9)


def test_occurrence_of_year_y0(table) -> None:
    annual = annual_losses(table, measure=AnnualMeasure.OCCURRENCE)
    np.testing.assert_array_equal(annual.totals, [150, 0, 200, 0])
    np.testing.assert_array_equal(annual.components["a"], [50, 0, 0, 0])
