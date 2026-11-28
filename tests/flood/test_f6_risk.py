"""F6 steps 4 and 5: the study's event-loss table and its figures, on small made-up inputs whose
sums are worked by hand, and a reconciliation of the committed outputs."""

from __future__ import annotations

import json
import math

import crc_framework as cf
import numpy as np
import pandas as pd
import pytest

from crc_event_loss import (
    AnnualLosses,
    AnnualMeasure,
    EventSet,
    IndependenceMethod,
    YearWeights,
    brackets,
)
from flood_lab import paths
from flood_lab.risk import building_depth, crc_adapter
from flood_lab.risk import event_loss as el
from flood_lab.risk import metrics as mx

FT = 0.3048
LABELS = ("cat_r0001", "cat_r0002", "cat_r0003")
WEIGHTS = np.array([1.0, 2.0, 7.0])  # years each run stands for, M = 10


def _catalogue() -> el.Catalogue:
    years = YearWeights(LABELS, tuple(WEIGHTS / 10))
    events = EventSet.synthetic_years({x: x for x in LABELS}, years=years, description="test")
    return el.Catalogue(LABELS, WEIGHTS, 10, ("T1", "T2", "T2"), (1, 2, 3), events, ())


def _buildings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "LocNumber": ["A", "B", "C", "D", "E"],
            "ffh_m": [0.0, 2.0, 0.5, 0.5, np.nan],
            "basement": ["N", "Y", "N", "N", ""],
            "curve_id": ["hazus_struct_107", "hazus_struct_108", "hazus_struct_107", "", ""],
            "value_mid_used": [100.0, 1000.0, 50.0, 50.0, 50.0],
        }
    )


# walls: runs x footprints; footprint 3 is building E, footprint 2 building C (never read);
# building D has no footprint
WALLS = np.array(
    [
        [1 * FT, 0.5, np.nan, 0.0],
        [0.0, 2.0 + FT, np.nan, 0.4],
        [0.02, 0.1, np.nan, 0.0],
    ]
)
COLUMNS = np.array([0, 1, 2, -1, 3])


def _cases(dry: float = 0.05) -> el.BuildingCases:
    return el.building_cases(_buildings(), WALLS, COLUMNS, crc_adapter.load(), dry_below_m=dry)


def test_failures_are_named_never_zero() -> None:
    cases = _cases()
    assert cases.reason == ["", "", el.NOT_READ, el.NOT_IN_HAZARD, el.NO_CURVE]
    assert (cases.case[:, 2] == building_depth.Case.FAILED).all()
    # E is dry in runs 1 and 3: no loss there; failed only where wet
    assert list(cases.case[:, 4]) == [
        building_depth.Case.NO_LOSS,
        building_depth.Case.FAILED,
        building_depth.Case.NO_LOSS,
    ]


def test_sums_by_hand() -> None:
    cat = _catalogue()
    table, left_out = el.building_table(
        cat, _buildings(), _cases(), value_column="value_mid_used", label="test"
    )
    assert left_out == ["C", "D", "E"]
    annual = el.annual(table)
    # A: run 1 at 1 ft above floor, 0.12 -> 12; run 3 at 0.02 m, below the dry threshold.
    # B: run 1 0.5 - 2.0 = -1.5 m, below -4 ft, basement: read at -4 ft, 0.04 -> 40;
    #    run 2 at 1 ft, 0.21 -> 210; run 3 at -1.9 m -> 40.
    assert annual.components["A"].tolist() == pytest.approx([12.0, 0.0, 0.0])
    assert annual.components["B"].tolist() == pytest.approx([40.0, 210.0, 40.0])
    assert annual.totals.tolist() == pytest.approx([52.0, 210.0, 40.0])
    eal = mx.mean_of(annual.distribution())  # CRC's mean of the weighted years
    assert eal == pytest.approx((52 * 1 + 210 * 2 + 40 * 7) / 10)
    occurrence = el.annual(table, AnnualMeasure.OCCURRENCE)
    assert np.array_equal(occurrence.totals, annual.totals)  # one storm a year


def test_literal_dry_rule_reads_a_basement_at_any_depth() -> None:
    cases = _cases(dry=0.0)
    # A in run 3: 0.02 m above a floor at grade, read on the curve
    assert cases.case[2, 0] == building_depth.Case.READ
    assert cases.at[2, 0] == pytest.approx(0.02)


