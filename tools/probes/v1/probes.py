"""The probes: one function per question, each returning what was run, what was observed and a
verdict per finding. Run through ``run.py``, one child process per probe.

Verdicts come from a fixed list (``VERDICTS``). Observations are numbers and exact error texts;
the wording of the report stays neutral (docs/validation/method.md, section 6).
"""

from __future__ import annotations

import inspect
import math
import os
import shutil
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import common as c
import numpy as np

NOT_REPRODUCED = "not reproduced on 1.0"
STILL = "still reproduces"
CHANGED = "changed"
NEW = "new behaviour"
COULD_NOT = "could not run"
VERDICTS = (NOT_REPRODUCED, STILL, CHANGED, NEW, COULD_NOT)


@dataclass
class Context:
    cache: Path  # data/cache/validation/v1/<sdk version>/
    network: bool


@dataclass
class Probe:
    id: str
    title: str
    findings: tuple[str, ...]
    network: bool
    timeout: int  # seconds, for one attempt
    run: Callable[[Context], dict[str, Any]]


def result(finding: str, verdict: str, note: str) -> dict[str, str]:
    assert verdict in VERDICTS, verdict
    return {"finding": finding, "verdict": verdict, "note": note}


def error_text(error: BaseException) -> dict[str, Any]:
    """Type and message of an error, with crc-sdk's report where it carries one."""
    out: dict[str, Any] = {"error": f"{type(error).__name__}: {error}"}
    report = getattr(error, "report", None)
    if report is not None:
        out["diagnostics"] = [
            {"code": d.code, "severity": d.severity.value, "message": d.message,
             "support_id": d.support_id}
            for d in report.diagnostics
        ]  # fmt: skip
        out["counts"] = _counts(report.counts)
    return out


def _counts(counts: Any) -> dict[str, int]:
    names = ("requested", "produced", "skipped", "no_data")
    return {n: int(getattr(counts, n)) for n in names if hasattr(counts, n)}


def _report(read: Any) -> dict[str, Any]:
    report = read.report
    return {
        "complete": report.complete,
        "valid": report.valid,
        "counts": _counts(report.counts),
        "diagnostics": [
            {"code": d.code, "severity": d.severity.value, "message": d.message}
            for d in report.diagnostics
        ],
    }


def _resources(metadata: Any) -> list[dict[str, Any]]:
    out = []
    for resource in metadata.source.resources:
        out.append({
            "uri": resource.uri, "license": resource.license,
            "attribution": resource.attribution, "sha256": resource.sha256,
            "retrieved_at": None if resource.retrieved_at is None
            else resource.retrieved_at.isoformat(timespec="seconds"),
        })  # fmt: skip
    return out


def _runtime(ctx: Context, *, offline: bool = False) -> Any:
    from crc_sdk import Cache, Runtime

    folder = ctx.cache / "crc-sdk-cache"
    return Runtime(cache=Cache.offline(folder) if offline else Cache.reuse(folder))


def _glofas(box: c.Box) -> Any:
    from crc_sdk import JRC

    return JRC(product=JRC.Product.GLOFAS).select(area=c.bounds(box))


def _depth_variable() -> Any:
    from crc_framework import DepthAboveGround, LengthUnit
    from crc_sdk import Variable

    return Variable("crc-lab:probe-depth", measurement=DepthAboveGround(unit=LengthUnit.METRE))


def _from_raster(window: c.Window, box: c.Box) -> Any:
    from crc_framework import Tail
    from crc_sdk import Dataset, Probability

    files = {1 - 1 / t: window.files[t] for t in window.periods}
    return Dataset.from_raster(
        files, variable=_depth_variable(), probability=Probability.annual(tail=Tail.UPPER)
    ).select(area=c.bounds(box))


def _reference_counts(windows: list[c.Window]) -> dict[str, int]:
    total = {"wet": 0, "skipped": 0, "decreasing": 0, "curve": 0}
    for window in windows:
        kinds = c.classify(window.depths)
        for key in total:
            total[key] += int(kinds[key].sum())
    return total


