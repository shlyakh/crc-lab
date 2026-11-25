# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk[raster]==1.0.0", "rasterio<1.5.2; sys_platform == 'darwin'"]
# ///
"""A JRC flood read whose box lies outside the product's extent looks like a dry area.

The EFAS flood maps cover Europe. Reading them for a box in California, one would
expect an error or a diagnostic saying the box is outside the product's extent.
crc-sdk returns no rows, no diagnostic and a report that is complete and valid,
which cannot be told from a covered box where nothing floods.

Run: uv run crc_024_jrc_outside_coverage.py
"""

import json
import sys
import time
from importlib.metadata import distribution

from crc_sdk import JRC, Bounds

BOX = Bounds(west=-122.15, south=37.42, east=-121.85, north=37.62)  # Fremont, California

dist = distribution("crc-sdk")
vcs = json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info")
built = f" (git {vcs['requested_revision']} {vcs['commit_id'][:10]})" if vcs else ""
print(f"crc-sdk {dist.version}{built}")
print(f"call: JRC(product=JRC.Product.EFAS).select(area={BOX}).read()")
for attempt in range(1, 4):
    try:
        result = JRC(product=JRC.Product.EFAS).select(area=BOX).read()
        break
    except OSError as error:
        if attempt == 3:
            print(f"COULD NOT RUN: the JRC data server did not answer: {error}")
            sys.exit(2)
        time.sleep(10 * attempt)
report = result.report
print(
    f"rows: {result.table.num_rows}; counts: requested={report.counts.requested} "
    f"produced={report.counts.produced} skipped={report.counts.skipped}; "
    f"complete={report.complete} valid={report.valid}"
)
for d in report.diagnostics:
    print(f"  diagnostic {d.code} [{d.severity.value}, {d.stage.value}]: {d.message}")
print("expected: an error, or a diagnostic saying the box is outside the EFAS extent")
print(f"observed: {len(report.diagnostics)} diagnostic(s)")
silent = result.table.num_rows == 0 and not report.diagnostics
print("REPRODUCED" if silent else "NOT REPRODUCED")