def test_weights_sum_to_m_and_catalogue_files(tmp_path) -> None:
    selection = [
        {"label": x, "rank": i + 1, "stratum": s, "weight": float(w), "synthetic_years": 10}
        for i, (x, s, w) in enumerate(zip(LABELS, ("T1", "T2", "T2"), WEIGHTS, strict=True))
    ]
    (tmp_path / "f4").mkdir()
    (tmp_path / el.SELECTION).write_text(json.dumps(selection))
    folder = tmp_path / el.PER_RUN
    folder.mkdir(parents=True)
    for i, x in enumerate([*LABELS, "ds_1h_2y"]):
        np.savez(
            folder / f"{x}.npz",
            key=np.array(json.dumps({"footprints": "k"})),
            walls=np.zeros(2, "float32"),
            site_ids=np.array(["S-1"]),
            site_lead=np.array([0.1 * i], "float32"),
        )
    cat = el.read_catalogue(tmp_path)
    assert cat.weights.sum() == 10 and cat.not_read == ("ds_1h_2y",)
    assert math.fsum(cat.events.years.weights) == pytest.approx(1.0, abs=1e-12)
    assert cat.events.rate("cat_r0003") == pytest.approx(0.7)
    depths = el.read_depths(tmp_path, cat)
    assert depths.lead[:, 0].tolist() == pytest.approx([0.0, 0.1, 0.2])
    bad = [dict(x, weight=x["weight"] + 1) for x in selection]
    (tmp_path / el.SELECTION).write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="sum to"):
        el.read_catalogue(tmp_path)


def _annual(values, weights=None) -> AnnualLosses:
    ids = tuple(f"y{i}" for i in range(len(values)))
    years = YearWeights.equal(ids) if weights is None else YearWeights(ids, tuple(weights))
    v = np.asarray(values, float)
    return AnnualLosses(
        measure=AnnualMeasure.AGGREGATE,
        years=years,
        totals=v,
        components={"p": v},
        currency="USD",
        valuation_basis="test",
        label="test",
        diagnostics=(),
    )


def test_tools_convention_against_crc() -> None:
    values = [80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]  # 8 equal years
    w = np.full(8, 1 / 8)
    # tools: return period of the k-th largest is 8 / k, so 1 in 4 is the 2nd largest
    assert mx.tools_level(np.array(values), w, 4) == 70.0
    (level,) = _annual(values).risk([0.75])
    assert level.value_at_risk == 60.0  # CRC: the 3rd largest
    # beyond the years it gives the largest loss; the callers keep T within P-2
    assert mx.tools_level(np.array(values), w, 100) == 80.0
    # with weights: 0.1 on the largest, 0.2 on the next
    assert mx.tools_level(np.array([5.0, 9.0, 1.0]), np.array([0.7, 0.1, 0.2]), 5) == 5.0


def test_bracket_inequality_on_cvar() -> None:
    rng = np.random.default_rng(3)
    a = rng.gamma(1.0, 10.0, 20) * (rng.random(20) < 0.4)
    b = a * 0.5 + rng.gamma(1.0, 5.0, 20) * (rng.random(20) < 0.2)
    years = YearWeights.equal(tuple(f"y{i}" for i in range(20)))
    annual = AnnualLosses(
        measure=AnnualMeasure.AGGREGATE,
        years=years,
        totals=a + b,
        components={"a": a, "b": b},
        currency="USD",
        valuation_basis="test",
        label="test",
        diagnostics=(),
    )
    (bracket,) = brackets(
        annual, levels=[0.9], independence=IndependenceMethod.RESAMPLED, samples=2000, seed=1
    )
    assert (
        bracket.from_events.conditional_value_at_risk
        <= bracket.comonotonic.conditional_value_at_risk * (1 + 1e-12)
    )