def _compare_knots(table: Any, windows: list[c.Window]) -> dict[str, Any]:
    """Each delivered row's knots against the publisher's depths at its pixel.

    JRC rows name the pixel in their support_id (``jrc:<product>:<tile>:<row>:<column>``,
    crc_sdk/_climate_io.py:183-185); rows of ``from_raster`` do not, and are matched by the
    centre of their geometry.
    """
    import shapely

    by_tile = {w.tile: w for w in windows}
    rows = table.select(["support_id", "geometry", "curve"]).to_pylist()
    matched, equal, largest, unmatched, probability_error = 0, 0, 0.0, 0, 0.0
    for row in rows:
        knots = row["curve"]["quantile_curve"]
        parts = row["support_id"].split(":")
        window = None
        if parts[0] == "jrc" and len(parts) == 5 and parts[2] in by_tile:
            window, r, col = by_tile[parts[2]], int(parts[3]), int(parts[4])
        elif len(windows) == 1:
            window = windows[0]
            centre = shapely.from_wkb(row["geometry"]).centroid
            col = math.floor((centre.x - window.left) / window.dx)
            r = math.floor((window.top - centre.y) / window.dy)
        if window is None or not (0 <= r - window.row < window.depths.shape[1]
                                  and 0 <= col - window.column < window.depths.shape[2]):  # fmt: skip
            unmatched += 1
            continue
        depths = window.at(r, col)
        expected = {1 - 1 / t: d for t, d in zip(window.periods, depths, strict=True)
                    if np.isfinite(d)}  # fmt: skip
        got = dict(zip(knots["probabilities"], knots["values"], strict=True))
        matched += 1
        if len(got) != len(expected):
            continue
        pairs = sorted(expected.items())
        gaps = [abs(g - e) for (pe, e), (pg, g) in zip(pairs, sorted(got.items()), strict=True)]
        probability_error = max(probability_error, max(
            abs(pe - pg) for (pe, _), (pg, _) in zip(pairs, sorted(got.items()), strict=True)))
        largest = max(largest, max(gaps))
        equal += all(gap == 0.0 for gap in gaps)
    return {
        "rows": len(rows), "matched_to_a_pixel": matched, "unmatched": unmatched,
        "rows_whose_knots_equal_the_publisher_depths": equal,
        "largest_depth_difference_m": largest,
        "largest_probability_difference": probability_error,
    }  # fmt: skip


def _timed(call: Callable[[], Any]) -> tuple[Any, float, BaseException | None]:
    start = time.perf_counter()
    try:
        value = call()
        return value, round(time.perf_counter() - start, 2), None
    except Exception as error:  # the error is the observation
        return None, round(time.perf_counter() - start, 2), error


def _rss_mb() -> float:
    import resource
    import sys

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1 << 20) if sys.platform == "darwin" else peak / 1024, 1)


# ---------------------------------------------------------------------------- a. JRC Fremont
def jrc_fremont(ctx: Context) -> dict[str, Any]:
    windows = c.publisher_windows("glofas", c.FREMONT)
    reference = _reference_counts(windows)
    observed: dict[str, Any] = {"box": list(c.FREMONT), "publisher_pixels": reference}
    # 1. the whole Fremont box, as the 0.11 assessment read it
    read, seconds, error = _timed(lambda: _glofas(c.FREMONT).read(runtime=_runtime(ctx)))
    observed["fremont_read"] = {"seconds": seconds, "peak_rss_mb_so_far": _rss_mb()}
    if error is not None:
        observed["fremont_read"].update(error_text(error))
    else:
        observed["fremont_read"].update(_report(read))
        observed["fremont_read"]["knots"] = _compare_knots(read.table, windows)
    # 2. a block of the box without a decreasing pixel, written to a file and reopened
    window = windows[0]
    block = c.clean_region(window, 60, 60)
    if block is None:
        raise RuntimeError("no 60 x 60 block without a decreasing pixel in the Fremont window")
    box = c.inner_box(window, *block, 60, 60)
    path = ctx.cache / "out" / "jrc-fremont-block.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    _, seconds, error = _timed(
        lambda: _glofas(box).write(path, overwrite=True, runtime=_runtime(ctx)))
    block_obs: dict[str, Any] = {
        "box": [round(v, 6) for v in box], "file_row_column": list(block), "pixels": 3600,
        "seconds": seconds, "peak_rss_mb_so_far": _rss_mb(),
    }  # fmt: skip
    block_ref = c.classify(window.depths[:, block[0] - window.row : block[0] - window.row + 60,
                                         block[1] - window.column : block[1] - window.column + 60])  # fmt: skip
    block_obs["publisher_pixels"] = {k: int(v.sum()) for k, v in block_ref.items() if k != "knots"}
    observed["block_read"] = block_obs
    if error is not None:
        block_obs.update(error_text(error))
    else:
        import pyarrow.parquet as pq
        from crc_sdk import Dataset

        saved = Dataset.open(path)
        table = saved.read().table
        resources = _resources(saved.metadata)
        footer = (pq.read_schema(path).metadata or {}).get(b"crc.dataset", b"").decode()
        block_obs.update({
            "file_bytes": path.stat().st_size,
            "report": _report(saved.read()),
            "resources": resources,
            "footer_key_crc_dataset_bytes": len(footer),
            "footer_mentions": {k: k in footer for k in
                                ("ODbL-1.0", "license", "attribution", "sha256", "retrieved_at")},
            "knots": _compare_knots(table, windows),
        })  # fmt: skip

    results = []
    res = observed["block_read"].get("resources")
    if res:
        depth_files = [r for r in res if r["uri"].endswith(".tif") or "depth" in r["uri"]] or res
        licences = sorted({str(r["license"]) for r in res})
        complete = all(r["license"] and r["attribution"] and r["sha256"] and r["retrieved_at"]
                       for r in depth_files)  # fmt: skip
        in_footer = all(observed["block_read"]["footer_mentions"].values())
        results.append(result(
            "CRC-018-JRC", CHANGED if licences == ["ODbL-1.0"] else STILL,
            f"licence recorded on every resource: {', '.join(licences)}"))
        results.append(result(
            "CRC-003-JRC", NOT_REPRODUCED if complete and in_footer else STILL,
            f"{len(res)} resources; licence, attribution, sha256 and retrieved_at "
            f"{'present on each' if complete else 'missing on some'}; "
            f"in the file footer: {'yes' if in_footer else 'not all'}"))
        knots = observed["block_read"]["knots"]
        results.append(result(
            "CRC-015-JRC",
            CHANGED if knots["rows_whose_knots_equal_the_publisher_depths"] == knots["rows"] else STILL,
            f"{knots['rows_whose_knots_equal_the_publisher_depths']} of {knots['rows']} rows carry "
            f"exactly the publisher's depths at the published return periods (no fitted curve)"))
    whole = observed["fremont_read"]
    if "error" in whole:
        results.append(result(
            "CRC-014-JRC", CHANGED,
            f"the whole-box read ends with {whole['error'][:160]} "
            f"({reference['decreasing']} of {reference['wet']} wet pixels decrease)"))
    else:
        results.append(result(
            "CRC-014-JRC", CHANGED,
            f"{whole['counts']} for {reference['wet']} wet pixels; diagnostics: "
            f"{[d['message'] for d in whole['diagnostics']]}"))
    results.append(result(
        "CRC-022-JRC", COULD_NOT,
        f"the Texas box was not run; Fremont took {whole['seconds']} s, the 60 x 60 block "
        f"{observed['block_read']['seconds']} s, peak memory of the process "
        f"{observed['block_read']['peak_rss_mb_so_far']} MB"))
    return {
        "ran": "JRC(product=JRC.Product.GLOFAS).select(area=Bounds(FREMONT)).read() with "
               "Runtime(cache=Cache.reuse(<cache>/crc-sdk-cache)); then the same on a 60 x 60 pixel "
               "block of the box without a decreasing pixel, written with .write(), reopened with "
               "Dataset.open(); knots compared with the publisher's files held under "
               "data/cache/validation/jrc-flood/original/glofas (read with "
               "data_source_check.reference.jrc_flood)",
        "observed": observed, "results": results,
    }  # fmt: skip


