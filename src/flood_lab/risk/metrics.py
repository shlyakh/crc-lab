"""F6 step 5: risk figures from the event-loss tables and from CRC's curves (FR5, FR6, FR8).

    uv run --extra flood python -m flood_lab.risk.metrics

Every figure of a distribution is CRC's: the portfolio's annual losses (the extension's sums of
``event_loss``) become a ``crc_framework.Distribution`` (``Distribution.discrete`` with the year
weights, since the catalogue's years are not equally weighted), and the expected annual loss,
VaR, CVaR and exceedance probabilities are read from it. This module adds, joins and resamples.

* **1 in T.** CRC's VaR at ``q = 1 - 1/T`` is the smallest loss whose cumulative mass reaches q
  (design note question 7). The tools' convention (Oasis LMF, OpenQuake, RainyDay's frequency
  file and the F4 depth frequency): the largest loss whose exceedance mass ``P(L >= x)`` reaches
  1/T; with M equal years the k-th largest has return period M / k. Both are reported, labelled
  (Yuri, 2026-11-28). The tools' figure is this module's rank by weights (``tools_level``), not a
  CRC statistic.
* **Occurrence and aggregate** are the same here: one storm per synthetic year. Both are summed by
  the extension and checked equal.
* **Highest return period (P-2).** The smallest year mass is 1/M = 0.001 (stratum T1), so the
  catalogue supports return periods up to 1,000 years; 10, 100 and 500 are reported.
* **Bootstrap (FR8).** Runs are resampled with replacement within each stratum (as many as the
  stratum has), each drawn run keeping its block weight, rescaled so the stratum keeps its
  years; each resample's figures come from CRC. Seed and count are parameters.
* **Brackets (FR6).** ``crc_event_loss.brackets``: full dependence (components' VaR and CVaR
  added) and independence (``RESAMPLED``: each component's year drawn independently), with the
  events' own figure; components whose losses are 0 in every year are left out of the brackets
  (they add 0 under any dependence).
* **Curve routes (FR5, FH7).** Per asset, CRC's depth curve by both routes:
  the point route (``crc_load.points_table`` -> ``Dataset.from_quantiles``) and the grid route
  (the F4 GeoTIFFs -> ``Dataset.from_raster``, evaluated at the asset point: substation outline
  centroid, building footprint centroid, as F4 loaded them). Expected annual damage:
  ``QuantileCurve.complete(TailCompletion(lower=0, upper=last knot))`` then
  ``Impact.expectation``; damage distribution: ``Impact.pushforward``; loss at 10, 100 and 500
  years: ``evaluate(assets).return_periods(...)`` with ``.impact(...)`` for the substations (one
  impact per call) and, for buildings, the depths of ``evaluate`` read through each building's
  own impact by ``Impact.evaluate``. A building's impact on depth above ground is its Hazus curve
  shifted by its first-floor height with BD-1 to BD-5 and the dry threshold written into its
  knots (``building_impact``).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import crc_framework as cf
import numpy as np
import pandas as pd

from crc_event_loss import (
    AnnualLosses,
    AnnualMeasure,
    IndependenceMethod,
    YearWeights,
    brackets,
)
from flood_lab import paths
from flood_lab.hazard import catalogue
from flood_lab.risk import building_depth, crc_adapter, crc_load
from flood_lab.risk import event_loss as el
from lab_common.io import write_json_atomic, write_text_atomic

OUT = paths.SITE / "data" / "f6"
WORK = "f6"  # under the cache: the full event-loss tables (Parquet), not committed
RETURN_PERIODS = (10, 100, 500)
LEVELS = tuple(1 - 1 / t for t in RETURN_PERIODS)
#: FR8: bootstrap resamples and seed [P]
BOOTSTRAP_N = 1000
BOOTSTRAP_SEED = 20261128
#: FR8: the interval reported, 5% and 95% of the resamples [P]
BOOTSTRAP_INTERVAL = (0.05, 0.95)
#: FR6: independence bracket by resampling, sample count and seed [P]
BRACKET_SAMPLES = 20_000
BRACKET_SEED = 20261128
#: width of a jump in a building's composite impact, metres (cf. crc_load.STEP_GAP)
JUMP_M = 1e-9
#: rounding allowance at a curve's two ends when its knots are shifted, metres (< JUMP_M)
KNOT_SLACK_M = 1e-10
#: return periods of the bootstrap band on the exceedance curve, years (at most 1,000: P-2)
BAND_YEARS = (2, 5, 10, 25, 50, 100, 250, 500, 1000)
#: pass rule of plan F6 (proposed): the event table and the curve routes within 5%
EAL_TOLERANCE = 0.05


# --- figures of one annual-loss set -----------------------------------------------------------


def mean_of(law: cf.Distribution) -> float:
    value = law.statistics(metrics=[cf.Statistic.MEAN]).values[cf.Statistic.MEAN]
    if value.status is not cf.StatisticStatus.FINITE or value.value is None:
        raise ValueError(f"CRC gives no finite mean: {value!r}")
    return float(value.value)


def tools_level(values: np.ndarray, weights: np.ndarray, years: float) -> float:
    """The tools' 1-in-T: the largest value whose weighted exceedance ``P(L >= x)`` reaches
    1/T (relative slack 1e-9, as ``catalogue.depth_at``); 0 if no year reaches it."""
    order = np.argsort(-np.asarray(values, float), kind="stable")
    v = np.asarray(values, float)[order]
    cum = np.cumsum(np.asarray(weights, float)[order])
    k = int((cum < (1 / years) * (1 - 1e-9)).sum())
    return float(v[k]) if k < len(v) else 0.0


def figures(annual: AnnualLosses, *, attribution: bool = False) -> dict[str, Any]:
    """EAL, VaR, CVaR (CRC) and the tools' 1-in-T for one annual-loss set."""
    law = annual.distribution()
    weights = np.asarray(annual.years.weights)
    out: dict[str, Any] = {"eal": mean_of(law), "levels": {}}
    for t, level in zip(RETURN_PERIODS, annual.risk(LEVELS), strict=True):
        row: dict[str, Any] = {
            "q": level.probability,
            "var_crc": level.value_at_risk,
            "cvar_crc": level.conditional_value_at_risk,
            "one_in_t_tools": tools_level(annual.totals, weights, t),
        }
        if attribution:
            top = sorted(level.attribution, key=lambda a: -a.conditional_value_at_risk)[:10]
            row["cvar_top_components"] = [[a.id, a.conditional_value_at_risk] for a in top]
        out["levels"][str(t)] = row
    return out


