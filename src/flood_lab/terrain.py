"""F1 terrain: the study area, the 1 m terrain, the water mask and the 5 m grid (FD1, FD2, FH2).

    FLOOD_CACHE=... uv run python -m flood_lab.terrain

builds, from the cache (``flood_lab.cache.root()``), offline:

* ``site/flood/data/study_area.geojson`` (committed): the land of ``domain.BOROUGH`` inside
  ``domain.SQUARE``, from the city's neighbourhood outlines, simplified to 1 m, in WGS84;
* ``terrain/dem_1m.tif``: the USGS 3DEP 1 m tile cut to the square plus ``domain.TERRAIN_MARGIN_M``,
  in the project CRS, float32, nodata ``NODATA``;
* ``terrain/dem_5m.tif``: the project grid, three bands: mean, minimum and maximum of the 25
  pixels of 1 m in each 5 m cell;
* ``terrain/water_1m.tif``: the water mask (1 water, 0 not), by the rule of ``water_mask``;
* ``terrain/build.json``: what was done, with the horizontal-datum finding.

Horizontal datum. The tile is in EPSG:26918 (NAD83 / UTM 18N), the project in EPSG:32618 (WGS 84
/ UTM 18N). The operation PROJ picks between the two in this installation is "NAD83 to WGS 84
(1)", a null operation (``proj=noop``, stated accuracy 4 m): coordinates are unchanged. The tile
is therefore cut on its own pixel grid and relabelled, never resampled, and ``build`` refuses if
PROJ ever picks an operation that moves the corners. The terrain then carries the NAD83-to-WGS84
frame difference as a horizontal offset; ``horizontal_datum`` states its size here from the most
accurate operation available (NAD83(2011) to WGS 84 (G1762) through ITRF2008, at the flight
epoch), about a metre: one pixel of the 1 m terrain, a fifth of a 5 m cell.

Nothing here needs matplotlib or the solver's builder; ``checks/f1_terrain.py`` draws and judges.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyproj
import rasterio
import rasterio.features
import shapely
from rasterio.transform import Affine
from rasterio.windows import Window
from scipy import ndimage

from lab_common.io import write_json_atomic, write_text_atomic

from . import cache, domain, paths
from . import facts as facts_module

# --- inputs, relative to the cache root -------------------------------------------------------
SOURCE_TILE = "f1/terrain/usgs-1m/USGS_one_meter_x58y451_NY_CMPG_2013.tif"
OUTLINES = "nyc-nta-2020/nta2020.geojson"
FOOTPRINTS = "nyc-building-footprints/footprints-box.geojson"
SOURCE_CRS = "EPSG:26918"
FACTS_ID = "usgs-3dep-1m"

# --- outputs ------------------------------------------------------------------------------------
STUDY_AREA = paths.SITE / "data" / "study_area.geojson"
TERRAIN_DIR = "terrain"
DEM_1M = "terrain/dem_1m.tif"
DEM_5M = "terrain/dem_5m.tif"
WATER_1M = "terrain/water_1m.tif"
BUILD_JSON = "terrain/build.json"

# --- parameters -----------------------------------------------------------------------------------
#: written where a pixel has no value; far below any elevation on Earth
NODATA = -9999.0
#: the one constant value of the hydro-flattened water surface [I]: the most common value of the
#: tile, read in F1 (facts file usgs-3dep-1m, fact water_treatment); stored as float32
HYDRO_FLAT_M = -1.62
#: the study area outline is simplified to this tolerance in the project CRS, metres [P]
SIMPLIFY_M = 1.0
#: holes smaller than this in the union of outlines are seams between neighbours, filled [P]
SEAM_HOLE_M2 = 1000.0
#: pixels below this level are mapped as deep patches, metres NAVD88 [P]
DEEP_M = -5.0
#: footprint check: ring of 1 m pixels between these distances outside a footprint, metres [P]
RING_M = (1.0, 3.0)
#: footprint check: fewest ring pixels for a comparison [P]
RING_MIN_PIXELS = 5
FEET = 0.3048  # metres per international foot [S] (exact by definition)
#: 5 m cell of 1 m pixels
FACTOR = int(round(domain.CELL_M))


def cache_path(relative: str) -> Path:
    return cache.root() / relative


def terrain_bounds() -> tuple[float, float, float, float]:
    """The square plus the margin: west, south, east, north, metres in the project CRS."""
    west, south, east, north = domain.SQUARE
    m = domain.TERRAIN_MARGIN_M
    return (west - m, south - m, east + m, north + m)


# --- study area -----------------------------------------------------------------------------------


def land_outlines(path: Path | None = None):
    """Neighbourhood outlines of every borough, in the project CRS (a GeoDataFrame)."""
    import geopandas as gpd

    frame = gpd.read_file(path or cache_path(OUTLINES))
    return frame[["boroname", "ntaname", "ntatype", "geometry"]].to_crs(domain.CRS)


def land_union(geometries, max_hole_m2: float = SEAM_HOLE_M2):
    """Union of outlines without the seams between neighbours.

    Adjacent outlines do not meet exactly, so their union keeps thin holes along shared edges;
    holes smaller than ``max_hole_m2`` are filled.
    """
    union = shapely.union_all([g for g in geometries if g is not None and not g.is_empty])
    parts = []
    for part in getattr(union, "geoms", [union]):
        if part.geom_type != "Polygon":
            continue
        keep = [ring for ring in part.interiors if shapely.Polygon(ring).area >= max_hole_m2]
        parts.append(shapely.Polygon(part.exterior, keep))
    return shapely.union_all(parts)


def study_area_polygon(
    outlines,
    square: tuple[float, float, float, float] = domain.SQUARE,
    borough: str = domain.BOROUGH,
    simplify_m: float = SIMPLIFY_M,
):
    """The land of one borough inside the square, in the outlines' CRS, simplified."""
    mine = outlines[outlines["boroname"] == borough]
    if mine.empty:
        raise ValueError(f"no outline has boroname {borough!r}")
    land = land_union(mine.geometry.to_numpy())
    area = shapely.intersection(land, shapely.box(*square))
    area = shapely.simplify(area, simplify_m, preserve_topology=True)
    if area.is_empty:
        raise ValueError(f"{borough} has no land inside the square")
    return shapely.make_valid(area)