# ---------------------------------------------------------------------------- b. support_id
def jrc_support_id(ctx: Context) -> dict[str, Any]:
    window = c.publisher_windows("glofas", c.FREMONT)[0]
    block = c.clean_region(window, 60, 90)
    if block is None:
        raise RuntimeError("no 60 x 90 block without a decreasing pixel in the Fremont window")
    row, column = block
    first = c.inner_box(window, row, column, 60, 60)
    second = c.inner_box(window, row, column + 30, 60, 60)
    ids = []
    observed: dict[str, Any] = {"boxes": [[round(v, 6) for v in first], [round(v, 6) for v in second]],
                                "overlap_pixels": 60 * 30}  # fmt: skip
    for name, box in (("first", first), ("second", second)):
        read, seconds, error = _timed(lambda box=box: _glofas(box).read(runtime=_runtime(ctx)))
        if error is not None:
            observed[name] = {"seconds": seconds, **error_text(error)}
            return {"ran": "two overlapping boxes read in turn", "observed": observed,
                    "results": [result("CRC-020-JRC", COULD_NOT, observed[name]["error"][:200])]}
        table = read.table.select(["support_id", "curve"]).to_pylist()
        observed[name] = {"seconds": seconds, "rows": len(table)}
        ids.append({r["support_id"]: r["curve"]["quantile_curve"]["values"] for r in table})
    overlap = set(ids[0]) & set(ids[1])
    expected = {f"jrc:glofas:{window.tile}:{r}:{col}"
                for r in range(row, row + 60) for col in range(column + 30, column + 60)
                if c.classify(window.at(r, col)[:, None, None])["curve"][0, 0]}  # fmt: skip
    observed.update({
        "ids_in_both": len(overlap),
        "curves_the_publisher_has_in_the_overlap": len(expected),
        "ids_equal_to_file_position": len(overlap & expected),
        "same_values_for_same_id": sum(ids[0][i] == ids[1][i] for i in overlap),
        "example_ids": sorted(overlap)[:3],
    })  # fmt: skip
    same = len(overlap) == len(expected) == len(overlap & expected)
    return {
        "ran": "JRC GloFAS read with Cache.reuse for two 60 x 60 pixel boxes inside the Fremont "
               "box that share 30 columns; support_id of every pixel of the overlap compared, and "
               "with jrc:glofas:<tile>:<row>:<column> of the pixel in the publisher's file",
        "observed": observed,
        "results": [result(
            "CRC-020-JRC", NOT_REPRODUCED if same else STILL,
            f"{len(overlap)} pixels of the overlap carry the same support_id in both reads; "
            f"{len(overlap & expected)} of {len(expected)} equal the position in the publisher's file")],
    }  # fmt: skip


