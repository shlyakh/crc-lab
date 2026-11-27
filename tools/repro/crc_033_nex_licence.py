# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk[netcdf]==1.1.0"]
# ///
"""NEX-GDDP-CMIP6 files are recorded without the licence written in them.

docs/data-licences.md: a resource's `license` retains "the source's actual terms"
when known. NASA's NEX-GDDP-CMIP6 files state the model's licence in the global
attribute `cmip6_license`; crc-sdk records the file with `license=None`. Reads one
year for a small box (about 250 MB of range requests: NASA's chunks span the globe),
then reads the file's attribute directly with h5py. A dropped connection is tried
again (urllib.request.urlopen is wrapped for that).

Run: uv run crc_033_nex_licence.py
"""

import io
import json
import sys
import time
import urllib.error
import urllib.request
from importlib.metadata import distribution

import h5py
from crc_sdk import NEX, Bounds, Period

MODEL, SCENARIO, MEMBER, YEAR = "ACCESS-CM2", "historical", "r1i1p1f1", 2014
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


class Remote(io.RawIOBase):  # the file over HTTP range requests of 1 MiB, for h5py
    def __init__(self, url):
        self.url, self.at, self.blocks = url, 0, {}
        self.size = int(self.block(0).headers["Content-Range"].rsplit("/", 1)[1])

    def block(self, index):
        ask = {"Range": f"bytes={index << 20}-{((index + 1) << 20) - 1}"}
        response = urlopen(urllib.request.Request(self.url, headers=ask))
        self.blocks[index] = response.getvalue()
        return response

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self.at = (0, self.at, self.size)[whence] + offset
        return self.at

    def readinto(self, buffer):
        block, start = divmod(self.at, 1 << 20)
        if block not in self.blocks:
            self.block(block)
        piece = self.blocks[block][start : start + len(buffer)]
        buffer[: len(piece)], self.at = piece, self.at + len(piece)
        return len(piece)


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
    files = [r for r in recipe.read().metadata.source.resources if "#crc-variable=" in r.uri]
    for resource in files:
        url = resource.uri.split("#", 1)[0]
        written = h5py.File(io.BufferedReader(Remote(url)), "r").attrs.get("cmip6_license")
        written = written.decode() if isinstance(written, bytes) else written
        print(f"  {url.rsplit('/', 1)[-1]} (dropped connections tried again: {len(retries)})")
        print(f"expected: license={written!r} (global attribute cmip6_license in that file)")
        print(f"observed: license={resource.license!r}")
except OSError as error:
    print(f"COULD NOT RUN: NASA did not answer: {error}")
    sys.exit(2)
print("REPRODUCED" if any(r.license is None for r in files) else "NOT REPRODUCED")
