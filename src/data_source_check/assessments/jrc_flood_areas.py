"""JRC flood maps by area, and per-cell review maps (Stage 2 of V8, 2026-11-17).

Two things that sit beside the checks of ``assessments/jrc_flood.py`` and are exploration:

- ``by_area``: the summary of crc-docs' ``flood_risk_by_province`` notebook (largest pixel-curve
  depth per H3 cell at 25 years, cells at or above 0.5 m, mean and largest depth per province),
  computed from crc-sdk's output of this assessment, set beside the notebook's saved numbers for
  the Rhine box, and applied to Texas counties and the city of Fremont.
- ``review_maps``: per H3 cell, what the reference reads in the publisher's files and how the
  fitted curves relate to it, written as files the map explorer draws. They exist so that the
  findings CRC-014-JRC, CRC-015-JRC and CRC-019-JRC can be looked at on a map.

    python -m data_source_check.assessments.jrc_flood_areas --maps
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..adapters.crc import jrc_flood_011 as framework
from ..core import compare
from ..reference import jrc_flood as reference
from . import jrc_flood_011 as base

RETURN_PERIOD = 25  # as in the notebook: read from the curve, not a published return period
THRESHOLD = 0.5  # metres, as in the notebook
#: the map explorer's fixed list of return periods (lab_common.horizons.RETURN_PERIODS)
MAP_PERIODS = (2, 5, 10, 20, 50, 100, 200, 500)
#: resolution of the review maps where it is not the area's own, to keep the files small
#: (cells of about 36 km2 in the Texas box and 0.74 km2 in the Houston box)
REVIEW_RESOLUTION = {"glofas-tx": 6, "glofas-houston": 8}
MAPS = Path("site/validation/data/review/jrc-flood")
#: the files leave out the return periods shorter than the publisher's shortest (10 years); the
#: page fills them with "no value" (`values_from` in the file)
FIRST_SHOWN = MAP_PERIODS.index(10)


@dataclass(frozen=True)
class Boundary:
    file: str
    url: str
    title: str
    name_field: str
    unit: str
    licence: str


TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
BOUNDARIES = {
    "efas-rhine": Boundary(
        "deu-adm1.geojson",
        "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/DEU/ADM1/"
        "geoBoundaries-DEU-ADM1_simplified.geojson",
        "German states: geoBoundaries ADM1, simplified, commit 9469f09 (the notebook's file)",
        "shapeName", "state", "CC BY 4.0 as the notebook states; the file states none",
    ),
    "glofas-tx": Boundary(
        "tx-counties.geojson",
        f"{TIGER}/State_County/MapServer/1/query?where=STATE%3D%2748%27"
        "&outFields=NAME,STATE,GEOID,BASENAME&returnGeometry=true&outSR=4326"
        "&maxAllowableOffset=0.002&f=geojson",
        "Texas counties: U.S. Census Bureau TIGERweb, vintage 1 January 2026, simplified to "
        "0.002 degrees by the service",
        "BASENAME", "county", "U.S. government work",
    ),
    "glofas-fremont": Boundary(
        "fremont-place.geojson",
        f"{TIGER}/Places_CouSub_ConCity_SubMCD/MapServer/4/query?where=NAME%3D%27Fremont+city%27"
        "+AND+STATE%3D%2706%27&outFields=NAME,STATE,GEOID,BASENAME,LSADC&returnGeometry=true"
        "&outSR=4326&f=geojson",
        "City of Fremont: U.S. Census Bureau TIGERweb incorporated places (BAS 2026)",
        "BASENAME", "city", "U.S. government work",
    ),
}  # fmt: skip
#: saved outputs of notebooks/sources/flood_risk_by_province.ipynb at crc-docs c6f78fb (2026-11-07)
NOTEBOOK = {
    "crc_docs_commit": "c6f78fb3eca4afe10df2a265e306ab23c86703eb",
    "curve_rows": 154532,
    "cells_at_or_above": 742,
    "rows": {
        "Rheinland-Pfalz": {"mean_depth_m": 7.681681, "max_depth_m": 21.862373, "cells": 508},
        "Nordrhein-Westfalen": {"mean_depth_m": 7.269981, "max_depth_m": 16.048452, "cells": 98},
        "Hessen": {"mean_depth_m": 5.357236, "max_depth_m": 15.385082, "cells": 205},
    },
    "places": "62,717 Overture places (release 2026-08-19.0, no longer hosted): not reproduced",
}


def cell_maximum(cells: np.ndarray, depths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One value per cell: the largest among the cell's rows."""
    unique, inverse = np.unique(cells, return_inverse=True)
    largest = np.full(len(unique), -np.inf)
    np.maximum.at(largest, inverse, depths)
    return unique, largest


