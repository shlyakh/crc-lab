"""P-6: the annual losses of crc_event_loss against Oasis LMF's exceedance-probability tables.

Oasis LMF (BSD-3-Clause) is a test dependency only; crc_event_loss never imports it. The
package's year sums and year maxima (AGGREGATE and OCCURRENCE) are handed to Oasis's own
EPT writers, ``write_ept_weighted`` for period weights and ``write_ept`` for equal ones
(``oasislmf.pytools.lec.aggreports.write_tables``), which rank the periods and give the return
period, loss and TVaR of each rank (AEP and OEP rows). Oasis's sum and maximum per period are
not driven here: they read its binary summary streams.

Expected differences, each asserted below rather than hidden:

- Return period. Oasis gives the k-th largest loss L_k the return period 1 / W_k, W_k the
  cumulative weight of the k largest years, i.e. P(X >= L_k) = W_k. CRC's exceedance agrees.
  CRC's VaR is the lower quantile (P-1): any level q with 1 - q strictly between W_(k-1) and
  W_k gives L_k. At a return period that falls between two ranks Oasis interpolates linearly
  in the return period, so its loss lies at or above CRC's VaR at 1 - 1/T. At a return period
  that is a rank's own, T = 1 / W_k, Oasis gives L_k and CRC's lower quantile at 1 - W_k gives
  L_(k+1), one rank lower: P(X <= L_(k+1)) = 1 - W_k already reaches the level.
- TVaR with period weights. Oasis's TVaR at rank k is the running mean of the k largest losses
  with every period counted once (``tvar - (tvar - value) / i``), also in the weighted writer;
  CRC's CVaR at 1 - W_k is the weighted mean. They agree for equal weights only.

Oasis holds losses in float32 (``OASIS_FLOAT`` defaults to f4), so the losses here are whole
numbers and comparisons allow 1e-6 relative.
"""

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
    YearWeights,
    annual_losses,
)

pytest.importorskip("oasislmf")
from oasislmf.pytools.common.data import periods_dtype  # noqa: E402
from oasislmf.pytools.lec.aggreports.write_tables import (  # noqa: E402
    write_ept,
    write_ept_weighted,
)
from oasislmf.pytools.lec.data import (  # noqa: E402
    AEP,
    AEPTVAR,
    MEANDR,
    OEP,
    OEPTVAR,
    EPT_dtype,
    LOSSVEC2MAP_dtype,
)

REL = 1e-6
CODES = {AnnualMeasure.AGGREGATE: (AEP, AEPTVAR), AnnualMeasure.OCCURRENCE: (OEP, OEPTVAR)}


def _table(years: YearWeights, rows: list[tuple[str, str, str, float]]) -> EventLossTable:
    """rows: (event, year, component, loss)."""
    events = EventSet.synthetic_years(
        {e: y for e, y, _, _ in rows}, years=years, description="cross-check, made up"
    )
    return EventLossTable.from_losses(
        events,
        pa.table(
            {
                "event_id": [e for e, _, _, _ in rows],
                "component_id": [c for _, _, c, _ in rows],
                "loss": [x for _, _, _, x in rows],
            }
        ),
        currency="USD",
        valuation_basis="v",
        label="l",
    )


def _oasis(annual: AnnualLosses, return_periods: list[int] | None = None):
    """Oasis EPT rows (return period, loss) and TVaR rows for the annual totals."""
    eptype, eptype_tvar = CODES[annual.measure]
    weights = np.asarray(annual.years.weights)
    used = annual.totals > 0  # Oasis lists the periods with a loss
    n = int(used.sum())
    items = np.zeros(n, dtype=LOSSVEC2MAP_dtype)
    items["summary_id"] = 1
    items["period_no"] = np.flatnonzero(used) + 1
    items["period_weighting"] = weights[used]
    items["value"] = annual.totals[used]
    start_end = np.array([[0, n]], dtype=np.int32)
    buffer = np.zeros(1024, dtype=EPT_dtype)
    use_rp = return_periods is not None
    rps = np.array(sorted(return_periods or [], reverse=True), dtype=np.int32)
    if annual.years.equal_weights:
        chunks = write_ept(
            buffer, items, start_end, len(weights), MEANDR, eptype, eptype_tvar, use_rp, rps, 1
        )
    else:
        unused = np.zeros(int((~used).sum()), dtype=periods_dtype)
        unused["period_no"] = np.flatnonzero(~used) + 1
        unused["weighting"] = weights[~used]
        chunks = write_ept_weighted(
            buffer, items, start_end, 1.0, MEANDR, eptype, eptype_tvar, unused, use_rp, rps, 1
        )
    out = np.concatenate([c.copy() for c in chunks])
    ep = out[out["EPType"] == eptype]
    tvar = out[out["EPType"] == eptype_tvar]
    return (
        [(float(r["ReturnPeriod"]), float(r["Loss"])) for r in ep],
        [(float(r["ReturnPeriod"]), float(r["Loss"])) for r in tvar],
    )


