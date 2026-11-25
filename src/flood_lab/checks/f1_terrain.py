"""F1 terrain: the record and figures of the terrain products (FD1, FD2, FH2; FP7, FP8).

    FLOOD_CACHE=... uv run --with matplotlib python -m flood_lab.checks.f1_terrain

Reads what ``flood_lab.terrain`` built in the cache (``terrain/``, ``build.json``), the sub-grid
build's ``terrain/sfincs_grid/real_grid.json`` if it exists, the city's neighbourhood outlines and
building footprints, and the committed study area. Writes the record
``site/flood/tests/records/f1-terrain.json`` and five PNG figures under ``docs/flood/figures/f1/``.
Offline. matplotlib is not a dependency of the project, so it is supplied on the command line
(requirement FG4). The figures are written without a timestamp, so a second run gives the same
bytes.
"""

from __future__ import annotations

import io
import json
from datetime import date
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from flood_lab import cache, domain, paths, terrain  # noqa: E402
from flood_lab.records import Check, Input, Parameter, Record  # noqa: E402

OUT = paths.FIGURES / "f1"
REL = "docs/flood/figures/f1"
SUBGRID_JSON = "terrain/sfincs_grid/real_grid.json"
#: the storm the terrain must predate: remnants of Ida (requirements D2)
IDA_DAY = date(2021, 9, 1)
# thresholds of the checks
STUDY_KM2 = (9.0, 14.0)  # [P] proposed
MEDIAN_ABS_M = 0.3  # [P] proposed
WITHIN_M = 0.5  # [P] proposed
WITHIN_SHARE = 0.80  # [P] proposed
# figure scales, fixed so that figures of later stages compare [P]
ELEVATION_RANGE_M = (-2.0, 30.0)
RANGE_SCALE_M = (0.0, 5.0)
HISTOGRAM_M = (-3.0, 3.0)
HISTOGRAM_BIN_M = 0.1
WATER_COLOUR = "#60a5fa"
DEEP_COLOUR = "#dc2626"
DPI = 100
#: cells of the 5 m grid recomputed from the 1 m terrain by window reads, and the seed [P]
RECOMPUTE_CELLS = 2000
RECOMPUTE_SEED = 20261125
RECOMPUTE_TOLERANCE_M = 1e-4  # [P]