def _to_wgs84() -> pyproj.Transformer:
    return pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True)


def write_study_area(polygon, path: Path = STUDY_AREA) -> None:
    """GeoJSON in WGS84 (longitude, latitude to 7 decimals, about 1 cm), byte-stable."""
    geometry = shapely.transform(polygon, lambda xy: np.column_stack(_to_wgs84().transform(*xy.T)))
    shape = json.loads(shapely.to_geojson(geometry, indent=None))

    def rounded(value):
        if isinstance(value, list):
            return [rounded(v) for v in value]
        return round(value, 7) if isinstance(value, float) else value

    shape["coordinates"] = rounded(shape["coordinates"])
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": f"Study area: {domain.BOROUGH} land inside the square",
                    "source": "NYC 2020 Neighborhood Tabulation Areas (nyc-nta-2020)",
                    "square_utm18n_m": list(domain.SQUARE),
                    "simplified_m": SIMPLIFY_M,
                    "area_km2_utm18n": round(polygon.area / 1e6, 4),
                },
                "geometry": shape,
            }
        ],
    }
    write_text_atomic(path, json.dumps(document, separators=(",", ":")) + "\n")


def study_area(path: Path = STUDY_AREA):
    """The committed study area polygon, in the project CRS."""
    document = json.loads(path.read_text(encoding="utf-8"))
    geometry = shapely.from_geojson(json.dumps(document["features"][0]["geometry"]))
    back = pyproj.Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True)
    return shapely.transform(geometry, lambda xy: np.column_stack(back.transform(*xy.T)))


# --- horizontal datum -----------------------------------------------------------------------------