# ---------------------------------------------------------------------------- c. decreasing depth
def jrc_decreasing(ctx: Context) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    cases = []
    for area, box in (("fremont", c.FREMONT), ("houston", c.HOUSTON)):
        for window in c.publisher_windows("glofas", box):
            spot = c.first_decreasing(window)
            if spot is not None:
                cases.append((area, window, spot))
                break
    for area, window, (row, column) in cases:
        # 5 x 5 pixels around the first decreasing pixel of the area
        box = c.inner_box(window, row - 2, column - 2, 5, 5)
        lo_r, lo_c = row - 2 - window.row, column - 2 - window.column
        sub = window.depths[:, max(lo_r, 0) : lo_r + 5, max(lo_c, 0) : lo_c + 5]
        kinds = {k: int(v.sum()) for k, v in c.classify(sub).items() if k != "knots"}
        case: dict[str, Any] = {
            "tile": window.tile, "pixel_row_column": [row, column],
            "depths_by_return_period": dict(zip(map(str, window.periods),
                                                [round(float(d), 4) for d in window.at(row, column)],
                                                strict=True)),
            "box": [round(v, 6) for v in box], "publisher_pixels_in_box": kinds,
        }  # fmt: skip
        read, seconds, error = _timed(lambda box=box, window=window: _from_raster(window, box).read())
        case["from_raster_on_publisher_files"] = (
            {"seconds": seconds, **error_text(error)} if error is not None
            else {"seconds": seconds, **_report(read)})  # fmt: skip
        if ctx.network:
            read, seconds, error = _timed(lambda box=box: _glofas(box).read(runtime=_runtime(ctx)))
            case["jrc_glofas"] = (
                {"seconds": seconds, **error_text(error)} if error is not None
                else {"seconds": seconds, **_report(read)})  # fmt: skip
        else:
            case["jrc_glofas"] = {"not_run": "--offline given"}
        observed[area] = case
    if not cases:
        raise RuntimeError("no decreasing pixel found in the Fremont or Houston windows")
    lines = []
    failed_all = True
    for area, case in observed.items():
        for side in ("from_raster_on_publisher_files", "jrc_glofas"):
            outcome = case[side]
            if "not_run" in outcome:
                continue
            if "error" in outcome:
                named = [d.get("support_id") for d in outcome.get("diagnostics", [])
                         if d["severity"] == "error"]  # fmt: skip
                lines.append(f"{area} {side}: {outcome['error'][:150]}; "
                             f"{case['publisher_pixels_in_box']['curve']} pixels with a valid "
                             f"curve in the box are lost with it; the error names the pixel: "
                             f"{'yes' if any(named) else 'no'}")  # fmt: skip
            else:
                failed_all = False
                lines.append(f"{area} {side}: completed, {outcome['counts']}")
    return {
        "ran": "for Fremont and Houston, the first GloFAS pixel whose depth decreases with "
               "return period; a 5 x 5 pixel box around it read with Dataset.from_raster on the "
               "publisher's files (the per-pixel reader JRC uses, crc_sdk/_climate_io.py:202) "
               "and, with the network, with JRC(product=JRC.Product.GLOFAS)",
        "observed": observed,
        "results": [result("new: decreasing depth", NEW if failed_all else CHANGED, "; ".join(lines))],
    }  # fmt: skip


# ---------------------------------------------------------------------------- raster knots, offline
def raster_knots(ctx: Context) -> dict[str, Any]:
    window = c.publisher_windows("glofas", c.FREMONT)[0]
    block = c.clean_region(window, 60, 60)
    if block is None:
        raise RuntimeError("no clean block in the Fremont window")
    box = c.inner_box(window, *block, 60, 60)
    read, seconds, error = _timed(lambda: _from_raster(window, box).read())
    sub = window.depths[:, block[0] - window.row : block[0] - window.row + 60,
                        block[1] - window.column : block[1] - window.column + 60]  # fmt: skip
    kinds = {k: int(v.sum()) for k, v in c.classify(sub).items() if k != "knots"}
    observed: dict[str, Any] = {"box": [round(v, 6) for v in box], "pixels": 3600,
                                "publisher_pixels": kinds, "seconds": seconds}  # fmt: skip
    if error is not None:
        observed.update(error_text(error))
        return {"ran": "Dataset.from_raster on a clean Fremont block", "observed": observed,
                "results": [result("CRC-014-JRC", COULD_NOT, observed["error"][:200])]}
    observed["report"] = _report(read)
    observed["knots"] = _compare_knots(read.table, [window])
    counts = observed["report"]["counts"]
    knots = observed["knots"]
    return {
        "ran": "Dataset.from_raster({1-1/T: publisher GeoTIFF}) on a 60 x 60 pixel block of the "
               "Fremont window without a decreasing pixel; the per-pixel reader the JRC provider "
               "uses (crc_sdk/_climate_io.py:202); offline, the publisher's files as held",
        "observed": observed,
        "results": [
            result("CRC-014-JRC", CHANGED,
                   f"{counts.get('produced')} rows for {kinds['curve']} pixels with two or more "
                   f"depths; {counts.get('skipped')} pixels skipped ({3600 - kinds['wet']} dry, "
                   f"{kinds['skipped']} with one depth), reported only as one count in a warning: "
                   f"{[d['message'] for d in observed['report']['diagnostics']]}"),
            result("CRC-015-JRC", CHANGED,
                   f"{knots['rows_whose_knots_equal_the_publisher_depths']} of {knots['rows']} rows "
                   f"carry the publisher's depths unchanged at probabilities 1 - 1/T "
                   f"(largest difference {knots['largest_depth_difference_m']} m)"),
        ],
    }  # fmt: skip


