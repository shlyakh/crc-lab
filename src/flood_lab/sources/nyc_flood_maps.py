"""NYC Stormwater Flood Maps: depth classes on the project grid and polygons into CRC (FS1).

Transformation statement (the data card repeats it):

1. Each scenario is one feature class of the publisher's zip (NYC Open Data ``9i7c-xyvv``), read
   with GDAL's open file-geodatabase driver through pyogrio. Geometry is MultiPolygon Z in
   EPSG:2263 (US survey feet); Z is dropped. The field ``Flooding_Category`` is kept as ``code``.
2. Coordinates go from EPSG:2263 to EPSG:26918 (NAD83 / UTM zone 18N), an exact change of
   projection on one datum, and are then used as project-grid coordinates unchanged. The terrain
   was laid on the grid the same way (``flood_lab.terrain``), so maps and terrain share the
   NAD83-to-WGS84 frame difference of about 1.1 m and stay aligned with each other.
3. Depth class of a cell: 2 where the cell centre is inside a code-2 polygon, else 1 where it is
   inside a code-1 polygon, else 0. Code 3 ("Future High Tides", tidal, present in the two
   sea-level-rise scenarios) never enters a depth class; it is a mask of its own.
4. For CRC the polygons are cut to the square, split into single polygons, put into longitude and
   latitude (EPSG:32618 to EPSG:4326, the convention of the asset table) and loaded with
   ``Layer.from_table``: ``value`` is the code, ``label`` its meaning. Nothing is loaded as a
   curve: a depth class is not a probability curve (FS1).

A depth class is a range, not a depth. Nothing here turns a class into metres.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import shapely
from rasterio import features
from rasterio.transform import Affine

from flood_lab import cache, domain

SOURCE_ID = "nyc-stormwater-flood-maps"
ZIP = f"{SOURCE_ID}/NYCFloodStormwaterFloodMaps.zip"
ZIP_SHA256 = "5effe9bcca896660f44a5e50c348ab4ebf7550ff3c764ef77f06d775f0c010f5"
SOURCE_CRS = "EPSG:2263"
#: NAD83 / UTM zone 18N; its coordinates are used as project-grid coordinates (statement, step 2)
GRID_FRAME_CRS = "EPSG:26918"
FIELD = "Flooding_Category"
_STEM = "NYC Stormwater Flood Map - "
_GDB = "NYC_Stormwater_Flood_Map_"

#: code -> meaning, from the publisher's data dictionaries (sheet Column Information)
LABELS = {
    1: "Nuisance flooding (4 in or more and less than 1 ft)",
    2: "Deep and contiguous flooding (1 ft and greater)",
    3: "Future high tides (tidal, not a rainfall depth)",
}
DEPTH_CODES = (1, 2)
TIDAL_CODE = 3


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    rain_in_per_hr: float
    sea_level: str
    folder: str
    gdb: str

    @property
    def member(self) -> str:
        """Path of the geodatabase inside the zip."""
        return f"NYCFloodStormwaterFloodMaps/{self.folder}/{self.gdb}"


SCENARIOS = {
    s.id: s
    for s in (
        Scenario(
            "limited-current",
            "Limited Flood (1.77 in/hr), current sea levels",
            1.77,
            "current",
            _STEM + "Limited Flood (1.77 inches per hr) with Current Sea Levels",
            _GDB + "Limited_Flood_1_77_inches_per_hr_with_Current_Sea_Levels.gdb",
        ),
        Scenario(
            "moderate-current",
            "Moderate Flood (2.13 in/hr), current sea levels",
            2.13,
            "current",
            _STEM + "Moderate Flood (2.13 inches per hr) with Current Sea Levels",
            _GDB + "Moderate_Flood_2_13_inches_per_hr_with_Current_Sea_Levels.gdb",
        ),
        Scenario(
            "moderate-2050",
            "Moderate Flood (2.13 in/hr), 2050 sea level rise",
            2.13,
            "2050 sea level rise",
            _STEM + "Moderate Flood (2.13 inches per hr) with 2050 Sea Level Rise",
            _GDB + "Moderate_Flood_2_13_per_hr_with_2050_Sea_Level_Rise.gdb",
        ),
        Scenario(
            "extreme-2080",
            "Extreme Flood (3.66 in/hr), 2080 sea level rise",
            3.66,
            "2080 sea level rise",
            _STEM + "Extreme Flood (3.66 inches per hr) with 2080 Sea Level Rise",
            _GDB + "Extreme_Flood_3_66_inches_per_hr_with_2080_Sea_Level_Rise.gdb",
        ),
    )
}


class UnreadableLayer(RuntimeError):
    """The geodatabase gives no feature class (the Limited Flood map's compressed table)."""


def unzip(scenario: Scenario, root: Path | None = None) -> Path:
    """The scenario's geodatabase folder, taken out of the publisher's zip once."""
    root = root or cache.root()
    target = root / SOURCE_ID / "unzipped" / scenario.gdb
    if target.is_dir() and any(target.iterdir()):
        return target
    prefix = scenario.member + "/"
    staging = target.with_name(target.name + ".part")
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(root / ZIP) as archive:
        names = [n for n in archive.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if not names:
            raise FileNotFoundError(f"{scenario.member} is not in {ZIP}")
        for name in names:
            (staging / name[len(prefix) :]).write_bytes(archive.read(name))
    staging.replace(target)
    return target


def read_polygons(path: Path, layer: str | None = None) -> gpd.GeoDataFrame:
    """Rows of one scenario: ``code`` and 2D geometry in EPSG:2263, as the publisher wrote them."""
    unreadable = (
        f"{path} gives no feature class to GDAL's open driver "
        "(the Limited Flood map is stored in ESRI's compressed format)"
    )
    try:
        layers = pyogrio.list_layers(path)
    except pyogrio.errors.DataSourceError as error:
        raise UnreadableLayer(f"{unreadable}: {error}") from error
    if len(layers) == 0:
        raise UnreadableLayer(unreadable)
    frame = pyogrio.read_dataframe(path, layer=layer or layers[0][0], columns=[FIELD])
    if frame.crs is None or frame.crs.to_epsg() != 2263:
        raise ValueError(f"{path}: expected EPSG:2263, found {frame.crs}")
    codes = frame[FIELD].astype(int)
    unknown = sorted(set(codes) - set(LABELS))
    if unknown:
        raise ValueError(f"{path}: codes {unknown} are not in the data dictionary")
    return gpd.GeoDataFrame(
        {"code": codes}, geometry=shapely.force_2d(frame.geometry.values), crs=SOURCE_CRS
    )


def on_grid_frame(polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Statement step 2: EPSG:2263 to EPSG:26918, read as project-grid coordinates."""
    moved = polygons.to_crs(GRID_FRAME_CRS)
    return moved.set_crs(domain.CRS, allow_override=True)


def _burn(shapes: list[Any], grid: domain.Grid) -> np.ndarray:
    if not shapes:
        return np.zeros((grid.height, grid.width), dtype=np.uint8)
    return features.rasterize(
        [(shape, 1) for shape in shapes],
        out_shape=(grid.height, grid.width),
        transform=Affine(*grid.transform),
        fill=0,
        all_touched=False,  # a cell is burnt when its centre is inside
        dtype="uint8",
    )


def classes_on_grid(polygons: gpd.GeoDataFrame, grid: domain.Grid = domain.GRID) -> dict[str, Any]:
    """Statement step 3 for polygons already on the grid frame (``on_grid_frame``)."""
    square = shapely.box(grid.west, grid.south, grid.east, grid.north)
    near = polygons[polygons.intersects(square)]
    by_code = {code: list(near.geometry[near["code"] == code]) for code in LABELS}
    depth = _burn(by_code[1], grid)
    depth[_burn(by_code[2], grid) == 1] = 2
    tidal = _burn(by_code[TIDAL_CODE], grid).astype(bool)
    area = {
        code: float(sum(shape.intersection(square).area for shape in shapes))
        for code, shapes in by_code.items()
        if (polygons["code"] == code).any()
    }
    return {"depth_class": depth, "tidal": tidal, "area_m2": area}


def layer_table(
    scenario: Scenario, polygons: gpd.GeoDataFrame, grid: domain.Grid = domain.GRID
) -> dict[str, list[Any]]:
    """Statement step 4: the rows given to ``Layer.from_table`` for one scenario."""
    square = shapely.box(grid.west, grid.south, grid.east, grid.north)
    cut = polygons.assign(geometry=polygons.geometry.intersection(square))
    cut = cut[~cut.geometry.is_empty].explode(index_parts=False)
    cut = cut[cut.geometry.geom_type == "Polygon"]
    cut = cut[cut.geometry.area > 0]
    # a fixed order, so that support ids do not depend on the order GDAL returns parts in
    cut = cut.assign(_x=cut.geometry.centroid.x, _y=cut.geometry.centroid.y)
    cut = cut.sort_values(["code", "_y", "_x"], kind="stable").reset_index(drop=True)
    cut = cut.to_crs("EPSG:4326")
    counters: dict[int, int] = {}
    ids = []
    for code in cut["code"]:
        counters[code] = counters.get(code, 0) + 1
        ids.append(f"{scenario.id}/class-{code}/{counters[code]:05d}")
    return {
        "support_id": ids,
        "geometry": [shape.wkb for shape in cut.geometry],
        "value": [float(code) for code in cut["code"]],
        "label": [LABELS[int(code)] for code in cut["code"]],
    }


def variable(scenario: Scenario) -> Any:
    """The CRC variable of one scenario's class code (a code, held as a dimensionless number)."""
    from crc_framework import Ratio
    from crc_sdk import Variable

    return Variable(f"flood-lab:nyc-stormwater-class:{scenario.id}", measurement=Ratio())


def to_crc(scenario: Scenario, table: dict[str, list[Any]]) -> Any:
    """Load one scenario's rows into CRC as a map layer and return what CRC reads back."""
    from crc_sdk import Layer, LayerColumns

    layer = Layer.from_table(
        table,
        variable=variable(scenario),
        columns=LayerColumns(geometry="geometry", label="label"),
    )
    return layer.read().table


def read_back_differences(table: dict[str, list[Any]], got: Any) -> dict[str, int]:
    """Rows of the CRC layer that differ from what was put in, by kind of difference."""
    back = {row["support_id"]: row for row in got.to_pylist()}
    missing = sum(1 for key in table["support_id"] if key not in back)
    extra = len(set(back) - set(table["support_id"]))
    value = label = geometry_bytes = geometry_shape = 0
    for key, wkb, val, lab in zip(
        table["support_id"], table["geometry"], table["value"], table["label"], strict=True
    ):
        row = back.get(key)
        if row is None:
            continue
        value += row["value"] != val
        label += row["label"] != lab
        if bytes(row["geometry"]) != wkb:
            geometry_bytes += 1
            geometry_shape += not shapely.from_wkb(row["geometry"]).equals(shapely.from_wkb(wkb))
    return {
        "rows_in": len(table["support_id"]),
        "rows_back": len(back),
        "missing": missing,
        "extra": extra,
        "value_differs": int(value),
        "label_differs": int(label),
        "geometry_bytes_differ": geometry_bytes,
        "geometry_shape_differs": int(geometry_shape),
    }


#: where an export of the Limited Flood map is looked for (tools/flood/limited_flood_map)
LIMITED_EXPORT = f"{SOURCE_ID}/converted/limited-current.gpkg"


def source_path(scenario: Scenario, root: Path | None = None) -> Path:
    """The file a scenario is read from: the publisher's geodatabase, or for the Limited Flood
    map the export made through ESRI's library when one exists."""
    root = root or cache.root()
    export = root / LIMITED_EXPORT
    if scenario.id == "limited-current" and export.exists():
        return export
    return unzip(scenario, root)