def summarize(cells: np.ndarray, depths: np.ndarray, polygons: Sequence[tuple[str, set[int]]],
              threshold: float = THRESHOLD) -> dict[str, Any]:  # fmt: skip
    """The notebook's table: per polygon, mean and largest depth of its cells at or above the
    threshold. A cell on a border belongs to every polygon it overlaps, as in the notebook."""
    unique, largest = cell_maximum(cells, depths)
    keep = largest >= threshold
    exposed, depth = unique[keep], largest[keep]
    rows = []
    for name, members in polygons:
        inside = np.isin(exposed, np.fromiter(members, dtype=np.uint64, count=len(members)))
        if inside.any():
            rows.append({"name": name, "mean_depth_m": round(float(depth[inside].mean()), 6),
                         "max_depth_m": round(float(depth[inside].max()), 6),
                         "cells": int(inside.sum()),
                         "cells_of_the_area": len(members)})  # fmt: skip
    rows.sort(key=lambda row: -row["mean_depth_m"])
    return {"cells_with_a_curve": int(len(unique)), "cells_at_or_above": int(keep.sum()),
            "areas_with_a_cell": len(rows), "rows": rows}  # fmt: skip


def by_area(cache: Path, areas: Sequence[base.Area], *, live: bool,
            log: Callable[[str], None] = lambda _: None) -> list[dict[str, Any]]:  # fmt: skip
    """The notebook's summary for every area that has a boundary file."""
    out = []
    for area in areas:
        boundary = BOUNDARIES.get(area.id)
        run = cache / "framework" / f"{area.id}-r{base._resolution(area.resolution)}"
        if boundary is None or not (run / "hazard.parquet").exists():
            continue
        log(f"{area.id}: depth by {boundary.unit}")
        path = cache / "boundaries" / boundary.file
        held = reference.fetch(boundary.url, path, live=live)
        features = json.loads(path.read_text(encoding="utf-8"))["features"]
        resolution = base._resolution(area.resolution)
        polygons = [
            (
                str(f["properties"][boundary.name_field]),
                reference.cells_of_polygon(f["geometry"], resolution),
            )
            for f in features
        ]
        cells, depths = framework.depths_at(run, RETURN_PERIOD)
        entry = {
            "area": area.id, "title": area.title, "unit": boundary.unit,
            "return_period": RETURN_PERIOD, "threshold_m": THRESHOLD, "h3_resolution": resolution,
            "curve_rows": int(len(cells)),
            "boundary": {"title": boundary.title, "licence": boundary.licence,
                         "features": len(features), **held},
            **summarize(cells, depths, polygons),
        }  # fmt: skip
        if area.id == "efas-rhine":
            entry["notebook"] = NOTEBOOK
        out.append(entry)
    return out


