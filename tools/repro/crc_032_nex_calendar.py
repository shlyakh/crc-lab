# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk[netcdf]==1.0.0", "crc-framework==1.0.0"]
# ///
"""NEX-GDDP-CMIP6: a model on a 365-day calendar is listed by inspection, then refused.

Expected (docs/sources.md): NEX exposes the published model/scenario/member combinations and
inspection reads their calendar. Observed: NEX().inspect() lists BCC-CSM2-MR, whose files declare
calendar "365_day", and reading it (one tiny box, one year) raises "NEX source does not use its
published Gregorian calendar". The calendar attribute is read by the script from the file header
with a few HTTP range requests (h5py). Real requests to NASA's public bucket.

    uv run crc_032_nex_calendar.py
"""

import re
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

import h5py
from crc_sdk import NEX, Bounds, Cache, Period, Runtime

BUCKET = "https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com"
MODEL, SCENARIO, MEMBER, YEAR = "BCC-CSM2-MR", "historical", "r1i1p1f1", 2014
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


def get(url: str, start: int | None = None, size: int = 1 << 20) -> bytes:
    headers = {"User-Agent": "repro-script/1.0"}
    if start is not None:
        headers["Range"] = f"bytes={start}-{start + size - 1}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


class RangeFile:
    """Just enough of a file object over HTTP range requests for h5py to read a header."""

    def __init__(self, url: str, size: int) -> None:
        self.url, self.size, self.at, self.blocks = url, size, 0, {}

    def seek(self, offset: int, whence: int = 0) -> int:
        self.at = (offset, self.at + offset, self.size + offset)[whence]
        return self.at

    def tell(self) -> int:
        return self.at

    def read(self, size: int) -> bytes:
        out = b""
        while len(out) < size:
            block, inner = divmod(self.at, 1 << 20)
            if block not in self.blocks:
                self.blocks[block] = tries("header", lambda b=block: get(self.url, b << 20))
            chunk = self.blocks[block][inner : inner + size - len(out)]
            if not chunk:
                break
            out, self.at = out + chunk, self.at + len(chunk)
        return out


prefix = (f"NEX-GDDP-CMIP6/{MODEL}/{SCENARIO}/{MEMBER}/pr/"
          f"pr_day_{MODEL}_{SCENARIO}_{MEMBER}_gn_{YEAR}")  # fmt: skip
listing = tries("listing", lambda: get(f"{BUCKET}/?list-type=2&prefix={prefix}")).decode()
files = re.findall(r"<Key>([^<]+\.nc)</Key>.*?<Size>(\d+)</Size>", listing)
key, size = max(files)  # the highest _v<X.Y> of the year
with h5py.File(RangeFile(f"{BUCKET}/{key}", int(size)), "r") as nc:
    calendar = nc["time"].attrs["calendar"]
    calendar = calendar.decode() if isinstance(calendar, bytes) else str(calendar)

print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print(f"file header: {key.rsplit('/', 1)[-1]}: time:calendar = {calendar!r}")
series = tries("inspect", lambda: NEX().inspect(runtime=RUNTIME).series)
listed = [s for s in series if s.model == MODEL]
print(
    f"call: NEX().inspect() -> {len(series)} series of {len({s.model for s in series})} models; "
    f"{MODEL}: {len(listed)} series, e.g. {listed[0].scenario.id} {listed[0].member}"
)
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
try:
    rows = tries("read", lambda: recipe.read(runtime=RUNTIME)).table.num_rows
    observed = f"{rows} rows"
except ValueError as error:
    observed = f"{type(error).__name__}: {error}"
print(f"expected: a model listed by inspection can be read (its {calendar} calendar recorded)")
print(f"observed: {observed}")
print("REPRODUCED" if listed and "rows" not in observed else "NOT REPRODUCED")
