"""Two CRC 1.0.0 behaviours the flood lab's figures rest on, kept as tests (plan F0, step 1).

The full set of calls is run by ``tools/flood/f0_crc_calls.py``; these two are cheap and guard the
loss figures of FR5 against a change in a later CRC release. Expected values come from numpy.
"""

from __future__ import annotations

import numpy as np
from crc_framework import (
    DepthAboveGround,
    Distribution,
    Impact,
    LengthUnit,
    QuantileCurve,
    Ratio,
    Statistic,
    Tail,
    TailCompletion,
)


def test_loss_statistics_of_a_sample_equal_numpy() -> None:
    rng = np.random.default_rng(1)
    annual = np.where(rng.random(1000) < 0.8, 0.0, rng.gamma(2.0, 50_000.0, 1000))
    law = Distribution.empirical(annual)
    summary = law.statistics(metrics=[Statistic.MEAN, Statistic.CVAR], level=0.99, tail=Tail.UPPER)
    assert float(law.quantile(0.99)) == float(np.quantile(annual, 0.99, method="inverted_cdf"))
    assert abs(summary.values[Statistic.CVAR].value - np.sort(annual)[-10:].mean()) < 1e-6
    assert abs(summary.values[Statistic.MEAN].value - annual.mean()) < 1e-6
    for level in (0.0, 1e5, 2e5):
        assert float(law.exceedance(level)) == float((annual > level).mean())
    assert float(Distribution.from_json(law.to_json()).quantile(0.99)) == float(law.quantile(0.99))


def test_damage_distribution_of_one_asset_has_the_numpy_mean() -> None:
    points = [(0.0, 0.0), (0.5, 0.2), (1.0, 0.4), (3.0, 0.8), (10.0, 0.8)]
    damage = Impact.tabulated(points, input=DepthAboveGround(unit=LengthUnit.METRE), output=Ratio())
    depth = QuantileCurve([0.5, 0.9, 0.99, 0.998], [0.0, 0.3, 1.2, 2.5]).complete(
        TailCompletion(lower=0.0, upper=4.0)
    )
    grid = np.linspace(0.0, 1.0, 2_000_001)
    depths = np.interp(grid, [0, 0.5, 0.9, 0.99, 0.998, 1.0], [0, 0, 0.3, 1.2, 2.5, 4.0])
    expected = float(np.trapezoid(np.interp(depths, *zip(*points, strict=True)), grid))
    pushed = damage.pushforward(depth)
    mean = pushed.statistics(metrics=[Statistic.MEAN]).values[Statistic.MEAN].value
    assert abs(mean - expected) < 1e-6
    assert abs(float(damage.expectation(depth)) - expected) < 1e-6
    # linear in probability between knots: halfway from 0.9 to 0.99 the depth is halfway
    assert abs(float(depth.quantile(0.945)) - 0.75) < 1e-9
