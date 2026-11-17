"""JRC flood hazard maps (GloFAS, EFAS): exploration, and verification of crc-sdk's fitted
curves against the publisher's GeoTIFF files.

Draft. GloFAS in the Texas box, in close-ups of Houston and Austin and in a box around
Fremont, California; EFAS in the Rhine box of crc-docs' ``flood_risk_by_province`` notebook.
EFAS is also asked for the Texas and Fremont boxes, which lie outside its raster.

How the two sides meet. The reference reader downloads the publisher's files whole,
checksums them and reads them with its own TIFF reader. crc-sdk is run as its documentation
shows (all return periods, the curated policy, a cache), reading the publisher over the
network; its cache folder and its output file are kept. Then, per area:

1. ``crop``: every pixel of crc-sdk's cached crops against the same window of the
   publisher's file, bit for bit, and the manifest's checksums against the crops;
2. ``curves``: which pixels get a curve, and the two parameters of each curve, against a
   closed-form least-squares fit of the publisher's depths;
3. ``values``, ``cells``, ``source-id``: for a seeded sample of pixels, the curve's depths
   as crc-framework evaluates them, the H3 cells and the identifier;
4. ``labels``, ``provenance``, ``manifest``: what the output and the cache say of themselves.

How far a fitted curve lies from the published depths, and which wet pixels get no curve,
are counted as exploration: they are what the statement says, not a disagreement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import numpy as np

from ..adapters.crc import jrc_flood as framework
from ..core import compare
from ..core.records import CheckRecord
from ..reference import jrc_flood as reference

SOURCE = "jrc-flood"
SEED = 20261117
TEXAS = (-106.645646, 25.837377, -93.508292, 36.500704)  # as in the data explorer
HOUSTON = (-95.9, 29.3, -94.9, 30.2)  # Buffalo Bayou, San Jacinto River, lower Brazos
AUSTIN = (-98.0, 30.0, -97.5, 30.5)  # Colorado River; the box of tools/probes/sources.py
FREMONT = (-122.15, 37.42, -121.85, 37.62)  # Alameda Creek and Niles Canyon to Coyote Creek
RHINE = (7.0, 49.7, 8.5, 50.9)  # crc-docs notebooks/sources/flood_risk_by_province.ipynb
TOLERANCE = 1e-6  # metres; crc-framework fits with an optimizer, the reference in closed form
EXTRA_PERIODS = (25, 250)  # evaluated besides the published return periods
SAMPLE_VALUES = 20_000
SAMPLE_PIXELS = 2_000
STRIP_ROWS = 512
DEEP = 10.0  # metres; the publisher's spurious-depth mask is about depths above this
KEY = 1 << 20  # more than the widest raster; a pixel is tile * KEY * KEY + row * KEY + column


@dataclass(frozen=True)
class Area:
    id: str
    dataset: str
    bounds: tuple[float, float, float, float]
    resolution: int | str
    title: str


AREAS = (
    Area("glofas-tx", "glofas", TEXAS, 7, "Texas box"),
    Area("glofas-houston", "glofas", HOUSTON, 9, "Houston"),
    Area("glofas-austin", "glofas", AUSTIN, 9, "Austin"),
    Area("glofas-fremont", "glofas", FREMONT, "native", "Fremont, California"),
    Area("efas-rhine", "efas", RHINE, 7, "Rhine, Bonn to Mainz"),
)
OUTSIDE = (
    Area("efas-tx", "efas", TEXAS, 7, "Texas box"),
    Area("efas-fremont", "efas", FREMONT, "native", "Fremont, California"),
)
EXPECTED_LABELS = {
    "hazard_name": ["RiverineInundation"],
    "pathway": ["historical"],
    "horizon": ["0"],
    "curve_kind": ["fitted"],
    "curve_type": ["gumbel_r"],
    "curve_shape": ["None"],
}
SOURCE_FIELDS = ("licence", "attribution", "retrieved_at", "checksum")


def _resolution(value: int | str) -> int:
    return 10 if value == "native" else int(value)


def _bits(array: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(array).view(f"u{array.dtype.itemsize}")


def _percentiles(values: np.ndarray) -> dict[str, float]:
    if not len(values):
        return {}
    points = np.percentile(values, [50, 90, 99])
    return {"median": float(points[0]), "p90": float(points[1]), "p99": float(points[2]),
            "largest": float(values.max())}  # fmt: skip


def _read_reference(copy: reference.Copy, area: Area, periods: Sequence[int], tiles: Sequence[str],
                    crops: dict[str, dict[int, Path]], rules: reference.Rules,
                    strip_rows: int, collect: Callable[..., None] | None = None,
                    ) -> dict[str, Any]:  # fmt: skip
    """The publisher's depths in the area: counts, fitted curves, and the crop comparison.

    ``collect`` is called once per strip with the flooded pixels of the strip (the review maps).
    """
    out: dict[str, Any] = {
        "tiles": [], "pixels": 0, "ever_wet": 0, "wet": {p: 0 for p in periods},
        "knots": {n: 0 for n in range(1, len(periods) + 1)},
        "too_few": 0, "constant": 0, "constant_at_one": 0, "decreasing": 0,
        "no_curve_wet": {p: 0 for p in periods},
        "deep": {p: 0 for p in periods}, "deep_in_mask": {p: 0 for p in periods},
        "mask_pixels": None, "largest_depth": 0.0,
        "dry_with_curve": {p: 0 for p in periods}, "dry_curve_positive": {p: 0 for p in periods},
        "dry_curve_tenth": {p: 0 for p in periods}, "dry_curve_largest": 0.0,
        "curve_below_zero": {p: 0 for p in periods},
        "crop": {"pixels_compared": 0, "pixels_differing": 0, "geometry": []},
    }  # fmt: skip
    keys, locations, scales, misfit, files = [], [], [], [], []
    for number, tile in enumerate(tiles):
        names = [reference.depth_name(copy.layout, p, tile) for p in periods]
        files += names
        stack = [reference.Tiff(copy.file(name)) for name in names]
        first = stack[0]
        window = first.window(area.bounds, rules)
        entry: dict[str, Any] = {"tile": tile, "window": window, "grid": first.describe()}
        out["tiles"].append(entry)
        if window is None:
            for tiff in stack:
                tiff.close()
            continue
        c0, r0, c1, r1 = window
        width = c1 - c0
        mask = _mask(copy, tile, first)
        if mask is not None:
            out["mask_pixels"] = (out["mask_pixels"] or 0) + int(mask[r0:r1, c0:c1].sum())
        local = crops.get(tile)
        crop_stack = [reference.Tiff(local[p]) for p in periods] if local else []
        if crop_stack:
            crop = crop_stack[0]
            entry["crop"] = {
                "shape": [crop.height, crop.width],
                "expected_shape": [r1 - r0, width],
                "left_offset": crop.left - (first.left + c0 * first.dx),
                "top_offset": crop.top - (first.top - r0 * first.dy),
                "pixel": [crop.dx, crop.dy],
                "nodata": crop.nodata,
                "dtype": crop.dtype.str,
            }
            same_grid = (crop.height, crop.width) == (r1 - r0, width)
            out["crop"]["geometry"].append(
                same_grid and abs(entry["crop"]["left_offset"]) < 1e-9
                and abs(entry["crop"]["top_offset"]) < 1e-9
                and crop.nodata == first.nodata and crop.dtype == first.dtype
                and (crop.dx, crop.dy) == (first.dx, first.dy)
            )  # fmt: skip
        for top in range(r0, r1, strip_rows):
            bottom = min(r1, top + strip_rows)
            raw = np.stack([tiff.read((c0, top, c1, bottom)) for tiff in stack])
            if crop_stack and out["crop"]["geometry"][-1]:
                theirs = np.stack(
                    [tiff.read((0, top - r0, width, bottom - r0)) for tiff in crop_stack]
                )
                out["crop"]["pixels_compared"] += raw.size
                out["crop"]["pixels_differing"] += int((_bits(raw) != _bits(theirs)).sum())
            values = reference.depths(raw, first.nodata, rules).reshape(len(periods), -1)
            out["pixels"] += values.shape[1]
            wet = np.isfinite(values).any(axis=0)
            if not wet.any():
                continue
            position = np.flatnonzero(wet)
            values = values[:, position]
            held = np.isfinite(values)
            fitted = reference.fit(periods, values, rules)
            good = fitted["enough"] & ~fitted["constant"] & fitted["increasing"]
            out["ever_wet"] += int(wet.sum())
            for count in range(1, len(periods) + 1):
                out["knots"][count] += int((fitted["knots"] == count).sum())
            out["too_few"] += int((~fitted["enough"]).sum())
            flat = fitted["enough"] & fitted["constant"]
            out["constant"] += int(flat.sum())
            out["constant_at_one"] += int((flat & (fitted["lowest"] == 1.0)).sum())
            out["decreasing"] += int(
                (fitted["enough"] & ~fitted["constant"] & ~fitted["increasing"]).sum()
            )
            out["largest_depth"] = max(out["largest_depth"], float(np.nanmax(values)))
            rows = top + position // width
            columns = c0 + position % width
            inside = mask[rows, columns] if mask is not None else None
            location, scale = fitted["location"][good], fitted["scale"][good]
            worst = np.zeros(int(good.sum()))
            for index, period in enumerate(periods):
                out["wet"][period] += int(held[index].sum())
                out["no_curve_wet"][period] += int((held[index] & ~good).sum())
                deep = held[index] & (values[index] > DEEP)
                out["deep"][period] += int(deep.sum())
                if inside is not None:
                    out["deep_in_mask"][period] += int((deep & inside).sum())
                curve = reference.quantile(location, scale, period)
                here = held[index][good]
                worst = np.maximum(worst, np.where(here, np.abs(curve - values[index][good]), 0))
                dry = curve[~here]
                out["dry_with_curve"][period] += len(dry)
                out["dry_curve_positive"][period] += int((dry > 0).sum())
                out["dry_curve_tenth"][period] += int((dry >= 0.1).sum())
                if len(dry):
                    out["dry_curve_largest"] = max(out["dry_curve_largest"], float(dry.max()))
                out["curve_below_zero"][period] += int((curve < 0).sum())
            if collect is not None:
                collect(first, rows, columns, values, held, good, location, scale, inside)
            keys.append((number * KEY + rows[good]) * KEY + columns[good])
            locations.append(location)
            scales.append(scale)
            misfit.append(worst)
        for tiff in [*stack, *crop_stack]:
            tiff.close()
    empty = np.empty(0)
    out["key"] = np.concatenate(keys) if keys else empty.astype(np.int64)
    out["location"] = np.concatenate(locations) if locations else empty
    out["scale"] = np.concatenate(scales) if scales else empty
    out["misfit"] = np.concatenate(misfit) if misfit else empty
    out["files"] = files
    return out


def _mask(copy: reference.Copy, tile: str, grid: reference.Tiff) -> np.ndarray | None:
    """The publisher's spurious-depth mask on the grid of a depth file, or None."""
    name = (f"Spurious_Depths/{tile}_spurious_depth_areas.tif" if copy.layout == "tiled"
            else "Europe_spurious_depth_areas.tif")  # fmt: skip
    if copy.layout != "tiled":
        return None  # the mask of Europe is one file of 71 MB; not read in this draft
    try:
        with reference.Tiff(copy.file(name)) as tiff:
            if (tiff.width, tiff.height) != (grid.width, grid.height):
                return None
            data = tiff.read()
            if tiff.nodata is not None:
                return (data != np.asarray(tiff.nodata, dtype=data.dtype)) & (data != 0)
            return data != 0
    except (OSError, reference.TiffError):
        return None


