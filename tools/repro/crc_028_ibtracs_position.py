# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.1.0", "crc-framework==1.1.0"]
# ///
"""IBTrACS: an agency's winds are placed at the combined position, not at the agency's own.

docs/sources.md states native storm points for an `Agency` and does not say which position is
used. NOAA's file has a combined LAT/LON and a position per agency (TOKYO_LAT/TOKYO_LON, ...).
Observed: rows of IBTrACS(agency=TOKYO) carry LAT/LON, also where TOKYO_LAT/LON differ. Real
data: the ~333 MB ALL file is downloaded once by the script, and once by crc-sdk into its own
cache, both under <temp dir>/ibtracs-repro and reused on later runs (and by the companion script).

    uv run crc_028_ibtracs_position.py
"""

import csv
import struct
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

import pyarrow.compute as pc
from crc_sdk import Cache, IBTrACS, Runtime

URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
       "stewardship-ibtracs/v04r01/access/csv/ibtracs.ALL.list.v04r01.csv")  # fmt: skip
CACHE = Path(tempfile.gettempdir()) / "ibtracs-repro"
CSV = CACHE / "ibtracs.ALL.list.v04r01.csv"


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


def download() -> None:
    if CSV.exists():
        return
    CACHE.mkdir(exist_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "repro-script/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, \
            open(CSV.with_suffix(".part"), "wb") as out:  # noqa: S310  # fmt: skip
        while chunk := response.read(1 << 20):
            out.write(chunk)
    CSV.with_suffix(".part").replace(CSV)


def east(text: str) -> float:
    """Longitude in [-180, 180), as crc-sdk writes it."""
    return (float(text) + 180) % 360 - 180


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
tries("IBTrACS file", download)
print(f"publisher's file: {URL.rsplit('/', 1)[-1]} ({CSV.stat().st_size / 1e6:.0f} MB, at {CACHE})")
print("call: IBTrACS(agency=IBTrACS.Agency.TOKYO).read(runtime=Runtime(cache=Cache.reuse(...)))")
runtime = Runtime(cache=Cache.reuse(CACHE / "crc-sdk-cache"))
recipe = IBTrACS(agency=IBTrACS.Agency.TOKYO)
table = tries("crc-sdk read", lambda: recipe.read(runtime=runtime)).table
is_wind = pc.ends_with(table["variable_id"], "maximum_sustained_wind")
wind = table.filter(pc.and_(pc.is_valid(table["value"]), is_wind))
delivered = {
    sid.split("@")[0]: struct.unpack("<BIdd", geometry)[2:]  # (lon, lat)
    for sid, geometry in zip(
        wind["support_id"].to_pylist(), wind["geometry"].to_pylist(), strict=True
    )  # fmt: skip
}
with open(CSV, newline="", encoding="utf-8-sig") as handle:
    rows = csv.DictReader(handle)
    next(rows)  # the units row
    differ = []
    for row in rows:
        key = f"{row['SID']}:{row['ISO_TIME'].replace(' ', 'T')}"
        if key in delivered and row["TOKYO_LAT"].strip():
            combined = (east(row["LON"]), float(row["LAT"]))
            tokyo = (east(row["TOKYO_LON"]), float(row["TOKYO_LAT"]))
            if combined != tokyo:
                differ.append((key, combined, tokyo, delivered[key]))
at_combined = sum(abs(g[0] - c[0]) < 1e-9 and abs(g[1] - c[1]) < 1e-9 for _, c, _, g in differ)
far = sum(max(min(abs(c[0] - t[0]), 360 - abs(c[0] - t[0])), abs(c[1] - t[1])) > 0.1
          for _, c, t, _ in differ)  # fmt: skip
print(
    f"Tokyo wind rows with a value: {len(delivered)}; of these, where LAT/LON != TOKYO_LAT/LON: "
    f"{len(differ)} (by more than 0.1 degree: {far})"
)
print(f"{'point (SID:time)':<34}{'LAT, LON':>18}{'TOKYO_LAT, _LON':>18}{'row lat, lon':>18}")
for key, (lon, lat), (tlon, tlat), (glon, glat) in sorted(
        differ, key=lambda d: -abs(d[1][1] - d[2][1]))[:4]:  # fmt: skip
    print(
        f"{key:<34}{lat:>8.2f}, {lon:>7.2f}{tlat:>10.2f}, {tlon:>7.2f}{glat:>10.2f}, {glon:>7.2f}"
    )
print("expected: rows of the Tokyo agency at TOKYO_LAT/TOKYO_LON, or the position used stated")
print(f"observed: of the {len(differ)} rows where the two differ, {at_combined} carry LAT/LON")
print("REPRODUCED" if differ and at_combined == len(differ) else "NOT REPRODUCED")
