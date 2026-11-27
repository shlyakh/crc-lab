"""FR1, FR2 (CH-27): the substation envelope in curves.yaml and its CRC impacts."""

from __future__ import annotations

import numpy as np
import pytest

from flood_lab.curves import envelope
from flood_lab.risk import crc_adapter

CURVES = crc_adapter.load()
SUB = {e["id"]: e for e in CURVES["substation_curves"]}


def test_every_family_is_present_for_each_tier() -> None:
    for kv in (345.0, 138.0, 500.0):
        chosen = envelope.envelope_for(kv)
        assert chosen is not None and set(chosen) == {"low", "high", "williams_min", "bor"}
        assert set(chosen.values()) <= set(SUB)
    assert envelope.envelope_for(None) is None
    assert envelope.envelope_for(float("nan")) is None
    assert envelope.envelope_for(13.0) is None  # below the lowest Hazus class


def test_hazus_tiers() -> None:
    assert envelope.voltage_tier(345.0) == "medium"
    assert envelope.voltage_tier(350.0) == "high"
    assert envelope.voltage_tier(138.0) == "low"
    assert envelope.voltage_tier(34.5) == "low"


@pytest.mark.parametrize("cid", sorted(SUB))
def test_curve_runs_from_zero_to_the_maximum_monotone_and_bounded(cid: str) -> None:
    pts = np.array(SUB[cid]["points"])
    assert pts[0].tolist() == [0.0, 0.0]
    assert pts[-1, 0] == CURVES["max_depth_m"]["value"] == envelope.MAX_DEPTH_M
    assert np.all(np.diff(pts[:, 0]) > 0)
    assert np.all(np.diff(pts[:, 1]) >= 0)
    assert np.all((pts[:, 1] >= 0) & (pts[:, 1] <= 1))
    assert SUB[cid]["tag"] in ("S", "I", "P") and SUB[cid]["source"]


def test_values_at_the_published_depths() -> None:
    """CH-27's comparison table, recomputed from curves.yaml."""
    imp = crc_adapter.substation_impacts(CURVES)
    at = np.array([0.5, 1.0, 2.0, 3.0])
    assert np.round(imp["nirandjan_F2"].evaluate(at), 3).tolist() == [0.033, 0.063, 0.096, 0.157]
    assert np.round(imp["bor_hv345_anchored"].evaluate(at), 3).tolist() == [
        0.032,
        0.171,
        0.501,
        0.737,
    ]
    assert imp["williams_substation_max"].evaluate(at).tolist() == [0.334, 0.484, 0.648, 0.755]
    assert imp["williams_distribution_substation_min"].evaluate(at).tolist() == [
        0.146,
        0.274,
        0.433,
        0.513,
    ]


def test_low_below_high_everywhere() -> None:
    imp = crc_adapter.substation_impacts(CURVES)
    d = np.linspace(0, envelope.MAX_DEPTH_M, 601)
    low = imp["nirandjan_F2"].evaluate(d)
    for tier in ("grid_exit_point", "substation", "distribution_substation"):
        assert np.all(imp[f"williams_{tier}_max"].evaluate(d) >= low)
        assert np.all(
            imp[f"williams_{tier}_max"].evaluate(d) >= imp[f"williams_{tier}_min"].evaluate(d)
        )


def test_crc_refuses_a_depth_past_the_table() -> None:
    import crc_framework as cf

    imp = crc_adapter.substation_impacts(CURVES)["nirandjan_F2"]
    with pytest.raises(cf.ImpactError):
        imp.evaluate(np.array([envelope.MAX_DEPTH_M + 0.01]))


def test_building_curves_build_in_crc() -> None:
    imps = crc_adapter.building_impacts(CURVES)
    assert len(imps) == len(CURVES["building_curves"]) > 0
    for e in CURVES["building_curves"]:
        assert e["datum"] == "above first floor"
        assert len(e["points"]) == 29
