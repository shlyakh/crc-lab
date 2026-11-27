# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.1.0", "crc-framework==1.1.0"]
# ///
"""GHCNh: with the default completeness rule, one incomplete day leaves a year without a value.

The default coverage is Coverage.complete(), and a day counts only with reports in all 24 hours
(docs/sources.md). Expected: the default read of major hourly airport stations gives annual values.
Observed: a station-year gets a value only when every day of the year is complete; years with 356
to 364 complete days get none, and get one with Coverage.minimum_fraction(0.9). For one
station-year the script also counts, from NOAA's own file, the days that have a temperature
report in all 24 hours. Real requests to NOAA's public bucket.

    uv run crc_035_ghcnh_default_coverage.py
"""

import io
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

import pyarrow.parquet as pq
from crc_sdk import Cache, Coverage, GHCNh, Period, Runtime

STATIONS = {"USW00013904": "Austin", "USW00003927": "Dallas/Fort Worth",
            "USW00012960": "Houston IAH", "USW00012921": "San Antonio",
            "USW00023044": "El Paso"}  # fmt: skip
YEARS = (2019, 2022)
ONE = ("USW00013904", 2022)
RUNTIME = Runtime(cache=Cache.reuse(Path(tempfile.gettempdir()) / "ghcnh-repro-cache"))
INDICATOR = GHCNh.Indicator.ANNUAL_MAXIMUM_DAILY_MAXIMUM_TEMPERATURE


def tries(what, call):
    """Three tries with a growing pause on connection errors; exit 2 if all fail."""
    for attempt in range(1, 4):
        try:
            return call()
        except OSError as error:
            print(f"  ({what}: try {attempt} failed: {type(error).__name__}: {error})")
            if attempt < 3:
                time.sleep(10 * attempt)
    print(f"COULD NOT RUN: the publisher did not answer for {what} after three tries")
    sys.exit(2)


def annual(station: str, coverage: Coverage | None) -> dict[int, dict]:
    recipe = GHCNh(indicator=INDICATOR) if coverage is None else GHCNh(
        indicator=INDICATOR, coverage=coverage)  # fmt: skip
    plan = recipe.select(stations=[station], time=Period.window(*YEARS))
    table = plan.read(runtime=RUNTIME).table
    return {int(r["time"]): r for r in table.to_pylist()}


def full_days(station: str, year: int) -> int:
    """Days of NOAA's file with a temperature report in each of the 24 hours (any quality)."""
    url = (f"https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/access/by-year/{year}/parquet/"
           f"GHCNh_{station}_{year}.parquet")  # fmt: skip
    request = urllib.request.Request(url, headers={"User-Agent": "repro-script/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        rows = pq.read_table(io.BytesIO(response.read()), columns=["DATE", "temperature"])
    hours: dict[str, set[str]] = {}
    for when, value in zip(rows["DATE"].to_pylist(), rows["temperature"].to_pylist(), strict=True):
        if value is not None:
            hours.setdefault(when[:10], set()).add(when[11:13])
    return sum(len(h) == 24 for h in hours.values())


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print(f"call: GHCNh(indicator={INDICATOR.name}[, coverage=Coverage.minimum_fraction(0.9)])")
print(f"      .select(stations=[<id>], time=Period.window{YEARS}).read()")
print(f"{'station':<12} {'name':<18} {'year':<5} {'default':>8} {'0.9':>8} {'complete days':>14}")
present = {"default": 0, "0.9": 0}
total = near = near_without = 0
for station, name in STATIONS.items():
    default = tries(station, lambda s=station: annual(s, None))
    relaxed = tries(station, lambda s=station: annual(s, Coverage.minimum_fraction(0.9)))
    for year in sorted(default):
        d, r = default[year], relaxed[year]
        cover = d["coverage"] or {}
        total += 1
        present["default"] += d["value"] is not None
        present["0.9"] += r["value"] is not None
        short = 0 < (cover.get("expected") or 0) - (cover.get("valid") or 0) <= 10
        near += short
        near_without += short and d["value"] is None
        shown = [("-" if x["value"] is None else f"{x['value']:.1f}") for x in (d, r)]
        print(
            f"{station:<12} {name:<18} {year:<5} {shown[0]:>8} {shown[1]:>8} "
            f"{cover.get('valid')!s:>6} of {cover.get('expected')!s:<5}"
        )
failures = sorted({(default[y]["failure"] or {}).get("code") for y in default})
noaa = tries("NOAA file", lambda: full_days(*ONE))
print(
    f"(value '-': no value; 'complete days': the default row's coverage; last station's "
    f"failures: {failures})"
)
print(
    f"NOAA's file {ONE[0]} {ONE[1]}: {noaa} days with a temperature report in all 24 hours "
    "(before any quality check)"
)
print("expected: annual values for major hourly airport stations with the default coverage")
print(
    f"observed: values present, default: {present['default']} of {total}; "
    f"Coverage.minimum_fraction(0.9): {present['0.9']} of {total}"
)
print(
    f"observed: station-years lacking 1 to 10 complete days: {near}; of these without a "
    f"default value: {near_without}"
)
print(
    "REPRODUCED"
    if near and near_without == near and present["0.9"] > present["default"]
    else "NOT REPRODUCED"
)
