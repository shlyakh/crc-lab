"""Event sets, year weights, building the table, failures and the Parquet file."""

from __future__ import annotations

import crc_framework as cf
import numpy as np
import pyarrow as pa
import pytest

from crc_event_loss import (
    AnnualMeasure,
    EventLossTable,
    EventSet,
    Exposure,
    FailurePolicy,
    MissingIntensity,
    Timeline,
    YearWeights,
    annual_losses,
)


def test_year_weights() -> None:
    equal = YearWeights.equal(["a", "b", "c", "d"])
    assert equal.weights == (0.25,) * 4 and equal.equal_weights
    # A stratum of 6 years with 2 run, and one of 4 years with 4 run: total 10 years.
    strata = YearWeights.stratified(
        {"wet": (6, ["y1", "y2"]), "dry": (4, ["y3", "y4", "y5", "y6"])}
    )
    assert strata.year_ids == ("y1", "y2", "y3", "y4", "y5", "y6")
    assert strata.weights == (0.3, 0.3, 0.1, 0.1, 0.1, 0.1)
    assert not strata.equal_weights
    with pytest.raises(ValueError, match="sum to"):
        YearWeights(("a", "b"), (0.5, 0.4))
    with pytest.raises(ValueError, match="positive"):
        YearWeights(("a", "b"), (1.0, 0.0))
    with pytest.raises(ValueError, match="unique"):
        YearWeights(("a", "a"), (0.5, 0.5))
    with pytest.raises(ValueError, match="were run"):
        YearWeights.stratified({"s": (1, ["y1", "y2"])})


def test_event_sets_and_json() -> None:
    years = YearWeights.stratified({"s1": (6, ["y1", "y2"]), "s2": (4, ["y3", "y4", "y5", "y6"])})
    events = EventSet.synthetic_years(
        {"e1": "y1", "e2": "y3"}, years=years, description="d", provenance={"generator": "g"}
    )
    assert events.timeline is Timeline.SYNTHETIC_YEARS
    assert events.rate("e1") == 0.3 and events.rate("e2") == 0.1
    assert EventSet.from_json(events.to_json()) == events
    rates = EventSet.annual_rates({"e1": 0.1, "e2": 0.0}, description="r")
    assert rates.years is None and rates.rate("e1") == 0.1
    assert EventSet.from_json(rates.to_json()) == rates
    assert rates != events
    with pytest.raises(ValueError, match="not in years"):
        EventSet.synthetic_years({"e1": "y9"}, years=years, description="d")
    with pytest.raises(ValueError, match="non-negative"):
        EventSet.annual_rates({"e1": -1.0}, description="r")
    with pytest.raises(TypeError):
        EventSet()


def test_refused_value_becomes_a_failure(make_table) -> None:
    # 4 m lies outside the curve's domain [0, 3]: CRC refuses it, the other rows keep ratios.
    table = make_table([1.0, 4.0, 0.5, 3.0])
    assert len(table.failures) == 1
    failure = table.failures[0]
    assert (failure.event_id, failure.component_id, failure.intensity) == ("e1", "b", 4.0)
    assert failure.code == "out_of_domain"
    rows = table.to_arrow()
    assert rows.num_rows == 3
    assert rows.column("loss").to_pylist() == [50.0, 25.0, 200.0]
    codes = {d.code: d for d in table.diagnostics}
    assert codes["impact_refused_values"].details["count"] == 1
    assert codes["impact_refused_values"].details["codes"] == {"out_of_domain": 1}

    with pytest.raises(ValueError, match="REFUSE"):
        annual_losses(table, measure=AnnualMeasure.AGGREGATE)
    annual = annual_losses(
        table, measure=AnnualMeasure.AGGREGATE, failures=FailurePolicy.EXCLUDE_COMPONENT
    )
    assert list(annual.components) == ["a"]
    np.testing.assert_array_equal(annual.totals, [75, 0, 0, 0])
    excluded = {d.code: d for d in annual.diagnostics}["components_excluded"]
    assert excluded.details["component_ids"] == ("b",)
    assert excluded.details["count"] == 1