def _png(figure, name: str) -> str:
    """Write a figure atomically, without the timestamp matplotlib would put in the file."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=DPI, metadata={"Software": None})
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.part")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(path)
    plt.close(figure)
    return f"{REL}/{name}"


def hillshade(z: np.ndarray, azimuth: float = 315.0, altitude: float = 45.0) -> np.ndarray:
    """Lambertian hillshade of a 1 m grid, row 0 north, values 0 to 1."""
    dzdy, dzdx = np.gradient(np.nan_to_num(z, nan=0.0))  # per pixel; rows run south
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(-dzdx, dzdy)
    az, alt = np.radians(360.0 - azimuth + 90.0), np.radians(altitude)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0.0, 1.0)


def _extent(bounds) -> list[float]:
    west, south, east, north = bounds
    return [west, east, south, north]


def _frame(axis, bounds, title: str) -> None:
    west, south, east, north = bounds
    axis.set_xlim(west, east)
    axis.set_ylim(south, north)
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])
    axis.set_title(title, fontsize=9.5, loc="left")
    width = east - west
    bar = 1000.0 if width > 2500 else 100.0
    x1, y1 = east - 0.05 * width, south + 0.05 * (north - south)
    axis.plot([x1 - bar, x1], [y1, y1], color="black", linewidth=3, zorder=12)
    axis.plot([x1 - bar, x1], [y1, y1], color="white", linewidth=1, zorder=13)
    label = f"{bar / 1000:.0f} km" if bar >= 1000 else f"{bar:.0f} m"
    axis.text(x1 - bar / 2, y1 + 0.012 * (north - south), label, ha="center", fontsize=8, zorder=13)


def _outline(axis, geometry, **style) -> None:
    for part in getattr(geometry, "geoms", [geometry]):
        if part.geom_type == "Polygon":
            rings = [part.exterior, *part.interiors]
        elif part.geom_type in ("LineString", "LinearRing"):
            rings = [part]
        else:
            continue
        for ring in rings:
            x, y = np.asarray(ring.coords).T
            axis.plot(x, y, **style)


def _stats(values: np.ndarray) -> dict[str, float]:
    return {
        "min_m": round(float(np.nanmin(values)), 3),
        "mean_m": round(float(np.nanmean(values)), 3),
        "max_m": round(float(np.nanmax(values)), 3),
        "pixels": int(np.isfinite(values).sum()),
    }


def footprint_comparison(z, transform, water, study, outlines_land) -> tuple[dict, np.ndarray]:
    frame = terrain.footprints()
    total = len(frame)
    brooklyn = frame["bin"].astype(str).str[0] == "3"
    unassigned = frame["bin"].astype(str).str[1:] == "000000"
    points = frame.geometry.representative_point()
    in_study = shapely.contains(study, points.to_numpy())
    has_ground = frame["ground_ft"].notna() & (frame["ground_ft"] > 0)
    chosen = frame[brooklyn & ~unassigned & in_study & has_ground].reset_index(drop=True)
    import rasterio.features

    under = rasterio.features.rasterize(
        [(g, 1) for g in frame.geometry.to_numpy()],
        out_shape=z.shape,
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)
    medians, counts = terrain.ring_medians(chosen.geometry.to_numpy(), z, transform, water | under)
    difference = medians - chosen["ground_m"].to_numpy()
    ok = np.isfinite(difference)
    d = difference[ok]
    by_source = {}
    for name in sorted(chosen["geom_source"].fillna("none").unique()):
        mask = ok & (chosen["geom_source"].fillna("none").to_numpy() == name)
        if mask.sum():
            by_source[name] = {
                "compared": int(mask.sum()),
                "median_m": round(float(np.median(difference[mask])), 3),
                "share_within_0.5_m": round(
                    float(np.mean(np.abs(difference[mask]) <= WITHIN_M)), 3
                ),
            }
    result = {
        "footprints_in_file": int(total),
        "brooklyn_bin": int(brooklyn.sum()),
        "brooklyn_in_study_area": int((brooklyn & ~unassigned & in_study).sum()),
        "with_city_ground_above_0": int(len(chosen)),
        "compared": int(ok.sum()),
        "too_few_ring_pixels": int((~ok).sum()),
        "median_ring_pixels": int(np.median(counts)) if len(counts) else 0,
        "median_difference_m": round(float(np.median(d)), 3),
        "mean_difference_m": round(float(np.mean(d)), 3),
        "p05_m": round(float(np.percentile(d, 5)), 3),
        "p95_m": round(float(np.percentile(d, 95)), 3),
        "share_within_0.5_m": round(float(np.mean(np.abs(d) <= WITHIN_M)), 4),
        "beyond_histogram_range": int(np.sum((d < HISTOGRAM_M[0]) | (d > HISTOGRAM_M[1]))),
        "by_geom_source": by_source,
    }
    return result, d


def recompute_5m(dem_1m, mean5, min5, max5, cells: int = RECOMPUTE_CELLS) -> dict[str, Any]:
    """Mean, minimum and maximum of randomly drawn 5 m cells, recomputed from the 1 m file.

    A different route from ``terrain.aggregate`` (which reshapes the whole square in memory): each
    cell's 5 x 5 pixels are read from ``dem_1m.tif`` with a rasterio window read, at the offset of
    the square in the file, and reduced in float64. A cell without value in the grid must have a
    pixel without value in its window.
    """
    import rasterio
    from rasterio.windows import Window

    rng = np.random.default_rng(RECOMPUTE_SEED)
    rows, cols = mean5.shape
    picks = rng.choice(rows * cols, size=min(cells, rows * cols), replace=False)
    worst = 0.0
    wrong: list[list[int]] = []
    with rasterio.open(dem_1m) as src:
        col0 = int(round((domain.SQUARE[0] - src.transform.c) / src.transform.a))
        row0 = int(round((src.transform.f - domain.SQUARE[3]) / -src.transform.e))
        f = terrain.FACTOR
        for pick in picks:
            r, c = divmod(int(pick), cols)
            block = src.read(1, window=Window(col0 + c * f, row0 + r * f, f, f)).astype("float64")
            block[block == src.nodata] = np.nan
            expected = (block.mean(), block.min(), block.max())
            got = (mean5[r, c], min5[r, c], max5[r, c])
            for e, g in zip(expected, got, strict=True):
                if np.isnan(e) or np.isnan(g):
                    ok = bool(np.isnan(e) and np.isnan(g))
                else:
                    worst = max(worst, abs(float(g) - e))
                    ok = abs(float(g) - e) <= RECOMPUTE_TOLERANCE_M
                if not ok:
                    wrong.append([r, c])
                    break
    return {
        "cells": int(len(picks)),
        "seed": RECOMPUTE_SEED,
        "cells_differing": len(wrong),
        "first_differing_row_col": wrong[:5],
        "largest_difference_m": float(f"{worst:.3g}"),
    }


def main() -> None:
    root = cache.root()
    build = json.loads((root / terrain.BUILD_JSON).read_text())
    z, transform = terrain.read_1m(root / terrain.DEM_1M)
    window = terrain.window_of(transform, domain.SQUARE)
    zs = z[window]
    mean5, min5, max5 = terrain.read_5m(root / terrain.DEM_5M)
    outlines = terrain.land_outlines()
    on_land = terrain.land_raster(outlines, transform, z.shape)
    water, water_counts = terrain.water_mask(z, on_land)
    study = terrain.study_area()
    shapely.prepare(study)
    square = shapely.box(*domain.SQUARE)

    # pixel centres of the square inside the study area
    gx, gy = np.meshgrid(
        domain.SQUARE[0] + 0.5 + np.arange(zs.shape[1]),
        domain.SQUARE[3] - 0.5 - np.arange(zs.shape[0]),
    )
    in_study = shapely.contains_xy(study, gx, gy)
    del gx, gy
    water_s = water[window]
    land_s = on_land[window]
    _, square_counts = terrain.water_mask(zs, land_s)

    with np.errstate(invalid="ignore"):  # shapely's oriented envelope warns on its own NaN steps
        patches, labels = terrain.deep_patches(z, transform, on_land, water, outlines, study)
    footprints, differences = footprint_comparison(z, transform, water, study, on_land)
    subgrid_path = root / SUBGRID_JSON
    subgrid = json.loads(subgrid_path.read_text()) if subgrid_path.exists() else None
    if subgrid is not None:
        subgrid.pop("traceback", None)

    # ---- figures ------------------------------------------------------------------------------
    figures = []
    sq = domain.SQUARE
    shade = hillshade(zs)
    lowland = shapely.intersection(terrain.land_union(outlines.geometry.to_numpy()), square)
    shoreline = lowland.boundary

    figure, axis = plt.subplots(figsize=(9, 9.6))
    axis.imshow(shade, cmap="gray", extent=_extent(sq), interpolation="antialiased", vmin=0, vmax=1)
    axis.imshow(
        np.ma.masked_where(~water_s, water_s),
        cmap=ListedColormap([WATER_COLOUR]),
        extent=_extent(sq),
        alpha=0.75,
        interpolation="nearest",
    )
    _outline(axis, study, color="#b91c1c", linewidth=1.6, zorder=10)
    _frame(axis, sq, "Hillshade of the 1 m terrain (USGS 3DEP, lidar 2013-14), the square")
    figure.legend(
        handles=[
            Patch(facecolor=WATER_COLOUR, label="Water by the F1 rule (flattened and off land)"),
            Patch(facecolor="none", edgecolor="#b91c1c", label="Study area: Brooklyn land"),
        ],
        loc="lower center",
        ncol=2,
        fontsize=8.5,
        frameon=False,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figures.append(_png(figure, "hillshade.png"))

    figure, axis = plt.subplots(figsize=(10.4, 8.8))
    image = axis.imshow(
        zs,
        cmap="terrain",
        vmin=ELEVATION_RANGE_M[0],
        vmax=ELEVATION_RANGE_M[1],
        extent=_extent(sq),
        interpolation="antialiased",
    )
    _outline(axis, shoreline, color="black", linewidth=0.7, zorder=10)
    _frame(axis, sq, "Elevation, metres above NAVD88; black line: outline of the land")
    bar = figure.colorbar(image, ax=axis, shrink=0.7, extend="both")
    bar.set_label("m NAVD88 (fixed scale)")
    figure.tight_layout()
    figures.append(_png(figure, "elevation.png"))

    figure, axis = plt.subplots(figsize=(8, 4.6))
    edges = np.arange(HISTOGRAM_M[0], HISTOGRAM_M[1] + HISTOGRAM_BIN_M / 2, HISTOGRAM_BIN_M)
    axis.hist(np.clip(differences, *HISTOGRAM_M), bins=edges, color="#475569")
    axis.axvline(0, color="black", linewidth=0.8)
    axis.axvline(footprints["median_difference_m"], color="#b91c1c", linewidth=1.2)
    for edge in (-WITHIN_M, WITHIN_M):
        axis.axvline(edge, color="#b91c1c", linewidth=0.8, linestyle="--")
    axis.set_xlabel("terrain (ring median) minus city ground elevation, m; ends hold values beyond")
    axis.set_ylabel("footprints")
    axis.set_title(
        f"{footprints['compared']} Brooklyn footprints in the study area: median "
        f"{footprints['median_difference_m']:+.2f} m, "
        f"{100 * footprints['share_within_0.5_m']:.1f}% within 0.5 m",
        fontsize=9.5,
        loc="left",
    )
    figure.tight_layout()
    figures.append(_png(figure, "footprint_difference.png"))

    figure, (left, right) = plt.subplots(1, 2, figsize=(13, 7))
    deep_s = labels[window] > 0
    for axis, view in ((left, sq), (right, None)):
        if view is None:
            inside = [p for p in patches if p["inside_square"]] or patches
            xs = [p["x"] for p in inside]
            ys = [p["y"] for p in inside]
            half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 250
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            view = (cx - half, cy - half, cx + half, cy + half)
        axis.imshow(shade, cmap="gray", extent=_extent(sq), interpolation="antialiased")
        axis.imshow(
            np.ma.masked_where(~water_s, water_s),
            cmap=ListedColormap([WATER_COLOUR]),
            extent=_extent(sq),
            alpha=0.6,
            interpolation="nearest",
        )
        axis.imshow(
            np.ma.masked_where(~deep_s, deep_s),
            cmap=ListedColormap([DEEP_COLOUR]),
            extent=_extent(sq),
            interpolation="nearest",
        )
        _outline(axis, shoreline, color="black", linewidth=0.6, zorder=10)
        _outline(axis, study, color="#b91c1c", linewidth=1.2, linestyle="--", zorder=10)
        if view is not sq:
            for p in patches:
                axis.text(
                    p["x"], p["y"], f"{p['id']}: {p['area_m2']} m², min {p['min_m']:.1f} m",
                    fontsize=8, ha="center", va="center", zorder=14,
                    bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"},
                )  # fmt: skip
        title = (
            f"Patches below {terrain.DEEP_M:.0f} m (red), the square"
            if view is sq
            else "The same, enlarged; dashed: study area"
        )
        _frame(axis, view, title)
    figure.tight_layout()
    figures.append(_png(figure, "deep_patches.png"))

    figure, axis = plt.subplots(figsize=(10.4, 8.8))
    image = axis.imshow(
        max5 - min5,
        cmap="magma_r",
        vmin=RANGE_SCALE_M[0],
        vmax=RANGE_SCALE_M[1],
        extent=_extent(sq),
        interpolation="nearest",
    )
    _outline(axis, shoreline, color="#0f766e", linewidth=0.7, zorder=10)
    _frame(axis, sq, "Sub-grid range: maximum minus minimum of the 25 pixels of each 5 m cell")
    bar = figure.colorbar(image, ax=axis, shrink=0.7, extend="max")
    bar.set_label("m (fixed scale)")
    figure.tight_layout()
    figures.append(_png(figure, "subgrid_range.png"))

    # ---- numbers ------------------------------------------------------------------------------
    begin, end = terrain.flight_dates()
    square_px = zs.size
    land_square = ~water_s
    rng = max5 - min5
    numbers: dict[str, Any] = {
        "terrain_bounds_utm18n_m": build["terrain_bounds"],
        "square_utm18n_m": list(domain.SQUARE),
        "terrain_pixels_1m": int(z.size),
        "square_pixels_1m": int(square_px),
        "grid_cells_5m": int(mean5.size),
        "grid_shape_5m": list(mean5.shape),
        "source_window_col_row_width_height": build["cut"]["window_col_row_width_height"],
        "horizontal_datum": build["horizontal_datum"],
        "flight_dates": [begin.isoformat(), end.isoformat()],
        "elevation_square_all": _stats(zs),
        "elevation_square_not_water": _stats(np.where(land_square, zs, np.nan)),
        "elevation_study_area": _stats(np.where(in_study, zs, np.nan)),
        "pixels_without_value_in_square": int(np.isnan(zs).sum()),
        "water_counts_margin_box": water_counts,
        "water_counts_square": square_counts,
        "water_share_of_square": round(float(water_s.mean()), 4),
        "study_area_km2": round(study.area / 1e6, 4),
        "study_area_share_of_square": round(study.area / square.area, 4),
        "study_area_pixels_1m": int(in_study.sum()),
        "study_area_pixels_water": int((in_study & water_s).sum()),
        "study_area_pixels_below_0_m": int((in_study & (zs < 0)).sum()),
        "deep_patch_threshold_m": terrain.DEEP_M,
        "deep_patches": len(patches),
        "pixels_below_deep_threshold_margin_box": int((labels > 0).sum()),
        "pixels_below_minus_10_m_margin_box": int((z < -10).sum()),
        "subgrid_range_5m": {
            "median_m": round(float(np.median(rng)), 3),
            "p95_m": round(float(np.percentile(rng, 95)), 3),
            "max_m": round(float(np.max(rng)), 3),
            "cells_over_1_m": int((rng > 1.0).sum()),
            "cells_over_2_m": int((rng > 2.0).sum()),
        },
        "footprint_comparison": {k: v for k, v in footprints.items() if k != "by_geom_source"},
        "subgrid_build": subgrid if subgrid is not None else "not built: no real_grid.json",
        "cache_outputs_bytes": build["outputs"],
    }
    tables = {"deep_patches": patches, "footprints_by_geom_source": footprints["by_geom_source"]}

    # ---- checks -------------------------------------------------------------------------------
    finite = np.isfinite(mean5)
    between = bool(np.all((min5[finite] <= mean5[finite]) & (mean5[finite] <= max5[finite])))
    recomputed = recompute_5m(root / terrain.DEM_1M, mean5, min5, max5)
    numbers["recomputed_5m_cells"] = recomputed
    lo, hi = STUDY_KM2
    km2 = study.area / 1e6
    checks = [
        Check(
            "no pixel without a value in the square",
            "count of 1 m pixels of the square without a value is 0",
            int(np.isnan(zs).sum()) == 0,
            int(np.isnan(zs).sum()),
            0,
        ),
        Check(
            "terrain against the city's ground elevation: median",
            "|median(terrain ring median - city ground_elevation in m)| over Brooklyn footprints "
            "in the study area",
            abs(footprints["median_difference_m"]) <= MEDIAN_ABS_M,
            footprints["median_difference_m"],
            MEDIAN_ABS_M,
            proposed=True,
            note="a wrong unit (feet) or datum would show as a median off by metres",
        ),
        Check(
            "terrain against the city's ground elevation: spread",
            "share of compared footprints with |difference| <= 0.5 m",
            footprints["share_within_0.5_m"] >= WITHIN_SHARE,
            footprints["share_within_0.5_m"],
            WITHIN_SHARE,
            proposed=True,
        ),
        Check(
            "the three bands of the 5 m grid are in order",
            "band min <= band mean <= band max in every 5 m cell with a value: true of any mean, "
            "so it catches swapped bands only",
            between,
            between,
            True,
        ),
        Check(
            "5 m grid recomputed from the 1 m terrain",
            f"for {recomputed['cells']} cells drawn with seed {RECOMPUTE_SEED}, the mean, minimum "
            "and maximum of the cell's 5 x 5 pixels, read from dem_1m.tif with a rasterio window "
            "read (not the reshape of flood_lab.terrain), equal the 5 m bands to within "
            f"{RECOMPUTE_TOLERANCE_M:g} m",
            recomputed["cells_differing"] == 0,
            recomputed["cells_differing"],
            0,
            note=f"largest difference {recomputed['largest_difference_m']:g} m",
        ),
        Check(
            "study area size",
            f"{lo} km² <= area of the study area <= {hi} km²",
            lo <= km2 <= hi,
            round(km2, 3),
            [lo, hi],
            proposed=True,
            note="F0 scoring found 78% of the square is Brooklyn or Queens land; this is "
            "Brooklyn only, from the outlines, so it excludes the river and Manhattan",
        ),
        Check(
            "terrain predates Ida",
            "last lidar flight day (facts file usgs-3dep-1m) before 2021-09-01",
            end < IDA_DAY,
            end.isoformat(),
            IDA_DAY.isoformat(),
        ),
    ]

    parameters = [
        Parameter("hydro_flat_level_m", terrain.HYDRO_FLAT_M, "I", "most common tile value"),
        Parameter("water_rule", "flat at the level AND outside all outlines", "P"),
        Parameter("nodata", terrain.NODATA, "P", "not a possible elevation"),
        Parameter("study_area_simplify_m", terrain.SIMPLIFY_M, "P"),
        Parameter("outline_seam_hole_m2", terrain.SEAM_HOLE_M2, "P", "holes filled below this"),
        Parameter("deep_threshold_m", terrain.DEEP_M, "P"),
        Parameter("ring_m", list(terrain.RING_M), "P", "pixels whose centres lie in the ring"),
        Parameter("ring_min_pixels", terrain.RING_MIN_PIXELS, "P"),
        Parameter("ring_excludes", "water pixels and pixels under any footprint", "P"),
        Parameter("feet_to_m", terrain.FEET, "S", "international foot, exact by definition"),
        Parameter("ground_elevation_sampling", "nearest 1 m pixel", "P"),
        Parameter(
            "horizontal_transformation",
            "none: PROJ's operation is null; cut on the source pixel grid, relabelled",
            "I",
            "pyproj computation in flood_lab.terrain.horizontal_datum",
        ),
        Parameter("aggregation_5m", "mean, min, max of 25 pixels", "P"),
        Parameter("recompute_cells", RECOMPUTE_CELLS, "P"),
        Parameter("recompute_seed", RECOMPUTE_SEED, "P"),
        Parameter("recompute_tolerance_m", RECOMPUTE_TOLERANCE_M, "P"),
        Parameter("ida_day", IDA_DAY.isoformat(), "S", "requirements D2"),
        Parameter("study_area_km2_range", list(STUDY_KM2), "P", "proposed"),
        Parameter("median_abs_m", MEDIAN_ABS_M, "P", "proposed"),
        Parameter("within_m", WITHIN_M, "P", "proposed"),
        Parameter("within_share", WITHIN_SHARE, "P", "proposed"),
        Parameter("elevation_colour_range_m", list(ELEVATION_RANGE_M), "P"),
        Parameter("subgrid_range_colour_m", list(RANGE_SCALE_M), "P"),
        Parameter("histogram_range_m", list(HISTOGRAM_M), "P"),
    ]
    if subgrid is not None:
        for key, value in subgrid.get("parameters", {}).items():
            if key != "tags":
                parameters.append(Parameter(f"subgrid.{key}", value, "P"))

    datum = build["horizontal_datum"]
    frame = datum["frame_difference_nad83_2011_to_wgs84_g1762"]
    fp = footprints
    notes = [
        "Bare-earth terrain from lidar flown 2013-08-06 to 2014-04-21 (USGS 3DEP 1 m, project "
        "NY_CMPG_2013): buildings, grading and shoreline changes since then are absent, and the "
        "river is a flat surface at -1.62 m, not a depth. Every threshold and colour scale is a "
        "placeholder [P]. Figures: hillshade.png, elevation.png, footprint_difference.png, "
        "deep_patches.png, subgrid_range.png; the limit of each is in the notes below.",
        "hillshade.png: shading exaggerates nothing but hides absolute height; water is the F1 "
        "rule, not a mapped shoreline; the study area outline comes from census-based "
        "neighbourhood outlines simplified to 1 m.",
        "elevation.png: the colour scale is fixed at -2 to 30 m, so the river (flat -1.62 m) and "
        "the deep patches (below -5 m) share the bottom colour; the black line is the outline of "
        "the land in the city's neighbourhood areas, not a surveyed shoreline.",
        f"footprint_difference.png: {fp['compared']} footprints; the city's ground elevation is "
        "a lowest-adjacent-grade value in feet whose accuracy varies by source and is not "
        "independent of lidar for every footprint; the terrain side is the median of 1 m pixels "
        f"{terrain.RING_M[0]:.0f} to {terrain.RING_M[1]:.0f} m outside the footprint, leaving "
        "out water and other footprints; values beyond +-3 m are drawn in the end bins "
        f"({fp['beyond_histogram_range']} of them). It tests units and vertical datum; a "
        "horizontal offset of about 1 m would barely show in it.",
        "deep_patches.png: patches are 8-connected pixels below -5 m; what they are is read "
        "from shape and position, not from a map of the place (see the notes on the patches).",
        "subgrid_range.png: maximum minus minimum of the 25 pixels of 1 m in each 5 m cell, on "
        "bare earth; walls and buildings are not in the terrain, so the relief a cell hides in "
        "the city is larger than shown. Scale fixed at 0 to 5 m.",
        f"Horizontal datum: PROJ {datum['proj_version']} (network off) uses "
        f"'{datum['operation_used']}' between EPSG:26918 and EPSG:32618, a null operation "
        f"(largest shift at the corners and centre {datum['max_shift_at_corners_and_centre_m']:.2e}"
        " m); the more accurate operations need grids that are not installed. The terrain is "
        "therefore cut on its own pixel grid and relabelled, not resampled. Its position carries "
        f"the NAD83-to-WGS84 difference: {frame.get('shift_m')} m here "
        f"({frame.get('shift_east_m')} m east, {frame.get('shift_north_m')} m north from NAD83 to "
        f"WGS 84 (G1762) at epoch {frame.get('epoch')}, by '{frame.get('operation', '')[:80]}...', "
        f"accuracy {frame.get('accuracy_m')} m), so a point labelled (x, y) on the terrain lies "
        "about that far from the WGS84 position of the same name. The tile's NAD83 is assumed to "
        "be NAD83(2011).",
    ]
    for p in patches:
        notes.append(
            f"Deep patch {p['id']}: {p['area_m2']} m², minimum {p['min_m']} m, median "
            f"{p['median_m']} m, at {p['lat']:.5f} N {abs(p['lon']):.5f} W, near "
            f"'{p['neighbourhood']}' ({p['borough']}); {100 * p['share_on_land']:.0f}% of its "
            f"pixels inside the land outlines, {100 * p['share_in_study_area']:.0f}% in the study "
            f"area; fits a rectangle {p['rectangle_length_m']} m by {p['rectangle_width_m']} m "
            f"filled to {100 * p['fill_of_rectangle']:.0f}%; "
            f"{100 * p['share_within_0.5_m_of_10th_percentile']:.0f}% of its pixels lie within "
            f"0.5 m of its 10th percentile (a flat floor); {100 * p['border_share_water']:.0f}% of "
            f"the pixels touching it are flattened water; their median is "
            f"{p['border_median_m']} m."
        )
    places = sorted({p["neighbourhood"] for p in patches})
    sealed = all(p["border_share_water"] == 0 for p in patches)
    if patches and places == ["Brooklyn Navy Yard"] and sealed:
        notes.append(
            "Deep patches, reading. Evidence: every patch lies in or beside the outline named "
            "Brooklyn Navy Yard, is a near-rectangle (fill of its rectangle above), mostly with "
            "a flat floor, and no flattened-water pixel touches it, so a rim of terrain closes it "
            "off from the flattened river. The two large ones lie in slips that the city's "
            "outlines leave out of the land. Guess, "
            "not checked against a map or record of the yard: they are the yard's dry docks, "
            "drained when the lidar was flown; the two of about 330 m by 50 m look like the two "
            "largest docks, the small one on land like an older, smaller dock. For the flood "
            "model they are pits 7 to 13 m deep: the parts inside the study area (see "
            "share_in_study_area) would hold water that in reality may be held out by a gate, or "
            "be already filled; F3 decides how to treat them."
        )
    if subgrid is not None and not subgrid.get("ok", False):
        notes.append(f"Sub-grid build failed: {subgrid.get('error')}")
    elif subgrid is not None:
        cmp = subgrid.get("compare_with_dem_5m", {})
        low = cmp.get("z_zmin_minus_dem5m_min", {})
        notes.append(
            f"Sub-grid tables (HydroMT-SFINCS {subgrid['builder'].get('hydromt-sfincs')}): "
            f"{subgrid.get('active_cells')} active cells of {subgrid.get('cells')}, "
            f"{subgrid.get('total_bytes', 0) / 1e6:.0f} MB, {subgrid.get('seconds')} s with "
            f"{subgrid.get('steps_s', {}).get('subgrid_s')} s for the tables, peak memory "
            f"{subgrid.get('peak_memory_bytes', 0) / 2**30:.2f} GiB. Grid only: no forcing, no "
            "boundary, no run; roughness uniform [P]. The tables' cell minimum is not the minimum "
            "of the 25 pixels of 1 m: "
            f"{100 * low.get('share_within_0.01_m', 0):.0f}% of cells agree within 0.01 m and "
            f"{100 * low.get('share_within_0.1_m', 0):.1f}% within 0.1 m (percentiles 0, 1, 50, "
            f"99, 100 of the difference: {_pick(low)}); HydroMT samples the terrain at 0.5 m, and "
            "how it interpolates was not read from its code."
        )

    record = Record(
        id="f1-terrain",
        stage="F1",
        title="Terrain: 1 m lidar, 5 m grid, water, deep patches and a check on datum and units",
        inputs=[
            Input.of(root / terrain.SOURCE_TILE, root=root),
            Input.of(root / terrain.DEM_1M, root=root),
            Input.of(root / terrain.DEM_5M, root=root),
            Input.of(root / terrain.OUTLINES, root=root),
            Input.of(root / terrain.FOOTPRINTS, root=root),
            Input.of(terrain.STUDY_AREA, root=paths.ROOT),
        ],
        parameters=parameters,
        numbers=numbers,
        tables=tables,
        checks=checks,
        figures=figures,
        notes=notes,
    )
    record.software = record.software | {
        "rasterio": _version("rasterio"),
        "pyproj": _version("pyproj"),
        "shapely": _version("shapely"),
        "geopandas": _version("geopandas"),
        "matplotlib": _version("matplotlib"),
        "numpy": _version("numpy"),
    }
    record.write(paths.RECORDS)
    summary = {
        "passed": record.passed,
        "checks": [(c.name, c.passed, c.value) for c in checks],
        "footprints": {k: v for k, v in footprints.items() if k != "by_geom_source"},
        "patches": patches,
    }
    print(json.dumps(summary, indent=1, default=str))


def _pick(summary: dict) -> str:
    values = summary.get("percentiles_0_1_5_50_95_99_100_m")
    if not values:
        return "not computed"
    return ", ".join(f"{values[i]:+.2f}" for i in (0, 1, 3, 5, 6)) + " m"


def _version(name: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


if __name__ == "__main__":
    main()
