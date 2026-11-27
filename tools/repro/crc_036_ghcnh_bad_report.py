# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.1.0"]
# ///
"""One unusable report in one GHCNh station file loses every selected station.

docs/execution.md: expected data failures are kept as rows. Two real Houston
stations are read for 2020; the second station's file is CONSTRUCTED from NOAA's
real file plus one duplicated report (same time and position), injected by
patching the private download function (one line, marked below). One would
expect the first station's row and a diagnostic for the second; crc-sdk raises
for the whole selection.

Run: uv run crc_036_ghcnh_bad_report.py
"""

import json
import sys
import time
from importlib.metadata import distribution

import crc_sdk._source_io
import pyarrow as pa
import pyarrow.parquet as pq
from crc_sdk import GHCNh, Period, UnavailableStationYear

GOOD, BAD, YEAR = "USW00012960", "USW00012918", 2020  # Houston Intercontinental, Hobby
original = crc_sdk._source_io._download


def download(uri, path):  # NOAA's file for BAD, with its first report written twice
    status = original(uri, path)
    if uri.endswith(f"GHCNh_{BAD}_{YEAR}.parquet"):
        table = pq.read_table(path)
        pq.write_table(pa.concat_tables([table, table.slice(0, 1)]), path)
    return status


crc_sdk._source_io._download = download  # the one private name patched
dist = distribution("crc-sdk")
vcs = json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info")
built = f" (git {vcs['requested_revision']} {vcs['commit_id'][:10]})" if vcs else ""
print(f"crc-sdk {dist.version}{built}")
print(
    f"call: GHCNh(indicator=ANNUAL_MAXIMUM_DAILY_MAXIMUM_TEMPERATURE)"
    f".select(stations=[{GOOD!r}, {BAD!r}], time=Period.window({YEAR}, {YEAR})).read()"
)
recipe = GHCNh(indicator=GHCNh.Indicator.ANNUAL_MAXIMUM_DAILY_MAXIMUM_TEMPERATURE).select(
    stations=[GOOD, BAD], time=Period.window(YEAR, YEAR)
)
result = error = None
for attempt in range(1, 4):
    try:
        result = recipe.read()
        break
    except OSError as failure:
        if attempt == 3:
            print(f"COULD NOT RUN: NOAA did not answer: {failure}")
            sys.exit(2)
        time.sleep(5 * attempt)
    except ValueError as failure:  # crc-sdk's ValidationError is a ValueError
        error = failure
        break
if result is None and error is not None:  # control: the good station read on its own
    alone = (
        GHCNh(indicator=GHCNh.Indicator.ANNUAL_MAXIMUM_DAILY_MAXIMUM_TEMPERATURE)
        .select(stations=[GOOD], time=Period.window(YEAR, YEAR))
        .read()
    )
    print(f"control: {GOOD} read alone returns {alone.table.num_rows} row(s)")
print(f"expected: a row for {GOOD}, and an UnavailableStationYear diagnostic for {BAD} {YEAR}")
if error is not None:
    print(f"observed: {type(error).__name__}: {error}; no rows for any station")
else:
    flagged = [
        (d.station_id, d.year, d.stage.value, d.message)
        for d in result.report.diagnostics
        if isinstance(d, UnavailableStationYear)
    ]
    print(f"observed: rows for {result.table['station_id'].to_pylist()}; diagnostics {flagged}")
print("REPRODUCED" if error is not None else "NOT REPRODUCED")