def test_missing_pairs_and_unknown_ids(impact) -> None:
    years = YearWeights.equal(["y0", "y1"])
    events = EventSet.synthetic_years({"e1": "y0", "e2": "y1"}, years=years, description="d")
    depth = impact.input
    exposures = (Exposure("a", 10.0, "curve"), Exposure("b", 10.0, "curve"))

    def build(event_ids, component_ids, **kwargs):
        hits = pa.table(
            {
                "event_id": event_ids,
                "component_id": component_ids,
                "value": [1.0] * len(event_ids),
            }
        )
        return EventLossTable.from_intensities(
            events,
            hits,
            intensity=kwargs.pop("intensity", depth),
            exposures=exposures,
            impacts=kwargs.pop("impacts", {"curve": impact}),
            currency="USD",
            valuation_basis="v",
            label="l",
            **kwargs,
        )

    table = build(["e1"], ["a"])
    absent = {d.code: d for d in table.diagnostics}["pairs_absent_as_no_loss"]
    assert absent.details["count"] == 3
    with pytest.raises(ValueError, match="3 .* pairs have no intensity"):
        build(["e1"], ["a"], missing=MissingIntensity.ERROR)
    complete = build(["e1", "e1", "e2", "e2"], ["a", "b", "a", "b"], missing=MissingIntensity.ERROR)
    assert complete.to_arrow().num_rows == 4
    with pytest.raises(ValueError, match="not in the event set"):
        build(["e9"], ["a"])
    with pytest.raises(ValueError, match="no exposure"):
        build(["e1"], ["z"])
    with pytest.raises(ValueError, match="repeat"):
        build(["e1", "e1"], ["a", "a"])
    with pytest.raises(ValueError, match="takes"):
        build(["e1"], ["a"], intensity=cf.DepthAboveGround(unit=cf.LengthUnit.FOOT))
    not_ratio = cf.Impact.tabulated([(0, 0), (1, 1)], input=depth, output=depth)
    with pytest.raises(ValueError, match="not a cf.Ratio"):
        build(["e1"], ["a"], impacts={"curve": not_ratio})


def test_parquet_round_trip_and_no_overwrite(make_table, tmp_path) -> None:
    table = make_table([1.0, 4.0, 0.5, 3.0])  # with one failure, to carry it through
    path = tmp_path / "table.parquet"
    assert table.write(path) == path
    back = EventLossTable.read(path)
    assert back == table
    assert back.failures == table.failures and back.diagnostics == table.diagnostics
    assert back.loss == cf.Measurement(quantity="loss", unit="USD")
    metadata = back.to_arrow().schema.metadata[b"crc_event_loss"]
    assert b'"format":"crc-event-loss"' in metadata and b'"version":"0.1"' in metadata
    with pytest.raises(FileExistsError):
        table.write(path)
    other = make_table()
    other.write(path, overwrite=True)
    assert EventLossTable.read(path) == other
    assert EventLossTable.read(path) != table
    assert sorted(p.name for p in tmp_path.iterdir()) == ["table.parquet"]


def test_from_losses_round_trip(tmp_path) -> None:
    events = EventSet.annual_rates({"e1": 0.1, "e2": 0.2}, description="r")
    losses = pa.table({"event_id": ["e1", "e2"], "component_id": ["x", "y"], "loss": [5.0, 7.0]})
    table = EventLossTable.from_losses(
        events, losses, currency="EUR", valuation_basis="v", label="l"
    )
    assert table.component_ids == ("x", "y")
    path = table.write(tmp_path / "t.parquet")
    assert EventLossTable.read(path) == table
    bad = pa.table({"event_id": ["e1"], "component_id": ["x"], "loss": [-1.0]})
    with pytest.raises(ValueError, match="non-negative"):
        EventLossTable.from_losses(events, bad, currency="EUR", valuation_basis="v", label="l")