# ---------------------------------------------------------------------------- d. outside coverage
def jrc_outside(ctx: Context) -> dict[str, Any]:
    from crc_sdk import JRC

    recipe = JRC(product=JRC.Product.EFAS).select(area=c.bounds(c.FREMONT))
    read, seconds, error = _timed(lambda: recipe.read(runtime=_runtime(ctx)))
    observed: dict[str, Any] = {"box": list(c.FREMONT), "seconds": seconds}
    if error is not None:
        observed.update(error_text(error))
        names = any(w in observed["error"].lower() for w in ("coverage", "extent", "europe", "outside"))
        verdict = NOT_REPRODUCED if names else STILL
        note = f"ends with {observed['error'][:200]}"
    else:
        observed.update({"rows": read.table.num_rows, **_report(read)})
        verdict = CHANGED
        note = (f"no error; {read.table.num_rows} rows; diagnostics: "
                f"{[d['message'] for d in observed['diagnostics']] or 'none'}")
    return {"ran": "JRC(product=JRC.Product.EFAS).select(area=Bounds(FREMONT)).read() with "
                   "Cache.reuse", "observed": observed,
            "results": [result("CRC-016-JRC", verdict, note)]}  # fmt: skip


# ---------------------------------------------------------------------------- e. relative cache
def jrc_relative_cache(ctx: Context) -> dict[str, Any]:
    from crc_sdk import Cache, Runtime

    window = c.publisher_windows("glofas", c.FREMONT)[0]
    block = c.clean_region(window, 20, 20)
    if block is None:
        raise RuntimeError("no clean block in the Fremont window")
    box = c.inner_box(window, *block, 20, 20)
    base = ctx.cache / "relative-cache"
    shutil.rmtree(base, ignore_errors=True)
    made, other = base / "made-here", base / "elsewhere"
    made.mkdir(parents=True)
    other.mkdir(parents=True)
    observed: dict[str, Any] = {"box": [round(v, 6) for v in box]}
    here = Path.cwd()
    try:
        os.chdir(made)
        read, seconds, error = _timed(
            lambda: _glofas(box).read(runtime=Runtime(cache=Cache.reuse("cache"))))
        observed["first_read_relative_cache"] = (
            {"seconds": seconds, **error_text(error)} if error else
            {"seconds": seconds, "rows": read.table.num_rows})  # fmt: skip
        if error:
            return {"ran": "read with Cache.reuse('cache')", "observed": observed,
                    "results": [result("CRC-021-JRC", COULD_NOT, observed[
                        "first_read_relative_cache"]["error"][:200])]}  # fmt: skip
        for name, folder, cache in (
            ("offline_same_folder", made, "cache"),
            ("offline_other_folder_absolute_path", other, str(made / "cache")),
            ("offline_other_folder_relative_path", other, "../made-here/cache"),
        ):
            os.chdir(folder)
            again, seconds, error = _timed(
                lambda cache=cache: _glofas(box).read(runtime=Runtime(cache=Cache.offline(cache))))
            observed[name] = ({"seconds": seconds, **error_text(error)} if error else
                              {"seconds": seconds, "rows": again.table.num_rows,
                               "same_rows": again.table.equals(read.table)})  # fmt: skip
    finally:
        os.chdir(here)
    absolute = observed["offline_other_folder_absolute_path"]
    ok = "error" not in absolute and absolute.get("same_rows")
    return {
        "ran": "in folder A, JRC GloFAS read of a 20 x 20 pixel Fremont block with "
               "Cache.reuse('cache'); then Cache.offline from A, and from folder B given the "
               "absolute and the relative path of A's cache",
        "observed": observed,
        "results": [result("CRC-021-JRC", NOT_REPRODUCED if ok else STILL,
                           "from another folder with the absolute path: "
                           + ("same rows" if ok else str(absolute.get("error", absolute))[:200]))],
    }  # fmt: skip


# ---------------------------------------------------------------------------- f. interpolation
STEPS = (15, 30, 40, 60, 90, 150, 300)  # return periods between the published ones


