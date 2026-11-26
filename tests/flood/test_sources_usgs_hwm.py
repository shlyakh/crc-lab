"""The USGS Ida high-water-mark loader (``flood_lab.sources.usgs_hwm``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from flood_lab import paths
from flood_lab.sources import usgs_hwm

HEADER = (
    "latitude_dd,longitude_dd,hwmTypeName,hwmQualityName,verticalDatumName,verticalMethodName,"
    "markerName,horizontalMethodName,horizontalDatumName,site_no,siteDescription,countyName,"
    "hwm_id,waterbody,site_id,event_id,hwm_locationdescription,survey_date,elev_ft,"
    "height_above_gnd,hwm_notes,hwm_environment,flag_date,stillwater,uncertainty,hwm_label"
)


def _row(lat, lon, quality, datum, site, hwm_id, date, elev, height, uncertainty) -> str:
    return (
        f'{lat},{lon},Seed line,"{quality}",{datum},RT-GNSS,Marker,Phone/Car GPS,'
        f'WGS84 (from Digital Map),{site},"A street, Brooklyn",Kings County,{hwm_id},'
        f"Flash flooding,1,312,on a post,{date},{elev},{height},,Riverine,9/7/2021,0,"
        f"{uncertainty},HWM-1"
    )


@pytest.fixture
def csv(tmp_path: Path) -> Path:
    path = tmp_path / "marks.csv"
    rows = [
        '"Capurso and others, 2023, a citation line."',
        HEADER,
        # in the square (near its centre), height given
        _row(
            40.7048, -73.9642, "Good: +/- 0.10 ft", "NAVD88", "NYKIN1", 3, "9/7/2021", 10, 1.5, 0.1
        ),
        # outside the square, height blank
        _row(40.62, -74.13, "Poor: +/- 0.40 ft", "NAVD88", "NYRIC2", 1, "9/10/2021", 19, "", 0.5),
        # a datum other than NAVD88: no metres
        _row(40.7048, -73.9642, "Fair: +/- 0.20 ft", "NGVD29", "NYKIN1", 2, "9/8/2021", 12, 2, ""),
    ]
    path.write_text("\n".join(rows) + "\n")
    return path


def test_columns_order_and_sorting(csv: Path) -> None:
    t = usgs_hwm.marks(csv)
    assert list(t.columns) == usgs_hwm.COLUMNS
    assert t["hwm_id"].tolist() == [1, 2, 3]
    assert t["survey_date"].tolist() == ["9/10/2021", "9/8/2021", "9/7/2021"]


def test_feet_become_metres_and_blanks_stay_missing(csv: Path) -> None:
    rows = {r["hwm_id"]: r for r in usgs_hwm.as_rows(usgs_hwm.marks(csv))}
    assert rows[3]["elev_navd88_m"] == 3.048
    assert rows[3]["height_above_ground_m"] == round(1.5 * 0.3048, 4)
    assert rows[3]["uncertainty_m"] == 0.0305
    assert rows[1]["height_above_ground_m"] is None
    assert rows[2]["uncertainty_m"] is None


def test_other_datum_is_not_converted(csv: Path) -> None:
    rows = {r["hwm_id"]: r for r in usgs_hwm.as_rows(usgs_hwm.marks(csv))}
    assert rows[2]["vertical_datum"] == "NGVD29"
    assert rows[2]["elev_navd88_m"] is None
    assert rows[2]["height_above_ground_m"] == 0.6096


def test_projection_and_in_square(csv: Path) -> None:
    rows = {r["hwm_id"]: r for r in usgs_hwm.as_rows(usgs_hwm.marks(csv))}
    assert rows[3]["in_square"] is True and rows[1]["in_square"] is False
    assert 585_500 < rows[3]["easting_m"] < 589_500
    assert rows[3]["easting_m"] == round(rows[3]["easting_m"], 2)
    assert rows[3]["longitude"] == -73.9642 and rows[3]["site_no"] == "NYKIN1"


REAL = paths.CACHE / usgs_hwm.FILE


@pytest.mark.skipif(not REAL.exists(), reason="high-water marks not in the cache")
def test_real_file_counts() -> None:
    t = usgs_hwm.marks(REAL)
    assert len(t) == 159 and t["hwm_id"].is_unique
    assert t["site_no"].nunique() == 83
    assert t["height_above_ground_m"].isna().sum() == 7
    inside = t[t["in_square"]]
    assert len(inside) == 11 and inside["site_no"].nunique() == 6