def _ranked(annual: AnnualLosses) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Positive totals from the largest, their weights and cumulative weights W_k."""
    weights = np.asarray(annual.years.weights)
    order = np.argsort(-annual.totals, kind="stable")
    order = order[annual.totals[order] > 0]
    return annual.totals[order], weights[order], np.cumsum(weights[order])


def _weighted() -> EventLossTable:
    # y1, y2 stand for 6 of 10 years (0.3 each); y3 to y6 for 4 (0.1 each).
    years = YearWeights.stratified({"s1": (6, ["y1", "y2"]), "s2": (4, ["y3", "y4", "y5", "y6"])})
    return _table(
        years,
        [
            ("e1", "y1", "a", 40.0),
            ("e2", "y1", "b", 30.0),
            ("e3", "y2", "a", 10.0),
            ("e4", "y3", "b", 200.0),
            ("e5", "y3", "a", 50.0),
            ("e6", "y4", "a", 120.0),
            ("e7", "y5", "b", 60.0),
            ("e8", "y5", "b", 20.0),
        ],
    )


def _equal() -> EventLossTable:
    years = YearWeights.equal([f"y{i}" for i in range(8)])
    rows = [
        ("e1", "y0", "a", 300.0),
        ("e2", "y0", "b", 100.0),
        ("e3", "y1", "a", 50.0),
        ("e4", "y2", "b", 250.0),
        ("e5", "y3", "a", 120.0),
        ("e6", "y3", "b", 70.0),
        ("e7", "y5", "a", 30.0),
        ("e8", "y6", "b", 500.0),
    ]
    return _table(years, rows)


@pytest.mark.parametrize("build", [_weighted, _equal], ids=["weighted", "equal"])
@pytest.mark.parametrize("measure", [AnnualMeasure.AGGREGATE, AnnualMeasure.OCCURRENCE])
def test_ranked_losses_and_return_periods(build, measure) -> None:
    annual = annual_losses(build(), measure=measure)
    law = annual.distribution()
    losses, _, cumulative = _ranked(annual)
    assert len(set(losses.tolist())) == len(losses)  # distinct, so ranks are unambiguous
    ep, _ = _oasis(annual)
    assert [x for _, x in ep] == losses.tolist()
    previous = 0.0
    for (period, loss), w in zip(ep, cumulative, strict=True):
        # Oasis: return period 1 / W_k; CRC: P(X >= L_k) = W_k
        assert math.isclose(period, 1 / w, rel_tol=REL)
        assert math.isclose(float(law.exceedance(loss, inclusive=True)), w, rel_tol=1e-12)
        # CRC's VaR inside the rank's interval of levels is the same loss (no interpolation).
        assert float(law.quantile(1 - (previous + w) / 2)) == loss
        previous = w


@pytest.mark.parametrize("build", [_weighted, _equal], ids=["weighted", "equal"])
@pytest.mark.parametrize("measure", [AnnualMeasure.AGGREGATE, AnnualMeasure.OCCURRENCE])
def test_interpolated_return_periods(build, measure) -> None:
    annual = annual_losses(build(), measure=measure)
    largest = round(1 / min(annual.years.weights))
    periods = [p for p in (2, 3, 4, 5, 8, 10) if p <= largest]
    losses, _, cumulative = _ranked(annual)
    ep, _ = _oasis(annual, periods)
    by_period = dict(ep)
    rank_periods = 1 / cumulative
    for period in periods:
        oasis = by_period[float(period)]
        # Oasis: linear in the return period between the two ranks around it.
        k = int(np.searchsorted(-rank_periods, -period))  # first rank with RP <= period
        if math.isclose(rank_periods[k], period, rel_tol=1e-9):
            expected = losses[k]
        else:
            hi_rp, lo_rp = rank_periods[k - 1], rank_periods[k]
            expected = (period - lo_rp) * (losses[k - 1] - losses[k]) / (hi_rp - lo_rp) + losses[k]
        assert math.isclose(oasis, expected, rel_tol=REL)
        # CRC (P-1): the lower quantile, at or below Oasis's interpolated loss.
        (level,) = annual.risk([1 - 1 / period])
        assert level.value_at_risk <= oasis * (1 + REL)
        assert level.value_at_risk in losses.tolist() or level.value_at_risk == 0
        if annual.years.equal_weights and math.isclose(rank_periods[k], period, rel_tol=1e-9):
            # At a return period that is a rank's own (1 / W_k), P(X <= L_(k+1)) = 1 - W_k
            # already reaches the level, so CRC's VaR is the next smaller loss, one rank below
            # Oasis. (Equal weights only: CRC counts years exactly there; with weights the
            # cumulative mass is a float sum and may fall either side of the level.)
            below = losses[k + 1] if k + 1 < len(losses) else 0.0
            assert level.value_at_risk == below < oasis


@pytest.mark.parametrize("measure", [AnnualMeasure.AGGREGATE, AnnualMeasure.OCCURRENCE])
def test_tvar_equal_weights_agrees(measure) -> None:
    annual = annual_losses(_equal(), measure=measure)
    n = len(annual.years.year_ids)
    _, tvar = _oasis(annual)
    for k, (_, oasis) in enumerate(tvar, start=1):
        if k == n:
            break
        (level,) = annual.risk([1 - k / n])
        assert math.isclose(oasis, level.conditional_value_at_risk, rel_tol=REL)


@pytest.mark.parametrize("measure", [AnnualMeasure.AGGREGATE, AnnualMeasure.OCCURRENCE])
def test_tvar_with_period_weights_differs_as_explained(measure) -> None:
    annual = annual_losses(_weighted(), measure=measure)
    losses, weights, cumulative = _ranked(annual)
    _, tvar = _oasis(annual)
    differs = 0
    for k, (_, oasis) in enumerate(tvar, start=1):
        # Oasis: every period once.
        assert math.isclose(oasis, losses[:k].mean(), rel_tol=REL)
        if cumulative[k - 1] >= 1 - 1e-12:
            continue
        (level,) = annual.risk([1 - cumulative[k - 1]])
        # CRC: weighted by the year masses.
        weighted = float(losses[:k] @ weights[:k]) / cumulative[k - 1]
        assert math.isclose(level.conditional_value_at_risk, weighted, rel_tol=1e-9)
        differs += not math.isclose(oasis, weighted, rel_tol=REL)
    assert differs > 0