def interpolation(ctx: Context) -> dict[str, Any]:
    from crc_framework import QuantileCurve

    example = QuantileCurve([0.9, 0.99], [0.5, 2.0])
    linear = float(np.asarray(example.quantile([1 - 1 / 20])).ravel()[0])
    by_hand = c.log_period_interpolation([10, 100], [0.5, 2.0], 20)
    observed: dict[str, Any] = {"upstream_example": {
        "knots": "0.5 m at 10 years, 2.0 m at 100 years", "at": 20,
        "crc_framework_1_0_m": round(linear, 4), "log_return_period_by_hand_m": round(by_hand, 4),
        "guide_states": "about 0.95 m in 0.6, 1.33 m in 1.0 (crc-framework docs/migration-v1.md)",
    }}  # fmt: skip
    window = c.publisher_windows("glofas", c.FREMONT)[0]
    kinds = c.classify(window.depths)
    pixels = np.argwhere(kinds["curve"])
    periods = np.asarray(window.periods, dtype=np.float64)
    per_step: dict[int, list[float]] = {t: [] for t in STEPS}
    for r, col in pixels:
        depths = window.depths[:, r, col]
        held = np.isfinite(depths)
        t, v = periods[held], depths[held]
        curve = QuantileCurve(list(1 - 1 / t), list(v))
        inside = [s for s in STEPS if t[0] <= s <= t[-1]]
        if not inside:
            continue
        new = np.asarray(curve.quantile([1 - 1 / s for s in inside])).ravel()
        for s, value in zip(inside, new, strict=True):
            per_step[s].append(float(value) - c.log_period_interpolation(t, v, s))
    every = [d for values in per_step.values() for d in values]
    observed["fremont_publisher_curves"] = {
        "pixels": int(len(pixels)),
        "difference_1_0_minus_log_T_m": {str(s): c.stats(v) for s, v in per_step.items()},
        "absolute_difference_all_steps_m": c.stats(np.abs(every)),
        "share_where_1_0_is_higher": round(float(np.mean(np.asarray(every) > 0)), 4) if every else None,
    }  # fmt: skip
    overall = observed["fremont_publisher_curves"]["absolute_difference_all_steps_m"]
    return {
        "ran": "crc_framework.QuantileCurve(probabilities, depths).quantile(1 - 1/T) against "
               "interpolation in ln(T) by hand (numpy) between the same knots: upstream's example, "
               f"and every Fremont GloFAS pixel that becomes a curve at T = {', '.join(map(str, STEPS))} "
               "(the publisher's depths, which 1.0 delivers unchanged; see raster-knots)",
        "observed": observed,
        "results": [result(
            "interpolation between knots", CHANGED,
            f"example at 20 years: {linear:.3f} m (1.0) against {by_hand:.3f} m (ln T); Fremont "
            f"curves, |1.0 - ln T|: median {overall.get('median')} m, 90th percentile "
            f"{overall.get('p90')} m, largest {overall.get('largest')} m over {overall.get('n')} values")],
    }  # fmt: skip


# ---------------------------------------------------------------------------- g. NEX
AUSTIN_SMALL: c.Box = (-97.85, 30.2, -97.6, 30.4)


def nex_txx(ctx: Context) -> dict[str, Any]:
    from crc_sdk import NEX, Period

    observed: dict[str, Any] = {
        "box": list(AUSTIN_SMALL),
        "nex_parameters": list(inspect.signature(NEX.__init__).parameters)[1:],
    }
    for name, value in (("version", "1.1"), ("grid_label", "gn")):
        try:
            NEX(**{name: value})
            observed[f"NEX({name}=...)"] = "accepted"
        except Exception as error:
            observed[f"NEX({name}=...)"] = f"{type(error).__name__}: {error}"
    recipe = NEX(indicator=NEX.Indicator.ANNUAL_MAXIMUM_DAILY_MAXIMUM_TEMPERATURE,
                 model="ACCESS-CM2", scenario="historical", member="r1i1p1f1").select(
        area=c.bounds(AUSTIN_SMALL), time=Period.window(2014, 2014))  # fmt: skip
    read, seconds, error = _timed(lambda: recipe.read(runtime=_runtime(ctx)))
    observed["seconds"] = seconds
    if error is not None:
        observed.update(error_text(error))
        return {"ran": "NEX txx read", "observed": observed, "results": [
            result("CRC-001-NEX", STILL, observed["error"][:200]),
            result("CRC-012-NEX", COULD_NOT, "the read failed")]}
    table = read.table
    observed.update({"rows": table.num_rows, "columns": table.schema.names, **_report(read)})
    uris = [r["uri"] for r in _resources(read.metadata)]
    observed["files_read"] = uris
    value_column = next((n for n in ("value", "sample", "values") if n in table.schema.names), None)
    if value_column:
        values = [v for v in table.column(value_column).to_pylist() if isinstance(v, int | float)]
        observed["values"] = c.stats(values)
    versions = sorted({u.rsplit("_v", 1)[-1].removesuffix(".nc") for u in uris if "_v" in u})
    return {
        "ran": "NEX(indicator=NEX.Indicator.ANNUAL_MAXIMUM_DAILY_MAXIMUM_TEMPERATURE, "
               "model='ACCESS-CM2', scenario='historical', member='r1i1p1f1')"
               ".select(area=Bounds(AUSTIN_SMALL), time=Period.window(2014, 2014)).read(); "
               "NEX(version=...) and NEX(grid_label=...) tried",
        "observed": observed,
        "results": [
            result("CRC-001-NEX", NOT_REPRODUCED, f"txx read completed: {table.num_rows} rows"),
            result("CRC-012-NEX", CHANGED,
                   f"file version read: {', '.join(versions) or 'not in the file name'}; "
                   f"NEX(version=...): {observed['NEX(version=...)'][:120]}"),
        ],
    }  # fmt: skip