# ------------------------------------------------------------------------------- review maps
FIELDS = (
    ("published", "Published depth, largest pixel in the cell", "m",
     "largest depth the publisher's files hold for a pixel whose centre is in the cell"),
    ("no_curve_share", "Flooded pixels without a curve, share", "%",
     "share of the cell's pixels flooded at this return period that get no curve under "
     "crc-sdk's rules (fewer than four depths, equal depths, a decreasing depth)"),
    ("no_curve_land", "Flooded land without a curve (fewer than four depths), share", "%",
     "share of the cell's pixels flooded at this return period that have a depth at fewer than "
     "four return periods and so get no curve; none of them is permanent water"),
    ("no_curve_water", "Water bodies without a curve (equal or decreasing depths), share", "%",
     "share of the cell's pixels flooded at this return period whose depths are all equal or "
     "decrease, and so get no curve; these lie in the publisher's permanent water"),
    ("not_converged", "Pixels the fit does not converge on", "pixels",
     "pixels that have depths at four or more return periods, not all equal and not decreasing, "
     "for which crc-sdk's output has no curve; the same at every return period"),
    ("dry_curve", "Dry in the published map, curve gives 0.1 m or more", "pixels",
     "pixels with no published depth at this return period whose fitted curve gives 0.1 m or "
     "more there"),
    ("below_zero", "Curve below zero", "pixels",
     "pixels whose fitted curve is below 0 m at this return period"),
    ("misfit", "Largest distance between curve and published depth", "m",
     "largest absolute difference between the fitted curve and the published depth among the "
     "cell's fitted pixels flooded at this return period"),
    ("deep", "Pixels deeper than 10 m", "pixels",
     "pixels whose published depth at this return period is above 10 m"),
    ("deep_in_mask", "Pixels deeper than 10 m inside JRC's spurious-depth mask", "pixels",
     "pixels above 10 m at this return period that lie in the publisher's spurious-depth mask"),
    ("water_share", "Flooded pixels that are permanent water, share", "%",
     "share of the cell's pixels flooded at this return period that lie in the publisher's "
     "permanent-water layer, where the maps hold a patch value"),
)  # fmt: skip
COUNTS = ("wet", "none", "dry_curve", "below_zero", "deep", "deep_in_mask", "few", "flat",
          "unfitted", "water")  # fmt: skip
LARGEST = ("published", "misfit")


class Cells:
    """Per-cell sums over an area's flooded pixels; a pixel belongs to the cell of its centre."""

    def __init__(self, resolution: int, periods: Sequence[int],
                 water: dict[tuple[float, float], np.ndarray] | None = None,
                 fitted: dict[tuple[float, float], np.ndarray] | None = None) -> None:  # fmt: skip
        """``water``: the permanent-water layer per tile, keyed by the tile's west and north edge.
        ``fitted``: per tile, the sorted positions (row * KEY + column) crc-sdk has a curve for."""
        self.resolution = resolution
        self.water, self.fitted = water, fitted
        self.shown = [p for p in MAP_PERIODS if p in periods]
        self.at = [list(periods).index(p) for p in self.shown]
        self.parts: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
        self.masked = False

    def __call__(self, grid: Any, rows: np.ndarray, columns: np.ndarray, values: np.ndarray,
                 held: np.ndarray, good: np.ndarray, location: np.ndarray, scale: np.ndarray,
                 inside: np.ndarray | None) -> None:  # fmt: skip
        from h3.api import basic_int as h3

        longitude = grid.left + (columns + 0.5) * grid.dx
        latitude = grid.top - (rows + 0.5) * grid.dy
        cells = np.fromiter(
            (h3.latlng_to_cell(float(lat), float(lon), self.resolution)
             for lat, lon in zip(latitude, longitude, strict=True)),
            dtype=np.uint64, count=len(rows),
        )  # fmt: skip
        unique, inverse = np.unique(cells, return_inverse=True)
        size = len(unique)
        counts = np.zeros((len(COUNTS), len(self.shown), size))
        largest = np.full((len(LARGEST), len(self.shown), size), -np.inf)
        self.masked = self.masked or inside is not None
        tile = (round(grid.left, 3), round(grid.top, 3))
        knots = held.sum(axis=0)
        few = knots < 4
        flat = ~few & ~good  # equal or decreasing depths
        wet_body = (self.water[tile][rows, columns] if self.water is not None
                    else np.zeros(len(rows), dtype=bool))  # fmt: skip
        unfitted = np.zeros(len(rows), dtype=bool)
        if self.fitted is not None:
            unfitted = good & ~np.isin(rows * base.KEY + columns, self.fitted[tile])
        for j, (period, i) in enumerate(zip(self.shown, self.at, strict=True)):
            wet, depth = held[i], values[i]
            curve = np.full(len(rows), np.nan)
            curve[good] = reference.quantile(location, scale, period)
            deep = wet & (depth > base.DEEP)
            for name, chosen in (
                ("wet", wet), ("none", wet & ~good),
                ("dry_curve", good & ~wet & (curve >= 0.1)), ("below_zero", good & (curve < 0)),
                ("deep", deep),
                ("deep_in_mask", deep & inside if inside is not None else np.zeros_like(wet)),
                ("few", wet & few), ("flat", wet & flat), ("unfitted", unfitted),
                ("water", wet & wet_body),
            ):  # fmt: skip
                counts[COUNTS.index(name), j] = np.bincount(inverse[chosen], minlength=size)
            np.maximum.at(largest[0, j], inverse[wet], depth[wet])
            both = wet & good
            np.maximum.at(largest[1, j], inverse[both], np.abs(curve[both] - depth[both]))
        self.parts.append((unique, np.bincount(inverse, minlength=size), counts, largest))

    def result(self) -> dict[str, Any]:
        if not self.parts:
            return {"cells": np.empty(0, np.uint64), "pixels": np.empty(0), "fields": {}}
        cells, inverse = np.unique(np.concatenate([p[0] for p in self.parts]), return_inverse=True)
        size = len(cells)
        pixels = np.bincount(inverse, weights=np.concatenate([p[1] for p in self.parts]),
                             minlength=size)  # fmt: skip
        counts = np.zeros((len(COUNTS), len(self.shown), size))
        largest = np.full((len(LARGEST), len(self.shown), size), -np.inf)
        joined_counts = np.concatenate([p[2] for p in self.parts], axis=2)
        joined_largest = np.concatenate([p[3] for p in self.parts], axis=2)
        for k in range(len(COUNTS)):
            for j in range(len(self.shown)):
                counts[k, j] = np.bincount(inverse, weights=joined_counts[k, j], minlength=size)
        for k in range(len(LARGEST)):
            for j in range(len(self.shown)):
                np.maximum.at(largest[k, j], inverse, joined_largest[k, j])
        wet = counts[COUNTS.index("wet")]

        def share(name: str) -> np.ndarray:
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(wet > 0, 100.0 * counts[COUNTS.index(name)] / wet, np.nan)

        fields = {
            "published": largest[0], "misfit": largest[1], "no_curve_share": share("none"),
            "no_curve_land": share("few"), "no_curve_water": share("flat"),
            "not_converged": counts[COUNTS.index("unfitted")],
            "water_share": share("water"),
            **{name: counts[COUNTS.index(name)] for name in
               ("dry_curve", "below_zero", "deep", "deep_in_mask")},
        }  # fmt: skip
        if not self.masked:
            del fields["deep_in_mask"]
        if self.water is None:
            del fields["water_share"]
        if self.fitted is None:
            del fields["not_converged"]
        return {"cells": cells, "pixels": pixels, "fields": fields}