def _framework_pixels(
    run: Path, tiles: Sequence[str], grids: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """crc-sdk's rows with the publisher-file pixel each belongs to."""
    rows = framework.curves(run)
    box = rows["box"]
    key = np.full(len(box), -1, dtype=np.int64)
    for number, tile in enumerate(tiles):
        grid = grids.get(tile)
        if grid is None:
            continue
        column = (box[:, 0] - grid["left"]) / grid["dx"]
        row = (grid["top"] - box[:, 3]) / grid["dy"]
        c, r = np.rint(column).astype(np.int64), np.rint(row).astype(np.int64)
        fits = ((np.abs(column - c) < 1e-4) & (np.abs(row - r) < 1e-4) & (c >= 0) & (r >= 0)
                & (c < grid["width"]) & (r < grid["height"]) & (key < 0))  # fmt: skip
        key[fits] = (number * KEY + r[fits]) * KEY + c[fits]
    order = np.argsort(key, kind="stable")
    unique, start, counts = np.unique(key[order], return_index=True, return_counts=True)
    return {**rows, "key": key, "order": order, "pixel": unique, "start": start,
            "counts": counts, "unplaced": int((key < 0).sum())}  # fmt: skip


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
    sample_values: int = SAMPLE_VALUES,
    sample_pixels: int = SAMPLE_PIXELS,
    strip_rows: int = STRIP_ROWS,
) -> dict[str, Any]:
    """The records of one run. ``rules`` overrides the reference rules (for fault tests);
    ``publisher`` names local folders that stand for the publisher (offline tests)."""
    rules = rules or reference.Rules()
    publisher = publisher or {}
    checks: list[CheckRecord] = []
    explored: dict[str, Any] = {"areas": [], "datasets": {}, "outside": [], "runs": []}

    def make(check: str, category: str, method: str, agrees: bool | None,
             **more: Any) -> None:  # fmt: skip
        checks.append(compare.record(source=SOURCE, check=check, tier="verification",
                                     category=category, method=method, agrees=agrees,
                                     versions=versions, **more))  # fmt: skip

    copies: dict[str, reference.Copy] = {}
    published: dict[str, dict[str, Any]] = {}
    facts: dict[str, dict[str, Any]] = {}
    for dataset in sorted({area.dataset for area in [*areas, *outside]}):
        log(f"{dataset}: what the publisher holds, what crc-sdk states")
        copy = copies[dataset] = _copy(dataset, cache, live=live, folder=publisher.get(dataset))
        readme = copy.text("README.txt")
        index = copy.index()
        held = {
            "version": reference.version(readme),
            "periods": reference.periods(index, copy.layout),
            "stated": reference.stated(readme),
            "copyright": copy.text("copyright.txt") if _has(index, "copyright.txt") else "",
            "listing": {row["name"]: row["modified"] for row in index["top"]},
        }
        published[dataset] = held
        with framework.publisher_at(dataset, publisher.get(dataset)):
            stated = facts[dataset] = _stored(
                cache, f"facts {dataset}", lambda d=dataset: framework.facts(d), live=live
            )
        differences: dict[str, Any] = {}
        for name, ours, theirs in (
            ("release", held["version"], stated["configured_version"]),
            ("release crc-sdk resolves", held["version"], stated["resolved_version"]),
            ("return periods", held["periods"], stated["return_periods"]),
            ("address", copy.base, stated["base_url"]),
            ("layout", copy.layout, stated["layout"]),
        ):
            if ours != theirs:
                differences[name] = {"reference": ours, "framework": theirs}
        make(
            f"files[{dataset}]", "consistency",
            "The release, the return periods, the address and the layout crc-sdk states for "
            "the dataset, against the release in the publisher's README.txt and the return "
            "periods its directory holds depth files for.",
            not differences,
            result={"items_compared": 5, "items_differing": len(differences),
                    "differences": differences, "release": held["version"],
                    "return_periods": held["periods"],
                    "readme_last_modified": held["listing"].get("README.txt", ""),
                    "crc_sdk_error": stated["error"]},
            inputs=({"role": "reference download", **copy.provenance(["README.txt"])},
                    {"role": "crc-sdk (its configuration and README.txt)",
                     "url": stated["readme_url"]}),
            tolerance={"values": "identical"}, steps=("release", "periods"),
        )  # fmt: skip
        licence = held["stated"]["licence"]
        explored["datasets"][dataset] = {
            "name": stated["dataset"], "release": held["version"], "periods": held["periods"],
            "readme_licence": licence, "copyright_names_cc_by": "CC BY 4.0" in held["copyright"],
            "coverage": held["stated"]["coverage"], "resolution": held["stated"]["resolution"],
            "files_last_modified": _span(index, copy.layout),
            "readme_last_modified": held["listing"].get("README.txt", ""),
            "other_files": sorted(n for n in held["listing"]
                                  if "ermanent" in n or "purious" in n),
        }  # fmt: skip

    for area in areas:
        copy, held, stated = copies[area.dataset], published[area.dataset], facts[area.dataset]
        periods = held["periods"]
        run = cache / "framework" / f"{area.id}-r{_resolution(area.resolution)}"
        log(f"{area.id}: crc-sdk's run")
        with framework.publisher_at(area.dataset, publisher.get(area.dataset)):
            summary = framework.materialize(area.dataset, area.bounds, area.resolution, run,
                                            live=live)  # fmt: skip
        explored["runs"].append({"area": area.id, **{k: summary[k] for k in (
            "rows", "seconds", "peak_memory_mb", "error_type", "error", "warnings")}})  # fmt: skip
        manifest = framework.manifest(run) or {}
        entries = {entry["source_id"]: entry for entry in manifest.get("resources", [])}
        crops = {tile: {int(p): Path(path) for p, path in entry["local"].items()}
                 for tile, entry in entries.items()}  # fmt: skip

        log(f"{area.id}: the publisher's files")
        if copy.layout == "tiled":
            tile_index = json.loads(copy.text("tile_extents.geojson"))
            tiles = reference.tiles_for(tile_index, area.bounds)
        else:
            tiles = ["continental"]
        ours = _read_reference(copy, area, periods, tiles, crops, rules, strip_rows)
        reached = [t["tile"] for t in ours["tiles"] if t["window"] is not None]
        source_input = {"role": "reference download", **copy.provenance(ours["files"])}
        sdk_input = {"role": "crc-sdk (GDAL over the network, cropped into its cache)",
                     "url": stated["base_url"]}  # fmt: skip

        # -------------------------------------------------------------- tiles and manifest
        wrong: dict[str, Any] = {}
        expected_urls = {
            tile: {str(p): f"{copy.base}/{reference.depth_name(copy.layout, p, tile)}"
                   for p in periods}
            for tile in reached
        }  # fmt: skip
        if sorted(entries) != sorted(reached):
            wrong["tiles"] = {"reference": sorted(reached), "framework": sorted(entries)}
        for tile in reached:
            entry = entries.get(tile, {})
            if not publisher and entry.get("remote") != expected_urls[tile]:
                wrong[f"addresses of {tile}"] = {"reference": expected_urls[tile],
                                                 "framework": entry.get("remote")}  # fmt: skip
            sums = {str(p): reference.sha256(path) for p, path in crops.get(tile, {}).items()}
            if entry.get("checksums") != sums:
                wrong[f"checksums of {tile}"] = "the manifest's are not the SHA-256 of the crops"
        for name, mine, theirs in (
            ("release", held["version"], manifest.get("resolved_version")),
            ("box", list(area.bounds), list(manifest.get("bounds", ()))),
            ("return periods", periods, list(manifest.get("source_periods", ()))),
        ):
            if mine != theirs:
                wrong[name] = {"reference": mine, "framework": theirs}
        make(
            f"manifest[{area.id}]", "consistency",
            "crc-sdk's cache manifest against the reference: the tiles (those of the "
            "publisher's tile index that meet the box and hold a pixel of it), each file's "
            "address, the release, the box, the return periods, and each recorded checksum "
            "against the SHA-256 of the cropped file, recomputed.",
            not wrong and bool(manifest),
            result={"items_differing": len(wrong), "differences": wrong,
                    "tiles_meeting_the_box": tiles, "tiles_with_a_pixel": reached,
                    "crops": sum(len(v) for v in crops.values()),
                    "manifest_keys": sorted(k for k in manifest if k != "plans"),
                    "publisher_checksum_recorded": any("remote_checksums" in e or "etag" in e
                                                       for e in entries.values()),
                    "resolved_at": manifest.get("resolved_at", "")},
            inputs=(source_input, sdk_input),
            tolerance={"values": "identical"}, steps=("tiles", "manifest"),
        )  # fmt: skip

        # -------------------------------------------------------------- crop
        crop = ours["crop"]
        make(
            f"crop[{area.id}]", "fidelity",
            "Every pixel of the local GeoTIFFs crc-sdk cropped for the box, read with the "
            "reference's own TIFF reader, against the same window of the publisher's file "
            "downloaded whole (the window of every pixel the box touches), bit for bit; and "
            "the crop's origin, shape, pixel size, type and nodata value against the window's.",
            (crop["pixels_differing"] == 0 and all(crop["geometry"])
             and len(crop["geometry"]) == len(reached)) if crop["pixels_compared"] else False,
            result={"pixels_compared": crop["pixels_compared"],
                    "pixels_differing": crop["pixels_differing"],
                    "crops_on_the_expected_window": int(sum(crop["geometry"])),
                    "tiles": len(reached), "return_periods": len(periods),
                    "windows": {t["tile"]: {"window": t["window"], **t.get("crop", {})}
                                for t in ours["tiles"]}},
            inputs=(source_input, sdk_input),
            sample={"pixels": "all in the box", "bounds": list(area.bounds)},
            tolerance={"values": "identical bits"}, steps=("crop", "nodata"),
        )  # fmt: skip

        # -------------------------------------------------------------- curves
        log(f"{area.id}: curves")
        grids = _grids(ours["tiles"])
        if summary["error"]:
            theirs = None
        else:
            theirs = _framework_pixels(run, tiles, grids)
        if theirs is None:
            make(f"curves[{area.id}]", "fidelity", "crc-sdk's fitted curves against the "
                 "reference's.", False,
                 result={"crc_sdk_error": f"{summary['error_type']}: {summary['error']}"[:300]},
                 inputs=(source_input, sdk_input),
                 steps=("knots", "fit", "fit-failure"))  # fmt: skip
            continue
        mine, its = ours["key"], theirs["pixel"]
        common, at_mine, at_its = np.intersect1d(mine, its, assume_unique=True,
                                                 return_indices=True)  # fmt: skip
        first_row = theirs["order"][theirs["start"]]
        location = theirs["location"][first_row][at_its]
        scale = theirs["scale"][first_row][at_its]
        d_location = np.abs(location - ours["location"][at_mine])
        d_scale = np.abs(scale - ours["scale"][at_mine])
        beyond = int(((d_location > TOLERANCE) | (d_scale > TOLERANCE)).sum())
        only_mine, only_its = len(mine) - len(common), len(its) - len(common)
        unmatched = [
            {"in": side, **_pixel(copy, periods, tiles, int(key))}
            for side, keys in (("reference only", np.setdiff1d(mine, its)[:5]),
                               ("crc-sdk only", np.setdiff1d(its[its >= 0], mine)[:5]))
            for key in keys
        ]  # fmt: skip
        make(
            f"curves[{area.id}]", "fidelity",
            "Every pixel of the box. Which pixels get a curve (four or more depths, not all "
            "equal, none lower than at a shorter return period), and the location and scale "
            "of each Gumbel curve, fitted by the reference in closed form (least squares on "
            "-ln(-ln(1 - 1/T))) from the publisher's files, against the rows of crc-sdk's "
            "output placed on the publisher's pixel grid by their geometry.",
            only_mine == 0 and only_its == 0 and beyond == 0 and theirs["unplaced"] == 0
            and len(common) > 0,
            result={"pixels_in_box": ours["pixels"], "pixels_with_a_depth": ours["ever_wet"],
                    "curves_reference": len(mine), "curves_framework": len(its),
                    "only_in_reference": only_mine, "only_in_framework": only_its,
                    "values_compared": 2 * len(common), "values_differing": beyond,
                    "largest_difference_location": float(d_location.max(initial=0.0)),
                    "largest_difference_scale": float(d_scale.max(initial=0.0)),
                    "rows_framework": int(len(theirs["key"])),
                    "rows_not_on_the_pixel_grid": theirs["unplaced"],
                    "examples": unmatched,
                    "no_curve": {"fewer_than_four_depths": ours["too_few"],
                                 "all_depths_equal": ours["constant"],
                                 "a_depth_decreases": ours["decreasing"]}},
            inputs=(source_input, sdk_input),
            sample={"pixels": "all in the box", "bounds": list(area.bounds)},
            tolerance={"location, scale": f"{TOLERANCE} m", "set of pixels": "identical"},
            steps=("nodata", "knots", "fit", "fit-failure"),
        )  # fmt: skip

        # -------------------------------------------------------------- values of the curve
        chosen = np.asarray(compare.sample(range(len(common)), sample_values, SEED), dtype=int)
        evaluated = [*periods, *EXTRA_PERIODS]
        got = framework.quantiles(location[chosen], scale[chosen], evaluated)
        want = np.column_stack([
            reference.quantile(ours["location"][at_mine][chosen],
                               ours["scale"][at_mine][chosen], period)
            for period in evaluated
        ]) if len(chosen) else np.empty((0, len(evaluated)))  # fmt: skip
        gap = np.abs(got - want)
        make(
            f"values[{area.id}]", "fidelity",
            "For a seeded sample of fitted pixels: the depth of crc-sdk's curve at each "
            "published return period and at 25 and 250 years, evaluated by crc-framework "
            "from crc-sdk's parameters, against the reference's own evaluation of its own fit.",
            bool(len(chosen)) and int((gap > TOLERANCE).sum()) == 0,
            result={"pixels": len(chosen), "values_compared": int(gap.size),
                    "values_differing": int((gap > TOLERANCE).sum()),
                    "largest_difference": float(gap.max(initial=0.0)),
                    "return_periods": evaluated},
            inputs=(source_input, sdk_input),
            sample={"pixels": len(chosen), "of": len(common), "seed": SEED},
            tolerance={"depth": f"{TOLERANCE} m"}, steps=("evaluation", "fit"),
        )  # fmt: skip

        # -------------------------------------------------------------- cells and identifiers
        picked = np.asarray(compare.sample(range(len(common)), sample_pixels, SEED + 1), dtype=int)
        resolution = _resolution(area.resolution)
        cells_differing = ids_differing = cells_total = 0
        examples: list[dict[str, Any]] = []
        positions = [int(theirs["order"][theirs["start"][at_its[i]]]) for i in picked]
        identifiers = framework.source_ids(run, positions) if len(picked) else []
        same_as_publisher = 0
        for index, pixel in enumerate(picked):
            key = int(common[pixel])
            tile = tiles[key // (KEY * KEY)]
            row, column = (key // KEY) % KEY, key % KEY
            grid = grids[tile]
            west = grid["file_left"] + column * grid["dx"]
            north = grid["file_top"] - row * grid["dy"]
            cells = reference.cells_of_box((west, north - grid["dy"], west + grid["dx"], north),
                                           resolution, rules)  # fmt: skip
            start = theirs["start"][at_its[pixel]]
            rows = theirs["order"][start : start + theirs["counts"][at_its[pixel]]]
            its_cells = sorted(int(c) for c in theirs["cell"][rows])
            cells_total += len(cells)
            if cells != its_cells:
                cells_differing += 1
                if len(examples) < 5:
                    examples.append({"tile": tile, "row": row, "column": column,
                                     "reference": [f"{c:x}" for c in cells],
                                     "framework": [f"{c:x}" for c in its_cells]})  # fmt: skip
            path = f"{stated['dataset']}/{tile}"
            in_crop = _identifier(path, row - grid["row0"], column - grid["column0"])
            ids_differing += in_crop != identifiers[index]
            same_as_publisher += _identifier(path, row, column) == identifiers[index]
        make(
            f"cells[{area.id}]", "consistency",
            "For a seeded sample of fitted pixels: the H3 cells of crc-sdk's rows for the "
            "pixel, against the cells whose boundary overlaps the pixel's square, found by "
            "the reference by testing the cells around the square one by one.",
            bool(len(picked)) and cells_differing == 0,
            result={"pixels": len(picked), "pixels_differing": cells_differing,
                    "cells_compared": cells_total, "resolution": resolution,
                    "rows_per_pixel": round(len(theirs["key"]) / max(1, len(its)), 3),
                    "examples": examples},
            inputs=(source_input, sdk_input),
            sample={"pixels": len(picked), "of": len(common), "seed": SEED + 1},
            tolerance={"cells": "identical set"}, steps=("cells",),
        )  # fmt: skip
        make(
            f"source-id[{area.id}]", "consistency",
            "For the same sample: crc-sdk's identifier of the pixel against the SHA-256 the "
            "reference computes from the dataset name, the tile and the pixel's row and "
            "column in the local crop. Also counted: how many identifiers equal the one "
            "computed from the row and column in the publisher's file.",
            bool(len(picked)) and ids_differing == 0,
            result={"pixels": len(picked), "identifiers_differing": int(ids_differing),
                    "equal_to_the_publisher_file_position": int(same_as_publisher),
                    "crop_origin": {t: [grids[t]["row0"], grids[t]["column0"]] for t in grids}},
            inputs=(source_input, sdk_input),
            sample={"pixels": len(picked), "of": len(common), "seed": SEED + 1},
            tolerance={"identifier": "identical text"}, steps=("source-id",),
        )  # fmt: skip

        # -------------------------------------------------------------- labels, provenance
        labels = framework.labels(run)
        metadata = labels["metadata"]
        wrong = {name: {"expected": want_, "framework": theirs["distinct"][name]}
                 for name, want_ in EXPECTED_LABELS.items()
                 if theirs["distinct"][name] != want_}  # fmt: skip
        for name, want_, got_ in (
            ("unit", "m", metadata["value_unit"]),
            ("release", held["version"], metadata["source"]["version"]),
            ("return-period range", [float(periods[0]), float(periods[-1])],
             list(metadata["return_period_support"] or ())),
            ("H3 resolution", resolution, metadata["h3_resolution"]),
        ):  # fmt: skip
            if want_ != got_:
                wrong[name] = {"expected": want_, "framework": got_}
        make(
            f"labels[{area.id}]", "consistency",
            "The labels of every row (hazard, pathway, horizon, curve type) and of the file "
            "(unit, release, return-period range of the inputs, H3 resolution) against the "
            "statement and the publisher's README.txt.",
            not wrong,
            result={"labels_wrong": wrong, "rows": labels["rows"],
                    "distinct": theirs["distinct"], "value_semantics": metadata["value_semantics"]},
            inputs=(source_input, sdk_input),
            tolerance={"labels": "identical"}, steps=("labels",),
        )  # fmt: skip
        source = metadata["source"]
        query = parse_qs(source["uri"].split("?", 1)[1]) if "?" in source["uri"] else {}
        named = {
            "dataset": source["uri"].split("/", 1)[0],
            "tiles": sorted(query.get("sources", [""])[0].split(",")),
            "return_periods": [int(p) for p in query.get("source_periods", ["0"])[0].split(",")],
            "bounds": [float(v) for v in query.get("bounds", ["0"])[0].split(",")],
        }
        has_curve = sorted({tiles[int(k) // (KEY * KEY)] for k in its[its >= 0]})
        uri_wrong = {
            name: {"expected": want_, "framework": named[name]}
            for name, want_ in (("dataset", stated["dataset"]), ("tiles", has_curve),
                                ("return_periods", periods),
                                # the uri gives the box to twelve significant digits
                                ("bounds", [float(format(v, ".12g")) for v in area.bounds]))
            if named[name] != want_
        }  # fmt: skip
        filled = {name: source[name] for name in SOURCE_FIELDS if source[name] is not None}
        make(
            f"provenance[{area.id}]", "consistency",
            "The source block of the output file's metadata: its uri against the dataset, "
            "the box, the tiles that gave a curve and the return periods; and whether "
            "licence, attribution, retrieval time and checksum are empty, as the statement "
            "says.",
            not uri_wrong and not filled,
            result={"uri": source["uri"], "uri_wrong": uri_wrong,
                    "empty_fields": [n for n in SOURCE_FIELDS if source[n] is None],
                    "filled_fields": filled, "file_keys": labels["file_keys"],
                    "licence_in_the_publisher_readme": held["stated"]["licence"]},
            inputs=(source_input, sdk_input),
            tolerance={"values": "identical"}, steps=("provenance",),
        )  # fmt: skip

        explored["areas"].append(_area_numbers(area, periods, ours, theirs, tiles, reached))

    for area in outside:
        copy, held = copies[area.dataset], published[area.dataset]
        log(f"{area.id}: a box outside the raster")
        name = reference.depth_name(copy.layout, held["periods"][0], "")
        with reference.Tiff(copy.file(name)) as tiff:
            window, extent = tiff.window(area.bounds, rules), list(tiff.bounds)
        run = cache / "framework" / f"{area.id}-r{_resolution(area.resolution)}"
        with framework.publisher_at(area.dataset, publisher.get(area.dataset)):
            summary = framework.materialize(area.dataset, area.bounds, area.resolution, run,
                                            live=live)  # fmt: skip
        as_stated = (summary["error_type"] == "LookupError"
                     and "no JRC resources intersect area" in summary["error"])  # fmt: skip
        names_extent = any(f"{value:.2f}"[:5] in summary["error"] for value in extent)
        make(
            f"coverage[{area.id}]", "completeness",
            "A box outside the dataset's raster: whether the reference finds a pixel of the "
            "publisher's file in the box, against what crc-sdk does when asked for it with "
            "a cache (the statement: LookupError 'no JRC resources intersect area').",
            window is None and as_stated,
            result={"pixels_of_the_raster_in_the_box": 0 if window is None else
                    (window[2] - window[0]) * (window[3] - window[1]),
                    "raster_extent": extent, "coverage_in_the_readme": held["stated"]["coverage"],
                    "crc_sdk_error_type": summary["error_type"],
                    "crc_sdk_error": summary["error"][:300], "rows": summary["rows"],
                    "message_names_the_extent": names_extent,
                    "seconds": summary["seconds"]},
            inputs=({"role": "reference download", **copy.provenance([name])},
                    {"role": "crc-sdk (GDAL over the network)",
                     "url": facts[area.dataset]["base_url"]}),
            sample={"bounds": list(area.bounds)},
            tolerance={"outcome": "as stated"}, steps=("coverage",),
        )  # fmt: skip
        explored["outside"].append({"area": area.id, "title": area.title,
                                    "error": f"{summary['error_type']}: {summary['error']}"[:200],
                                    "seconds": summary["seconds"]})  # fmt: skip

    if not publisher:  # the by-area summary needs real boundaries; not run on constructed files
        from . import jrc_flood_areas

        explored["by_area"] = jrc_flood_areas.by_area(cache, areas, live=live, log=log)
        from . import jrc_flood_evidence

        outside_evidence = jrc_flood_evidence.comparisons(cache, live=live, log=log)
    else:
        outside_evidence = []

    return present({
        "source": SOURCE,
        "versions": dict(versions),
        "run_at": compare.now(),
        "selection": {"areas": {a.id: {"dataset": a.dataset, "bounds": list(a.bounds),
                                       "h3_resolution": _resolution(a.resolution),
                                       "title": a.title} for a in [*areas, *outside]},
                      "seed": SEED, "tolerance_m": TOLERANCE,
                      "policy": "JRCFloodPolicy.curated", "cache_mode": "reuse",
                      "source_periods": "all"},
        "options_assessed": {"dataset": sorted({a.dataset for a in areas})},
        "checks": [check.to_dict() for check in checks],
        "exploration": explored,
        # numbers beside outside evidence; a comparison carries no outcome and feeds no tally
        "comparisons": outside_evidence,
    })  # fmt: skip


def _copy(dataset: str, cache: Path, *, live: bool, folder: Path | None) -> reference.Copy:
    return reference.Copy(dataset, cache, live=live, folder=folder)


def _has(index: dict[str, Any], name: str) -> bool:
    return any(row["name"] == name for row in index["top"])


def _span(index: dict[str, Any], layout: str) -> list[str]:
    rows = ([row for rows in index["folders"].values() for row in rows] if layout == "tiled"
            else index["top"])  # fmt: skip
    dates = sorted(row["modified"][:10] for row in rows
                   if row["name"].endswith("depth.tif") and row["modified"])  # fmt: skip
    return [dates[0], dates[-1]] if dates else []


def _stored(cache: Path, name: str, ask: Callable[[], Any], *, live: bool) -> Any:
    """crc-sdk's answer, stored so that a run without the network gives the same records."""
    path = cache / "framework" / f"{name.replace(' ', '-')}.json"
    if live:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ask()), encoding="utf-8")
        temporary.replace(path)
    elif not path.exists():
        raise FileNotFoundError(f"no stored crc-sdk answer for {name}; run with --live")
    return json.loads(path.read_text(encoding="utf-8"))


def _grids(tiles: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per tile with a window: the window's grid, as the framework's rows are placed on it."""
    out = {}
    for tile in tiles:
        if tile["window"] is None:
            continue
        c0, r0, c1, r1 = tile["window"]
        west, _, _, north = tile["grid"]["bounds"]
        dx, dy = tile["grid"]["pixel_degrees"]
        # rows are placed by position in the publisher's file: left and top are the file's
        out[tile["tile"]] = {"left": west, "top": north, "dx": dx, "dy": dy,
                             "width": tile["grid"]["width"], "height": tile["grid"]["height"],
                             "file_left": west, "file_top": north,
                             "row0": r0, "column0": c0}  # fmt: skip
    return out


def _pixel(copy: reference.Copy, periods: Sequence[int], tiles: Sequence[str],
           key: int) -> dict[str, Any]:  # fmt: skip
    """One pixel of the publisher's files: where it is and its value at each return period."""
    tile, row, column = tiles[key // (KEY * KEY)], (key // KEY) % KEY, key % KEY
    values = []
    for period in periods:
        with reference.Tiff(copy.file(reference.depth_name(copy.layout, period, tile))) as tiff:
            values.append(round(float(tiff.read((column, row, column + 1, row + 1))[0, 0]), 4))
    return {"tile": tile, "row": row, "column": column, "values": values}


def _identifier(path: str, row: int, column: int) -> str:
    return hashlib.sha256(f"jrc\0{path}\0{row}\0{column}".encode()).hexdigest()


def _area_numbers(area: Area, periods: Sequence[int], ours: dict[str, Any],
                  theirs: dict[str, Any], tiles: Sequence[str],
                  reached: Sequence[str]) -> dict[str, Any]:  # fmt: skip
    fitted = len(ours["key"])
    misfit = ours["misfit"]
    return {
        "area": area.id, "title": area.title, "dataset": area.dataset,
        "bounds": list(area.bounds), "h3_resolution": _resolution(area.resolution),
        "tiles_meeting_the_box": list(tiles), "tiles_with_a_pixel": list(reached),
        "pixels": ours["pixels"], "ever_wet": ours["ever_wet"], "fitted": fitted,
        "wet": {str(p): ours["wet"][p] for p in periods},
        "knots": {str(n): c for n, c in ours["knots"].items()},
        "no_curve": {"fewer_than_four_depths": ours["too_few"],
                     "all_depths_equal": ours["constant"],
                     "a_depth_decreases": ours["decreasing"]},
        "all_depths_equal_to_one_metre": ours["constant_at_one"],
        "no_curve_wet": {str(p): ours["no_curve_wet"][p] for p in periods},
        "largest_depth": ours["largest_depth"],
        "deep": {str(p): ours["deep"][p] for p in periods},
        "deep_in_mask": {str(p): ours["deep_in_mask"][p] for p in periods},
        "mask_pixels": ours["mask_pixels"],
        "misfit": _percentiles(misfit),
        "misfit_over_half_metre": int((misfit > 0.5).sum()),
        "misfit_over_one_metre": int((misfit > 1.0).sum()),
        "dry_with_curve": {str(p): ours["dry_with_curve"][p] for p in periods},
        "dry_curve_positive": {str(p): ours["dry_curve_positive"][p] for p in periods},
        "dry_curve_tenth": {str(p): ours["dry_curve_tenth"][p] for p in periods},
        "dry_curve_largest": ours["dry_curve_largest"],
        "curve_below_zero": {str(p): ours["curve_below_zero"][p] for p in periods},
        "rows": int(len(theirs["key"])),
        "cells": int(len(np.unique(theirs["cell"]))),
    }  # fmt: skip


# ---------------------------------------------------------------------------- presentation
def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else ""


def _summary(check: dict[str, Any]) -> str:
    result = check["result"]
    n = compare.number
    name = check["check"].split("[")[0]
    if name == "files":
        text = (f"release {result['release']}, return periods "
                f"{', '.join(str(p) for p in result['return_periods'])}; "
                f"{result['items_compared']} items compared, "
                f"{result['items_differing']} differ")  # fmt: skip
        return text + (f" ({', '.join(result['differences'])})" if result["differences"] else "")
    if name == "manifest":
        return (f"{len(result['tiles_with_a_pixel'])} of {len(result['tiles_meeting_the_box'])} "
                f"tiles meeting the box hold a pixel of it; {result['crops']} crops, "
                f"{result['items_differing']} items differ; checksum of the publisher's file "
                "recorded: "
                f"{'yes' if result['publisher_checksum_recorded'] else 'no'}")  # fmt: skip
    if name == "crop":
        return (f"{n(result['pixels_compared'])} pixel values compared ({result['tiles']} tiles, "
                f"{result['return_periods']} return periods), {n(result['pixels_differing'])} "
                f"differ; {result['crops_on_the_expected_window']} of {result['tiles']} crops "
                "on the expected window")  # fmt: skip
    if name == "curves":
        if "crc_sdk_error" in result:
            return f"crc-sdk raises: {result['crc_sdk_error'][:160]}"
        none = result["no_curve"]
        largest = max(result["largest_difference_location"], result["largest_difference_scale"])
        return (f"{n(result['curves_reference'])} curves against "
                f"{n(result['curves_framework'])}; only in the reference "
                f"{n(result['only_in_reference'])}, only in crc-sdk "
                f"{n(result['only_in_framework'])}; {n(result['values_compared'])} parameters "
                f"compared, {n(result['values_differing'])} differ by more than {TOLERANCE} m "
                f"(largest {largest:.1e}); "
                f"of {n(result['pixels_with_a_depth'])} pixels with a depth, no curve for "
                f"{n(sum(none.values()))}")  # fmt: skip
    if name == "values":
        return (f"{n(result['pixels'])} pixels, {n(result['values_compared'])} depths compared, "
                f"{n(result['values_differing'])} differ; largest difference "
                f"{result['largest_difference']:.1e} m")  # fmt: skip
    if name == "cells":
        return (f"{n(result['pixels'])} pixels at resolution {result['resolution']}, "
                f"{n(result['cells_compared'])} cells; pixels whose cells differ: "
                f"{result['pixels_differing']}; "
                f"{result['rows_per_pixel']} rows per pixel")  # fmt: skip
    if name == "source-id":
        return (f"{n(result['pixels'])} identifiers, {result['identifiers_differing']} differ "
                "from the crop position; equal to the position in the publisher's file: "
                f"{result['equal_to_the_publisher_file_position']}")  # fmt: skip
    if name == "labels":
        return (f"{n(result['rows'])} rows; labels wrong: "
                f"{', '.join(result['labels_wrong']) or 'none'}")  # fmt: skip
    if name == "provenance":
        return (f"uri wrong: {', '.join(result['uri_wrong']) or 'nothing'}; empty: "
                f"{', '.join(result['empty_fields']) or 'none'}; the publisher's README names "
                f"the licence '{result['licence_in_the_publisher_readme']}'")  # fmt: skip
    if name == "coverage":
        return (f"pixels of the raster in the box: {result['pixels_of_the_raster_in_the_box']}; "
                f"crc-sdk: {result['crc_sdk_error_type']}: {result['crc_sdk_error'][:90]}; "
                f"the message names the extent: "
                f"{'yes' if result['message_names_the_extent'] else 'no'}")  # fmt: skip
    return check.get("note", "")


def present(run: dict[str, Any]) -> dict[str, Any]:
    """Add what the page and the report show: summaries, headline numbers, tables."""
    for check in run["checks"]:
        check["summary"] = _summary(check)
    count = compare.tally(run["checks"])
    explored = run["exploration"]
    crops = [c["result"] for c in run["checks"] if c["check"].startswith("crop[")]
    curves = [c["result"] for c in run["checks"]
              if c["check"].startswith("curves[")
              and "curves_reference" in c["result"]]  # fmt: skip
    run["headline"] = [
        [sum(r["pixels_compared"] for r in crops), "pixel values compared bit for bit"],
        [sum(r["pixels_differing"] for r in crops), "pixel values that differ"],
        [sum(r["curves_reference"] for r in curves), "curves refitted"],
        [sum(r["values_differing"] + r["only_in_reference"] + r["only_in_framework"]
             for r in curves), "curves that differ"],
        [f"{count.get('confirmed', 0)} of {len(run['checks'])}", "checks confirmed"],
        [count.get("differs", 0), "checks that differ"],
    ]  # fmt: skip
    areas = explored["areas"]
    n = compare.number
    tables = [
        {
            "title": "What was read",
            "note": "Counted from the publisher's files by the reference reader. A pixel is "
            "wet at a return period when the file gives it a depth; dry pixels hold the "
            "nodata value, not zero.",
            "head": ["Area", "Dataset", "H3", "Tiles", "Pixels in box", "Wet at the shortest",
                     "Wet at the longest", "Wet at any", "With a curve", "Deepest (m)"],
            "rows": [
                [a["title"], a["dataset"], a["h3_resolution"], len(a["tiles_with_a_pixel"]),
                 n(a["pixels"]), n(next(iter(a["wet"].values()))),
                 n(list(a["wet"].values())[-1]), n(a["ever_wet"]), n(a["fitted"]),
                 f"{a['largest_depth']:.2f}"]
                for a in areas
            ],
        },
        {
            "title": "Wet pixels that get no curve",
            "note": "crc-sdk fits a pixel only when it has a depth at four or more return "
            "periods that are not all equal and never decrease. Share is of the pixels wet "
            "at any return period. The publisher patches permanent water bodies into the "
            "maps; whether the pixels at exactly 1 m are those was not checked.",
            "head": ["Area", "Wet at any", "Fewer than four depths", "All depths equal",
                     "Of those, all exactly 1 m", "A depth decreases", "No curve", "Share"],
            "rows": [
                [a["title"], n(a["ever_wet"]), n(a["no_curve"]["fewer_than_four_depths"]),
                 n(a["no_curve"]["all_depths_equal"]), n(a["all_depths_equal_to_one_metre"]),
                 n(a["no_curve"]["a_depth_decreases"]),
                 n(a["ever_wet"] - a["fitted"]), _share(a["ever_wet"] - a["fitted"], a["ever_wet"])]
                for a in areas
            ],
        },
        {
            "title": "Published wet pixels without a curve, by return period",
            "note": "Of the pixels the publisher shows flooded at a return period, how many "
            "have no row in crc-sdk's output.",
            "head": ["Area", *[f"{p} y" for p in _all_periods(areas)]],
            "rows": [
                [a["title"], *[
                    f"{n(a['no_curve_wet'][p])} ({_share(a['no_curve_wet'][p], a['wet'][p])})"
                    if p in a["wet"] else "" for p in _all_periods(areas)]]
                for a in areas
            ],
        },
        {
            "title": "How far the fitted curve lies from the published depths",
            "note": "Per fitted pixel, the largest gap in metres between the curve and the "
            "published depth over the return periods at which the pixel is wet.",
            "head": ["Area", "Curves", "Median", "90th percentile", "99th percentile",
                     "Largest", "Over 0.5 m", "Over 1 m"],
            "rows": [
                [a["title"], n(a["fitted"]), *[f"{a['misfit'].get(k, 0):.3f}" for k in
                                               ("median", "p90", "p99", "largest")],
                 n(a["misfit_over_half_metre"]), n(a["misfit_over_one_metre"])]
                for a in areas
            ],
        },
        {
            "title": "Curve where the publisher is dry, and curve below zero",
            "note": "Pixels with a curve that the publisher shows dry at the shortest return "
            "period: how many curves give a depth above 0 and of 0.1 m or more there (0.1 m "
            "is the smallest published depth). And fitted curves that are below zero at the "
            "shortest return period.",
            "head": ["Area", "Dry at the shortest, with a curve", "Curve above 0",
                     "Curve 0.1 m or more", "Largest such depth (m)", "Curves below 0"],
            "rows": [
                [a["title"], n(_first(a["dry_with_curve"])), n(_first(a["dry_curve_positive"])),
                 n(_first(a["dry_curve_tenth"])), f"{a['dry_curve_largest']:.2f}",
                 n(_first(a["curve_below_zero"]))]
                for a in areas
            ],
        },
        {
            "title": "Depths above 10 m and the publisher's spurious-depth mask",
            "note": "The publisher marks areas where depths above 10 m are predicted in small "
            "channels and asks for caution there; crc-sdk does not read the mask. Counted at "
            "the 100-year return period. The mask of EFAS was not read.",
            "head": ["Area", "Pixels in the mask", "Deeper than 10 m", "Of those, in the mask"],
            "rows": [
                [a["title"], "" if a["mask_pixels"] is None else n(a["mask_pixels"]),
                 n(a["deep"].get("100", 0)),
                 "" if a["mask_pixels"] is None else n(a["deep_in_mask"].get("100", 0))]
                for a in areas
            ],
        },
        {
            "title": "crc-sdk's runs",
            "note": "One run per area, reading the publisher over the network into an empty "
            "cache. Memory is the peak of the whole process when the run ended, so it "
            "includes whatever that process did before the run; it is crc-sdk's own only "
            "for a run that began its process (the Texas box here).",
            "head": ["Area", "Rows", "Seconds", "Process peak memory (MB)", "Outcome"],
            "rows": [
                [r["area"], n(r["rows"]), r["seconds"], r["peak_memory_mb"],
                 f"{r['error_type']}: {r['error'][:80]}" if r["error"] else "completed"]
                for r in explored["runs"]
            ] + [[o["area"], 0, o["seconds"], "", o["error"][:100]] for o in explored["outside"]],
        },
        {
            "title": "The publisher's releases",
            "note": "From each dataset's README.txt, copyright.txt and directory page.",
            "head": ["Dataset", "Release", "Return periods", "Licence in README.txt",
                     "copyright.txt names CC BY 4.0", "Depth files last modified",
                     "README last modified", "Coverage in README.txt"],
            "rows": [
                [d["name"], d["release"], ", ".join(str(p) for p in d["periods"]),
                 d["readme_licence"], "yes" if d["copyright_names_cc_by"] else "no",
                 " to ".join(d["files_last_modified"]), d["readme_last_modified"], d["coverage"]]
                for d in explored["datasets"].values()
            ],
        },
    ]  # fmt: skip
    for entry in explored.get("by_area", ()):
        unit = entry["unit"]
        tables.append({
            "title": f"River flood depth at {entry['return_period']} years by {unit}: "
                     f"{entry['title']}",
            "note": f"The summary of crc-docs' flood_risk_by_province notebook, from crc-sdk's "
                    f"output of this run: each row's curve read at {entry['return_period']} "
                    f"years, the largest value per H3 resolution-{entry['h3_resolution']} cell, "
                    f"cells at or above {entry['threshold_m']} m "
                    f"({n(entry['cells_at_or_above'])} of {n(entry['cells_with_a_curve'])} cells "
                    f"with a curve), then mean and largest per {unit}; a cell on a border counts "
                    f"in each {unit} it overlaps. Boundaries: {entry['boundary']['title']}.",
            "head": [unit.capitalize(), "Mean depth of those cells (m)", "Largest (m)",
                     f"Cells at or above {entry['threshold_m']} m", f"Cells of the {unit}"],
            "rows": [[r["name"], f"{r['mean_depth_m']:.2f}", f"{r['max_depth_m']:.2f}",
                      n(r["cells"]), n(r["cells_of_the_area"])] for r in entry["rows"]],
        })  # fmt: skip
        saved = entry.get("notebook")
        if saved:
            mine = {r["name"]: r for r in entry["rows"]}
            rows = [["Curve rows crc-sdk returned", n(saved["curve_rows"]), n(entry["curve_rows"])],
                    [f"Cells at or above {entry['threshold_m']} m", n(saved["cells_at_or_above"]),
                     n(entry["cells_at_or_above"])]]  # fmt: skip
            for name, theirs in saved["rows"].items():
                ours = mine.get(name, {})
                for key, label, form in (("mean_depth_m", "mean depth (m)", "{:.2f}"),
                                         ("max_depth_m", "largest depth (m)", "{:.2f}"),
                                         ("cells", "cells", "{:,}")):  # fmt: skip
                    rows.append([f"{name}: {label}", form.format(theirs[key]),
                                 form.format(ours[key]) if key in ours else "none"])  # fmt: skip
            rows.append(["Places in those cells", saved["places"], "not computed"])
            tables.append({
                "title": "The crc-docs notebook's saved numbers against this run (Rhine box)",
                "note": f"Notebook outputs as saved at crc-docs {saved['crc_docs_commit'][:7]}. "
                        "Same box, dataset, policy, resolution, return period and threshold.",
                "head": ["Number", "Notebook, saved output", "This run"],
                "rows": rows,
            })  # fmt: skip
    # where each table's numbers come from: crc-sdk's output, or the publisher's files read here
    from_crc_sdk = ("crc-sdk's runs", "River flood depth at", "The crc-docs notebook")
    for table in tables:
        table["origin"] = "crc-sdk" if table["title"].startswith(from_crc_sdk) else "publisher"
    run["tables"] = tables
    if areas:
        run["charts"] = _charts(run, areas)
        run["chart"] = {
            "origin": "publisher",
            "title": "Published wet pixels without a curve in crc-sdk, by return period",
            "unit": "% of the pixels wet at that return period",
            "x": "Return period",
            "select": "Area",
            "default": areas[0]["title"],
            "series": {
                a["title"]: [
                    [f"{p} y", round(100 * a["no_curve_wet"][p] / a["wet"][p], 2) if a["wet"][p]
                     else 0]
                    for p in a["wet"]
                ]
                for a in areas
            },
        }  # fmt: skip
    return run


def _charts(run: dict[str, Any], areas: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Charts for reviewing the findings; each names the finding it bears on."""
    unfitted = {c["check"][7:-1]: c["result"].get("only_in_reference", 0)
                for c in run["checks"] if c["check"].startswith("curves[")}  # fmt: skip

    def share(part: int, whole: int) -> float:
        return round(100 * part / whole, 2) if whole else 0

    def per_area(title: str, unit: str, x: str, rows: Callable[[dict[str, Any]], list[Any]],
                 finding: str) -> dict[str, Any]:  # fmt: skip
        return {"title": title, "finding": finding, "origin": "publisher", "unit": unit, "x": x,
                "select": "Area",
                "default": areas[0]["title"],
                "series": {a["title"]: rows(a) for a in areas}}  # fmt: skip

    charts = [
        per_area("Flooded pixels without a curve, by cause", "pixels", "Cause", lambda a: [
            ["fewer than four depths", a["no_curve"]["fewer_than_four_depths"]],
            ["all depths equal", a["no_curve"]["all_depths_equal"]],
            ["a depth decreases", a["no_curve"]["a_depth_decreases"]],
            ["fit did not converge", unfitted.get(a["area"], 0)],
        ], "CRC-014-JRC, CRC-013-FWK"),
        per_area("Flooded pixels by the number of return periods with a depth", "pixels",
                 "Depths", lambda a: [[int(k), v] for k, v in a["knots"].items()], "CRC-014-JRC"),
        per_area("Fitted pixels dry in the published map where the curve gives 0.1 m or more",
                 "% of fitted pixels", "Return period",
                 lambda a: [[f"{p} y", share(a["dry_curve_tenth"][p], a["fitted"])]
                            for p in a["wet"]], "CRC-015-JRC"),
        per_area("Fitted pixels whose curve is below zero", "% of fitted pixels", "Return period",
                 lambda a: [[f"{p} y", share(a["curve_below_zero"][p], a["fitted"])]
                            for p in a["wet"]], "CRC-015-JRC"),
        per_area("Distance between the fitted curve and the published depths", "m", "Statistic",
                 lambda a: [["median", round(a["misfit"].get("median", 0), 3)],
                            ["90th percentile", round(a["misfit"].get("p90", 0), 3)],
                            ["99th percentile", round(a["misfit"].get("p99", 0), 3)],
                            ["largest", round(a["misfit"].get("largest", 0), 3)]], "CRC-015-JRC"),
        per_area("Pixels deeper than 10 m, and those inside the publisher's spurious-depth mask",
                 "pixels", "Return period",
                 lambda a: [x for p in a["wet"] for x in (
                     [f"{p} y, all", a["deep"][p]], [f"{p} y, in mask", a["deep_in_mask"][p]])],
                 "CRC-019-JRC"),
    ]  # fmt: skip
    for entry in run["exploration"].get("by_area", ()):
        if len(entry["rows"]) < 2:
            continue
        top = entry["rows"][:15]
        charts.append({
            "title": f"Mean flood depth at {entry['return_period']} years of the cells at or "
                     f"above {entry['threshold_m']} m, by {entry['unit']}: {entry['title']}"
                     + (f" (first 15 of {len(entry['rows'])})" if len(entry["rows"]) > 15 else ""),
            "finding": "", "origin": "crc-sdk", "unit": "m", "x": entry["unit"].capitalize(),
            "ranked": True,
            "select": "", "default": "all",
            "series": {"all": [[r["name"], round(r["mean_depth_m"], 2)] for r in top]},
        })  # fmt: skip
    return charts


def _all_periods(areas: Sequence[dict[str, Any]]) -> list[str]:
    return sorted({p for a in areas for p in a["wet"]}, key=int)


def _first(values: dict[str, int]) -> int:
    return next(iter(values.values()), 0)
