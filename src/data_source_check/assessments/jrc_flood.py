"""JRC flood maps (GloFAS, EFAS): verification of what crc-sdk 1.x returns by default.

From 1.0 crc-sdk fits nothing: for each pixel of the publisher's maps it returns the published
depths as the knots of a quantile curve, at probabilities 1 - 1/T. Every pixel of each area is
read from the publisher's files by the reference reader, which decides independently which
pixels should be delivered and with which knots, and the two are compared pixel by pixel.

The assessment of crc-sdk 0.11, which fitted a curve per pixel, is ``jrc_flood_011``; the review
maps and the comparisons with outside evidence still rest on it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np

from ..adapters.crc import jrc_flood as framework
from ..core import compare
from ..core.records import CheckRecord
from ..reference import jrc_flood as reference

SOURCE = "jrc-flood"
SEED = 20261124
TEXAS = (-106.645646, 25.837377, -93.508292, 36.500704)  # as in the data explorer
HOUSTON = (-95.9, 29.3, -94.9, 30.2)  # Buffalo Bayou, San Jacinto River, lower Brazos
AUSTIN = (-98.0, 30.0, -97.5, 30.5)  # Colorado River
FREMONT = (-122.15, 37.42, -121.85, 37.62)  # Alameda Creek and Niles Canyon to Coyote Creek
RHINE = (7.0, 49.7, 8.5, 50.9)  # crc-docs notebooks/sources/flood_risk_by_province.ipynb
STRIP_ROWS = 512
SAMPLE_CELLS = 2_000
PROBABILITY_TOLERANCE = 1e-12
CELL_RESOLUTION = 9
OVERLAP_LIMIT = 2_000_000  # pixels; the overlap check reads an area twice more


@dataclass(frozen=True)
class Area:
    id: str
    dataset: str
    bounds: tuple[float, float, float, float]
    title: str


AREAS = (
    Area("glofas-tx", "glofas", TEXAS, "Texas box"),
    Area("glofas-houston", "glofas", HOUSTON, "Houston"),
    Area("glofas-austin", "glofas", AUSTIN, "Austin"),
    Area("glofas-fremont", "glofas", FREMONT, "Fremont, California"),
    Area("efas-rhine", "efas", RHINE, "Rhine, Bonn to Mainz"),
)
#: the areas of a quick run: everything but the state-sized box
QUICK_AREAS = tuple(area for area in AREAS if area.id != "glofas-tx")
#: boxes outside a product's coverage
OUTSIDE = (Area("efas-fremont", "efas", FREMONT, "Fremont, California (outside EFAS)"),)


def _answers(url: str) -> bool:
    try:
        with urlopen(Request(url, method="HEAD"), timeout=20) as response:  # noqa: S310
            return int(response.status) == 200
    except OSError:
        return False


def _tile_name(layout: str, tile: str) -> str:
    return tile if layout == "tiled" else "continental"


def _parse(table: Any) -> dict[str, Any]:
    """Tile, row and column of every row's ``support_id``, and its knots as flat arrays."""
    import pyarrow.compute as pc

    parts = pc.split_pattern(table["support_id"].combine_chunks(), ":")
    sizes = pc.list_value_length(parts).to_numpy(zero_copy_only=False)
    if len(sizes) and not (sizes == 5).all():
        raise ValueError("a support_id is not jrc:<product>:<tile>:<row>:<column>")
    out: dict[str, Any] = {
        "tile": np.asarray(pc.list_element(parts, 2).to_pylist(), dtype=object),
        "row": pc.cast(pc.list_element(parts, 3), "int64").to_numpy(zero_copy_only=False),
        "column": pc.cast(pc.list_element(parts, 4), "int64").to_numpy(zero_copy_only=False),
        "cell": table["cell_id"].combine_chunks().to_numpy(zero_copy_only=False),
    }
    for name in ("probabilities", "values"):
        column = table[name].combine_chunks()
        out[name] = column.flatten().to_numpy(zero_copy_only=False)
        out["length"] = pc.list_value_length(column).to_numpy(zero_copy_only=False)
    out["start"] = np.concatenate([[0], np.cumsum(out["length"])[:-1]]).astype(np.int64)
    return out


