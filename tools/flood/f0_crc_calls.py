"""F0, step 1: every crc-sdk and crc-framework call the flood lab relies on, run once on toy data.

Requirements section 9, item 12; the calls are listed in ``docs/flood/crc-1.0-mapping.md``. Each
probe returns what was observed and whether it matches the reading in the mapping. Nothing here is
flood data: the rasters, curves and assets are made up so that every expected value can be worked
out by hand.

    uv run python tools/flood/f0_crc_calls.py            # all probes but the timing
    uv run python tools/flood/f0_crc_calls.py --timing   # also the 600,000-cell read

Writes ``site/flood/tests/records/f0-crc-calls.json``. Run from a file, never from ``python -``.
"""

from __future__ import annotations

import argparse
import itertools
import resource
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RETURN_PERIODS = (2, 5, 10, 25, 50, 100, 500)
PROBABILITIES = tuple(1 - 1 / t for t in RETURN_PERIODS)
NODATA = -9999.0
#: toy damage table, depth in metres to damage ratio; flat from 3 m to the stated maximum of 10 m
DAMAGE_POINTS = [(0.0, 0.0), (0.5, 0.2), (1.0, 0.4), (3.0, 0.8), (10.0, 0.8)]


def _variable() -> Any:
    from crc_framework import DepthAboveGround, LengthUnit
    from crc_sdk import Variable

    return Variable("flood-lab:toy-depth", measurement=DepthAboveGround(unit=LengthUnit.METRE))


def _damage() -> Any:
    from crc_framework import Impact, Ratio

    return Impact.tabulated(DAMAGE_POINTS, input=_variable().measurement, output=Ratio())


def _annual() -> Any:
    from crc_framework import Tail
    from crc_sdk import Probability

    return Probability.annual(tail=Tail.UPPER)


def _write_rasters(folder: Path, depths: np.ndarray, *, cell: float = 5.0) -> dict[float, Path]:
    """One GeoTIFF per probability, EPSG:32618, north-west corner near Jamaica Bay."""
    import rasterio
    from rasterio.transform import from_origin

    rows, cols = depths.shape[1:]
    transform = from_origin(598_000.0, 4_500_000.0, cell, cell)
    files = {}
    for index, probability in enumerate(PROBABILITIES):
        path = folder / f"depth_q{index}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=rows,
            width=cols,
            count=1,
            dtype="float32",
            crs="EPSG:32618",
            transform=transform,
            nodata=NODATA,
            compress="deflate",
        ) as dst:
            dst.write(depths[index].astype("float32"), 1)
        files[probability] = path
    return files


def _toy_depths(rows: int, cols: int, seed: int = 7) -> np.ndarray:
    """Non-decreasing depths per cell: about half the cells dry at every probability."""
    rng = np.random.default_rng(seed)
    scale = np.where(rng.random((rows, cols)) < 0.5, 0.0, rng.gamma(2.0, 0.3, (rows, cols)))
    onset = rng.integers(0, len(PROBABILITIES), (rows, cols))  # first probability that is wet
    steps = np.arange(len(PROBABILITIES))[:, None, None]
    growth = np.clip(steps - onset[None] + 1, 0, None) / len(PROBABILITIES)
    return (scale[None] * growth).astype("float32")


def _knots(row: dict[str, Any]) -> tuple[list[float], list[float]]:
    curve = row["curve"]["quantile_curve"]
    return list(curve["probabilities"]), list(curve["values"])


