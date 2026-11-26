"""F4: figures of the simulated events for ``docs/flood/simulated-events.md``.

    uv run --with matplotlib python -m flood_lab.checks.f4_events

* ``synthetic_years.png``: every synthetic year of the chosen catalogue by return period, its
  3-hour box rainfall and its wettest hour, the 30 mm/h constant loss rate, and the 150 years
  selected for the solver by stratum.
* ``parent_storms.png``: the observed storms the synthetic years come from, by month and by year
  (how often each parent storm is reused among the 1,000 years).

Inputs: RainyDay's scenario and catalogue tables (``rainyday_run read``) and
``data/cache/flood/f4/selection.json``. Numbers only from those files.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CAT = ROOT / "data/cache/flood/f4/rainyday/catalogue_n960/f4_B_d3_n960"
SEL = ROOT / "data/cache/flood/f4/selection.json"
OUT = ROOT / "docs/flood/figures/f4"
ALLOWANCE_MM_H = 30.0  # frozen at F3 (CH-16)
COLOURS = {"T1": "#b2182b", "T2": "#ef8a62", "T3": "#4393c3"}


def _rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def synthetic_years(scen: list[dict], sel: list[dict]) -> dict:
    m = len(scen)
    rank = {r["path"].rsplit("/", 1)[-1]: m - int(r["year_index"]) + 1 for r in scen}
    rp = [m / rank[r["path"].rsplit("/", 1)[-1]] for r in scen]
    total = [float(r["total_mm"]) for r in scen]
    peak = [float(r["peak_hour_mm"]) for r in scen]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), sharex=True)
    ax[0].scatter(rp, total, s=6, c="#999999", label=f"all {m} synthetic years")
    ax[1].scatter(rp, peak, s=6, c="#999999")
    for s in ("T1", "T2", "T3"):
        mine = [x for x in sel if x["stratum"] == s]
        x = [m / x_["rank"] for x_ in mine]
        ax[0].scatter(
            x,
            [x_["box_total_mm"] for x_ in mine],
            s=22,
            c=COLOURS[s],
            label=f"{s}: {len(mine)} run",
        )
        ax[1].scatter(x, [x_["box_peak_hour_mm"] for x_ in mine], s=22, c=COLOURS[s])
    ax[1].axhline(ALLOWANCE_MM_H, color="k", lw=1, ls="--")
    ax[1].text(1.05, ALLOWANCE_MM_H + 1, "constant loss rate 30 mm/h (F3)", fontsize=8)
    above = sum(p > ALLOWANCE_MM_H for p in peak)
    for a, t in zip(
        ax,
        ("3-hour rainfall over the study box (mm)", "wettest hour over the study box (mm)"),
        strict=True,
    ):
        a.set_xscale("log")
        a.set_xlabel("return period of the year's 3-hour rainfall (years, M / rank)")
        a.set_ylabel(t)
        a.grid(alpha=0.3)
    ax[0].legend(fontsize=8)
    fig.suptitle(
        f"Simulated events: {m} synthetic years (RainyDay, 960 storms, domain B); "
        f"{above} have a wettest hour above 30 mm/h"
    )
    fig.tight_layout()
    fig.savefig(OUT / "synthetic_years.png", dpi=130)
    plt.close(fig)
    return {
        "years": m,
        "peak_hour_above_allowance": above,
        "peak_hour_above_allowance_selected": sum(
            x["box_peak_hour_mm"] > ALLOWANCE_MM_H for x in sel
        ),
    }


def parent_storms(scen: list[dict], cat: list[dict]) -> dict:
    use = Counter(int(r["parent_storm"]) for r in scen)
    key = next(k for k in cat[0] if "start" in k or "time" in k)
    idk = next(k for k in cat[0] if k in ("storm", "storm_number", "id", "storm_id"))
    start = {int(r[idk]): r[key] for r in cat}
    months = Counter(start[s][5:7] for s in start)
    years_used = Counter()
    for s, n in use.items():
        years_used[start[s][:4]] += n
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.8))
    mm = [f"{i:02d}" for i in range(1, 13)]
    ax[0].bar(mm, [months.get(x, 0) for x in mm], color="#4393c3")
    ax[0].set_title("catalogue storms by month of their start (960)")
    yy = sorted({start[s][:4] for s in start})
    ax[1].bar(yy, [years_used.get(y, 0) for y in yy], color="#ef8a62")
    ax[1].set_title("synthetic years by the year of their parent storm (1000)")
    ax[1].tick_params(axis="x", rotation=90)
    fig.tight_layout()
    fig.savefig(OUT / "parent_storms.png", dpi=130)
    plt.close(fig)
    top = use.most_common(5)
    return {
        "parents_used": len(use),
        "most_used": [(s, n, start[s]) for s, n in top],
        "months": dict(sorted(months.items())),
        "start_column": key,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scen, cat = _rows(CAT / "scenarios.csv"), _rows(CAT / "catalogue.csv")
    sel = json.loads(SEL.read_text())
    print(
        json.dumps(
            {"synthetic_years": synthetic_years(scen, sel), "parents": parent_storms(scen, cat)},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
