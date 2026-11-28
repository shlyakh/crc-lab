"""F6 visual test: curves, the event-loss table and risk (FR4-FR8; plan F6).

    uv run --extra flood --with matplotlib python -m flood_lab.checks.f6_risk

Offline. Reads what ``python -m flood_lab.risk.metrics`` wrote under ``site/flood/data/f6/``
and the per-run substation depths of the F4 catalogue, draws the figures of plan F6 under
``docs/flood/figures/f6/`` and writes the record ``site/flood/tests/records/f6.json``. Every
figure prints the number of storms it rests on (requirements §15).

Figures: a card per substation (depth frequency with the catalogue points, the damage-curve
envelope with the asset's 10-, 100- and 500-year depths marked, loss by return period as a band
over the four curve families); the portfolio exceedance curve with its bootstrap band; the
bracket chart; the expected-annual-loss bars, event table against CRC's curves by both routes.

Pass rules (plan F6): the hand recomputation (FR7, done apart by an agent that does not see this
code: pending here); the event-table CVaR at 99% at or below the full-dependence bracket (CH-28);
the expected annual loss of the event table and of CRC's curves within 5% or the difference
explained (proposed); every failure row accounted for.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flood_lab import paths
from flood_lab.checks import f3_model
from flood_lab.hazard import catalogue
from flood_lab.records import Check, Input, Parameter, Record
from flood_lab.risk import crc_adapter
from flood_lab.risk import event_loss as el
from flood_lab.risk import metrics as mx

RECORD_ID = "f6"
REL = "docs/flood/figures/f6"
DATA = paths.SITE / "data" / "f6"
BLUE, ORANGE, AQUA, PURPLE = "#2a78d6", "#eb6834", "#1baf7a", "#8a5cd6"
INK, INK2, GRID_GREY = "#0b0b0b", "#52514e", "#e5e5e5"
FAMILY_COLOURS = {"low": BLUE, "high": ORANGE, "williams_min": AQUA, "bor": PURPLE}
RP_INDEX = {10: 0, 100: 1, 500: 2}
CURVE_YEARS = (2, 5, 10, 25, 50, 100, 250, 500, 1000)


def _png(figure, name: str, out: Path) -> str:
    import io

    plt = f3_model._plt()
    buffer = io.BytesIO()
    figure.savefig(
        buffer, format="png", dpi=f3_model.DPI, metadata={"Software": None}, facecolor="white"
    )
    path = out / name
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".png.part")
    part.write_bytes(buffer.getvalue())
    part.replace(path)
    plt.close(figure)
    return f"{REL}/{name}"


def storms_text(n: int, m: int) -> str:
    return f"N = {n} catalogue storms (one per synthetic year, M = {m:,} years)"


def _style(axis) -> None:
    axis.grid(color=GRID_GREY, lw=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)


def plotting_positions(depth: np.ndarray, w: np.ndarray, m: float) -> tuple[np.ndarray, np.ndarray]:
    """Each run's depth with its exceedance mass ``P(D >= d)`` (weights / M), tools' rank."""
    order = np.argsort(-depth, kind="stable")
    return depth[order], np.cumsum(w[order]) / m


def figure_substation(
    loc: str,
    name: str,
    lead: np.ndarray,
    w: np.ndarray,
    m: float,
    rows: pd.DataFrame,
    curves: dict[str, Any],
    n: int,
    out: Path,
) -> str:
    plt = f3_model._plt()
    figure, (a, b, c) = plt.subplots(1, 3, figsize=(15, 4.8))
    # (a) depth frequency: catalogue points, CRC's point-route curve, grid route at the knots
    d, p = plotting_positions(lead, w, m)
    wet = d >= catalogue.WET_M
    a.scatter(1 / p[wet], d[wet], s=16, color=INK2, label="catalogue runs (P(D >= d) by weight)")
    ts = np.geomspace(1.0001, 1000, 300)
    a.plot(
        ts,
        mx.point_route_depths(lead, w, m, ts).tolist(),
        color=BLUE,
        lw=2,
        label="CRC point route (from_quantiles knots)",
    )
    grid_depths = [
        rows[f"depth_{t}y_grid"].iloc[0] if f"depth_{t}y_grid" in rows else None
        for t in mx.RETURN_PERIODS
    ]
    if all(g is not None and np.isfinite(g) for g in grid_depths):
        a.plot(
            mx.RETURN_PERIODS,
            grid_depths,
            "s",
            color=ORANGE,
            ms=8,
            label="CRC grid route (5 m cell at the outline centroid)",
        )
    a.set_xscale("log")
    a.set_xlabel("Return period, years")
    a.set_ylabel("Lead depth (exceeded on 25 m² of open ground), m")
    if not all(g is not None and np.isfinite(g) for g in grid_depths):
        a.text(
            0.98,
            0.04,
            "grid route: no read 5 m cell at the outline centroid",
            transform=a.transAxes,
            ha="right",
            fontsize=7,
            color=INK2,
        )
    a.set_title("Depth frequency at the site", fontsize=9)
    a.legend(fontsize=7, frameon=False, loc="upper left")
    _style(a)
    # (b) damage-curve envelope with the 10/100/500-year depths
    by_id = {e["id"]: e for e in curves["substation_curves"]}
    top = 0.0
    for _, r in rows.iterrows():
        pts = np.array(by_id[r["curve_id"]]["points"], float)
        b.plot(
            pts[:, 0],
            pts[:, 1],
            color=FAMILY_COLOURS[r["family"]],
            lw=2,
            label=f"{el.FAMILY_NAMES[r['family']]}: {r['curve_id']}",
        )
    for t, style in zip(mx.RETURN_PERIODS, (":", "--", "-"), strict=True):
        dt = float(rows[f"depth_{t}y_point"].iloc[0])
        top = max(top, dt)
        b.axvline(dt, color=INK, ls=style, lw=1)
        b.annotate(
            f"{t} y: {dt:.2f} m",
            (dt, 0.97 - 0.12 * RP_INDEX[t]),
            fontsize=7,
            ha="left",
            va="top",
            xytext=(3, 0),
            textcoords="offset points",
        )
    b.set_xlim(0, max(1.0, top * 2))
    b.set_ylim(0, 1)
    b.set_xlabel("Depth above ground, m")
    b.set_ylabel("Damage ratio")
    b.set_title(
        "Damage-curve envelope (C-3, C-5 by role); lines: the site's\n"
        "10-, 100- and 500-year depths (point route)",
        fontsize=9,
    )
    b.legend(fontsize=6.5, frameon=False, loc="lower right")
    _style(b)
    # (c) loss by return period: band across the families
    value = float(rows["value_mid_usd_2026"].iloc[0])
    depth_t = mx.point_route_depths(lead, w, m, CURVE_YEARS)
    losses = {}
    for _, r in rows.iterrows():
        losses[r["family"]] = mx.substation_ratios(r["curve_id"], depth_t) * value / 1e6
    stack = np.vstack(list(losses.values()))
    c.fill_between(
        CURVE_YEARS,
        stack.min(axis=0),
        stack.max(axis=0),
        color=BLUE,
        alpha=0.15,
        label="band across the four families",
    )
    for fam, ys in losses.items():
        c.plot(CURVE_YEARS, ys, color=FAMILY_COLOURS[fam], lw=1.5, label=el.FAMILY_NAMES[fam])
    c.set_xscale("log")
    c.set_xlabel("Return period, years")
    c.set_ylabel("Loss, million 2026 USD (mid value [P])")
    c.set_title(
        f"Loss by return period (mid value ${value / 1e6:,.1f} M, placeholder [P])", fontsize=9
    )
    c.legend(fontsize=7, frameon=False, loc="upper left")
    _style(c)
    figure.suptitle(f"{name} ({loc}) — {storms_text(n, int(m))}", fontsize=10)
    figure.tight_layout()
    return _png(figure, f"substation_{loc}.png", out)


def figure_exceedance(metrics: dict, n: int, m: int, out: Path) -> str:
    plt = f3_model._plt()
    figure, axes = plt.subplots(1, 2, figsize=(14, 5.2), sharey=True)
    for axis, fam in zip(axes, ("low", "high"), strict=True):
        pts = np.array(metrics["exceedance_main"][fam])
        keep = pts[:, 2] > 0
        axis.step(
            1 / pts[keep, 2],
            pts[keep, 0] / 1e6,
            where="post",
            color=BLUE,
            lw=2,
            label="event table, occurrence = aggregate (one storm a year)",
        )
        band = metrics["bootstrap"][fam]["var_band_by_return_period"]
        ys = sorted(int(t) for t in band)
        lo = [band[str(t)][0] / 1e6 for t in ys]
        hi = [band[str(t)][1] / 1e6 for t in ys]
        axis.fill_between(
            ys,
            lo,
            hi,
            color=BLUE,
            alpha=0.15,
            label="bootstrap 5-95% of CRC's VaR (runs within strata)",
        )
        crc = metrics["loss_by_return_period_main"][fam]
        axis.plot(
            [int(t) for t in crc],
            [v["var_crc"] / 1e6 for v in crc.values()],
            "o",
            color=ORANGE,
            ms=5,
            label="CRC VaR at 1 - 1/T",
        )
        axis.plot(
            [int(t) for t in crc],
            [v["one_in_t_tools"] / 1e6 for v in crc.values()],
            "x",
            color=INK,
            ms=6,
            label="tools' convention, P(L >= x) = 1/T",
        )
        axis.set_xscale("log")
        axis.set_xlabel("Return period, years (1 / annual exceedance)")
        axis.set_title(
            f"Portfolio annual loss, substations on {el.FAMILY_NAMES[fam]}\n"
            f"{storms_text(n, m)}; bootstrap {metrics['bootstrap'][fam]['resamples']} resamples",
            fontsize=9,
        )
        axis.legend(fontsize=7, frameon=False, loc="upper left")
        _style(axis)
    axes[0].set_ylabel("Annual loss, million 2026 USD")
    figure.tight_layout()
    return _png(figure, "portfolio_exceedance.png", out)


def figure_brackets(metrics: dict, n: int, m: int, out: Path) -> str:
    plt = f3_model._plt()
    figure, axes = plt.subplots(1, 2, figsize=(14, 5))
    fams = list(el.FAMILIES)
    x = np.arange(len(fams))
    width = 0.27
    for axis, k, what in ((axes[0], 1, "CVaR at 99%"), (axes[1], 0, "VaR at 99% (1 in 100, CRC)")):
        for j, (key, colour, label) in enumerate(
            (
                ("full_dependence", ORANGE, "full dependence"),
                ("events", BLUE, "event table"),
                ("independence", AQUA, "independence (resampled)"),
            )
        ):
            ys = [metrics["brackets"][f]["levels"]["100"][key][k] / 1e6 for f in fams]
            bars = axis.bar(x + (j - 1) * width, ys, width * 0.92, color=colour, label=label)
            for bar, y in zip(bars, ys, strict=True):
                axis.annotate(
                    f"{y:,.0f}",
                    (bar.get_x() + bar.get_width() / 2, y),
                    xytext=(0, 2),
                    textcoords="offset points",
                    ha="center",
                    fontsize=6.5,
                )
        axis.set_xticks(x, [el.FAMILY_NAMES[f] for f in fams], fontsize=7)
        axis.set_ylabel(f"{what}, million 2026 USD")
        verdict = (
            "pass rule (CH-28): event table at or below full dependence"
            if k == 1
            else ("shown against both brackets without a verdict (CH-28)")
        )
        axis.set_title(f"Portfolio {what}: {verdict}\n{storms_text(n, m)}", fontsize=9)
        axis.legend(fontsize=7, frameon=False)
        _style(axis)
    figure.tight_layout()
    return _png(figure, "brackets.png", out)


def figure_eal(metrics: dict, n: int, m: int, out: Path) -> str:
    """Event table against CRC's curves, each route beside the event table on the same assets."""
    plt = f3_model._plt()
    routes = metrics["routes"]
    figure, axes = plt.subplots(1, 2, figsize=(14, 5.2), gridspec_kw={"width_ratios": [1, 2]})
    items_left = [("buildings", routes["buildings"])]
    items_right = list(routes["substations"].items())
    bars = (
        ("point", "eal_event_table_same_assets", BLUE, "event table (assets of the point route)"),
        ("point", "eal_point", ORANGE, "CRC curves, point route"),
        ("grid", "eal_event_table_same_assets", AQUA, "event table (assets the grid reads)"),
        ("grid", "eal_grid", PURPLE, "CRC curves, grid route"),
    )
    width = 0.2
    for axis, items in ((axes[0], items_left), (axes[1], items_right)):
        for i, (_gname, by_route) in enumerate(items):
            for j, (route, key, colour, label) in enumerate(bars):
                if route not in by_route:
                    continue
                v = by_route[route][key] / 1e6
                x = i + (j - 1.5) * width
                axis.bar(x, v, width * 0.92, color=colour, label=label if i == 0 else None)
                axis.annotate(
                    f"{v:,.3f}",
                    (x, v),
                    xytext=(0, 2),
                    textcoords="offset points",
                    ha="center",
                    fontsize=6,
                )
        axis.set_xticks(
            np.arange(len(items)),
            [
                f"{el.FAMILY_NAMES.get(g, g)}\npoint {r['point']['assets_compared']:,}"
                + (f", grid {r['grid']['assets_compared']:,} assets" if "grid" in r else "")
                for g, r in items
            ],
            fontsize=7,
        )
        axis.set_ylabel("Expected annual loss, million 2026 USD")
        _style(axis)
        axis.legend(fontsize=7, frameon=False, loc="upper right")
    axes[0].set_title("Buildings", fontsize=9)
    axes[1].set_title("Substations (4 valued sites), by curve family", fontsize=9)
    figure.suptitle(
        f"Expected annual loss: event table and CRC's curves by both routes of FH7 — "
        f"{storms_text(n, m)}",
        fontsize=10,
    )
    figure.tight_layout()
    return _png(figure, "eal_routes.png", out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--figures", type=Path, default=paths.FIGURES / "f6")
    ap.add_argument("--records", type=Path, default=paths.RECORDS)
    args = ap.parse_args(argv)
    metrics = json.loads((args.data / "metrics.json").read_text())
    root = el.root_default()
    cat = el.read_catalogue(root)
    depths = el.read_depths(root, cat)
    n, m = len(cat.labels), cat.m
    curves = crc_adapter.load()
    subs = pd.read_csv(args.data / "substations.csv")
    figures = []
    for loc, rows in subs.groupby("LocNumber", sort=True):
        j = depths.site_ids.index(loc)
        figures.append(
            figure_substation(
                loc,
                rows["name"].iloc[0],
                depths.lead[:, j],
                cat.weights,
                float(m),
                rows,
                curves,
                n,
                args.figures,
            )
        )
    figures.append(figure_exceedance(metrics, n, m, args.figures))
    figures.append(figure_brackets(metrics, n, m, args.figures))
    figures.append(figure_eal(metrics, n, m, args.figures))

    # --- checks -------------------------------------------------------------------------------
    checks = [
        Check(
            "hand recomputation of three assets (FR7)",
            "a notebook written by an agent that does not see the code recomputes the three "
            "assets of metrics.json 'hand_check' to the cent",
            None,
            metrics["hand_check"],
            "to the cent",
            note="pending: done separately (plan F6 step 6)",
        )
    ]
    cvar = {
        f: [
            metrics["brackets"][f]["levels"]["100"]["events"][1],
            metrics["brackets"][f]["levels"]["100"]["full_dependence"][1],
        ]
        for f in el.FAMILIES
    }
    checks.append(
        Check(
            "event-table CVaR at 99% at or below the full-dependence bracket (CH-28)",
            "CVaR_0.99(event table) <= sum of the components' CVaR_0.99, every curve family",
            all(e <= c * (1 + 1e-12) for e, c in cvar.values()),
            cvar,
            "event table <= full dependence",
        )
    )
    var = {f: metrics["brackets"][f]["levels"]["100"] for f in el.FAMILIES}
    checks.append(
        Check(
            "1-in-100 loss against both brackets (no verdict, CH-28)",
            "VaR at 99% of the event table shown beside full dependence and independence",
            None,
            {
                f: {k: v[k][0] for k in ("independence", "events", "full_dependence")}
                for f, v in var.items()
            },
            "no verdict",
            note="CH-28: VaR has no bound from the brackets; reported without a verdict",
        )
    )
    routes = metrics["routes"]
    point_ok = all(
        r["point"]["within_5_percent"]
        for r in [routes["buildings"], *routes["substations"].values()]
    )
    checks.append(
        Check(
            "expected annual loss, event table against CRC's curves, point route",
            "within 5% (proposed), on the same assets",
            point_ok,
            {
                "buildings": routes["buildings"]["point"]["relative_difference"],
                **{f: r["point"]["relative_difference"] for f, r in routes["substations"].items()},
            },
            0.05,
            proposed=True,
        )
    )
    if "grid" in routes["buildings"]:
        grid_rel = {
            "buildings": routes["buildings"]["grid"]["relative_difference"],
            **{f: r["grid"]["relative_difference"] for f, r in routes["substations"].items()},
        }
        within = all(abs(v) <= mx.EAL_TOLERANCE for v in grid_rel.values() if v is not None)
        checks.append(
            Check(
                "expected annual loss, event table against CRC's curves, grid route",
                "within 5% (proposed), or the difference explained",
                True if within else None,
                grid_rel,
                0.05,
                proposed=True,
                note=(
                    ""
                    if within
                    else "outside 5%: explained in docs/flood/reports/F6-risk.md (a 5 m cell at "
                    "the asset point instead of the wall or lead depth, eight probabilities with "
                    "linear interpolation between them, the tail completion); the verdict is "
                    "Yuri's"
                ),
            )
        )
    f = metrics["failures"]
    accounted = (
        f["crc_failure_rows_buildings"] == 0
        and all(v == 0 for v in f["crc_failure_rows_substations"].values())
        and sum(f["by_reason"].values()) == metrics["results"]["main"]["buildings_left_out"]
        and sum(f["event_rows"].values()) == n * f["buildings"]
    )
    checks.append(
        Check(
            "every failure row accounted for",
            "CRC refusals counted; every building left out of the sums named with its reason",
            bool(accounted),
            {
                "by_reason": f["by_reason"],
                "crc_failure_rows_buildings": f["crc_failure_rows_buildings"],
                "crc_failure_rows_substations": f["crc_failure_rows_substations"],
            },
            "all counted",
        )
    )
    checks.append(
        Check(
            "occurrence equals aggregate (one storm per synthetic year)",
            "the extension's OCCURRENCE and AGGREGATE sums are equal year by year",
            metrics["catalogue"]["one_storm_per_year_occurrence_equals_aggregate"],
            metrics["catalogue"]["one_storm_per_year_occurrence_equals_aggregate"],
            True,
        )
    )
    checks.append(
        Check(
            "year weights sum to M",
            "catalogue block weights sum to M = 1,000",
            abs(metrics["catalogue"]["weights_sum"] - m) < 1e-9,
            metrics["catalogue"]["weights_sum"],
            m,
        )
    )
    main = metrics["results"]["main"]["families"]
    numbers: dict[str, Any] = {
        "N_catalogue_runs": n,
        "M_synthetic_years": m,
        "highest_return_period_supported_y": metrics["catalogue"][
            "highest_return_period_supported_y"
        ],
        "portfolio_eal_usd": {f: v["eal"] for f, v in main.items()},
        "portfolio_100y_var_crc_usd": {f: v["levels"]["100"]["var_crc"] for f, v in main.items()},
        "portfolio_100y_cvar_crc_usd": {f: v["levels"]["100"]["cvar_crc"] for f, v in main.items()},
        "portfolio_100y_tools_usd": {
            f: v["levels"]["100"]["one_in_t_tools"] for f, v in main.items()
        },
        "buildings_eal_usd": metrics["results"]["main"]["buildings_eal"],
        "substations_eal_usd": {f: v["substations_eal"] for f, v in main.items()},
        "buildings_in_sums": metrics["results"]["main"]["buildings_in_sums"],
        "buildings_left_out": metrics["results"]["main"]["buildings_left_out"],
        "bootstrap_eal_interval_usd": {
            f: b["interval"]["eal"] for f, b in metrics["bootstrap"].items()
        },
        "bootstrap_100y_var_interval_usd": {
            f: b["interval"]["var_100_crc"] for f, b in metrics["bootstrap"].items()
        },
        "dry_threshold_m": metrics["dry_threshold_m"],
    }
    tables = {
        "sensitivities": {
            name: {
                f: {
                    "eal": v["eal"],
                    "var_100_crc": v["levels"]["100"]["var_crc"],
                    "cvar_100_crc": v["levels"]["100"]["cvar_crc"],
                    "one_in_100_tools": v["levels"]["100"]["one_in_t_tools"],
                }
                for f, v in r["families"].items()
            }
            | {"buildings_in_sums": r["buildings_in_sums"]}
            for name, r in metrics["results"].items()
        },
        "brackets": metrics["brackets"],
        "routes": metrics["routes"],
        "failures": metrics["failures"],
        "substations": subs.to_dict(orient="records"),
        "hand_check": metrics["hand_check"],
    }
    inputs = [
        Input.of(root / el.SELECTION, root=root),
        *[Input.of(root / el.PER_RUN / f"{x}.npz", root=root) for x in cat.labels],
        *[Input.of(root / p, root=root) for p in metrics["grid_files"].values()],
        Input.of(el.EXPOSURES, root=paths.ROOT),
        Input.of(crc_adapter.CURVES, root=paths.ROOT),
        *[Input.of(p, root=paths.ROOT) for p in sorted(args.data.glob("*.csv"))],
        Input.of(args.data / "metrics.json", root=paths.ROOT),
    ]
    record = Record(
        id=RECORD_ID,
        stage="F6",
        title="Curves, the event-loss table and risk: portfolio and substation figures from CRC",
        inputs=inputs,
        parameters=[
            Parameter("runs", n, "I", "f4/selection.json (CH-26 runs_cover)"),
            Parameter("synthetic_years_M", m, "P", "RainyDay NYEARS, CH-19"),
            Parameter("dry_threshold_m", metrics["dry_threshold_m"], "P", "catalogue.WET_M"),
            Parameter("return_periods_y", list(mx.RETURN_PERIODS), "P", "plan F6"),
            Parameter("value_level_main", "mid", "P", "brief; V-1"),
            Parameter("c5_basis_main", "role", "P", "C-5, CH-30"),
            Parameter("bootstrap_resamples", mx.BOOTSTRAP_N, "P", "FR8"),
            Parameter("bootstrap_seed", mx.BOOTSTRAP_SEED, "P", "FR8"),
            Parameter("bracket_samples", mx.BRACKET_SAMPLES, "P", "FR6, RESAMPLED"),
            Parameter("bracket_seed", mx.BRACKET_SEED, "P", "FR6"),
            Parameter("tail_completion", "lower 0 m, upper = last knot held", "P", "FR5"),
            Parameter("eal_tolerance", mx.EAL_TOLERANCE, "P", "plan F6 (proposed)"),
        ],
        numbers=numbers,
        tables=tables,
        checks=checks,
        figures=figures,
        notes=[
            "Occurrence and aggregate annual losses are the same here: one storm per synthetic "
            "year (RainyDay keeps each year's largest 3-hour storm).",
            "1 in T: CRC's VaR at q = 1 - 1/T (lower quantile, the extension reports it) and "
            "the tools' convention (largest loss with P(L >= x) >= 1/T, as Oasis LMF, OpenQuake "
            "and the F4 depth frequency) are shown side by side (design-note question 7).",
            "The main case reads depths below 0.05 m (catalogue.WET_M, the wet rule of the F4 "
            "frequency) as 0 before BD-1; read literally (0 m), BD-1 makes about 10,900 "
            "buildings wet in every run by sub-millimetre depths: shown as a sensitivity.",
            "Substation values are placeholders [P] (MISO and Con Edison figures, V-1 to V-5); "
            "building values are NSI [S] or Hazus substitutes (A-8).",
            "Bor 2026's set is for substations above 345 kV; it is applied to the 138 kV sites "
            "as the alternative FR2 names, outside its stated range.",
        ],
    )
    path = record.write(args.records)
    print(json.dumps({"record": str(path), "passed": record.passed, "figures": figures}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