def test_bootstrap_repeats_and_keeps_the_original() -> None:
    # T1: 10 runs of 1 year each; T2: 10 runs of 99 years each; M = 1,000
    totals = np.array([100.0] * 5 + [10.0] * 5 + [0.0] * 5 + [5.0] * 5)
    weights = np.array([1.0] * 10 + [99.0] * 10)
    strata = ("T1",) * 10 + ("T2",) * 10
    one = mx.bootstrap(totals, weights, strata, n=50, seed=7)
    two = mx.bootstrap(totals, weights, strata, n=50, seed=7)
    assert one["values"] == two["values"]
    # each stratum keeps its mass (T1 0.01, T2 0.99) in every resample, so EAL lies within these
    eals = np.array(one["values"]["eal"])
    assert eals.min() >= 0.01 * 10 + 0.99 * 0 - 1e-9
    assert eals.max() <= 0.01 * 100 + 0.99 * 5 + 1e-9


@pytest.mark.parametrize("basement,ffh", [("N", 2.0), ("Y", 2.0), ("N", 0.3), ("Y", -0.2)])
def test_building_impact_reads_like_the_event_table(basement: str, ffh: float) -> None:
    curves = crc_adapter.load()
    cid = "hazus_struct_108" if basement == "Y" else "hazus_struct_107"
    points = next(c["points"] for c in curves["building_curves"] if c["id"] == cid)
    curve = crc_adapter.building_impacts(curves)[cid]
    impact = mx.building_impact(points, ffh, basement, dry_below_m=0.05, curve=curve)
    depths = np.array([0.0, 0.04, 0.05, 0.3, 0.77, 1.5, 2.0 + 2 * FT, ffh + 7.0])
    depths = depths[depths <= ffh + points[-1][0]]
    at, case = building_depth.curve_depth(
        np.where(depths < 0.05, 0.0, depths),
        np.full(depths.shape, ffh),
        np.full(depths.shape, basement, dtype=object),
        points[0][0],
        points[-1][0],
    )
    want = np.zeros(depths.shape)
    read = case == building_depth.Case.READ
    want[read] = np.asarray(curve.evaluate(at[read]))
    got = np.asarray(impact.evaluate(depths))
    assert got == pytest.approx(want, abs=1e-12)
    with pytest.raises(cf.ImpactError):
        impact.evaluate(np.array([ffh + points[-1][0] + 0.01]))  # BD-4


# --- the committed outputs ---------------------------------------------------------------------

OUT = paths.SITE / "data" / "f6"


@pytest.mark.skipif(not (OUT / "metrics.json").exists(), reason="F6 outputs not built")
def test_committed_outputs_reconcile() -> None:
    metrics = json.loads((OUT / "metrics.json").read_text())
    annual = pd.read_csv(OUT / "annual_losses.csv")
    assert annual["weight_years"].sum() == pytest.approx(metrics["catalogue"]["M_synthetic_years"])
    assert annual["mass"].sum() == pytest.approx(1.0, abs=1e-12)
    buildings = pd.read_csv(OUT / "buildings.csv", low_memory=False)
    subs = pd.read_csv(OUT / "substation_event_losses.csv")
    events = subs.merge(annual[["event_id", "mass"]], on="event_id")
    main = metrics["results"]["main"]
    for fam, fig in main["families"].items():
        column = annual[f"main__{fam}"]
        assert float(column @ annual["mass"]) == pytest.approx(fig["eal"], rel=1e-9)
        sub = events[events["family"] == fam]
        assert float(sub["loss_usd_2026"] @ sub["mass"]) == pytest.approx(
            fig["substations_eal"], rel=1e-9
        )
        assert float(buildings["eal_event_table"].sum()) + fig["substations_eal"] == pytest.approx(
            fig["eal"], rel=1e-9
        )
        # damage ratio times value is the loss
        merged = sub.merge(
            pd.read_csv(OUT / "substations.csv")[["LocNumber", "family", "value_mid_usd_2026"]],
            on=["LocNumber", "family"],
        )
        assert (merged["damage_ratio"] * merged["value_mid_usd_2026"]).to_numpy() == pytest.approx(
            merged["loss_usd_2026"].to_numpy(), rel=1e-9
        )
    assert float(annual["main__buildings"] @ annual["mass"]) == pytest.approx(
        main["buildings_eal"], rel=1e-9
    )
    failed = buildings["failure"].fillna("") != ""
    assert int(failed.sum()) == sum(metrics["failures"]["by_reason"].values())
    assert buildings.loc[failed, "eal_event_table"].isna().all()