def flight_dates() -> tuple[date, date]:
    """First and last lidar flight day, from the facts file (fact ``lidar_flight_dates``)."""
    source = facts_module.load(paths.FACTS / f"{FACTS_ID}.toml")
    fact = source.fact("lidar_flight_dates")
    if fact is None:
        raise ValueError(f"facts file {FACTS_ID} has no fact lidar_flight_dates")
    begin = re.search(r"<begdate>(\d{8})</begdate>", fact.passage)
    end = re.search(r"<enddate>(\d{8})</enddate>", fact.passage)
    if not (begin and end):
        raise ValueError("lidar_flight_dates: no <begdate>/<enddate> in the passage")

    def day(text: str) -> date:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))

    return day(begin.group(1)), day(end.group(1))


def _decimal_year(day: date) -> float:
    start = date(day.year, 1, 1)
    length = (date(day.year + 1, 1, 1) - start).days
    return day.year + (day - start).days / length


def horizontal_datum(bounds: tuple[float, float, float, float] | None = None) -> dict[str, Any]:
    """What PROJ does between the tile's CRS and the project's, and the frame difference here."""
    west, south, east, north = bounds or terrain_bounds()
    used = pyproj.Transformer.from_crs(SOURCE_CRS, domain.CRS, always_xy=True)
    xs = np.array([west, east, east, west, (west + east) / 2])
    ys = np.array([south, south, north, north, (south + north) / 2])
    tx, ty = used.transform(xs, ys)
    shift = float(np.max(np.hypot(tx - xs, ty - ys)))
    group = pyproj.transformer.TransformerGroup(SOURCE_CRS, domain.CRS, always_xy=True)
    begin, end = flight_dates()
    epoch = round((_decimal_year(begin) + _decimal_year(end)) / 2, 3)
    lon, lat = pyproj.Transformer.from_crs(SOURCE_CRS, "EPSG:4269", always_xy=True).transform(
        xs[-1], ys[-1]
    )
    # NAD83(2011) -> WGS 84 (G1762): the best operation PROJ has without grids
    frames = pyproj.transformer.TransformerGroup("EPSG:6318", "EPSG:9057", always_xy=True)
    best = min(
        (t for t in frames.transformers if t.accuracy >= 0), key=lambda t: t.accuracy, default=None
    )
    frame: dict[str, Any] = {"available": best is not None}
    if best is not None:
        lon2, lat2, *_ = best.transform(lon, lat, 0.0, epoch)
        azimuth, _, distance = pyproj.Geod(ellps="WGS84").inv(lon, lat, lon2, lat2)
        frame |= {
            "operation": best.description,
            "accuracy_m": best.accuracy,
            "epoch": epoch,
            "at_lonlat_nad83": [round(lon, 6), round(lat, 6)],
            "shift_m": round(distance, 3),
            "shift_east_m": round(distance * math.sin(math.radians(azimuth)), 3),
            "shift_north_m": round(distance * math.cos(math.radians(azimuth)), 3),
        }
    return {
        "source_crs": SOURCE_CRS,
        "project_crs": domain.CRS,
        "proj_version": pyproj.proj_version_str,
        "pyproj_version": pyproj.__version__,
        "network_enabled": bool(pyproj.network.is_network_enabled()),
        "operation_used": used.description,
        "operation_used_definition": used.definition,
        "operation_used_accuracy_m": used.accuracy,
        "max_shift_at_corners_and_centre_m": shift,
        "null_operation": shift < 1e-3,
        "operations_unavailable_here": len(group.unavailable_operations),
        "best_unavailable_accuracy_m": min(
            (o.accuracy for o in group.unavailable_operations if o.accuracy >= 0), default=None
        ),
        "flight_dates": [begin.isoformat(), end.isoformat()],
        "frame_difference_nad83_2011_to_wgs84_g1762": frame,
        "assumption": "the tile's NAD83 is taken as the NAD83(2011) realisation for the size of "
        "the frame difference; the tile metadata says only 'NAD83'",
        "choice": "the PROJ operation is a null operation, so the tile is cut on its own pixel "
        "grid and relabelled EPSG:32618, with no resampling; the terrain's horizontal position "
        "carries the NAD83-to-WGS84 frame difference stated above",
    }


# --- the 1 m terrain ----------------------------------------------------------------------------


def _profile(width: int, height: int, transform: Affine, count: int = 1, dtype="float32"):
    return {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": count,
        "dtype": dtype,
        "crs": domain.CRS,
        "transform": transform,
        "nodata": NODATA if dtype == "float32" else None,
        "compress": "deflate",
        "predictor": 3 if dtype == "float32" else 2,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }


