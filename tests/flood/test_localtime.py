"""Section 5: a FloodNet time in GMT is matched to a storm by its day in New York."""

from __future__ import annotations

from flood_lab.localtime import local_day


def test_summer_times_use_the_four_hour_offset() -> None:
    days = local_day(["2021-09-02T01:30:00", "2023-09-29T03:59:59", "2023-09-29T04:00:00"])
    assert days.tolist() == ["2021-09-01", "2023-09-28", "2023-09-29"]


def test_winter_times_use_the_five_hour_offset() -> None:
    days = local_day(["2023-01-15T04:59:59.000", "2023-01-15T05:00:00.000"])
    assert days.tolist() == ["2023-01-14", "2023-01-15"]


def test_a_time_with_its_zone_is_converted_from_that_zone() -> None:
    assert local_day(["2023-09-29T03:59:59Z"]).tolist() == ["2023-09-28"]
