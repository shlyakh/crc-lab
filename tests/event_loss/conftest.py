"""Shared builders for the crc_event_loss tests: the design note's worked example (section 3)."""

from __future__ import annotations

import crc_framework as cf
import pyarrow as pa
import pytest

from crc_event_loss import EventLossTable, EventSet, Exposure, YearWeights

DEPTH = cf.DepthAboveGround(unit=cf.LengthUnit.METRE)


def curve() -> cf.Impact:
    return cf.Impact.tabulated([(0, 0), (1, 0.5), (3, 1)], input=DEPTH, output=cf.Ratio())


def example_events() -> EventSet:
    years = YearWeights.equal(["y0", "y1", "y2", "y3"])
    return EventSet.synthetic_years(
        {"e1": "y0", "e2": "y0", "e3": "y2"},
        years=years,
        description="four synthetic years, made up",
    )


def example_table(values: list[float] | None = None) -> EventLossTable:
    hits = pa.table(
        {
            "event_id": ["e1", "e1", "e2", "e3"],
            "component_id": ["a", "b", "a", "b"],
            "value": values or [1.0, 1.0, 0.5, 3.0],
        }
    )
    return EventLossTable.from_intensities(
        example_events(),
        hits,
        intensity=DEPTH,
        impacts={"curve": curve()},
        exposures=(Exposure("a", 100.0, "curve"), Exposure("b", 200.0, "curve")),
        currency="USD",
        valuation_basis="replacement cost",
        label="example",
    )


@pytest.fixture
def table() -> EventLossTable:
    return example_table()


@pytest.fixture
def make_table():
    return example_table


@pytest.fixture
def impact() -> cf.Impact:
    return curve()