def _write_raster(path: Path, bands: list[np.ndarray], profile: dict, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".part.tif")
    with rasterio.open(temporary, "w", **profile) as dst:
        for index, (band, name) in enumerate(zip(bands, names, strict=True), start=1):
            dst.write(band, index)
            dst.set_band_description(index, name)
    temporary.replace(path)


def cut_window(transform: Affine, bounds: tuple[float, float, float, float]) -> Window:
    """The source window of the bounds; refuses unless it falls on whole pixels of 1 m."""
    if abs(transform.a - 1.0) > 1e-9 or abs(transform.e + 1.0) > 1e-9 or transform.b or transform.d:
        raise ValueError(f"source pixels are not 1 m north-up: {transform}")
    west, south, east, north = bounds
    col = (west - transform.c) / transform.a
    row = (transform.f - north) / -transform.e
    if abs(col - round(col)) > 1e-6 or abs(row - round(row)) > 1e-6:
        raise ValueError(f"bounds do not fall on source pixel edges (col {col}, row {row})")
    return Window(round(col), round(row), round(east - west), round(north - south))


def cut_terrain(source: Path, out: Path, bounds: tuple[float, float, float, float]) -> dict:
    """Cut the tile to the bounds on its own pixel grid, relabel it in the project CRS."""
    with rasterio.open(source) as src:
        if src.crs.to_epsg() != int(SOURCE_CRS.split(":")[1]):
            raise ValueError(f"source CRS is {src.crs}, expected {SOURCE_CRS}")
        window = cut_window(src.transform, bounds)
        if (
            window.col_off < 0
            or window.row_off < 0
            or window.col_off + window.width > src.width
            or window.row_off + window.height > src.height
        ):
            raise ValueError("the bounds reach beyond the tile")
        z = src.read(1, window=window)
        missing = (z == src.nodata) | ~np.isfinite(z) if src.nodata is not None else ~np.isfinite(z)
    z = np.where(missing, np.float32(NODATA), z).astype("float32")
    west, _, _, north = bounds
    profile = _profile(z.shape[1], z.shape[0], Affine(1.0, 0.0, west, 0.0, -1.0, north))
    _write_raster(out, [z], profile, ["elevation_m_navd88"])
    return {
        "window_col_row_width_height": [
            int(window.col_off),
            int(window.row_off),
            int(window.width),
            int(window.height),
        ],
        "pixels_without_value": int(missing.sum()),
    }


def read_1m(path: Path | None = None) -> tuple[np.ndarray, Affine]:
    """The 1 m terrain as float32 with NaN where it has no value, and its transform."""
    with rasterio.open(path or cache_path(DEM_1M)) as src:
        z = src.read(1).astype("float32")
        z[z == src.nodata] = np.nan
        return z, src.transform


def window_of(transform: Affine, bounds: tuple[float, float, float, float]) -> tuple[slice, slice]:
    """Row and column slices of bounds on a north-up 1 m grid whose edges they fall on."""
    west, south, east, north = bounds
    col0 = int(round((west - transform.c) / transform.a))
    row0 = int(round((transform.f - north) / -transform.e))
    return (
        slice(row0, row0 + int(round(north - south))),
        slice(col0, col0 + int(round(east - west))),
    )


# --- 5 m grid -----------------------------------------------------------------------------------


