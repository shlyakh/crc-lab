# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.0.0", "crc-framework==1.0.0"]
# ///
"""IBTrACS: every point of the file is returned for every agency, most as rows with no value.

docs/sources.md describes the output as the chosen agency's storm observations. Observed: for a
small agency (New Delhi) the read returns two rows (wind, pressure) for every point of NOAA's
file, and almost all of them carry no value (failure "source_no_data"). Real data: crc-sdk
downloads the ~333 MB ALL file once into <temp dir>/ibtracs-repro/crc-sdk-cache (shared with the
companion position script) and reuses it on later runs.

    uv run crc_029_ibtracs_empty_rows.py
"""

import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import pyarrow.compute as pc
from crc_sdk import Cache, IBTrACS, Runtime

CACHE = Path(tempfile.gettempdir()) / "ibtracs-repro" / "crc-sdk-cache"


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


print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print("call: IBTrACS(agency=IBTrACS.Agency.NEWDELHI).read(runtime=Runtime(cache=Cache.reuse(...)))")
runtime = Runtime(cache=Cache.reuse(CACHE))
read = tries("crc-sdk read", lambda: IBTrACS(agency=IBTrACS.Agency.NEWDELHI).read(runtime=runtime))
table = read.table
point = pc.list_element(pc.split_pattern(table["support_id"], "@"), 0)  # "<SID>:<time>"
points = pc.count_distinct(point).as_py()
empty = table["value"].null_count
codes = pc.value_counts(pc.struct_field(table["failure"], "code")).to_pylist()
print(f"rows returned:            {table.num_rows}")
print(f"distinct storm points:    {points}  (rows per point: {table.num_rows / points:g})")
print(f"rows with a value:        {table.num_rows - empty}")
print(f"rows with no value:       {empty}  ({100 * empty / table.num_rows:.1f}%)")
print(f"failure codes:            {[(c['values'], c['counts']) for c in codes]}")
print(
    f"report counts:            produced={read.report.counts.produced}, "
    f"no_data={read.report.counts.no_data}"
)
print("expected: the New Delhi agency's observations (rows where it reported a value)")
print(f"observed: {table.num_rows} rows, of which {empty} have no value")
print("REPRODUCED" if empty > table.num_rows / 2 else "NOT REPRODUCED")