# ---------------------------------------------------------------------------- h. CRC Open
def crc_open(ctx: Context) -> dict[str, Any]:
    from crc_sdk import CRCOpen

    found, seconds, error = _timed(lambda: CRCOpen().inspect(runtime=_runtime(ctx)))
    observed: dict[str, Any] = {"seconds": seconds}
    if error is not None:
        observed.update(error_text(error))
        note = f"CRCOpen().inspect() ends with {observed['error'][:220]}"
    else:
        listed = {name: len(getattr(found, name, ()) or ())
                  for name in ("series", "releases", "variables", "datasets") if hasattr(found, name)}  # fmt: skip
        observed.update({"listed": listed, "inspection": repr(found)[:2000]})
        note = f"CRCOpen().inspect() lists {listed}"
    return {"ran": "CRCOpen().inspect() with defaults (crc_sdk/_crc_open.py: "
                   "https://data.riskthinking.ai/crc-open/_CURRENT.json)",
            "observed": observed,
            "results": [result("CRC Open readable with defaults", NEW, note)]}  # fmt: skip


# ---------------------------------------------------------------------------- i. IBTrACS
IBTRACS_ALL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
               "stewardship-ibtracs/v04r01/access/csv/ibtracs.ALL.list.v04r01.csv")
IBTRACS_LIMIT = 500 * 1 << 20


def ibtracs(ctx: Context) -> dict[str, Any]:
    from crc_sdk import IBTrACS

    request = urllib.request.Request(IBTRACS_ALL, method="HEAD",
                                     headers={"User-Agent": "crc-lab-probes"})  # fmt: skip
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        size = int(response.headers.get("Content-Length", -1))
    observed: dict[str, Any] = {
        "all_file_bytes": size,
        "ibtracs_parameters": list(inspect.signature(IBTrACS.__init__).parameters)[1:],
    }
    if size < 0 or size > IBTRACS_LIMIT:
        return {"ran": "HEAD of the ALL file", "observed": observed, "results": [
            result("CRC-011-IBT", COULD_NOT, f"the ALL file is {size} bytes, above the limit")]}
    read, seconds, error = _timed(lambda: IBTrACS().read(limit=100, runtime=_runtime(ctx)))
    observed["seconds"] = seconds
    if error is not None:
        observed.update(error_text(error))
        return {"ran": "IBTrACS().read(limit=100)", "observed": observed, "results": [
            result("CRC-011-IBT", COULD_NOT, observed["error"][:200])]}
    meta = (read.table.schema.metadata or {})
    observed.update({"rows": read.table.num_rows, "schema_metadata_keys": sorted(k.decode() for k in meta),
                     "resources": _resources(read.metadata)})  # fmt: skip
    res = observed["resources"]
    has = all(r["license"] and r["attribution"] for r in res)
    return {
        "ran": "IBTrACS().read(limit=100) with Cache.reuse (reads the whole ALL file once)",
        "observed": observed,
        "results": [
            result("CRC-011-IBT", NOT_REPRODUCED if has else STILL,
                   "licence: " + "; ".join(sorted({str(r['license']) for r in res}))),
            result("CRC-010-IBT", CHANGED,
                   f"subsets are gone; IBTrACS takes {observed['ibtracs_parameters']} and reads "
                   f"the ALL file"),
        ],
    }  # fmt: skip


# ---------------------------------------------------------------------------- j. CRC-013 fit
PERIODS_0_11 = (10, 20, 50, 75, 100, 200, 500)
CASES_0_11 = (  # tools/probes/jrc_flood_probes.py, 'optimizer'; answers of crc-framework 0.6.0
    ((1, 1, 1, 1, 1, 2.639, 3.768), "32-bit", "did not converge after 374 iterations"),
    ((1, 1, 1, 1, 1, 2.639, 3.768), "decimal", "converged after 91 iterations"),
    ((1, 1, 1, 1, 1, 1.016, 1.13), "32-bit", "did not converge after 358 iterations"),
    ((1, 1, 1, 1, 1, 1.016, 1.13), "decimal", "converged after 89 iterations"),
)