def aggregate(z: np.ndarray, factor: int = FACTOR) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean, minimum and maximum of each ``factor`` x ``factor`` block; NaN if a pixel is NaN.

    Row 0 of the result is the northern row of blocks when row 0 of ``z`` is the northern row.
    """
    rows, cols = z.shape
    if rows % factor or cols % factor:
        raise ValueError(f"shape {z.shape} is not a multiple of {factor}")
    blocks = z.reshape(rows // factor, factor, cols // factor, factor).astype("float64")
    mean = blocks.mean(axis=(1, 3))
    low = blocks.min(axis=(1, 3))
    high = blocks.max(axis=(1, 3))
    return mean.astype("float32"), low.astype("float32"), high.astype("float32")


def write_5m(z_square: np.ndarray, out: Path) -> None:
    mean, low, high = aggregate(z_square)
    grid = domain.GRID
    if mean.shape != (grid.height, grid.width):
        raise ValueError(f"5 m grid shape {mean.shape}, expected {(grid.height, grid.width)}")
    bands = [
        np.where(np.isnan(b), np.float32(NODATA), b).astype("float32") for b in (mean, low, high)
    ]
    profile = _profile(grid.width, grid.height, Affine(*grid.transform), count=3)
    _write_raster(out, bands, profile, ["mean_m", "min_m", "max_m"])


def read_5m(path: Path | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with rasterio.open(path or cache_path(DEM_5M)) as src:
        bands = src.read().astype("float32")
        bands[bands == src.nodata] = np.nan
    return bands[0], bands[1], bands[2]


# --- water --------------------------------------------------------------------------------------


def land_raster(outlines, transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """True where a pixel centre lies inside the union of the outlines, seams filled."""
    land = land_union(outlines.geometry.to_numpy())
    return rasterio.features.rasterize(
        [(land, 1)], out_shape=shape, transform=transform, fill=0, dtype="uint8"
    ).astype(bool)


def water_mask(
    z: np.ndarray, on_land: np.ndarray, flat_level: float = HYDRO_FLAT_M
) -> tuple[np.ndarray, dict[str, int]]:
    """Water: the pixel holds exactly the hydro-flattened level AND lies outside every outline.

    Neither test alone is used: the flat value also occurs inside the outlines (basins and slips
    the outlines count as land), and outside the outlines there is terrain that is not flattened
    (piers, dry docks, shore). The counts say what each test catches.
    """
    flat = z == np.float32(flat_level)
    near = np.isclose(z, np.float32(flat_level), rtol=0.0, atol=0.005) & ~flat
    off = ~on_land
    water = flat & off
    counts = {
        "pixels": int(z.size),
        "flat_at_level": int(flat.sum()),
        "within_5_mm_of_level_not_equal": int(near.sum()),
        "outside_outlines": int(off.sum()),
        "water_both_tests": int(water.sum()),
        "flat_inside_outlines_not_water": int((flat & on_land).sum()),
        "outside_outlines_not_flat_not_water": int((off & ~flat).sum()),
    }
    return water, counts


# --- point sampling -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Terrain:
    """The 1 m terrain in memory, for sampling."""

    z: np.ndarray  # float32, NaN without value, row 0 north
    transform: Affine

    @classmethod
    def open(cls, path: Path | None = None) -> Terrain:
        return cls(*read_1m(path))

    def sample(self, x, y) -> np.ndarray:
        """Nearest-pixel value: the 1 m pixel that contains each point, metres NAVD88.

        A point on a pixel edge belongs to the pixel east and south of the edge (``floor``). Raises
        on a point outside the terrain (the east and south outer edges are outside) or on a pixel
        without value.
        """
        x = np.asarray(x, dtype="float64")
        y = np.asarray(y, dtype="float64")
        col = np.floor((x - self.transform.c) / self.transform.a)
        row = np.floor((y - self.transform.f) / self.transform.e)
        rows, cols = self.z.shape
        outside = ~((col >= 0) & (col < cols) & (row >= 0) & (row < rows))
        if np.any(outside):
            first = int(np.flatnonzero(outside.ravel())[0])
            raise ValueError(
                f"{int(outside.sum())} point(s) outside the terrain, first "
                f"({x.ravel()[first]}, {y.ravel()[first]})"
            )
        values = self.z[row.astype(int), col.astype(int)]
        if np.any(np.isnan(values)):
            raise ValueError(f"{int(np.isnan(values).sum())} point(s) on pixels without value")
        return values


_TERRAIN: dict[Path, Terrain] = {}


def ground_elevation(x, y, path: Path | None = None) -> np.ndarray:
    """Ground elevation in metres NAVD88 at points in the project CRS (nearest 1 m pixel).

    Vectorised; raises on points outside the terrain. Reads ``terrain/dem_1m.tif`` once.
    """
    path = Path(path or cache_path(DEM_1M))
    if path not in _TERRAIN:
        _TERRAIN[path] = Terrain.open(path)
    return _TERRAIN[path].sample(x, y)


# --- deep patches -------------------------------------------------------------------------------


def deep_patches(
    z: np.ndarray,
    transform: Affine,
    on_land: np.ndarray,
    water: np.ndarray,
    outlines,
    study,
    threshold: float = DEEP_M,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    """Every 8-connected patch of pixels below ``threshold``, with what is known of where it is."""
    deep = z < threshold
    labels, count = ndimage.label(deep, structure=np.ones((3, 3), dtype=bool))
    to_lonlat = _to_wgs84()
    shore = land_union(outlines.geometry.to_numpy()).boundary
    names = list(outlines.itertuples(index=False))
    shapely.prepare(study)
    square = shapely.box(*domain.SQUARE)
    rows_out = []
    for index, where in enumerate(ndimage.find_objects(labels), start=1):
        inside = labels[where] == index
        values = z[where][inside]
        rr, cc = np.nonzero(inside)
        xs = transform.c + (cc + where[1].start + 0.5) * transform.a
        ys = transform.f + (rr + where[0].start + 0.5) * transform.e
        cx, cy = float(xs.mean()), float(ys.mean())
        points = shapely.points(xs, ys)
        hull = shapely.convex_hull(shapely.multipoints(np.column_stack([xs, ys])))
        rect = shapely.minimum_rotated_rectangle(hull.buffer(0.5))
        edges = np.diff(np.asarray(rect.exterior.coords)[:3], axis=0)
        sides = sorted(float(np.hypot(*e)) for e in edges)
        # the pixels touching the patch: a one-pixel border around its bounding box
        pad = (
            slice(max(where[0].start - 1, 0), min(where[0].stop + 1, z.shape[0])),
            slice(max(where[1].start - 1, 0), min(where[1].stop + 1, z.shape[1])),
        )
        own = labels[pad] == index
        border = ndimage.binary_dilation(own, structure=np.ones((3, 3), dtype=bool)) & ~own
        centre = shapely.Point(cx, cy)
        containing = [n for n in names if n.geometry.contains(centre)]
        if containing:
            place, borough, distance_outline = containing[0].ntaname, containing[0].boroname, 0.0
        else:
            nearest = min(names, key=lambda n: n.geometry.distance(centre))
            place, borough = nearest.ntaname, nearest.boroname
            distance_outline = float(nearest.geometry.distance(centre))
        lon, lat = to_lonlat.transform(cx, cy)
        floor = float(np.percentile(values, 10))
        rows_out.append(
            {
                "id": index,
                "area_m2": int(inside.sum()),
                "min_m": round(float(values.min()), 2),
                "median_m": round(float(np.median(values)), 2),
                "share_within_0.5_m_of_10th_percentile": round(
                    float(np.mean(values <= floor + 0.5)), 3
                ),
                "x": round(cx, 1),
                "y": round(cy, 1),
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "neighbourhood": place,
                "borough": borough,
                "centre_distance_to_nearest_outline_m": round(distance_outline, 1),
                "centre_distance_to_shoreline_m": round(float(shore.distance(centre)), 1),
                "share_on_land": round(float(on_land[where][inside].mean()), 3),
                "share_in_study_area": round(float(np.mean(shapely.contains(study, points))), 3),
                "inside_square": bool(square.contains(centre)),
                "rectangle_length_m": round(sides[1], 1),
                "rectangle_width_m": round(sides[0], 1),
                "fill_of_rectangle": round(inside.sum() / max(rect.area, 1.0), 3),
                "border_pixels": int(border.sum()),
                "border_share_water": round(float(water[pad][border].mean()), 3),
                "border_median_m": round(float(np.nanmedian(z[pad][border])), 2),
            }
        )
    return rows_out, labels


# --- footprints -----------------------------------------------------------------------------------


def footprints(path: Path | None = None):
    """The city's footprints in the project CRS, with ground elevation in metres."""
    import geopandas as gpd
    import pandas as pd

    frame = gpd.read_file(path or cache_path(FOOTPRINTS))
    frame = frame[["bin", "ground_elevation", "geom_source", "feature_code", "geometry"]].copy()
    frame["ground_ft"] = pd.to_numeric(frame["ground_elevation"], errors="coerce")
    frame["ground_m"] = frame["ground_ft"] * FEET
    return frame.set_crs("EPSG:4326", allow_override=True).to_crs(domain.CRS)