def _compare_area(copy: reference.Copy, area: Area, periods: Sequence[int],
                  tiles: Sequence[str], table: Any, rules: reference.Rules,
                  strip_rows: int) -> dict[str, Any]:  # fmt: skip
    """Every pixel of the area: what the publisher's files hold against crc-sdk's rows."""
    count = len(periods)
    expected_probability = np.asarray([1 - 1 / period for period in periods])
    theirs = _parse(table) if table is not None and table.num_rows else None
    out: dict[str, Any] = {
        "tiles": [], "pixels": 0, "dry": 0, "one_depth": 0, "decreasing": 0, "deliverable": 0,
        "equal_depths": 0, "fewer_than_four": 0, "filled": 0,
        "rows": 0 if theirs is None else int(len(theirs["row"])),
        "rows_outside_window": 0, "rows_repeated": 0, "missing": 0, "extra": 0,
        "pixels_compared": 0, "pixels_differing": 0, "values_compared": 0,
        "values_differing": 0, "probabilities_differing": 0, "largest_difference": 0.0,
        "examples": [], "cells": [],
    }  # fmt: skip
    seen_tiles = set()
    for tile in tiles:
        names = [reference.depth_name(copy.layout, p, tile) for p in periods]
        stack = [reference.Tiff(copy.file(name)) for name in names]
        first = stack[0]
        window = first.window(area.bounds, rules)
        label = _tile_name(copy.layout, tile)
        seen_tiles.add(label)
        out["tiles"].append({"tile": label, "window": window, "grid": first.describe()})
        if theirs is None:
            mine = np.zeros(0, dtype=np.int64)
        else:
            mine = np.flatnonzero(theirs["tile"] == label)
        if window is None:
            out["rows_outside_window"] += len(mine)
            for tiff in stack:
                tiff.close()
            continue
        c0, r0, c1, r1 = window
        width = c1 - c0
        if theirs is not None:
            mine = mine[np.argsort(theirs["row"][mine], kind="stable")]
            their_rows = theirs["row"][mine]
        for top in range(r0, r1, strip_rows):
            bottom = min(r1, top + strip_rows)
            raw = np.stack([tiff.read((c0, top, c1, bottom)) for tiff in stack])
            values = reference.depths(raw, first.nodata, rules).reshape(count, -1)
            valid = ~np.isnan(values)
            knots = valid.sum(axis=0)
            # crc-sdk 1.1.0 (pull request #64): a return period with no depth at a pixel that
            # has a depth at another one is read as 0 m; the pixel is left out when the depths
            # so completed fall anywhere as the return period rises; a dry pixel gives no row.
            zeroed = np.where(valid, values, 0.0)
            falls = (np.diff(zeroed, axis=0) < 0).any(axis=0)
            wet = knots >= 1
            deliverable = wet & ~falls
            out["pixels"] += values.shape[1]
            out["dry"] += int((knots == 0).sum())
            out["one_depth"] += int((knots == 1).sum())
            out["decreasing"] += int((wet & falls).sum())
            out["deliverable"] += int(deliverable.sum())
            out["filled"] += int((deliverable & (knots < count)).sum())
            out["fewer_than_four"] += int((deliverable & (knots < 4)).sum())
            spread = np.where(valid, values, np.nan)
            with np.errstate(invalid="ignore"):
                same = np.nanmax(np.where(deliverable, spread, 0.0), axis=0) == np.nanmin(
                    np.where(deliverable, spread, 0.0), axis=0
                )
            out["equal_depths"] += int((deliverable & same).sum())

            delivered = np.zeros(values.shape[1], dtype=bool)
            given_values = np.full(values.shape, np.nan)
            given_probability = np.full(values.shape, np.nan)
            if theirs is not None and len(mine):
                low, high = np.searchsorted(their_rows, [top, bottom])
                chosen = mine[low:high]
                column = theirs["column"][chosen] - c0
                inside = (column >= 0) & (column < width)
                out["rows_outside_window"] += int((~inside).sum())
                chosen, column = chosen[inside], column[inside]
                position = (theirs["row"][chosen] - top) * width + column
                delivered[position] = True
                out["rows_repeated"] += int(len(position) - delivered.sum())
                length = np.minimum(theirs["length"][chosen], count)
                which = np.repeat(np.arange(len(chosen)), length)
                step = np.arange(int(length.sum())) - np.repeat(np.cumsum(length) - length, length)
                source = np.repeat(theirs["start"][chosen], length) + step
                given_values[step, position[which]] = theirs["values"][source]
                given_probability[step, position[which]] = theirs["probabilities"][source]
                too_long = theirs["length"][chosen] > count
                out["values_differing"] += int(too_long.sum())
                if len(out["cells"]) < SAMPLE_CELLS * 4:  # a pool to sample the cell check from
                    keep = chosen[:: max(1, len(chosen) // 200)]
                    out["cells"] += [
                        (label, int(theirs["row"][i]), int(theirs["column"][i]),
                         int(theirs["cell"][i]),
                         first.left + (int(theirs["column"][i]) + 0.5) * first.dx,
                         first.top - (int(theirs["row"][i]) + 0.5) * first.dy)
                        for i in keep
                    ]  # fmt: skip
            out["missing"] += int((deliverable & ~delivered).sum())
            out["extra"] += int((delivered & ~deliverable).sum())

            both = deliverable & delivered
            if both.any():
                wanted_values = zeroed
                wanted_probability = np.broadcast_to(expected_probability[:, None], values.shape)
                a, b = given_values[:, both], wanted_values[:, both]
                wrong = ~((a == b) | (np.isnan(a) & np.isnan(b)))
                p, q = given_probability[:, both], wanted_probability[:, both]
                with np.errstate(invalid="ignore"):
                    off = ~((np.abs(p - q) <= PROBABILITY_TOLERANCE) | (np.isnan(p) & np.isnan(q)))
                    gap = np.abs(a - b)
                out["pixels_compared"] += int(both.sum())
                out["pixels_differing"] += int((wrong | off).any(axis=0).sum())
                out["values_compared"] += int((~np.isnan(b)).sum())
                out["values_differing"] += int(wrong.sum())
                out["probabilities_differing"] += int(off.sum())
                if np.isfinite(gap).any():
                    out["largest_difference"] = max(out["largest_difference"],
                                                    float(np.nanmax(gap)))  # fmt: skip
                if wrong.any() and len(out["examples"]) < 5:
                    at = int(np.flatnonzero(both)[np.flatnonzero(wrong.any(axis=0))[0]])
                    out["examples"].append({
                        "tile": label, "row": top + at // width, "column": c0 + at % width,
                        "publisher": [None if np.isnan(v) else float(v) for v in values[:, at]],
                        "crc_sdk": [None if np.isnan(v) else float(v)
                                    for v in given_values[:, at]],
                    })  # fmt: skip
        for tiff in stack:
            tiff.close()
    if theirs is not None:
        out["rows_outside_window"] += int((~np.isin(theirs["tile"], list(seen_tiles))).sum())
    return out


def _cells(pool: list[tuple[Any, ...]]) -> dict[str, Any]:
    """A sample of rows: is ``cell_id`` the H3 cell that holds the pixel's centre?"""
    from h3.api import basic_int as h3

    sample = compare.sample(pool, SAMPLE_CELLS, SEED)
    wrong = [
        {"tile": tile, "row": row, "column": column, "crc_sdk": cell}
        for tile, row, column, cell, lon, lat in sample
        if h3.latlng_to_cell(lat, lon, CELL_RESOLUTION) != cell
    ]
    return {"rows_checked": len(sample), "cells_differing": len(wrong), "examples": wrong[:5]}


def _plain(uri: str) -> str:
    return uri.split("#", 1)[0]


def assess(
    cache: Path,
    *,
    live: bool,
    versions: dict[str, str],
    rules: reference.Rules | None = None,
    log: Callable[[str], None] = lambda _: None,
    areas: Sequence[Area] = AREAS,
    outside: Sequence[Area] = OUTSIDE,
    publisher: dict[str, Path] | None = None,
    strip_rows: int = STRIP_ROWS,
) -> dict[str, Any]:
    """The records of one run. ``rules`` overrides the reference rules (for fault tests);
    ``publisher`` names local folders that stand for the publisher (offline tests)."""
    rules = rules or reference.Rules()
    publisher = publisher or {}
    checks: list[CheckRecord] = []
    explored: dict[str, Any] = {"areas": [], "datasets": {}, "outside": [], "runs": []}
    copies: dict[str, reference.Copy] = {}
    read_from: dict[str, Path | None] = {}

    def record(check: str, category: str, method: str, agrees: bool | None, *,
               steps: Sequence[str], result: dict[str, Any], inputs: Sequence[dict[str, Any]] = (),
               tolerance: dict[str, Any] | None = None, note: str = "") -> None:  # fmt: skip
        checks.append(compare.record(
            source=SOURCE, check=check, tier="verification", category=category, method=method,
            agrees=agrees, versions=versions, result=result, inputs=inputs,
            tolerance=tolerance, steps=steps, note=note,
        ))  # fmt: skip

    for dataset in dict.fromkeys(area.dataset for area in (*areas, *outside)):
        folder = publisher.get(dataset)
        stated = framework.facts(dataset)
        reachable = folder is None and live and _answers(stated["base_url"] + "/README.txt")
        if folder is None and live and not reachable:
            log(f"{dataset}: the publisher's server does not answer; using the copy held")
        copy = reference.Copy(dataset, cache, live=reachable, folder=folder)
        copies[dataset] = copy
        # crc-sdk reads the publisher when it answers; otherwise the copy the reference holds
        read_from[dataset] = None if reachable else copy.root
        readme = copy.text("README.txt")
        index = copy.index()
        periods = reference.periods(index, copy.layout)
        explored["datasets"][dataset] = {
            "address": copy.base, "release": reference.version(readme),
            "stated": reference.stated(readme), "return_periods": periods,
            "crc_sdk": stated, "publisher_answered": bool(reachable or folder is not None),
            "crc_sdk_read_from": "the publisher" if reachable else
            "a local copy of the publisher's files",
        }  # fmt: skip

    def run_read(area: Area, name: str, bounds: Sequence[float]) -> tuple[dict[str, Any], Path]:
        folder = cache / "framework" / name
        answer = framework.materialize(area.dataset, bounds, folder, live=live,
                                       publisher=read_from[area.dataset],
                                       isolated=not publisher)  # fmt: skip
        return answer, folder

    for area in areas:
        copy = copies[area.dataset]
        facts = explored["datasets"][area.dataset]
        periods = facts["return_periods"]
        log(f"{area.id}: crc-sdk's read")
        run, folder = run_read(area, area.id, area.bounds)
        explored["runs"].append({
            "area": area.id, "seconds": run.get("seconds"), "rows": run.get("rows", 0),
            "peak_memory_mb": run.get("peak_memory_mb"), "error": run.get("error", ""),
            "error_type": run.get("error_type", ""), "read_from": run.get("read_from", ""),
        })  # fmt: skip
        if copy.layout == "tiled":
            import json

            tiles = reference.tiles_for(json.loads(copy.text("tile_extents.geojson")), area.bounds)
        else:
            tiles = [""]
        log(f"{area.id}: the publisher's files")
        table = None if run.get("error") else framework.rows(folder)
        ours = _compare_area(copy, area, periods, tiles, table, rules, strip_rows)
        names = [reference.depth_name(copy.layout, p, t) for t in tiles for p in periods]
        inputs = (
            {"role": "publisher's files", **copy.provenance(n for n in names if n in copy.used)},
            {"role": "crc-sdk read", "url": copy.base, "read_from": run.get("read_from", "")},
        )
        counts = run.get("counts") or {}
        skipped = ours["decreasing"]  # dry pixels are not skipped since crc-sdk 1.1.0
        codes = str(run.get("diagnostics", []))
        notes = {
            "unmapped_depth_as_zero": "unmapped_depth_as_zero" in codes,
            "dry_pixels": "dry_pixels" in codes,
        }
        dry_noted = next(
            (int(m.group(1)) for d in run.get("diagnostics", [])
             if isinstance(d, dict) and d.get("code") == "dry_pixels"
             and (m := re.match(r"\s*(\d+)", str(d.get("message", ""))))),
            0 if not ours["dry"] else None,
        )  # fmt: skip
        summary = {k: ours[k] for k in (
            "pixels", "dry", "one_depth", "decreasing", "deliverable", "filled", "equal_depths",
            "fewer_than_four", "rows", "rows_outside_window", "rows_repeated", "missing", "extra",
        )}  # fmt: skip
        explored["areas"].append({
            "area": area.id, "title": area.title, "dataset": area.dataset,
            "bounds": list(area.bounds), "tiles": [t["tile"] for t in ours["tiles"]],
            **summary, "counts_reported": counts,
            "diagnostics": run.get("diagnostics", []), "warnings": run.get("warnings", []),
        })  # fmt: skip
        if run.get("error"):
            record(f"read[{area.id}]", "completeness",
                   "Ask crc-sdk for every pixel of the box.", False,
                   steps=("area",), inputs=inputs,
                   result={"error_type": run["error_type"], "error": run["error"][:600],
                           "pixels_in_the_publisher_window": ours["pixels"],
                           "pixels_that_should_be_delivered": ours["deliverable"]})  # fmt: skip
            continue
        record(
            f"area[{area.id}]", "completeness",
            "The pixels the publisher's grids hold inside the box (every pixel the box touches) "
            "against the number crc-sdk reports as requested plus the number its dry_pixels note "
            "gives (since crc-sdk 1.1.0 a dry pixel is not counted as requested), and the "
            "positions of its rows.",
            (counts.get("requested") or 0) + (dry_noted or 0) == ours["pixels"]
            and dry_noted == ours["dry"] and not ours["rows_outside_window"],
            steps=("area",), inputs=inputs,
            result={"pixels_reference": ours["pixels"],
                    "requested_crc_sdk": counts.get("requested"),
                    "dry_reference": ours["dry"], "dry_noted_crc_sdk": dry_noted,
                    "rows_outside_window": ours["rows_outside_window"],
                    "tiles": [t["tile"] for t in ours["tiles"]]},
            tolerance={"counts": "identical"},
        )  # fmt: skip
        record(
            f"delivered[{area.id}]", "completeness",
            "Which pixels get a row. The reference delivers a pixel that has a depth at one or "
            "more return periods unless, with the return periods it has no depth for read as "
            "0 m, a depth is lower than the one at a shorter return period; it skips those and "
            "gives dry pixels no row. crc-sdk's rows, its skipped count (the decreasing pixels "
            "only) and its notes on filled and dry pixels are compared with that.",
            not ours["missing"] and not ours["extra"] and counts.get("produced") == ours["rows"]
            and counts.get("skipped") == skipped and ours["rows"] == ours["deliverable"]
            and notes["unmapped_depth_as_zero"] == bool(ours["filled"])
            and notes["dry_pixels"] == bool(ours["dry"]),
            steps=("selection", "skipped-count"), inputs=inputs,
            result={**summary, "skipped_reference": skipped, "counts_crc_sdk": counts,
                    "notes_crc_sdk": notes, "diagnostics": run.get("diagnostics", [])},
            tolerance={"pixels": "the same set", "counts": "identical"},
        )  # fmt: skip
        record(
            f"values[{area.id}]", "fidelity",
            "For every delivered pixel: crc-sdk's knots against the publisher's depths in order "
            "of return period, and its probabilities against 1 - 1/T for the same periods.",
            (not ours["values_differing"] and not ours["probabilities_differing"])
            if ours["pixels_compared"] else None,
            steps=("knots", "depths", "nodata"), inputs=inputs,
            result={k: ours[k] for k in (
                "pixels_compared", "pixels_differing", "values_compared", "values_differing",
                "probabilities_differing", "largest_difference", "examples")},
            tolerance={"depths": "identical", "probabilities": f"within {PROBABILITY_TOLERANCE}"},
            note="" if ours["pixels_compared"] else "no pixel to compare",
        )  # fmt: skip
        cells = _cells(ours["cells"])
        record(
            f"cells[{area.id}]", "consistency",
            f"A seeded sample of rows: cell_id against the H3 cell of resolution "
            f"{CELL_RESOLUTION} that holds the centre of the pixel named by the support_id.",
            (not cells["cells_differing"] and not ours["rows_repeated"])
            if cells["rows_checked"] else None,
            steps=("identifier", "cell"), inputs=inputs,
            result=cells | {"rows_repeated": ours["rows_repeated"]},
            tolerance={"cells": "identical"},
            note="" if cells["rows_checked"] else "no row to check",
        )  # fmt: skip
        kinds = run.get("curve_kinds", {})
        record(
            f"shape[{area.id}]", "consistency",
            "The shape of crc-sdk's rows: one quantile curve per row and nothing fitted, the "
            "product's variable, and no scenario or period.",
            (set(kinds) <= {"quantile_curve"} and not run.get("fit_present")
             and not run.get("failure_present")
             and run.get("variable_ids") in ([f"jrc:{area.dataset}:flood_depth"], [])
             and run.get("scenario_ids") in ([None], []) and run.get("period_ids") in ([None], [])),
            steps=("no-fit", "labels"), inputs=inputs,
            result={"curve_kinds": kinds, "rows_with_a_fit": run.get("fit_present"),
                    "rows_with_a_failure": run.get("failure_present"),
                    "variable_ids": run.get("variable_ids"), "columns": run.get("columns"),
                    "index_resolution": (run.get("spatial") or {}).get("index_resolution")},
            tolerance={"labels": "identical text"},
        )  # fmt: skip
        resources = [r for identity in run.get("identities", []) for r in identity["resources"]]
        found = sorted({_plain(r["uri"]) for r in resources})
        base = (read_from[area.dataset].resolve().as_uri() if read_from[area.dataset]
                else copy.base)  # fmt: skip
        wanted = sorted(
            {
                f"{base}/README.txt",
                *(f"{base}/{name}" for name in names),
                *([f"{base}/tile_extents.geojson"] if copy.layout == "tiled" else []),
            }
        )
        record(
            f"files[{area.id}]", "completeness",
            "The addresses crc-sdk records as read against the publisher's README, tile index "
            "and the depth file of every return period for every tile the box meets.",
            found == wanted, steps=("files",), inputs=inputs,
            result={"files_reference": len(wanted), "files_crc_sdk": len(found),
                    "only_reference": sorted(set(wanted) - set(found))[:8],
                    "only_crc_sdk": sorted(set(found) - set(wanted))[:8]},
            tolerance={"addresses": "the same set"},
        )  # fmt: skip
        complete = [
            r
            for r in resources
            if r["sha256"] and r["license"] and r["attribution"] and r["retrieved_at"]
        ]
        sums = {_plain(r["uri"]).rsplit("/", 1)[-1]: r["sha256"] for r in resources
                if "#" not in r["uri"]}  # fmt: skip
        whole = {
            name: "sha256:" + copy.used[name]["sha256"]
            for name in ("README.txt", "tile_extents.geojson")
            if name in copy.used
        }
        record(
            f"provenance[{area.id}]", "consistency",
            "Every file crc-sdk records carries a checksum, a licence, an attribution and a "
            "retrieval time; for the files it reads whole (README, tile index) the checksum is "
            "compared with the reference's.",
            len(complete) == len(resources) and bool(resources)
            and all(sums.get(name) == value for name, value in whole.items()),
            steps=("provenance",), inputs=inputs,
            result={"resources": len(resources), "resources_complete": len(complete),
                    "whole_files_compared": len(whole),
                    "whole_files_differing": sum(sums.get(n) != v for n, v in whole.items()),
                    "raster_resources": sum("#" in r["uri"] for r in resources),
                    "raster_checksum_is_of": "crc-sdk's crop of the file, not the publisher's "
                    "file; it cannot be compared with a checksum of the publisher's file",
                    "licences": sorted({r["license"] for r in resources}),
                    "attributions": sorted({r["attribution"] for r in resources})},
            tolerance={"checksums": "identical"},
        )  # fmt: skip
        releases = sorted({i["release"]["id"] for i in run.get("identities", []) if i["release"]})
        record(
            f"release[{area.id}]", "consistency",
            "The release crc-sdk records against the version line of the publisher's README.",
            facts["release"] in releases and facts["crc_sdk"]["version"] == facts["release"],
            steps=("release",), inputs=inputs,
            result={"readme_version": facts["release"], "crc_sdk_releases": releases,
                    "crc_sdk_expects": facts["crc_sdk"]["version"]},
            tolerance={"version": "identical text"},
        )  # fmt: skip
        licence = facts["stated"].get("licence", "")
        try:
            other = copy.text("copyright.txt").strip()[:400]
        except (OSError, FileNotFoundError):
            other = ""
        named = {r["license"] for r in resources}
        record(
            f"licence[{area.id}]", "consistency",
            "The licence crc-sdk records against the licence line of the publisher's README; "
            "the publisher's copyright.txt is quoted beside it where there is one.",
            named == {"ODbL-1.0"} and "open database" in licence.lower() if licence else None,
            steps=("licence",), inputs=inputs,
            result={"crc_sdk": sorted(named), "readme": licence, "copyright_txt": other},
            tolerance={"licence": "the licence the README names"},
            note="" if licence else "the README states no licence line",
        )  # fmt: skip

    # the same pixels must carry the same identifier and knots whatever box asked for them
    small = [a for a, e in zip(areas, explored["areas"], strict=False)
             if e["rows"] and e["pixels"] <= OVERLAP_LIMIT]  # fmt: skip
    if small:
        area = min(small, key=lambda a: next(e["pixels"] for e in explored["areas"]
                                              if e["area"] == a.id))  # fmt: skip
        west, south, east, north = area.bounds
        cut = west + (east - west) * 0.6, west + (east - west) * 0.4
        log(f"{area.id}: two overlapping boxes")
        halves = []
        for name, box in (("west", (west, south, cut[0], north)),
                          ("east", (cut[1], south, east, north))):  # fmt: skip
            run, folder = run_read(area, f"{area.id}-{name}", box)
            table = None if run.get("error") else framework.rows(folder)
            halves.append({} if table is None else {
                row["support_id"]: (row["cell_id"], tuple(row["probabilities"]),
                                    tuple(row["values"]))
                for row in table.to_pylist()
            })  # fmt: skip
        whole_table = framework.rows(cache / "framework" / area.id)
        whole_rows = {row["support_id"]: (row["cell_id"], tuple(row["probabilities"]),
                                          tuple(row["values"]))
                      for row in whole_table.to_pylist()}  # fmt: skip
        shared = set(halves[0]) & set(halves[1])
        differing = sum(halves[0][k] != halves[1][k] for k in shared)
        union = halves[0] | halves[1]
        record(
            f"overlap[{area.id}]", "consistency",
            "The box is read again as two boxes that overlap by a fifth of its width: pixels in "
            "the overlap must carry the same support_id, cell and knots in both, and the two "
            "together must give the rows of the whole box.",
            bool(shared) and not differing and union == whole_rows,
            steps=("identifier",),
            inputs=({"role": "crc-sdk reads", "url": copies[area.dataset].base},),
            result={"rows_west": len(halves[0]), "rows_east": len(halves[1]),
                    "rows_in_both": len(shared), "rows_differing": differing,
                    "rows_of_the_whole_box": len(whole_rows),
                    "rows_only_in_the_whole_box": len(set(whole_rows) - set(union)),
                    "rows_only_in_the_two_boxes": len(set(union) - set(whole_rows))},
            tolerance={"rows": "identical"},
        )  # fmt: skip

    for area in outside:
        log(f"{area.id}: a box outside the coverage")
        run, _ = run_read(area, area.id, area.bounds)
        counts = run.get("counts") or {}
        explored["outside"].append({
            "area": area.id, "title": area.title, "rows": run.get("rows", 0),
            "error": run.get("error", ""), "error_type": run.get("error_type", ""),
            "counts": counts, "diagnostics": run.get("diagnostics", []),
            "complete": run.get("complete"), "valid": run.get("valid"),
        })  # fmt: skip
        record(
            f"coverage[{area.id}]", "completeness",
            "Ask crc-sdk for a box that lies outside the product's coverage and record what "
            "comes back: an error, or no rows with an area_outside_coverage warning (crc-sdk "
            "1.0.1, pull request #55).",
            not run.get("error") and not run.get("rows")
            and "area_outside_coverage" in str(run.get("diagnostics", [])),
            steps=("coverage",),
            inputs=({"role": "crc-sdk read", "url": copies[area.dataset].base},),
            result={"rows": run.get("rows", 0), "error_type": run.get("error_type", ""),
                    "error": run.get("error", "")[:400], "counts": counts,
                    "diagnostics": run.get("diagnostics", []),
                    "reported_complete": run.get("complete"),
                    "reported_valid": run.get("valid")},
            tolerance={"behaviour": "no rows, no error, the warning"},
        )  # fmt: skip

    local = sorted(d for d, where in read_from.items() if where is not None and d not in publisher)
    if local or publisher:
        record(
            "transport", "fidelity",
            "crc-sdk's own downloads from the publisher (range requests pinned to the file's "
            "ETag) were not exercised: it read a local copy of the publisher's files.",
            None, steps=("transport",),
            inputs=({"role": "crc-sdk read", "url": "; ".join(c.base for c in copies.values())},),
            result={"read_from_a_local_copy": local or sorted(publisher)},
            note="the publisher's server did not answer" if local else "constructed files",
        )  # fmt: skip
    else:
        record(
            "transport", "fidelity",
            "crc-sdk read from the publisher's server; the values it returned are compared in "
            "the values checks.",
            all(c["outcome"] == "confirmed" for c in (x.to_dict() for x in checks)
                if c["check"].startswith("values[")),
            steps=("transport",),
            inputs=({"role": "crc-sdk read", "url": "; ".join(c.base for c in copies.values())},),
            result={"read_from_a_local_copy": []},
        )  # fmt: skip

    return present({
        "source": SOURCE,
        "seed": SEED,
        "versions": dict(versions),
        "run_at": compare.now(),
        "areas_assessed": [area.id for area in areas],
        "options_assessed": {"product": sorted({area.dataset for area in areas})},
        "checks": [check.to_dict() for check in checks],
        "exploration": explored,
    })  # fmt: skip


def n_(value: Any) -> str:
    return compare.number(value) if isinstance(value, int | float) else str(value)


def _summary(check: dict[str, Any]) -> str:
    result, name = check["result"], check["check"].split("[")[0]
    if name == "read":
        return f"crc-sdk raises {result['error_type']}: {result['error'][:200]}"
    if name == "area":
        return (f"{n_(result['pixels_reference'])} pixels in the publisher's window, "
                f"{n_(result['requested_crc_sdk'])} requested by crc-sdk and "
                f"{n_(result.get('dry_noted_crc_sdk') or 0)} noted dry; "
                f"{n_(result['rows_outside_window'])} rows outside the window")  # fmt: skip
    if name == "delivered":
        return (f"{n_(result['rows'])} rows for {n_(result['deliverable'])} deliverable pixels; "
                f"{n_(result['missing'])} missing, {n_(result['extra'])} extra; skipped "
                f"{n_(result['counts_crc_sdk'].get('skipped'))} against "
                f"{n_(result['skipped_reference'])} ({n_(result['dry'])} dry, "
                f"{n_(result['decreasing'])} with a depth that decreases); "
                f"{n_(result.get('filled', 0))} delivered with an unmapped return period read as "
                f"0 m ({n_(result['one_depth'])} with one depth)")  # fmt: skip
    if name == "values":
        return (f"{n_(result['values_compared'])} depths of {n_(result['pixels_compared'])} "
                f"pixels compared; {n_(result['values_differing'])} depths and "
                f"{n_(result['probabilities_differing'])} probabilities differ")  # fmt: skip
    if name == "cells":
        return (f"{n_(result['rows_checked'])} rows checked; {n_(result['cells_differing'])} "
                f"cells differ; {n_(result['rows_repeated'])} rows repeated")  # fmt: skip
    if name == "shape":
        return (f"curve kinds {result['curve_kinds']}; {n_(result['rows_with_a_fit'] or 0)} rows "
                f"with a fit; variable {result['variable_ids']}")  # fmt: skip
    if name == "files":
        return (f"{n_(result['files_crc_sdk'])} addresses recorded against "
                f"{n_(result['files_reference'])} expected")  # fmt: skip
    if name == "provenance":
        return (f"{n_(result['resources_complete'])} of {n_(result['resources'])} recorded files "
                f"carry all four fields; {n_(result['whole_files_differing'])} of "
                f"{n_(result['whole_files_compared'])} whole-file checksums differ; "
                f"{n_(result['raster_resources'])} raster checksums are of crc-sdk's crop"
                )  # fmt: skip
    if name == "release":
        return (f"README {result['readme_version']}; crc-sdk records "
                f"{', '.join(result['crc_sdk_releases'])}")  # fmt: skip
    if name == "licence":
        return f"crc-sdk {', '.join(result['crc_sdk'])}; README: {result['readme'][:120]}"
    if name == "overlap":
        return (f"{n_(result['rows_in_both'])} rows in both boxes, "
                f"{n_(result['rows_differing'])} differ; the two boxes together against the "
                f"whole: {n_(result['rows_only_in_the_whole_box'])} and "
                f"{n_(result['rows_only_in_the_two_boxes'])} rows on one side only")  # fmt: skip
    if name == "coverage":
        if result["error_type"]:
            return f"crc-sdk raises {result['error_type']}: {result['error'][:160]}"
        return (f"{n_(result['rows'])} rows, {len(result['diagnostics'])} diagnostics, "
                f"reported complete: {result['reported_complete']}")  # fmt: skip
    return check.get("note", "")


def present(run: dict[str, Any]) -> dict[str, Any]:
    """Add what the page and the report show: summaries, headline numbers, tables."""
    for check in run["checks"]:
        check["summary"] = _summary(check)
    count = compare.tally(run["checks"])
    values = [c["result"] for c in run["checks"] if c["check"].startswith("values[")]
    areas = run["exploration"]["areas"]
    run["headline"] = [
        [sum(a["pixels"] for a in areas), "pixels read from the publisher's files"],
        [sum(a["rows"] for a in areas), "pixels delivered by crc-sdk"],
        [sum(v["values_compared"] for v in values), "depths compared one by one"],
        [sum(v["values_differing"] for v in values), "depths that differ"],
        [f"{count.get('confirmed', 0)} of {len(run['checks'])}", "checks confirmed"],
        [count.get("differs", 0), "checks that differ"],
    ]
    runs = {r["area"]: r for r in run["exploration"]["runs"]}
    run["tables"] = [
        {
            "title": "Pixels by area",
            "note": "Counted from the publisher's files by the reference reader. A pixel is "
            "delivered when it has two or more depths and none is lower than an earlier one. "
            "crc-sdk reports the three other groups as one number.",
            "head": ["Area", "Pixels in the box", "Dry", "One depth", "A depth decreases",
                     "Delivered by crc-sdk", "of them: fewer than four depths",
                     "of them: equal depths", "Skipped, as crc-sdk reports it"],
            "rows": [
                [a["title"], n_(a["pixels"]), n_(a["dry"]), n_(a["one_depth"]),
                 n_(a["decreasing"]), n_(a["rows"]), n_(a["fewer_than_four"]),
                 n_(a["equal_depths"]), n_((a["counts_reported"] or {}).get("skipped", ""))]
                for a in areas
            ],
        },
        {
            "title": "crc-sdk's reads",
            "note": "Each read ran in a process of its own.",
            "head": ["Area", "Read from", "Rows", "Seconds", "Peak memory, MB", "Error"],
            "rows": [
                [a["title"], runs[a["area"]]["read_from"], n_(runs[a["area"]]["rows"]),
                 n_(runs[a["area"]]["seconds"] or ""), n_(runs[a["area"]]["peak_memory_mb"] or ""),
                 runs[a["area"]]["error_type"]]
                for a in areas
            ],
        },
        {
            "title": "Outside the coverage",
            "note": "What a read returns for a box the product does not cover.",
            "head": ["Box", "Rows", "Diagnostics", "Reported complete", "Error"],
            "rows": [
                [o["title"], n_(o["rows"]), str(len(o["diagnostics"])), str(o["complete"]),
                 o["error_type"]]
                for o in run["exploration"]["outside"]
            ],
        },
    ]  # fmt: skip
    return run