def crc013_fit(ctx: Context) -> dict[str, Any]:
    from crc_framework import DistributionFamily, QuantileCurve, QuantileFit, fit_quantiles

    probabilities = [1 - 1 / t for t in PERIODS_0_11]
    cases = []
    for depths, kind, before in CASES_0_11:
        values = ([float(np.float32(d)) for d in depths] if kind == "32-bit"
                  else [float(d) for d in depths])  # fmt: skip
        case: dict[str, Any] = {"depths": list(depths), "as": kind, "crc_framework_0_6": before}
        try:
            fitted = fit_quantiles(QuantileCurve(probabilities, values),
                                   QuantileFit(family=DistributionFamily.GUMBEL_RIGHT))  # fmt: skip
            record = getattr(fitted, "record", None)
            case.update({
                "outcome": "fitted",
                "distribution": fitted.distribution.to_json(),
                "converged": getattr(record, "converged", None),
                "record": record.to_json() if hasattr(record, "to_json") else repr(record),
                "diagnostic": repr(getattr(fitted, "diagnostic", None))[:600],
            })  # fmt: skip
        except Exception as error:
            case.update({"outcome": "error", "error": f"{type(error).__name__}: {error}"})
            record = getattr(error, "record", None)
            if record is not None:
                case["record"] = record.to_json() if hasattr(record, "to_json") else repr(record)
        cases.append(case)
    failing = [k for k in cases if k["outcome"] != "fitted" or k.get("converged") is False]

    def said(k: dict[str, Any]) -> str:
        now = (k["error"].rsplit(": ", 1)[-1] if k["outcome"] != "fitted"
               else "converged after " + str(_iterations(k.get("record"))) + " iterations")  # fmt: skip
        return f"{k['as']} {k['depths'][-2:]}: {now} (0.6: {k['crc_framework_0_6']})"

    return {
        "ran": "crc_framework.fit_quantiles(QuantileCurve(1 - 1/T, depths), "
               "QuantileFit(family=DistributionFamily.GUMBEL_RIGHT)) for the two real flat-then-rising "
               "pixels of the 0.11 probe, as 32-bit and as decimal depths",
        "observed": {"cases": cases},
        "results": [result(
            "CRC-013-FWK", STILL if failing else NOT_REPRODUCED,
            f"{len(cases) - len(failing)} of {len(cases)} cases converged; "
            + "; ".join(said(k) for k in cases))],
    }  # fmt: skip


def _iterations(record: Any) -> Any:
    import json

    try:
        data = json.loads(record) if isinstance(record, str) else {}
        return data["attempts"][data["selected_attempt"]]["diagnostic"]["iterations"]
    except Exception:
        return "?"


PROBES = (
    Probe("jrc-fremont", "JRC GloFAS, Fremont box: licence, provenance, delivered depths, time",
          ("CRC-003-JRC", "CRC-014-JRC", "CRC-015-JRC", "CRC-018-JRC", "CRC-022-JRC"),
          True, 900, jrc_fremont),
    Probe("raster-knots", "The per-pixel raster reader on the publisher's files (offline)",
          ("CRC-014-JRC", "CRC-015-JRC"), False, 600, raster_knots),
    Probe("jrc-support-id", "support_id of the same pixel in two overlapping boxes",
          ("CRC-020-JRC",), True, 900, jrc_support_id),
    Probe("jrc-decreasing", "A pixel whose depth decreases with return period",
          ("new: decreasing depth",), False, 900, jrc_decreasing),
    Probe("jrc-outside", "EFAS asked for a box outside its coverage (Fremont)",
          ("CRC-016-JRC",), True, 600, jrc_outside),
    Probe("jrc-relative-cache", "A cache made under a relative path, read offline elsewhere",
          ("CRC-021-JRC",), True, 900, jrc_relative_cache),
    Probe("interpolation", "Depths between the published return periods: 1.0 against ln(T)",
          ("interpolation between knots",), False, 600, interpolation),
    Probe("nex-txx", "NEX-GDDP-CMIP6 txx near Austin, 2014: does it run, which file version",
          ("CRC-001-NEX", "CRC-012-NEX"), True, 1500, nex_txx),
    Probe("crc-open", "CRC Open with default settings", ("CRC Open readable with defaults",),
          True, 300, crc_open),
    Probe("ibtracs", "IBTrACS: licence and attribution in the output; subsets",
          ("CRC-010-IBT", "CRC-011-IBT"), True, 900, ibtracs),
    Probe("crc013-fit", "Gumbel fit of flat-then-rising depths in crc-framework 1.0",
          ("CRC-013-FWK",), False, 300, crc013_fit),
)

#: open findings these probes do not touch; their state at 1.0 is from code reading only
NOT_PROBED = ("CRC-002-FWK", "CRC-004-EDO", "CRC-005-EDO", "CRC-006-ERA5", "CRC-007-OPEN",
              "CRC-008-OSC", "CRC-009-CDL", "CRC-017-JRC", "CRC-019-JRC")  # fmt: skip
