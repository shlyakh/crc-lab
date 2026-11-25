# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk[netcdf]==1.0.0"]
# ///
"""A NEX year that NASA does not publish comes back as rows with gaps.

NASA's NEX-GDDP-CMIP6 historical run ends in 2014. Asking for 2015 one would
expect an error, or a diagnostic saying the source has no 2015. crc-sdk instead
reads the nearest year's file (2014, about 250 MB of range requests) and returns
one row per cell without a value, whose only diagnostic is about completeness.
A dropped connection is tried again (urllib.request.urlopen is wrapped for that).

Run: uv run crc_034_nex_missing_year.py
"""

import io
import json
import sys
import time
import urllib.error
import urllib.request
from importlib.metadata import distribution

from crc_sdk import NEX, Bounds, Period

MODEL, SCENARIO, MEMBER, YEAR = "ACCESS-CM2", "historical", "r1i1p1f1", 2015
BOX = Bounds(west=-95.5, south=29.5, east=-95.25, north=29.75)  # Houston, Texas
_urlopen, retries = urllib.request.urlopen, []


def urlopen(*args, **kwargs):  # up to 3 tries on a dropped connection; an HTTP answer is final
    for attempt in range(1, 4):
        try:
            with _urlopen(*args, **kwargs) as response:
                body = io.BytesIO(response.read())
                body.status, body.headers = response.status, response.headers
                return body
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == 3:
                raise
            retries.append(attempt)
            time.sleep(5 * attempt)


urllib.request.urlopen = urlopen
dist = distribution("crc-sdk")
vcs = json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info")
built = f" (git {vcs['requested_revision']} {vcs['commit_id'][:10]})" if vcs else ""
print(f"crc-sdk {dist.version}{built}")
print(
    f"call: NEX(indicator=ANNUAL_MAXIMUM_DAILY_PRECIPITATION, model={MODEL!r},"
    f" scenario={SCENARIO!r}, member={MEMBER!r})"
    f".select(area={BOX}, time=Period.window({YEAR}, {YEAR})).read()"
)
recipe = NEX(
    indicator=NEX.Indicator.ANNUAL_MAXIMUM_DAILY_PRECIPITATION,
    model=MODEL,
    scenario=SCENARIO,
    member=MEMBER,
).select(area=BOX, time=Period.window(YEAR, YEAR))
try:
    result = recipe.read()
except OSError as error:
    print(f"COULD NOT RUN: NASA did not answer: {error}")
    sys.exit(2)
table, report = result.table, result.report
files = sorted(
    {
        r.uri.split("#")[0].rsplit("/", 1)[-1]
        for r in result.metadata.source.resources
        if "#crc-variable=" in r.uri
    }
)
values = table["value"].to_pylist()
print(f"files read: {files} (dropped connections tried again: {len(retries)})")
print(
    f"rows: {table.num_rows}, years {sorted(set(table['time'].to_pylist()))}, "
    f"with a value: {sum(v is not None for v in values)}"
)
print(
    f"counts: requested={report.counts.requested} produced={report.counts.produced} "
    f"incomplete_years={report.counts.incomplete_years}"
)
for d in report.diagnostics:
    print(f"  diagnostic {d.code} [{d.severity.value}, {d.stage.value}]: {d.message}")
print(f"expected: an error, or a diagnostic stating the source publishes no {YEAR}")
named = [d for d in report.diagnostics if str(YEAR) in d.message and "2014" in d.message]
print(f"observed: {'a diagnostic names it: ' + named[0].code if named else 'none names it'}")
print("NOT REPRODUCED" if named else "REPRODUCED")
