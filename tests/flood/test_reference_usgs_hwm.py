"""FS4: the second reader of the USGS Ida high-water marks, on a five-row fixture and the real file.

Fixture rows (hwm_id): 10 non-NAVD88 datum, 20 blank height, 30 plain, 40 just outside the west
edge (about 1 m), 50 on the west edge (5 mm inside). Row 30, 20 and 10 sit at the centre point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flood_lab.reference import usgs_hwm

FIXTURE = Path(__file__).parent / "fixtures" / "usgs_hwm_small.csv"
REAL = Path("data/cache/flood/usgs-ida-high-water-marks/FilteredHWMs_NewYork.csv")


def by_id():
    return {m["hwm_id"]: m for m in usgs_hwm.marks(FIXTURE)}


def test_sorted_and_keys():
    rows = usgs_hwm.marks(FIXTURE)
    assert [m["hwm_id"] for m in rows] == [10, 20, 30, 40, 50]
    assert set(rows[0]) == {
        "hwm_id", "site_no", "longitude", "latitude", "easting_m", "northing_m",
        "vertical_datum", "elev_navd88_m", "height_above_ground_m", "uncertainty_m",
        "quality", "survey_date", "in_square",
    }  # fmt: skip


def test_conversions_by_hand():
    m = by_id()[30]
    assert m["site_no"] == "NYKIN1"
    assert (m["longitude"], m["latitude"]) == (-73.9642, 40.7048)
    assert m["elev_navd88_m"] == 3.048  # 10 ft
    assert m["height_above_ground_m"] == 0.762  # 2.5 ft
    assert m["uncertainty_m"] == 0.0305  # 0.1 ft = 0.03048
    assert m["quality"] == "Good: +/- 0.10 ft"
    assert m["survey_date"] == "9/10/2021"
    assert m["easting_m"] == pytest.approx(587500.59, abs=0.011)
    assert m["northing_m"] == pytest.approx(4506503.74, abs=0.011)
    assert m["in_square"] is True


def test_blank_height_is_none():
    m = by_id()[20]
    assert m["height_above_ground_m"] is None
    assert m["elev_navd88_m"] == 1.524  # 5 ft
    assert m["uncertainty_m"] == 0.061  # 0.2 ft = 0.06096


def test_other_datum_has_no_navd88_elevation():
    m = by_id()[10]
    assert m["vertical_datum"] == "NGVD29"
    assert m["elev_navd88_m"] is None
    assert m["height_above_ground_m"] == 0.3048
    assert m["uncertainty_m"] == 0.1219  # 0.4 ft = 0.12192


def test_square_edges():
    rows = by_id()
    assert rows[50]["in_square"] is True  # 5 mm inside the west edge
    assert rows[50]["easting_m"] == pytest.approx(585500.0, abs=0.011)
    assert rows[40]["in_square"] is False  # about 1 m outside
    assert rows[40]["easting_m"] == pytest.approx(585499.0, abs=0.011)


@pytest.mark.skipif(not REAL.exists(), reason="real file not cached")
def test_real_file_counts():
    rows = usgs_hwm.marks(REAL)
    assert len(rows) == 159
    assert len({m["site_no"] for m in rows}) == 83
    assert sum(m["in_square"] for m in rows) == 11