def probe_from_raster(tmp: Path) -> dict[str, Any]:
    import pyproj
    import shapely
    from crc_sdk import Dataset

    depths = _toy_depths(20, 20)
    depths[:, 0, 0] = NODATA  # one masked cell
    depths[:, 0, 1] = 0.0  # one cell dry at every probability
    files = _write_rasters(tmp / "ok", depths) if (tmp / "ok").mkdir() is None else {}
    result = Dataset.from_raster(files, variable=_variable(), probability=_annual()).read()
    table = result.table
    rows = table.to_pylist()
    to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    differ, compared, largest = 0, 0, 0.0
    seen_dry = False
    for row in rows:
        centre = shapely.from_wkb(row["geometry"]).centroid
        x, y = to_utm.transform(centre.x, centre.y)
        col, line = int((x - 598_000.0) // 5), int((4_500_000.0 - y) // 5)
        probabilities, values = _knots(row)
        expected = depths[:, line, col]
        gap = float(np.max(np.abs(np.array(values) - expected)))
        prob_gap = float(np.max(np.abs(np.array(probabilities) - np.array(PROBABILITIES))))
        largest = max(largest, gap, prob_gap)
        differ += gap > 1e-6 or prob_gap > 1e-12
        compared += 1
        seen_dry |= (line, col) == (0, 1) and max(values) == 0.0
    counts = getattr(result.report, "counts", None)
    return {
        "call": "Dataset.from_raster",
        "cells_in_raster": 400,
        "rows_returned": len(rows),
        "columns": table.column_names,
        "cells_compared": compared,
        "cells_differing": int(differ),
        "largest_difference": largest,
        "all_dry_cell_delivered_with_zeros": seen_dry,
        "masked_cell_delivered": len(rows) == 400,
        "report_counts": str(counts),
        "geometry_type": shapely.from_wkb(rows[0]["geometry"]).geom_type,
        "matches_reading": differ == 0 and len(rows) == 399 and seen_dry,
    }


def probe_from_raster_decreasing(tmp: Path) -> dict[str, Any]:
    from crc_sdk import Dataset

    depths = _toy_depths(20, 20)
    depths[3, 5, 5] = depths[2, 5, 5] + 0.5
    depths[4, 5, 5] = depths[2, 5, 5] + 0.1  # falls as probability rises
    (tmp / "bad").mkdir()
    files = _write_rasters(tmp / "bad", depths)
    try:
        rows = Dataset.from_raster(files, variable=_variable(), probability=_annual()).read()
        return {
            "call": "Dataset.from_raster, one decreasing cell",
            "raised": False,
            "rows_returned": rows.table.num_rows,
            "matches_reading": False,
        }
    except Exception as error:  # noqa: BLE001  the kind of failure is what is being observed
        message = str(error)
        fixed = np.maximum.accumulate(depths, axis=0)
        (tmp / "fixed").mkdir()
        again = Dataset.from_raster(
            _write_rasters(tmp / "fixed", fixed), variable=_variable(), probability=_annual()
        ).read()
        return {
            "call": "Dataset.from_raster, one decreasing cell",
            "raised": True,
            "error_type": type(error).__name__,
            "message": message[:400],
            "message_names_the_cell": "5" in message and ("row" in message or "pixel" in message),
            "rows_after_running_maximum": again.table.num_rows,
            "matches_reading": again.table.num_rows == 400,
        }


def _points_table(dry_probability: float) -> dict[str, list[Any]]:
    """Three points near Jamaica Bay; the first has a dry-year mass as an exact knot."""
    table: dict[str, list[Any]] = {
        "support_id": [],
        "longitude": [],
        "latitude": [],
        "probability": [],
        "value": [],
    }
    curves = {
        "asset-a": (
            -73.850,
            40.650,
            [0.0, dry_probability, 0.98, 0.99, 0.998],
            [0, 0, 0.6, 1.1, 2.4],
        ),
        "asset-b": (-73.840, 40.655, [0.5, 0.9, 0.99, 0.998], [0.0, 0.3, 1.2, 2.5]),
        "asset-c": (-73.830, 40.660, [0.5, 0.9, 0.99, 0.998], [0.1, 0.5, 1.6, 3.2]),
    }
    for support, (lon, lat, probabilities, values) in curves.items():
        for probability, value in zip(probabilities, values, strict=True):
            table["support_id"].append(support)
            table["longitude"].append(lon)
            table["latitude"].append(lat)
            table["probability"].append(probability)
            table["value"].append(float(value))
    return table


def probe_from_quantiles() -> dict[str, Any]:
    from crc_sdk import Dataset, decode_curves

    table = _points_table(0.93)
    rows = Dataset.from_quantiles(table, variable=_variable(), probability=_annual()).read().table
    curves = decode_curves(rows)
    by_id = dict(zip(rows["support_id"].to_pylist(), curves, strict=True))
    a = by_id["asset-a"]
    return {
        "call": "Dataset.from_quantiles, decode_curves",
        "rows_returned": rows.num_rows,
        "asset_a_knots": _knots(rows.to_pylist()[rows["support_id"].to_pylist().index("asset-a")]),
        "asset_a_depth_at_dry_probability": float(a.quantile(0.93)),
        "asset_a_depth_just_below": float(a.quantile(0.92)),
        "asset_a_depth_at_0.955_linear_in_probability": float(a.quantile(0.955)),
        "expected_at_0.955": 0.6 * (0.955 - 0.93) / (0.98 - 0.93),
        "matches_reading": rows.num_rows == 3
        and float(a.quantile(0.93)) == 0.0
        and abs(float(a.quantile(0.955)) - 0.3) < 1e-9,
    }


def probe_two_routes() -> dict[str, Any]:
    """The same cell by fixed probabilities (raster route) and by its own knots (point route)."""
    from crc_framework import QuantileCurve, TailCompletion

    dry = 0.93  # dry in 93% of years: falls between the 10-year (0.9) and 25-year (0.96) rasters
    exact = QuantileCurve([0.0, dry, 0.98, 0.99, 0.998], [0.0, 0.0, 0.6, 1.1, 2.4])
    exact_law = exact.complete(TailCompletion(lower=0.0, upper=2.4))
    fixed_values = [float(exact_law.quantile(q)) for q in PROBABILITIES]
    fixed = QuantileCurve(list(PROBABILITIES), fixed_values)
    fixed_law = fixed.complete(TailCompletion(lower=0.0, upper=2.4))
    damage = _damage()
    exact_mean, fixed_mean = (
        float(damage.expectation(exact_law)),
        float(damage.expectation(fixed_law)),
    )
    return {
        "call": "QuantileCurve.complete, Impact.expectation on both routes",
        "dry_probability": dry,
        "depths_at_fixed_probabilities": fixed_values,
        "expected_damage_exact_knots": exact_mean,
        "expected_damage_fixed_probabilities": fixed_mean,
        "relative_difference": (fixed_mean - exact_mean) / exact_mean,
        "exceedance_of_zero_exact": float(exact_law.exceedance(0.0)),
        "exceedance_of_zero_fixed": float(fixed_law.exceedance(0.0)),
        "matches_reading": abs(float(exact_law.exceedance(0.0)) - (1 - dry)) < 1e-9
        and fixed_mean != exact_mean,
    }


def probe_impact() -> dict[str, Any]:
    from crc_framework import ImpactError, QuantileCurve, TailCompletion

    damage = _damage()
    values = [float(v) for v in damage.evaluate([0.25, 0.75, 2.0])]
    curve = QuantileCurve([0.5, 0.9, 0.99, 0.998], [0.0, 0.3, 1.2, 2.5])
    law = curve.complete(TailCompletion(lower=0.0, upper=4.0))
    # by hand: depth is piecewise linear in probability and damage piecewise linear in depth, so
    # the mean is a sum of trapezoids over the segments cut at every damage-table breakpoint
    grid = np.linspace(0.0, 1.0, 2_000_001)
    hand = float(
        np.trapezoid(
            np.interp(
                np.interp(grid, [0, 0.5, 0.9, 0.99, 0.998, 1.0], [0, 0, 0.3, 1.2, 2.5, 4.0]),
                *zip(*DAMAGE_POINTS, strict=True),
            ),
            grid,
        )
    )
    mean = float(damage.expectation(law))
    outside: dict[str, Any] = {}
    try:
        outside["value"] = float(damage.evaluate(12.0))
        outside["raised"] = False
    except (ImpactError, Exception) as error:  # noqa: BLE001
        outside = {"raised": True, "error_type": type(error).__name__, "message": str(error)[:200]}
    incomplete: dict[str, Any] = {}
    try:
        incomplete["value"] = float(damage.expectation(curve))
        incomplete["raised"] = False
    except Exception as error:  # noqa: BLE001
        incomplete = {
            "raised": True,
            "error_type": type(error).__name__,
            "message": str(error)[:200],
        }
    return {
        "call": "Impact.tabulated, evaluate, expectation",
        "ratios_at_0.25_0.75_2.0_m": values,
        "expected_ratios": [0.1, 0.3, 0.6],
        "expectation": mean,
        "expectation_by_fine_trapezoid": hand,
        "depth_beyond_table": outside,
        "expectation_of_incomplete_curve": incomplete,
        "matches_reading": np.allclose(values, [0.1, 0.3, 0.6])
        and abs(mean - hand) < 1e-6
        and outside["raised"]
        and incomplete["raised"],
    }


def probe_evaluate() -> dict[str, Any]:
    from crc_sdk import Assets, Dataset, Distance, PointColumns, SpatialMatch

    depth = Dataset.from_quantiles(_points_table(0.93), variable=_variable(), probability=_annual())
    assets = Assets(
        {
            "asset_id": ["on-a", "near-b", "far-away"],
            "lon": [-73.850, -73.8401, -73.50],
            "lat": [40.650, 40.6551, 40.90],
            "value_usd": [1_000_000.0, 2_000_000.0, 3_000_000.0],
        },
        id_column="asset_id",
        location=PointColumns(longitude="lon", latitude="lat"),
        columns=["value_usd"],
    )
    spatial = SpatialMatch.nearest(max_distance=Distance.kilometres(1))
    result = (
        depth.evaluate(assets, spatial=spatial)
        .return_periods([10, 100, 500, 1000])
        .impact("damage_ratio", _damage(), variable=_variable())
        .read()
    )
    rows = result.table.to_pylist()
    keep = ("asset_id", "support_id", "response_id", "query_value", "value", "distance_metres")
    slim = [
        {k: row.get(k) for k in keep} | {"failure": (row.get("failure") or {}).get("code")}
        for row in rows
    ]
    codes = sorted({row["failure"] for row in slim if row["failure"]})
    by_key = {(r["asset_id"], r["response_id"], r["query_value"]): r["value"] for r in slim}
    # asset-a at 100 years: depth 1.1 m, ratio 0.4 + (1.1 - 1.0) / 2.0 * 0.4 = 0.42
    depth_100 = by_key[("on-a", None, 100.0)]
    ratio_100 = next(v for (a, r, q), v in by_key.items() if a == "on-a" and r and q == 100.0)
    return {
        "call": "Dataset.evaluate(Assets).return_periods(...).impact(...).read()",
        "columns": result.table.column_names,
        "row_count": len(rows),
        "rows": slim,
        "failure_codes": codes,
        "report_counts": str(result.report.counts),
        "on_a_depth_and_ratio_at_100_years": [depth_100, ratio_100],
        "note": "one set of rows for the exposure (response_id empty) and one per named response; "
        "under SpatialMatch.nearest an unmatched asset fails with outside_max_distance",
        "matches_reading": codes == ["outside_max_distance", "query_outside_support"]
        and abs(depth_100 - 1.1) < 1e-9
        and abs(ratio_100 - 0.42) < 1e-9
        and len(rows) == 24,
    }


def probe_compute_risk() -> dict[str, Any]:
    from crc_framework import BinaryOutcome, compute_risk

    spec = [("a", 0.9, 0.0, 100.0), ("b", 0.8, 0.0, 250.0), ("c", 0.95, 10.0, 400.0)]
    outcomes = [
        BinaryOutcome(
            i, lower_rank_mass=p, lower_impact=low, upper_rank_mass=1 - p, upper_impact=up
        )
        for i, p, low, up in spec
    ]
    result = compute_risk(outcomes, levels=[0.9, 0.99])
    branches = []
    for states in itertools.product((0, 1), repeat=3):
        mass, total = 1.0, 0.0
        for (_, p, low, up), state in zip(spec, states, strict=True):
            mass *= (1 - p) if state else p
            total += up if state else low
        branches.append((total, mass))
    branches.sort()

    def hand(level: float) -> tuple[float, float]:
        cumulative, var = 0.0, branches[-1][0]
        for total, mass in branches:
            cumulative += mass
            if cumulative >= level - 1e-15:
                var = total
                break
        tail, cumulative, acc = 1 - level, 0.0, 0.0
        for total, mass in reversed(branches):
            take = min(mass, tail - cumulative)
            if take <= 0:
                break
            acc += take * total
            cumulative += take
        return var, acc / tail

    levels = {}
    ok = True
    for level in (0.9, 0.99):
        got = result.at(level)
        var, cvar = hand(level)
        levels[str(level)] = {
            "value_at_risk": got.value_at_risk,
            "conditional_value_at_risk": got.conditional_value_at_risk,
            "by_hand": [var, cvar],
            "attribution": [
                (a.id, a.value_at_risk, a.conditional_value_at_risk) for a in got.attribution
            ],
        }
        ok &= (
            abs(got.value_at_risk - var) < 1e-9 and abs(got.conditional_value_at_risk - cvar) < 1e-9
        )
    return {
        "call": "compute_risk on three independent two-state outcomes",
        "branch_count": result.branch_count,
        "levels": levels,
        "serves_as_independence_bracket": ok,
        "limit": "each asset has exactly two loss states; a loss distribution per asset must first "
        "be reduced to two states",
        "matches_reading": ok,
    }


def probe_distribution() -> dict[str, Any]:
    from crc_framework import Distribution, QuantileCurve, Statistic, Tail, TailCompletion

    rng = np.random.default_rng(1)
    annual = np.where(rng.random(1000) < 0.8, 0.0, rng.gamma(2.0, 50_000.0, 1000))
    law = Distribution.empirical(annual)
    summary = law.statistics(metrics=[Statistic.MEAN, Statistic.CVAR], level=0.99, tail=Tail.UPPER)
    var = float(law.quantile(0.99))
    cvar = summary.values[Statistic.CVAR].value
    exceed = [float(v) for v in law.exceedance([0.0, 1e5, 2e5])]
    again = Distribution.from_json(law.to_json())
    depth = QuantileCurve([0.5, 0.9, 0.99, 0.998], [0.0, 0.3, 1.2, 2.5]).complete(
        TailCompletion(lower=0.0, upper=4.0)
    )
    pushed = _damage().pushforward(depth)
    pushed_mean = pushed.statistics(metrics=[Statistic.MEAN]).values[Statistic.MEAN].value
    ok = (
        var == float(np.quantile(annual, 0.99, method="inverted_cdf"))
        and abs(cvar - np.sort(annual)[-10:].mean()) < 1e-6
        and exceed == [float((annual > x).mean()) for x in (0.0, 1e5, 2e5)]
        and float(again.quantile(0.99)) == var
        and abs(pushed_mean - float(_damage().expectation(depth))) < 1e-12
    )
    return {
        "call": "Distribution.empirical and its figures; Impact.pushforward",
        "value_at_risk_99": var,
        "conditional_value_at_risk_99": cvar,
        "mean": summary.values[Statistic.MEAN].value,
        "exceedance_at_0_1e5_2e5": exceed,
        "json_round_trip_equal": float(again.quantile(0.99)) == var,
        "pushforward_mean": pushed_mean,
        "matches_reading": bool(ok),
    }


def probe_observations() -> dict[str, Any]:
    """Ten sensor events: irregular in time, which is what FloodNet's event table is."""
    from crc_sdk import Observations

    table = {
        "support_id": [f"sensor-{i % 3}" for i in range(10)],
        "longitude": [-73.85 + 0.01 * (i % 3) for i in range(10)],
        "latitude": [40.65 + 0.005 * (i % 3) for i in range(10)],
        "time": [f"2023-09-{20 + i:02d}T{(7 * i) % 24:02d}:15:00Z" for i in range(10)],
        "value": [0.05 * (i + 1) for i in range(10)],
    }
    out: dict[str, Any] = {"call": "Observations.from_table on ten irregular sensor events"}
    try:
        result = Observations.from_table(table, variable=_variable()).read()
        got = result.table
        out |= {
            "without_sampling": "accepted",
            "rows_returned": got.num_rows,
            "columns": got.column_names,
            "values_equal": sorted(got["value"].to_pylist()) == sorted(table["value"]),
        }
    except Exception as error:  # noqa: BLE001
        out |= {
            "without_sampling": "refused",
            "error_type": type(error).__name__,
            "message": str(error)[:400],
        }
    out["matches_reading"] = out.get("without_sampling") == "accepted" and out.get("values_equal")
    return out


def probe_layer() -> dict[str, Any]:
    import shapely
    from crc_sdk import Layer, LayerColumns

    polygons = [
        shapely.box(-73.86 + 0.002 * i, 40.64, -73.859 + 0.002 * i, 40.641).wkb for i in range(10)
    ]
    table = {
        "support_id": [f"poly-{i}" for i in range(10)],
        "geometry": polygons,
        "value": [float(1 + i % 2) for i in range(10)],  # a depth class code
        "label": ["4 in to 1 ft" if i % 2 == 0 else "over 1 ft" for i in range(10)],
    }
    out: dict[str, Any] = {"call": "Layer.from_table on ten polygons with a class code"}
    try:
        from crc_framework import Ratio
        from crc_sdk import Variable

        variable = Variable("flood-lab:toy-depth-class", measurement=Ratio())
        result = Layer.from_table(
            table, variable=variable, columns=LayerColumns(geometry="geometry", label="label")
        ).read()
        got = result.table
        out |= {
            "accepted": True,
            "rows_returned": got.num_rows,
            "columns": got.column_names,
            "geometry_equal": all(
                shapely.from_wkb(a).equals(shapely.from_wkb(b))
                for a, b in zip(sorted(got["geometry"].to_pylist()), sorted(polygons), strict=True)
            ),
        }
    except Exception as error:  # noqa: BLE001
        out |= {"accepted": False, "error_type": type(error).__name__, "message": str(error)[:400]}
    out["matches_reading"] = bool(out.get("accepted") and out.get("geometry_equal"))
    return out


def probe_timing(tmp: Path) -> dict[str, Any]:
    from crc_sdk import Dataset

    side = 775  # 775 x 775 = 600,625 cells of 5 m: about 15 km2
    (tmp / "big").mkdir()
    files = _write_rasters(tmp / "big", _toy_depths(side, side))
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    start = time.perf_counter()
    table = Dataset.from_raster(files, variable=_variable(), probability=_annual()).read().table
    seconds = time.perf_counter() - start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "call": "Dataset.from_raster, 775 x 775 cells, seven probabilities",
        "cells": side * side,
        "rows_returned": table.num_rows,
        "seconds": round(seconds, 1),
        "cells_per_second": round(side * side / seconds),
        "peak_memory_gib": round(peak / 2**30, 2),  # macOS reports bytes
        "peak_memory_before_gib": round(before / 2**30, 2),
        "table_bytes_gib": round(table.nbytes / 2**30, 2),
        "matches_reading": table.num_rows == side * side,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timing", action="store_true", help="also time the 600,000-cell read")
    parser.add_argument("--only", help="run one probe by name")
    args = parser.parse_args()

    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from flood_lab.records import Check, Parameter, Record

    with tempfile.TemporaryDirectory(prefix="f0-crc-") as name:
        tmp = Path(name)
        probes: dict[str, Any] = {
            "from_raster": lambda: probe_from_raster(tmp),
            "from_raster_decreasing": lambda: probe_from_raster_decreasing(tmp),
            "from_quantiles": probe_from_quantiles,
            "two_routes": probe_two_routes,
            "impact": probe_impact,
            "evaluate": probe_evaluate,
            "compute_risk": probe_compute_risk,
            "distribution": probe_distribution,
            "observations": probe_observations,
            "layer": probe_layer,
        }
        if args.timing:
            probes["timing"] = lambda: probe_timing(tmp)
        results: dict[str, Any] = {}
        for key, probe in probes.items():
            if args.only and key != args.only:
                continue
            try:
                results[key] = probe()
            except Exception as error:  # noqa: BLE001  a probe that cannot run is itself a result
                results[key] = {
                    "could_not_run": True,
                    "error_type": type(error).__name__,
                    "message": str(error)[:600],
                    "where": traceback.format_exc().strip().splitlines()[-3:],
                    "matches_reading": False,
                }
            print(
                key, "->", "as read" if results[key].get("matches_reading") else "DIFFERS / FAILED"
            )

    if args.only:
        import json

        print(json.dumps(results, indent=1, default=str))
        return
    record = Record(
        id="f0-crc-calls",
        stage="F0",
        title="CRC 1.0.0 calls the flood lab relies on, run once on toy data",
        parameters=[
            Parameter("return_periods_years", list(RETURN_PERIODS), "P"),
            Parameter("toy_damage_points_m_ratio", DAMAGE_POINTS, "P"),
            Parameter("raster_crs", "EPSG:32618", "P"),
            Parameter("raster_nodata", NODATA, "P"),
        ],
        tables=results,
        checks=[
            Check(
                key,
                "behaves as read in docs/flood/crc-1.0-mapping.md",
                bool(value.get("matches_reading")),
                note=value.get("call", ""),
            )
            for key, value in results.items()
        ],
        notes=["Toy data only. Nothing here is a flood depth, an asset or a loss."],
    )
    print("record:", record.write(ROOT / "site" / "flood" / "tests" / "records"))


if __name__ == "__main__":
    main()
