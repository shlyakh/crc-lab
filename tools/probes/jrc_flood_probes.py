"""Probes behind the jrc-flood findings that are not checks of the assessment (2026-11-17).

Run after `python -m data_source_check.build jrc-flood --draft --live`:

    uv run python tools/probes/jrc_flood_probes.py [--live]

Writes data/cache/validation/jrc-flood/probes/probes.json. `--live` also runs the cache probe,
which asks crc-sdk for the Fremont box once more over the network (about 30 MB).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/cache/validation/jrc-flood"
PERIODS = [10.0, 20.0, 50.0, 75.0, 100.0, 200.0, 500.0]
PIXEL = 0.0008333333356347339  # GloFAS pixel size, from the tile headers


def _keys(box: np.ndarray) -> np.ndarray:
    """One integer per pixel from the west and south edge of its square."""
    west = np.rint((box[:, 0] + 180.00708234) / PIXEL).astype(np.int64)
    south = np.rint((box[:, 1] + 89.9946) / PIXEL).astype(np.int64)
    return west * (1 << 20) + south


def same_pixel_in_two_areas() -> dict:
    """The pixels of the Austin run, looked up in the Texas run: curve and source_id."""
    from data_source_check.adapters.crc import jrc_flood as adapter

    small, large = CACHE / "framework/glofas-austin-r9", CACHE / "framework/glofas-tx-r7"
    a, t = adapter.curves(small), adapter.curves(large)
    ka, kt = _keys(a["box"]), _keys(t["box"])
    first_a = np.unique(ka, return_index=True)
    order = np.argsort(kt, kind="stable")
    position = np.searchsorted(kt[order], first_a[0])
    position[position >= len(order)] = 0
    found = kt[order][position] == first_a[0]
    rows_a, rows_t = first_a[1][found], order[position[found]]
    rng = np.random.default_rng(20261117)
    pick = rng.choice(len(rows_a), size=min(2000, len(rows_a)), replace=False)
    ids_a = adapter.source_ids(small, rows_a[pick].tolist())
    ids_t = adapter.source_ids(large, rows_t[pick].tolist())
    gap = np.abs(a["location"][rows_a] - t["location"][rows_t])
    return {
        "austin_pixels_with_a_curve": int(len(first_a[0])),
        "found_in_the_texas_run": int(found.sum()),
        "largest_difference_of_location_m": float(gap.max()),
        "source_ids_compared": len(ids_a),
        "source_ids_equal": int(sum(x == y for x, y in zip(ids_a, ids_t, strict=True))),
        "example": {"austin": ids_a[0], "texas": ids_t[0]},
    }


def tile_seams() -> dict:
    """Rows of the Texas run: is any (pixel, cell) pair there twice, and are seam pixels there?"""
    from data_source_check.adapters.crc import jrc_flood as adapter

    t = adapter.curves(CACHE / "framework/glofas-tx-r7")
    key = _keys(t["box"])
    pairs = np.stack([key.astype(np.uint64), t["cell"]], axis=1)
    distinct = np.unique(pairs, axis=0)
    west, south = t["box"][:, 0], t["box"][:, 1]
    east, north = t["box"][:, 2], t["box"][:, 3]
    tolerance = PIXEL / 4
    # where the four tiles meet, read from their headers: the tiles are 11,999 pixels wide and
    # their edges are not on whole degrees
    meridian, parallel = -100.00708234, 30.0054
    across = ((west < meridian - tolerance) & (east > meridian + tolerance)) | (
        (south < parallel - tolerance) & (north > parallel + tolerance)
    )
    return {
        "rows": int(len(key)),
        "distinct_pixel_and_cell_pairs": int(len(distinct)),
        "pixels": int(len(np.unique(key))),
        "seam_meridian": meridian,
        "seam_parallel": parallel,
        "pixels_west_of_the_meridian_seam_touching_it": int(
            len(np.unique(key[np.abs(east - meridian) < tolerance]))
        ),
        "pixels_east_of_the_meridian_seam_touching_it": int(
            len(np.unique(key[np.abs(west - meridian) < tolerance]))
        ),
        "pixels_south_of_the_parallel_seam_touching_it": int(
            len(np.unique(key[np.abs(north - parallel) < tolerance]))
        ),
        "pixels_north_of_the_parallel_seam_touching_it": int(
            len(np.unique(key[np.abs(south - parallel) < tolerance]))
        ),
        "pixels_lying_across_a_seam": int(len(np.unique(key[across]))),
    }


def optimizer() -> dict:
    """The same depths as decimal numbers and as the 32-bit numbers of the file."""
    from crc_framework import TabulatedDistribution, fit_quantiles

    out = []
    for depths in ([1, 1, 1, 1, 1, 1.016, 1.13], [1, 1, 1, 1, 1, 2.639, 3.768]):
        for label, values in (
            ("decimal", [float(v) for v in depths]),
            ("32-bit", [float(v) for v in np.asarray(depths, dtype=np.float32)]),
        ):
            table = TabulatedDistribution.from_return_periods(PERIODS, values, tail="upper")
            try:
                result = fit_quantiles(table, family="gumbel_r")
                answer = f"converged after {result.diagnostics.iterations} iterations"
            except ValueError as error:
                answer = f"ValueError: {error}"
            out.append({"depths": depths, "as": label, "answer": answer})
    return {"cases": out}


def relative_cache() -> dict:
    """A cache made under a relative path, then read offline from another working folder."""
    from crc_sdk.workflows import HazardDataset, JRCFloodPolicy

    box = (-122.15, 37.42, -121.85, 37.62)

    def plan(cache: Path | str, mode: str):  # noqa: ANN202
        area = HazardDataset.glofas(version="latest").for_area(box).cache(cache, mode=mode)
        return area.source_periods([10, 20, 50, 100]).canonicalize(
            policy=JRCFloodPolicy.curated(h3_resolution=7)
        )

    here = Path.cwd()
    with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
        try:
            os.chdir(first)
            plan(Path("cache"), "reuse").materialize(Path(first) / "a.parquet")
            manifest = json.loads(next(Path(first, "cache").rglob("manifest.json")).read_text())
            stored = sorted({str(Path(str(v)).parent) for v in _paths(manifest)})
            os.chdir(second)
            try:
                plan(Path(first) / "cache", "offline").materialize(Path(second) / "b.parquet")
                answer = "completed"
            except Exception as error:  # noqa: BLE001
                answer = f"{type(error).__name__}: {str(error)[:300]}"
            os.chdir(first)
            try:
                plan(Path("cache"), "offline").materialize(Path(first) / "c.parquet")
                same = "completed"
            except Exception as error:  # noqa: BLE001
                same = f"{type(error).__name__}: {str(error)[:300]}"
        finally:
            os.chdir(here)
    return {
        "paths_in_the_manifest_start_with": stored[:3],
        "offline_from_another_working_folder": answer.replace(first, "<first>"),
        "offline_from_the_same_working_folder": same.replace(first, "<first>"),
    }


def _paths(node: object) -> list[str]:
    if isinstance(node, dict):
        return [p for v in node.values() for p in _paths(v)]
    if isinstance(node, list):
        return [p for v in node for p in _paths(v)]
    return [node] if isinstance(node, str) and node.endswith(".tif") and "://" not in node else []


def permanent_water(live: bool) -> dict:
    """Flooded pixels of each GloFAS area by what crc-sdk does with them, and how many of each
    kind lie in the publisher's permanent-water layer (the layer the README says was used to
    patch the maps)."""
    from data_source_check.assessments import jrc_flood as base
    from data_source_check.reference import jrc_flood as reference

    out = {}
    rules = reference.Rules()
    for area in base.AREAS:
        if area.dataset != "glofas":
            continue
        copy = reference.Copy(area.dataset, CACHE, live=live)
        periods = reference.periods(copy.index(), copy.layout)
        tiles = reference.tiles_for(json.loads(copy.text("tile_extents.geojson")), area.bounds)
        water = {}
        for tile in tiles:
            with reference.Tiff(copy.file(f"Permanent_WaterBodies/{tile}_permanent_water.tif")) as t:
                data = t.read()
                water[(round(t.left, 3), round(t.top, 3))] = (
                    (data != 0) if t.nodata is None
                    else (data != 0) & (data != np.asarray(t.nodata, dtype=data.dtype))
                )
        kinds = ("fitted", "fewer than four depths", "all depths equal", "a depth decreases")
        count = {k: [0, 0] for k in kinds}

        def collect(grid, rows, columns, values, held, good, location, scale, inside,
                    water=water, count=count):  # noqa: ANN001, ANN202
            wet = water[(round(grid.left, 3), round(grid.top, 3))][rows, columns]
            enough = held.sum(axis=0) >= 4
            low, high = np.nanmin(values, axis=0), np.nanmax(values, axis=0)
            equal = enough & (low == high)
            for name, chosen in (
                ("fitted", good), ("fewer than four depths", ~enough), ("all depths equal", equal),
                ("a depth decreases", enough & ~equal & ~good),
            ):
                count[name][0] += int(chosen.sum())
                count[name][1] += int((chosen & wet).sum())

        base._read_reference(copy, area, periods, tiles, {}, rules, base.STRIP_ROWS,
                             collect=collect)
        out[area.id] = {
            "pixels_in_permanent_water": int(sum(
                int(w[r0:r1, c0:c1].sum()) for w, (c0, r0, c1, r1) in (
                    (water[(round(g.left, 3), round(g.top, 3))], g.window(area.bounds, rules))
                    for g in (reference.Tiff(copy.file(reference.depth_name(copy.layout, periods[0], t)))
                              for t in tiles)
                ) if (c0, r0, c1, r1)
            )),
            **{k: {"pixels": v[0], "in_permanent_water": v[1]} for k, v in count.items()},
        }
    return out


def main() -> None:
    target = CACHE / "probes/probes.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = json.loads(target.read_text()) if target.exists() else {}
    result["optimizer"] = optimizer()
    result["same_pixel_in_two_areas"] = same_pixel_in_two_areas()
    result["tile_seams"] = tile_seams()
    result["permanent_water"] = permanent_water("--live" in sys.argv)
    if "--live" in sys.argv and "--no-cache-probe" not in sys.argv:
        result["relative_cache"] = relative_cache()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=1), encoding="utf-8")
    os.replace(temporary, target)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