def exceedance_points(annual: AnnualLosses) -> list[list[float]]:
    """``[loss, P(L > loss) from CRC, P(L >= loss)]`` at each distinct annual loss."""
    law = annual.distribution()
    xs = np.unique(annual.totals)
    above = np.asarray(law.exceedance(xs.tolist()), float)
    w = np.asarray(annual.years.weights)
    at_least = [float(w[annual.totals >= x].sum()) for x in xs]
    return [[float(x), float(a), b] for x, a, b in zip(xs, above, at_least, strict=True)]


# --- bootstrap --------------------------------------------------------------------------------


def bootstrap(
    totals: np.ndarray,
    weights: np.ndarray,
    strata: tuple[str, ...],
    *,
    n: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Resample runs within strata; EAL, VaR and CVaR at 1 in 100 from CRC per resample, the
    tools' 1-in-100 by ``tools_level``. Returns the interval and the resamples' figures."""
    rng = np.random.default_rng(seed)
    labels = np.asarray(strata)
    groups = {s: np.flatnonzero(labels == s) for s in dict.fromkeys(strata)}
    m = float(weights.sum())
    rows, curve = [], []
    for b in range(n):
        idx, w = [], []
        for members in groups.values():
            drawn = rng.choice(members, size=len(members), replace=True)
            scale = weights[members].sum() / weights[drawn].sum()
            idx.append(drawn)
            w.append(weights[drawn] * scale)
        idx_a = np.concatenate(idx)
        mass = np.concatenate(w) / m
        mass = mass / math.fsum(mass)
        years = YearWeights(tuple(f"b{k}" for k in range(len(idx_a))), tuple(mass))
        values = totals[idx_a]
        annual = AnnualLosses(
            measure=AnnualMeasure.AGGREGATE,
            years=years,
            totals=values,
            components={"portfolio": values},
            currency=el.CURRENCY,
            valuation_basis=el.VALUATION,
            label=f"bootstrap {b}",
            diagnostics=(),
        )
        (level,) = annual.risk([0.99])
        law = annual.distribution()
        curve.append([float(law.quantile(1 - 1 / t)) for t in BAND_YEARS])
        rows.append(
            [
                mean_of(annual.distribution()),
                level.value_at_risk,
                level.conditional_value_at_risk,
                tools_level(values, mass, 100),
            ]
        )
    arr = np.array(rows)
    names = ("eal", "var_100_crc", "cvar_100_crc", "one_in_100_tools")
    interval = {}
    for k, name in enumerate(names):
        law = cf.Distribution.empirical(arr[:, k])
        interval[name] = [float(law.quantile(q)) for q in BOOTSTRAP_INTERVAL]
    band = np.array(curve)
    exceedance_band = {
        str(t): [
            float(cf.Distribution.empirical(band[:, k]).quantile(q)) for q in BOOTSTRAP_INTERVAL
        ]
        for k, t in enumerate(BAND_YEARS)
    }
    return {
        "resamples": n,
        "seed": seed,
        "var_band_by_return_period": exceedance_band,
        "interval_quantiles": list(BOOTSTRAP_INTERVAL),
        "interval": interval,
        "values": {name: arr[:, k].tolist() for k, name in enumerate(names)},
    }


# --- brackets ---------------------------------------------------------------------------------


def bracket_figures(annual: AnnualLosses) -> dict[str, Any]:
    nonzero = {c: v for c, v in annual.components.items() if np.any(v > 0)}
    slim = AnnualLosses(
        measure=annual.measure,
        years=annual.years,
        totals=annual.totals,
        components=nonzero,
        currency=annual.currency,
        valuation_basis=annual.valuation_basis,
        label=annual.label,
        diagnostics=annual.diagnostics,
    )
    result = brackets(
        slim,
        levels=LEVELS,
        independence=IndependenceMethod.RESAMPLED,
        samples=BRACKET_SAMPLES,
        seed=BRACKET_SEED,
    )
    out: dict[str, Any] = {
        "components_with_loss": len(nonzero),
        "components_left_out_all_zero": len(annual.components) - len(nonzero),
        "independence": "resampled",
        "samples": BRACKET_SAMPLES,
        "seed": BRACKET_SEED,
        "levels": {},
    }
    for t, b in zip(RETURN_PERIODS, result, strict=True):
        out["levels"][str(t)] = {
            "q": b.level,
            "full_dependence": [
                b.comonotonic.value_at_risk,
                b.comonotonic.conditional_value_at_risk,
            ],
            "events": [b.from_events.value_at_risk, b.from_events.conditional_value_at_risk],
            "independence": [b.independent.value_at_risk, b.independent.conditional_value_at_risk],
        }
    return out


# --- curve routes -----------------------------------------------------------------------------


def building_impact(
    points: list[list[float]],
    ffh_m: float,
    basement: str,
    *,
    dry_below_m: float,
    curve: cf.Impact,
) -> cf.Impact | None:
    """One building's impact on depth above ground (``crc_adapter.DEPTH``): its Hazus curve read
    by the event table's rules, written as knots. Breakpoints: 0, the dry threshold, and every
    Hazus knot shifted by the first-floor height; a jump (at the dry threshold, and at the curve's
    lowest point for a building without basement) is two knots ``JUMP_M`` apart. The domain ends at
    the curve's highest point (BD-4): a deeper depth is CRC's ``out_of_domain``. Values come from
    CRC (``curve.evaluate``) at the depths ``building_depth.curve_depth`` gives. None where the
    rules fail inside the domain (BD-3 with unknown basement, BD-5)."""
    xs = np.array([p[0] for p in points], float)
    if not math.isfinite(ffh_m):
        # BD-5: no height; only depths below the dry threshold have a loss (none)
        return cf.Impact.tabulated(
            [(0.0, 0.0), (dry_below_m - JUMP_M, 0.0)], input=crc_adapter.DEPTH, output=cf.Ratio()
        )
    top = ffh_m + xs[-1]
    breaks = {0.0, top}
    if 0 < dry_below_m < top:
        breaks |= {dry_below_m, dry_below_m - JUMP_M}
    for x in xs:
        if 0 < ffh_m + x < top:
            breaks.add(ffh_m + x)
    low = ffh_m + xs[0]
    if basement != "Y" and 0 < low - JUMP_M:
        breaks.add(low - JUMP_M)
    d = np.array(sorted(b for b in breaks if 0 <= b <= top))
    used = np.where(d < dry_below_m, 0.0, d)
    # the knots are sums ffh + x, so a curve's own ends come back within rounding of its ends:
    # the ends are widened by KNOT_SLACK_M and the depths clipped back onto the curve
    at, case = building_depth.curve_depth(
        used,
        np.full(d.shape, ffh_m),
        np.full(d.shape, basement, dtype=object),
        xs[0] - KNOT_SLACK_M,
        xs[-1] + KNOT_SLACK_M,
    )
    at = np.clip(at, xs[0], xs[-1])
    if (case == building_depth.Case.FAILED).any():
        return None
    ratio = np.zeros(d.shape)
    read = case == building_depth.Case.READ
    if read.any():
        ratio[read] = np.asarray(curve.evaluate(at[read]), float)
    return cf.Impact.tabulated(
        list(zip(d.tolist(), ratio.tolist(), strict=True)),
        input=crc_adapter.DEPTH,
        output=cf.Ratio(),
    )


def _curve_of(record: dict) -> cf.QuantileCurve:
    q = record["quantile_curve"]
    return cf.QuantileCurve(list(q["probabilities"]), list(q["values"]))


def complete(curve: cf.QuantileCurve) -> cf.Distribution:
    """Tail completion [P]: depth 0 at non-exceedance 0, the last knot's depth held to 1."""
    values = list(curve.values)
    return curve.complete(cf.TailCompletion(lower=0.0, upper=float(max(values))))


def point_route_depths(depth: np.ndarray, w: np.ndarray, m: float, years) -> np.ndarray:
    """Depth at each return period from CRC's ``QuantileCurve`` on the point route's knots."""
    curve = cf.QuantileCurve(*crc_load.asset_knots(depth, w, m))
    return np.array([float(curve.quantile(1 - 1 / t)) for t in years])


def substation_ratios(curve_id: str, depths: np.ndarray) -> np.ndarray:
    """Damage ratios of one substation curve of ``curves.yaml`` from CRC (``Impact.evaluate``)."""
    return np.asarray(crc_adapter.substation_impacts()[curve_id].evaluate(depths), float)


def point_dataset(assets: list[dict], depth: np.ndarray, w: np.ndarray, m: float):
    from crc_sdk import Dataset

    table = crc_load.points_table(assets, depth, w, m)
    return Dataset.from_quantiles(
        table, variable=crc_load.variable(), probability=crc_load.annual()
    )


def grid_dataset(root: Path):
    from crc_sdk import Dataset

    folder = root / "f4" / "frequency_cover" / "grid"
    files = {1.0 - a: folder / f"depth_aep_{a:g}.tif" for a in catalogue.AEPS}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"grid route rasters missing: {missing}")
    return (
        Dataset.from_raster(
            dict(sorted(files.items())), variable=crc_load.variable(), probability=crc_load.annual()
        ),
        files,
    )


