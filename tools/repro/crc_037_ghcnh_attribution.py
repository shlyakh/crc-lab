# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.0.0"]
# ///
"""GHCNh hourly files are attributed to NOAA CO-OPS as well as NOAA NCEI.

GHCNh (the station list and each station-year file) is published by NOAA NCEI.
docs/data-licences.md says a resource's attribution retains "the source's actual
terms". Reading one station-year from NOAA's GHCNh bucket records an attribution
that also names NOAA CO-OPS, the tides and currents service.

Run: uv run crc_037_ghcnh_attribution.py
"""

import json
import sys
import time
from importlib.metadata import distribution

from crc_sdk import GHCNh, Period

STATION, YEAR = "USW00012960", 2020  # Houston Intercontinental Airport
EXPECTED = "NOAA National Centers for Environmental Information; original source records retained."


def read():
    recipe = GHCNh().select(stations=STATION, time=Period.window(YEAR, YEAR))
    for attempt in range(1, 4):
        try:
            return recipe.observations().read()
        except OSError as error:
            if attempt == 3:
                print(f"COULD NOT RUN: NOAA did not answer: {error}")
                sys.exit(2)
            time.sleep(5 * attempt)


def installed():
    dist = distribution("crc-sdk")
    vcs = json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info")
    built = f" (git {vcs['requested_revision']} {vcs['commit_id'][:10]})" if vcs else ""
    return f"crc-sdk {dist.version}{built}"


print(installed())
print(
    f"call: GHCNh().select(stations={STATION!r}, time=Period.window({YEAR}, {YEAR}))"
    ".observations().read()"
)
result = read()
resources = result.metadata.source.resources
print(f"rows read: {result.table.num_rows}")
for resource in resources:
    print(f"  {resource.uri.rsplit('/', 1)[-1]:32} attribution: {resource.attribution!r}")
attributions = {resource.attribution for resource in resources}
print(f"expected: every resource attributed {EXPECTED!r}")
print(f"observed: {sorted(attributions, key=str)!r}")
wrong = any(a and "CO-OPS" in a for a in attributions)
print("REPRODUCED" if wrong else "NOT REPRODUCED")
