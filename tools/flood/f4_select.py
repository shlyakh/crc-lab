"""F4: the synthetic years that go to the solver (FH5), from RainyDay's scenario table.

    uv run python tools/flood/f4_select.py <scenarios.csv> <selection.json>

RainyDay sorts the synthetic years by the box rainfall of their storm, ``year_index`` 1 the
smallest, so rank from the top (1 = largest) is ``NYEARS - year_index + 1``. The ranks to run and
their weights come from ``flood_lab.hazard.catalogue.select`` (stratified by rank, fixed seed).
Each item carries what the queue needs (``label``, ``scenario``, ``weight``) and, passed through
to every run record, the rank, stratum, block, run order and the storm's descriptors (parent
storm, dates, box total and peak hour, shift), which are F9's training inputs.

``after_h`` is 0: RainyDay already appends ``PADSCENARIOS`` dry hours (1) to each scenario.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

from flood_lab.hazard import catalogue

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    table, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = list(csv.DictReader(table.open(encoding="utf-8")))
    rows = [r for r in rows if int(r["storm_in_year"]) == 1 and int(r["realization"]) == 1]
    m = len(rows)
    by_rank = {m - int(r["year_index"]) + 1: r for r in rows}
    if sorted(by_rank) != list(range(1, m + 1)):
        raise SystemExit(f"ranks are not 1..{m}: the table is not one storm per year")
    items = []
    for sel in catalogue.select(m):
        r = by_rank[sel["rank"]]
        path = Path(r["path"])
        items.append(
            sel
            | {
                "scenario": str(path if path.is_absolute() else ROOT / path),
                "after_h": 0,
                "synthetic_years": m,
                "return_period_y": float(r["return_period_y"]),
                "parent_storm": int(r["parent_storm"]),
                "first_stamp_utc": r["first_stamp_utc"],
                "box_total_mm": float(r["total_mm"]),
                "box_peak_hour_mm": float(r["peak_hour_mm"]),
                "shift_lon_deg": float(r["shift_lon_deg"]),
                "shift_lat_deg": float(r["shift_lat_deg"]),
            }
        )
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    print(f"{len(items)} runs of {m} synthetic years written to {out}")


if __name__ == "__main__":
    main()