def crc_assets(assets: list[dict]):
    from crc_sdk import Assets

    return Assets(
        {
            "asset_id": [a["id"] for a in assets],
            "longitude": [float(a["longitude"]) for a in assets],
            "latitude": [float(a["latitude"]) for a in assets],
        },
        id_column="asset_id",
    )


def evaluated(dataset, assets: list[dict], query: str, values, impact=None) -> dict:
    """``{asset_id: {query_value: (exposure value or None, ratio or None, failure code)}}``."""
    ev = dataset.evaluate(crc_assets(assets))
    ev = ev.return_periods(list(values)) if query == "rp" else ev.probabilities(list(values))
    if impact is not None:
        ev = ev.impact("damage_ratio", impact, variable=crc_load.variable())
    rows = ev.read().table.to_pylist()
    out: dict[str, dict] = {}
    for r in rows:
        slot = out.setdefault(r["asset_id"], {}).setdefault(
            float(r["query_value"]), [None, None, ""]
        )
        code = (r.get("failure") or {}).get("code") or ""
        if r.get("response_id"):
            slot[1] = r["value"]
        else:
            slot[0] = r["value"]
        slot[2] = slot[2] or code
    return out


# --- the build --------------------------------------------------------------------------------


def _valued(frame: pd.DataFrame, level: str) -> pd.Series:
    """Value at ``level``; where low or high is not stated, the mid value (labelled)."""
    mid = frame["value_mid_usd_2026"]
    if level == "mid":
        return mid
    return frame[f"value_{level}_usd_2026"].where(frame[f"value_{level}_usd_2026"].notna(), mid)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    write_text_atomic(path, frame.to_csv(index=False, float_format="%.12g", lineterminator="\n"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP_N)
    ap.add_argument("--skip-grid", action="store_true", help="leave out the grid route")
    args = ap.parse_args(argv)
    t_start = time.perf_counter()
    timing: dict[str, float] = {}

    def lap(name: str, t0: float) -> float:
        timing[name] = round(time.perf_counter() - t0, 1)
        return time.perf_counter()

    t0 = time.perf_counter()
    root = el.root_default()
    cat = el.read_catalogue(root)
    fp = el.study_footprints(root)
    depths = el.read_depths(root, cat, fp["doitt_id"].tolist())
    exposures = el.read_exposures()
    detail = pd.read_csv(root / el.BUILDINGS_DETAIL, dtype=str)
    curves = crc_adapter.load()
    buildings = exposures[exposures["asset_type"] == "building"].reset_index(drop=True)
    alt = el.alt_first_floors(root)
    buildings["ffh_ff4_m"] = (
        buildings["LocNumber"]
        .map(alt)
        .where(buildings["LocNumber"].map(alt).notna(), buildings["ffh_m"])
    )
    for level in el.VALUE_LEVELS:
        buildings[f"value_{level}_used"] = _valued(buildings, level)
    columns = el.wall_columns(depths.footprint_ids, detail, buildings["LocNumber"].tolist())
    w, m = cat.weights, float(cat.m)
    t0 = lap("inputs_s", t0)

    # --- event-loss tables, main case and sensitivities ---------------------------------------
    wet = catalogue.WET_M
    cases = {
        "main": el.building_cases(buildings, depths.walls, columns, curves, dry_below_m=wet),
        "ff4_alt": el.building_cases(
            buildings, depths.walls, columns, curves, dry_below_m=wet, ffh_column="ffh_ff4_m"
        ),
        "dry_literal": el.building_cases(buildings, depths.walls, columns, curves, dry_below_m=0.0),
    }
    t0 = lap("building_cases_s", t0)
    variants = {
        # name: (cases, value column, building filter, dry threshold, C-5 basis)
        "main": ("main", "mid", None, wet, "role"),
        "value_low": ("main", "low", None, wet, "role"),
        "value_high": ("main", "high", None, wet, "role"),
        "c5_hazus_kv": ("main", "mid", None, wet, "hazus_kv"),
        "ff4_alt_heights": ("ff4_alt", "mid", None, wet, "role"),
        "without_lot_shared_with_nsi": ("main", "mid", "lot_shared_with_nsi", wet, "role"),
        "without_substitute_values": ("main", "mid", "value_substitute", wet, "role"),
        "dry_threshold_0_literal_bd1": ("dry_literal", "mid", None, 0.0, "role"),
    }
    work = root / WORK
    work.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    main_tables: dict[str, Any] = {}
    annual_cols: dict[str, np.ndarray] = {}
    b_cache: dict[tuple, Any] = {}
    s_cache: dict[tuple, Any] = {}
    for name, (case_key, level, drop, dry, basis) in variants.items():
        key = (case_key, level)
        if key not in b_cache:
            table, left_out = el.building_table(
                cat,
                buildings,
                cases[case_key],
                value_column=f"value_{level}_used",
                label=f"buildings, {case_key}, value {level}",
            )
            b_cache[key] = (table, el.annual(table), left_out)
        b_table, b_annual, left_out = b_cache[key]
        if drop:
            dropped = set(buildings.loc[buildings[drop], "LocNumber"])
            b_annual = AnnualLosses(
                measure=b_annual.measure,
                years=b_annual.years,
                totals=np.sum(
                    [v for c, v in b_annual.components.items() if c not in dropped], axis=0
                ),
                components={c: v for c, v in b_annual.components.items() if c not in dropped},
                currency=b_annual.currency,
                valuation_basis=b_annual.valuation_basis,
                label=f"{b_annual.label}, without {drop}",
                diagnostics=b_annual.diagnostics,
            )
        skey = (level, dry, basis)
        if skey not in s_cache:
            s_tables = el.substation_tables(
                cat,
                exposures,
                depths.lead,
                depths.site_ids,
                dry_below_m=dry,
                value_column=f"value_{level}_usd_2026",
                basis=basis,
            )
            s_cache[skey] = (s_tables, {f: el.annual(t) for f, t in s_tables.items()})
        s_tables, s_annual = s_cache[skey]
        res: dict[str, Any] = {
            "buildings_in_sums": len(b_annual.components),
            "buildings_left_out": len(left_out) + (int(buildings[drop].sum()) if drop else 0),
            "buildings_value_in_sums": float(
                buildings.set_index("LocNumber")
                .loc[list(b_annual.components), f"value_{level}_used"]
                .sum()
            ),
            "buildings_eal": mean_of(b_annual.distribution()),
            "families": {},
        }
        for fam in el.FAMILIES:
            port = el.combine([b_annual, s_annual[fam]], f"{name}, substations {fam}")
            fig = figures(port, attribution=(name == "main"))
            fig["substations_eal"] = mean_of(s_annual[fam].distribution())
            res["families"][fam] = fig
            annual_cols[f"{name}__{fam}"] = port.totals
            if name == "main":
                main_tables[fam] = (port, s_tables[fam], s_annual[fam])
        annual_cols[f"{name}__buildings"] = b_annual.totals
        results[name] = res
    t0 = lap("tables_and_figures_s", t0)
    main_b_table, main_b_annual, main_left_out = b_cache[("main", "mid")]
    main_b_table.write(work / "event_losses_buildings_main.parquet", overwrite=True)
    for fam, (_, st, _) in main_tables.items():
        st.write(work / f"event_losses_substations_{fam}.parquet", overwrite=True)

    # occurrence = aggregate (one storm a year)
    occ = el.annual(main_b_table, AnnualMeasure.OCCURRENCE)
    occurrence_equal = bool(np.array_equal(occ.totals, main_b_annual.totals))

    # --- failures -----------------------------------------------------------------------------
    case = cases["main"]
    reasons = pd.Series(case.reason)
    failures = {
        "buildings": len(buildings),
        "by_reason": {r: int((reasons == r).sum()) for r in sorted(set(case.reason)) if r},
        "value_of_failed_buildings": float(
            buildings.loc[reasons != "", "value_mid_usd_2026"].sum()
        ),
        "event_rows": {
            "read": int((case.case == building_depth.Case.READ).sum()),
            "no_loss": int((case.case == building_depth.Case.NO_LOSS).sum()),
            "failed": int((case.case == building_depth.Case.FAILED).sum()),
        },
        "crc_failure_rows_buildings": len(main_b_table.failures),
        "crc_failure_rows_substations": {f: len(t[1].failures) for f, t in main_tables.items()},
        "basement_read_at_minus_4ft_rows": int(
            np.sum(
                (case.case == building_depth.Case.READ)
                & np.isclose(case.at, -1.2192)
                & (buildings["basement"].to_numpy() == "Y")[None, :]
            )
        ),
        "substations": {
            "with_value_and_curve": len(main_tables["low"][1].component_ids),
            "without": sorted(
                set(exposures.loc[exposures["asset_type"] == "substation", "LocNumber"])
                - set(main_tables["low"][1].component_ids)
            ),
        },
        "footprints_of_hazard_set_not_assets": int(
            len(depths.footprint_ids) - int((columns >= 0).sum())
        ),
        "dry_literal_by_reason": {
            r: int((pd.Series(cases["dry_literal"].reason) == r).sum())
            for r in sorted(set(cases["dry_literal"].reason))
            if r
        },
    }
    for fam, (_, st, _) in main_tables.items():
        for d in st.diagnostics:
            if d.code == "impact_refused_values" and d.details.get("count"):
                failures.setdefault("crc_refusals", {})[fam] = dict(d.details)

    # --- bootstrap and brackets ---------------------------------------------------------------
    boot = {}
    brk = {}
    for fam, (port, _, _) in main_tables.items():
        boot[fam] = bootstrap(port.totals, w, cat.strata, n=args.bootstrap)
        t0 = lap(f"bootstrap_{fam}_s", t0)
        brk[fam] = bracket_figures(port)
        t0 = lap(f"brackets_{fam}_s", t0)

    # --- curve routes -------------------------------------------------------------------------
    import geopandas as gpd

    from flood_lab.checks import f4_catalogue

    sites = {s["id"]: s for s in f4_catalogue.sites(f4_catalogue.f3_model.SUBSTATIONS)}
    centroids = gpd.GeoSeries(fp.geometry.centroid, crs=fp.crs).to_crs("EPSG:4326")
    valued_sites = list(main_tables["low"][1].component_ids)
    site_col = {s: depths.site_ids.index(s) for s in valued_sites}
    in_sums = list(main_b_annual.components)
    pos = {loc: j for j, loc in enumerate(buildings["LocNumber"])}
    b_assets = [
        {
            "id": loc,
            "longitude": float(centroids.iloc[columns[pos[loc]]].x),
            "latitude": float(centroids.iloc[columns[pos[loc]]].y),
        }
        for loc in in_sums
    ]
    s_assets = [
        {"id": s, "longitude": sites[s]["longitude"], "latitude": sites[s]["latitude"]}
        for s in valued_sites
    ]
    b_depth = np.stack([case.depth[:, pos[loc]] for loc in in_sums], axis=1)
    s_depth = depths.lead[:, [site_col[s] for s in valued_sites]]
    point = point_dataset(s_assets + b_assets, np.hstack([s_depth, b_depth]), w, m)
    rows = point.read().table
    point_curves = {
        sid: _curve_of(rec)
        for sid, rec in zip(rows["support_id"].to_pylist(), rows["curve"].to_pylist(), strict=True)
    }
    t0 = lap("point_route_load_s", t0)
    if args.skip_grid:
        grid = None
        grid_files = {}
    else:
        grid, grid_files = grid_dataset(root)
    probs = [1.0 - a for a in catalogue.AEPS]

    def grid_curves(assets: list[dict]) -> tuple[dict, dict]:
        if grid is None:
            return {}, {}
        got = evaluated(grid, assets, "p", probs)
        curves_, fails = {}, {}
        for aid, by_q in got.items():
            vals = [by_q.get(float(p), [None, None, "missing"]) for p in probs]
            if any(v[0] is None for v in vals):
                fails[aid] = next((v[2] for v in vals if v[2]), "no value")
                continue
            curves_[aid] = cf.QuantileCurve(probs, [float(v[0]) for v in vals])
        return curves_, fails

    # one grid call for every asset (each call reads the eight rasters again)
    all_grid, all_grid_fail = grid_curves(s_assets + b_assets)
    s_grid = {k: v for k, v in all_grid.items() if k in site_col}
    s_grid_fail = {k: v for k, v in all_grid_fail.items() if k in site_col}
    b_grid = {k: v for k, v in all_grid.items() if k not in site_col}
    b_grid_fail = {k: v for k, v in all_grid_fail.items() if k not in site_col}
    rp_grid = evaluated(grid, s_assets + b_assets, "rp", RETURN_PERIODS) if grid is not None else {}
    s_point = point_dataset(s_assets, s_depth, w, m)
    rp_impact: dict[str, dict] = {}
    t0 = lap("grid_route_load_s", t0)

    s_impacts = crc_adapter.substation_impacts()
    choice = el.substation_choice(exposures)
    values_s = exposures.set_index("LocNumber")["value_mid_usd_2026"]
    sub_rows = []
    for s in valued_sites:
        for fam in el.FAMILIES:
            impact = s_impacts[choice[s][fam]]
            row: dict[str, Any] = {
                "LocNumber": s,
                "name": sites[s]["name"],
                "family": fam,
                "curve_id": choice[s][fam],
                "value_mid_usd_2026": float(values_s[s]),
                "eal_event_table": float(main_tables[fam][2].components[s] @ (w / m)),
            }
            for route, curve in (("point", point_curves.get(s)), ("grid", s_grid.get(s))):
                if curve is None:
                    row[f"eal_{route}"] = None
                    row[f"{route}_failure"] = s_grid_fail.get(s, "no curve")
                    continue
                law = complete(curve)
                row[f"ead_{route}"] = float(impact.expectation(law))
                row[f"eal_{route}"] = row[f"ead_{route}"] * float(values_s[s])
                pushed = impact.pushforward(law)
                row[f"damage_mean_pushforward_{route}"] = mean_of(pushed)
                for t in RETURN_PERIODS:
                    row[f"damage_q{t}_pushforward_{route}"] = float(pushed.quantile(1 - 1 / t))
            # loss at T: the point route through .impact() (one call per curve, cached), the grid
            # route's depths (one call for every asset) through Impact.evaluate
            if choice[s][fam] not in rp_impact:
                rp_impact[choice[s][fam]] = evaluated(
                    s_point, s_assets, "rp", RETURN_PERIODS, impact
                )
            got_p = rp_impact[choice[s][fam]].get(s, {})
            for t in RETURN_PERIODS:
                d, r, code = got_p.get(float(t), [None, None, "no row"])
                row[f"depth_{t}y_point"] = d
                row[f"ratio_{t}y_point"] = r
                row[f"loss_{t}y_point"] = None if r is None else r * float(values_s[s])
                if code:
                    row[f"failure_{t}y_point"] = code
                d, _, code = rp_grid.get(s, {}).get(float(t), [None, None, "no row"])
                row[f"depth_{t}y_grid"] = d
                r = None if d is None else float(np.asarray(impact.evaluate([float(d)]))[0])
                row[f"ratio_{t}y_grid"] = r
                row[f"loss_{t}y_grid"] = None if r is None else r * float(values_s[s])
                if code:
                    row[f"failure_{t}y_grid"] = code
            sub_rows.append(row)
    t0 = lap("substation_curves_s", t0)

    # buildings: EAL by both routes and loss at 10/100/500 y
    b_impacts = crc_adapter.building_impacts()
    points_of = {c["id"]: c["points"] for c in curves["building_curves"]}
    bframe = buildings.set_index("LocNumber")
    rp_point = evaluated(point, b_assets, "rp", RETURN_PERIODS)
    t0 = lap("building_return_periods_s", t0)
    b_rows = []
    route_fail = {"point": {}, "grid": {}}
    for loc in in_sums:
        b = bframe.loc[loc]
        value = float(b["value_mid_usd_2026"])
        comp = building_impact(
            points_of[b["curve_id"]],
            float(b["ffh_m"]) if pd.notna(b["ffh_m"]) else float("nan"),
            str(b["basement"]),
            dry_below_m=wet,
            curve=b_impacts[b["curve_id"]],
        )
        row = {
            "LocNumber": loc,
            "value_mid_usd_2026": value,
            "eal_event_table": float(main_b_annual.components[loc] @ (w / m)),
        }
        for route, curve in (("point", point_curves.get(loc)), ("grid", b_grid.get(loc))):
            if comp is None or curve is None:
                row[f"eal_{route}"] = None
                why = (
                    "impact not representable" if comp is None else b_grid_fail.get(loc, "no curve")
                )
                route_fail[route][why] = route_fail[route].get(why, 0) + 1
                continue
            try:
                row[f"eal_{route}"] = float(comp.expectation(complete(curve))) * value
            except cf.ImpactError as error:
                row[f"eal_{route}"] = None
                route_fail[route][error.code] = route_fail[route].get(error.code, 0) + 1
        for route, got in (("point", rp_point), ("grid", rp_grid)):
            for t in RETURN_PERIODS:
                d = got.get(loc, {}).get(float(t), [None, None, ""])[0]
                row[f"depth_{t}y_{route}"] = d
                loss = None
                if d is not None and comp is not None:
                    try:
                        loss = float(np.asarray(comp.evaluate([float(d)]))[0]) * value
                    except cf.ImpactError:
                        loss = None
                row[f"loss_{t}y_{route}"] = loss
        b_rows.append(row)
    t0 = lap("building_curves_s", t0)

    # per-asset table of every building (with case counts and the failure reason)
    per_building = pd.DataFrame(
        {
            "LocNumber": buildings["LocNumber"],
            "curve_id": buildings["curve_id"],
            "ffh_m": buildings["ffh_m"],
            "basement": buildings["basement"],
            "value_mid_usd_2026": buildings["value_mid_usd_2026"],
            "value_substitute": buildings["value_substitute"],
            "lot_shared_with_nsi": buildings["lot_shared_with_nsi"],
            "runs_read": (case.case == building_depth.Case.READ).sum(axis=0),
            "runs_no_loss": (case.case == building_depth.Case.NO_LOSS).sum(axis=0),
            "runs_failed": (case.case == building_depth.Case.FAILED).sum(axis=0),
            "failure": case.reason,
        }
    ).merge(pd.DataFrame(b_rows), on=["LocNumber", "value_mid_usd_2026"], how="left")
    subs = pd.DataFrame(sub_rows)

    # --- comparison of the routes ---------------------------------------------------------------
    comp_b = pd.DataFrame(b_rows)

    def route_compare(frame: pd.DataFrame, route: str) -> dict[str, Any]:
        ok = frame[f"eal_{route}"].notna()
        ev = float(frame.loc[ok, "eal_event_table"].sum())
        cv = float(frame.loc[ok, f"eal_{route}"].sum())
        rel = (cv - ev) / ev if ev else None
        diff = (frame.loc[ok, f"eal_{route}"] - frame.loc[ok, "eal_event_table"]).abs()
        return {
            "assets_compared": int(ok.sum()),
            "assets_not_compared": int((~ok).sum()),
            "eal_event_table_same_assets": ev,
            f"eal_{route}": cv,
            "relative_difference": rel,
            "largest_asset_difference_usd": float(diff.max()) if len(diff) else None,
            "within_5_percent": None if rel is None else abs(rel) <= EAL_TOLERANCE,
        }

    routes = {
        "buildings": {
            r: route_compare(comp_b, r) for r in ("point", "grid") if grid or r == "point"
        },
        "buildings_route_failures": route_fail,
        "substations": {
            fam: {
                r: route_compare(subs[subs["family"] == fam], r)
                for r in ("point", "grid")
                if grid or r == "point"
            }
            for fam in el.FAMILIES
        },
    }

    # --- hand-check selection -----------------------------------------------------------------
    sub_pick = max(valued_sites, key=lambda s: float(depths.lead[:, site_col[s]].max()))
    pb = per_building.set_index("LocNumber")
    ordinary = pb[
        (pb["failure"] == "")
        & ~buildings.set_index("LocNumber")["value_substitute"]
        & (buildings.set_index("LocNumber")["asset_substitute_class"].fillna("") == "")
        & (pb["runs_read"] >= 3)
        & (pb["eal_event_table"] > 0)
    ]
    ordinary_pick = ordinary.index[0]
    minus4 = (case.case == building_depth.Case.READ) & np.isclose(case.at, -1.2192)
    special = pb[
        (pb["failure"] == "")
        & buildings.set_index("LocNumber")["value_substitute"]
        & (pb["runs_read"] >= 3)
        & pd.Series(minus4.any(axis=0), index=buildings["LocNumber"])
        & (pb["eal_event_table"] > 0)
        & pd.Series(
            [bool(c) and points_of[c][0][1] > 0 for c in buildings["curve_id"]],
            index=buildings["LocNumber"],
        )
    ]
    special_pick = special.index[0] if len(special) else None
    hand_rows = []
    for i, label in enumerate(cat.labels):
        base = {"event_id": label, "rank": cat.ranks[i], "stratum": cat.strata[i], "weight": w[i]}
        j = site_col[sub_pick]
        for fam in el.FAMILIES:
            hand_rows.append(
                base
                | {
                    "LocNumber": sub_pick,
                    "family": fam,
                    "depth_raw_m": depths.lead[i, j],
                }
            )
        for loc in (ordinary_pick, special_pick):
            if loc is None:
                continue
            k = pos[loc]
            raw = depths.walls[i, columns[k]]
            hand_rows.append(
                base
                | {
                    "LocNumber": loc,
                    "family": "",
                    "depth_raw_m": raw,
                }
            )
    hand = pd.DataFrame(hand_rows)

    # substation event losses (every run, valued site, family)
    se_rows = []
    for fam, (_, st, _) in main_tables.items():
        rows_t = st.to_arrow().to_pylist()
        got = {(r["event_id"], r["component_id"]): r for r in rows_t}
        for i, label in enumerate(cat.labels):
            for s in valued_sites:
                r = got.get((label, s))
                se_rows.append(
                    {
                        "event_id": label,
                        "LocNumber": s,
                        "family": fam,
                        "curve_id": choice[s][fam],
                        "depth_raw_m": depths.lead[i, site_col[s]],
                        "depth_used_m": r["intensity"] if r else 0.0,
                        "damage_ratio": r["damage_ratio"] if r else 0.0,
                        "loss_usd_2026": r["loss"] if r else 0.0,
                    }
                )
    sub_events = pd.DataFrame(se_rows)

    annual_frame = pd.DataFrame(
        {
            "event_id": cat.labels,
            "rank": cat.ranks,
            "stratum": cat.strata,
            "weight_years": w,
            "mass": [x / m for x in w],
            **{k: v for k, v in annual_cols.items()},
        }
    )

    # --- write --------------------------------------------------------------------------------
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "distributions").mkdir(exist_ok=True)
    for fam, (port, _, _) in main_tables.items():
        write_text_atomic(
            out / "distributions" / f"portfolio_main_{fam}.json", port.distribution().to_json()
        )
    _write_csv(annual_frame, out / "annual_losses.csv")
    _write_csv(per_building, out / "buildings.csv")
    _write_csv(subs, out / "substations.csv")
    _write_csv(sub_events, out / "substation_event_losses.csv")
    _write_csv(hand, out / "hand_check_inputs.csv")
    metrics = {
        "generated_by": "flood_lab.risk.metrics",
        "currency": el.CURRENCY,
        "valuation_basis": el.VALUATION,
        "catalogue": {
            "runs": len(cat.labels),
            "M_synthetic_years": cat.m,
            "weights_sum": float(w.sum()),
            "smallest_year_mass": float(min(w) / m),
            "highest_return_period_supported_y": float(m / min(w)),
            "per_run_files_not_catalogue": list(cat.not_read),
            "one_storm_per_year_occurrence_equals_aggregate": occurrence_equal,
        },
        "dry_threshold_m": wet,
        "return_periods": list(RETURN_PERIODS),
        "results": results,
        "failures": failures,
        "bootstrap": {f: {k: v for k, v in b.items() if k != "values"} for f, b in boot.items()},
        "brackets": brk,
        "routes": routes,
        "exceedance_main": {f: exceedance_points(t[0]) for f, t in main_tables.items()},
        "loss_by_return_period_main": {
            f: {
                str(y): {
                    "var_crc": float(t[0].distribution().quantile(1 - 1 / y)),
                    "one_in_t_tools": tools_level(t[0].totals, np.asarray(t[0].years.weights), y),
                }
                for y in BAND_YEARS
            }
            for f, t in main_tables.items()
        },
        "hand_check": {
            "substation": sub_pick,
            "ordinary_building": ordinary_pick,
            "substitute_value_and_minus_4ft_building": special_pick,
        },
        "grid_files": {f"{k:.3f}": str(v.relative_to(root)) for k, v in grid_files.items()},
        "timing_s": timing | {"total_s": round(time.perf_counter() - t_start, 1)},
    }
    write_json_atomic(out / "metrics.json", metrics, indent=1, sort_keys=True, default=float)
    write_json_atomic(
        work / "bootstrap_values.json", {f: b["values"] for f, b in boot.items()}, default=float
    )
    print(json.dumps({k: metrics[k] for k in ("catalogue", "timing_s")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