def ring_medians(
    geometries,
    z: np.ndarray,
    transform: Affine,
    exclude: np.ndarray,
    ring: tuple[float, float] = RING_M,
    min_pixels: int = RING_MIN_PIXELS,
) -> tuple[np.ndarray, np.ndarray]:
    """Median of the 1 m pixels whose centres lie between ``ring`` metres outside each footprint.

    Pixels where ``exclude`` is True (water, other footprints) are left out. Returns the medians
    (NaN where fewer than ``min_pixels`` remain) and the pixel counts.
    """
    medians = np.full(len(geometries), np.nan)
    counts = np.zeros(len(geometries), dtype=int)
    inner, outer = ring
    for i, shape in enumerate(geometries):
        band = shapely.difference(shape.buffer(outer), shape.buffer(inner))
        w, s, e, n = band.bounds
        c0 = max(int(math.floor((w - transform.c) / transform.a)), 0)
        c1 = min(int(math.ceil((e - transform.c) / transform.a)), z.shape[1])
        r0 = max(int(math.floor((n - transform.f) / transform.e)), 0)
        r1 = min(int(math.ceil((s - transform.f) / transform.e)), z.shape[0])
        if c1 <= c0 or r1 <= r0:
            continue
        cols = np.arange(c0, c1)
        rows = np.arange(r0, r1)
        xs = transform.c + (cols + 0.5) * transform.a
        ys = transform.f + (rows + 0.5) * transform.e
        gx, gy = np.meshgrid(xs, ys)
        hit = shapely.contains_xy(band, gx, gy)
        hit &= ~exclude[r0:r1, c0:c1]
        values = z[r0:r1, c0:c1][hit]
        values = values[np.isfinite(values)]
        counts[i] = values.size
        if values.size >= min_pixels:
            medians[i] = float(np.median(values))
    return medians, counts