def _column(values: np.ndarray, shown: Sequence[int], digits: int) -> list[list[float | None]]:
    """Rows per cell over the explorer's return periods; null where there is no value."""
    out = []
    for cell in range(values.shape[1]):
        row: list[float | None] = []
        for period in MAP_PERIODS[FIRST_SHOWN:]:
            value = values[shown.index(period), cell] if period in shown else math.nan
            row.append(None if not math.isfinite(value) else
                       (int(value) if digits == 0 else round(float(value), digits)))  # fmt: skip
        out.append(row)
    return out


def _layers(copy: reference.Copy, area: base.Area, periods: Sequence[int], tiles: Sequence[str],
            cache: Path, rules: reference.Rules, *, with_runs: bool,
            ) -> tuple[dict[tuple[float, float], np.ndarray] | None,
                       dict[tuple[float, float], np.ndarray] | None]:  # fmt: skip
    """Per tile of the area: the publisher's permanent-water layer (GloFAS), and the positions
    crc-sdk's stored output of the assessment has a curve for (when that output exists)."""
    described = []
    water: dict[tuple[float, float], np.ndarray] = {}
    for tile in tiles:
        with reference.Tiff(copy.file(reference.depth_name(copy.layout, periods[0], tile))) as t:
            described.append({"tile": tile, "window": t.window(area.bounds, rules),
                              "grid": t.describe()})  # fmt: skip
            edge = (round(t.left, 3), round(t.top, 3))
        if copy.layout == "tiled" and not copy.local:  # constructed publishers hold no such layer
            name = f"Permanent_WaterBodies/{tile}_permanent_water.tif"
            with reference.Tiff(copy.file(name)) as w:
                data = w.read()
                water[edge] = (data != 0) if w.nodata is None else (
                    (data != 0) & (data != np.asarray(w.nodata, dtype=data.dtype)))  # fmt: skip
    run = cache / "framework" / f"{area.id}-r{base._resolution(area.resolution)}"
    fitted = None
    if with_runs and (run / "hazard.parquet").exists():
        theirs = base._framework_pixels(run, tiles, base._grids(described))
        pixel = theirs["pixel"][theirs["pixel"] >= 0]
        fitted = {}
        for number, entry in enumerate(described):
            with reference.Tiff(
                copy.file(reference.depth_name(copy.layout, periods[0], entry["tile"]))
            ) as t:
                edge = (round(t.left, 3), round(t.top, 3))
            here = pixel[pixel // (base.KEY * base.KEY) == number]
            fitted[edge] = np.sort(here % (base.KEY * base.KEY))
    return (water if len(water) == len(tiles) else None), fitted


def review_maps(cache: Path, target: Path = MAPS, *, live: bool = False,
                areas: Sequence[base.Area] = base.AREAS,
                log: Callable[[str], None] = print,
                publisher: dict[str, Path] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """One file per area under ``target``; returns what was written (for the report).

    ``publisher`` names local folders that stand for the publisher (offline tests)."""
    rules = reference.Rules()
    written = []
    for area in areas:
        copy = reference.Copy(area.dataset, cache, live=live,
                              folder=(publisher or {}).get(area.dataset))  # fmt: skip
        periods = reference.periods(copy.index(), copy.layout)
        tiles = (reference.tiles_for(json.loads(copy.text("tile_extents.geojson")), area.bounds)
                 if copy.layout == "tiled" else ["continental"])  # fmt: skip
        resolution = REVIEW_RESOLUTION.get(area.id, base._resolution(area.resolution))
        log(f"{area.id}: review map at resolution {resolution}")
        water, fitted = _layers(copy, area, periods, tiles, cache, rules,
                                with_runs=publisher is None)  # fmt: skip
        collector = Cells(resolution, periods, water, fitted)
        read = base._read_reference(copy, area, periods, tiles, {}, rules, base.STRIP_ROWS,
                                    collect=collector)  # fmt: skip
        found = collector.result()
        digits = {"published": 3, "misfit": 3, "no_curve_share": 1, "no_curve_land": 1,
                  "no_curve_water": 1, "water_share": 1}  # fmt: skip
        payload = {
            "hazard": f"jrc-review-{area.id}",
            "horizon": 0,
            "pathway": "historical",
            "release": f"{copy.dataset} {reference.version(copy.text('README.txt'))}",
            "unit": "",
            "value_semantics": "",
            "tail": "upper",
            "probability_semantics": None,
            "h3_resolution": resolution,
            "return_periods": list(MAP_PERIODS),
            "probabilities": [1 - 1 / p for p in MAP_PERIODS],
            "values_from": FIRST_SHOWN,
            "kinds": ["computed by the validation project from the publisher's files"],
            "cells": [f"{int(cell):x}" for cell in found["cells"]],
            "params": [[0, int(count)] for count in found["pixels"]],
            "fields": {
                key: {"title": title, "unit": unit, "semantics": semantics,
                      "values": _column(found["fields"][key], collector.shown,
                                        digits.get(key, 0))}
                for key, title, unit, semantics in FIELDS if key in found["fields"]
            },
            "built_at": compare.now(),
            "bounds": list(area.bounds),
            "pixels_flooded": int(read["ever_wet"]),
            "inputs": copy.provenance(read["files"]),
        }  # fmt: skip
        path = target / f"{area.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
        written.append({"area": area.id, "file": str(path), "cells": len(payload["cells"]),
                        "h3_resolution": resolution, "fields": list(payload["fields"]),
                        "pixels_flooded": payload["pixels_flooded"],
                        "bytes": path.stat().st_size})  # fmt: skip
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", action="store_true", help="write the review maps")
    parser.add_argument("--live", action="store_true", help="download what the cache lacks")
    parser.add_argument("--cache", type=Path, default=Path("data/cache/validation/jrc-flood"))
    args = parser.parse_args()
    if args.maps:
        for entry in review_maps(args.cache, live=args.live):
            print(json.dumps(entry))


if __name__ == "__main__":
    main()
