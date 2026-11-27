# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk[netcdf]==1.1.0", "crc-framework==1.1.0"]
# ///
"""NEX-GDDP-CMIP6: the file version read cannot be chosen and shows only inside a file name.

NASA serves several revisions of some files (_v1.0, _v1.1, _v2.0). Expected: a parameter to
choose the revision, or the revision read stated in the output's fields. Observed: NEX(...) has
no such parameter, the highest version on NASA's listing is read, and the version appears only
in the file name inside the recorded resource address. One tiny box, one year; real requests to
NASA's public bucket (crc-sdk reads the year's file by HTTP range requests).

    uv run crc_031_nex_version.py
"""

import inspect
import re
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

from crc_sdk import NEX, Bounds, Cache, Period, Runtime

BUCKET = "https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com"
MODEL, SCENARIO, MEMBER, YEAR = "ACCESS-CM2", "historical", "r1i1p1f1", 2014
BOX = dict(west=-97.80, south=30.20, east=-97.70, north=30.30)  # Austin, Texas
RUNTIME = Runtime(cache=Cache.reuse(Path(tempfile.gettempdir()) / "nex-repro-cache"))


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


def served() -> list[str]:
    prefix = (f"NEX-GDDP-CMIP6/{MODEL}/{SCENARIO}/{MEMBER}/pr/"
              f"pr_day_{MODEL}_{SCENARIO}_{MEMBER}_gn_{YEAR}")  # fmt: skip
    request = urllib.request.Request(f"{BUCKET}/?list-type=2&prefix={prefix}",
                                     headers={"User-Agent": "repro-script/1.0"})  # fmt: skip
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        keys = re.findall(r"<Key>([^<]+)</Key>", response.read().decode())
    return [k.rsplit("/", 1)[-1] for k in keys]


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print(f"NEX parameters: {list(inspect.signature(NEX).parameters)}")
print(f"NASA serves for {MODEL} {SCENARIO} {MEMBER} pr {YEAR}: {tries('listing', served)}")
print(
    f"call: NEX(indicator=ANNUAL_MAXIMUM_DAILY_PRECIPITATION, model={MODEL!r}, "
    f"scenario={SCENARIO!r}, member={MEMBER!r})"
)
print(f"      .select(area=Bounds(**{BOX}), time=Period.window({YEAR}, {YEAR})).read()")
recipe = NEX(
    indicator=NEX.Indicator.ANNUAL_MAXIMUM_DAILY_PRECIPITATION,
    model=MODEL,
    scenario=SCENARIO,
    member=MEMBER,
).select(  # fmt: skip
    area=Bounds(**BOX), time=Period.window(YEAR, YEAR)
)
result = tries("read", lambda: recipe.read(runtime=RUNTIME))
uris = [r.uri for r in result.metadata.source.resources]
files = sorted({u.split("#")[0].rsplit("/", 1)[-1] for u in uris if ".nc" in u})
print(f"rows: {result.table.num_rows}; columns: {result.table.schema.names}")
print(f"release id: {result.metadata.source.release and result.metadata.source.release.id}")
print("files named in result.metadata.source.resources[*].uri:")
for name in files:
    print(f"  {name}")
in_columns = [c for c in result.table.schema.names if "version" in c.lower()]
read_versions = sorted({m for f in files for m in re.findall(r"_v([0-9.]+)\.nc", f)})
print(
    "expected: a parameter to choose the file version, or the version read in the output's fields"
)
print(
    f"observed: no version parameter: {'version' not in inspect.signature(NEX).parameters}; "
    f"columns naming a version: {in_columns}; versions read: {read_versions}"
)
print("REPRODUCED" if "version" not in inspect.signature(NEX).parameters and not in_columns
      else "NOT REPRODUCED")  # fmt: skip