# --- build ----------------------------------------------------------------------------------------


def build() -> dict[str, Any]:
    started = time.perf_counter()
    root = cache.root()
    source = root / SOURCE_TILE
    datum = horizontal_datum()
    if not datum["null_operation"]:
        raise RuntimeError(
            "PROJ's operation between the tile and project CRS moves points by "
            f"{datum['max_shift_at_corners_and_centre_m']:.3f} m: the terrain must be warped, "
            "which this build does not do"
        )
    outlines = land_outlines()
    polygon = study_area_polygon(outlines)
    write_study_area(polygon)
    bounds = terrain_bounds()
    cut = cut_terrain(source, root / DEM_1M, bounds)
    z, transform = read_1m(root / DEM_1M)
    square = z[window_of(transform, domain.SQUARE)]
    write_5m(square, root / DEM_5M)
    on_land = land_raster(outlines, transform, z.shape)
    water, counts = water_mask(z, on_land)
    profile = _profile(z.shape[1], z.shape[0], transform, dtype="uint8")
    _write_raster(root / WATER_1M, [water.astype("uint8")], profile, ["water"])
    result = {
        "source_tile": SOURCE_TILE,
        "terrain_bounds": list(bounds),
        "cut": cut,
        "horizontal_datum": datum,
        "water_counts_margin_box": counts,
        "seconds": round(time.perf_counter() - started, 1),
        "outputs": {rel: (root / rel).stat().st_size for rel in (DEM_1M, DEM_5M, WATER_1M)},
    }
    write_json_atomic(root / BUILD_JSON, result, indent=1, separators=(",", ": "))
    return result


def main() -> None:
    result = build()
    print(json.dumps({k: v for k, v in result.items() if k != "horizontal_datum"}, indent=1))
    datum = result["horizontal_datum"]
    print("operation used:", datum["operation_used"], datum["operation_used_definition"])
    print("frame difference:", json.dumps(datum["frame_difference_nad83_2011_to_wgs84_g1762"]))


if __name__ == "__main__":
    main()
