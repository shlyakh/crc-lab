"""Export the Limited Flood map through ESRI's File Geodatabase API, with a proof on a sibling.

    uv run python tools/flood/limited_flood_map/export.py            # proof, then the export
    uv run python tools/flood/limited_flood_map/export.py --proof-only

The Limited Flood (1.77 in/hr) geodatabase of NYC Open Data ``9i7c-xyvv`` is stored in ESRI's
compressed format, which GDAL's open driver cannot read. ``dump_gdb.cpp`` reads a geodatabase
through ESRI's own library and writes the rows out as plain numbers; this script builds it, runs
it, assembles the rings into polygons and writes a GeoPackage.

Proof: the same route is run on the uncompressed Moderate Flood (2.13 in/hr, current sea levels)
geodatabase and compared with GDAL's open driver. Only if that agrees is the Limited map written.

ESRI's library is not in the repository. It is expected, unpacked, under
``data/cache/flood/f2/esri-filegdb/FileGDB_API_MacOS-ARM64-clang`` (see README.md).

Rings to polygons: in ESRI's shape format an outer ring runs clockwise and a hole
counter-clockwise. A hole is given to the smallest outer ring that covers it. Nothing is repaired.

Curved segments: ESRI can store an arc between two vertices. This route takes vertices only, so
an arc becomes the straight line between its ends. Two things bound what that loses: the area
ESRI stored with each row (``Shape_Area``, which counts arcs) is set beside the area of the
vertices, and the count and place of curved segments is read from the raw shape
(``beyond_vertices``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import shapely

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("FLOOD_CACHE") or ROOT / "data" / "cache" / "flood")
SDK = CACHE / "f2" / "esri-filegdb" / "FileGDB_API_MacOS-ARM64-clang"
SDK_ZIP = CACHE / "f2" / "esri-filegdb" / "FileGDB_API_MacOS-ARM64-clang.zip"
SDK_URL = (
    "https://raw.githubusercontent.com/Esri/file-geodatabase-api/master/"
    "FileGDB_API_1.5.5/FileGDB_API_MacOS-ARM64-clang.zip"
)
WORK = CACHE / "f2" / "esri-filegdb" / "out"
BINARY = CACHE / "f2" / "esri-filegdb" / "dump_gdb"
MAPS = CACHE / "nyc-stormwater-flood-maps"
PREFIX = "NYC_Stormwater_Flood_Map_"
MODERATE = PREFIX + "Moderate_Flood_2_13_inches_per_hr_with_Current_Sea_Levels.gdb"
LIMITED = PREFIX + "Limited_Flood_1_77_inches_per_hr_with_Current_Sea_Levels.gdb"
OUT = MAPS / "converted" / "limited-current.gpkg"
FIELD = "Flooding_Category"
#: largest relative difference allowed in the proof, for area and for the symmetric difference
PROOF_TOLERANCE = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build() -> None:
    if not (SDK / "lib" / "libFileGDBAPI.dylib").exists():
        sys.exit(f"ESRI's library is not at {SDK}; see {HERE / 'README.md'}")
    subprocess.run(
        [
            "clang++",
            "-std=c++17",
            f"-I{SDK / 'include'}",
            f"-L{SDK / 'lib'}",
            "-lFileGDBAPI",
            "-lfgdbunixrtl",
            f"-Wl,-rpath,{SDK / 'lib'}",
            "-o",
            str(BINARY),
            str(HERE / "dump_gdb.cpp"),
        ],
        check=True,
    )


def dump(gdb: Path) -> tuple[Path, str]:
    """Run the dump program on one geodatabase; returns the prefix of its files and its log."""
    WORK.mkdir(parents=True, exist_ok=True)
    prefix = WORK / gdb.stem
    # ESRI's library names its companions (libpe++, libpe) by the path on ESRI's build machine;
    # the fallback path lets the loader find them beside it, by file name
    env = os.environ | {"DYLD_FALLBACK_LIBRARY_PATH": str(SDK / "lib")}
    done = subprocess.run(
        [str(BINARY), str(gdb), str(prefix)], capture_output=True, text=True, env=env
    )
    log = done.stdout + done.stderr
    if done.returncode != 0:
        sys.exit(f"dump_gdb failed on {gdb.name} (exit {done.returncode}):\n{log}")
    return prefix, log


def read_rows(path: Path) -> list[dict]:
    """The rows of ``<prefix>.rows.bin`` as written by ``dump_gdb.cpp``."""
    data = path.read_bytes()
    at = 0
    rows = []
    while at < len(data):
        oid, code, stored_area, kind, parts, points = struct.unpack_from("<ihdiii", data, at)
        at += struct.calcsize("<ihdiii")
        starts = np.frombuffer(data, "<i4", parts, at)
        at += 4 * parts
        xy = np.frombuffer(data, "<f8", 2 * points, at).reshape(points, 2)
        at += 16 * points
        (has_z,) = struct.unpack_from("<i", data, at)
        at += 4
        if has_z:
            at += 8 * points
        rows.append(
            {
                "oid": oid,
                "code": code,
                "stored_area": stored_area,
                "shape_type": kind,
                "starts": starts,
                "xy": xy,
                "z": has_z,
            }
        )
    return rows


#: flags ESRI sets in the high bits of a general shape type
HAS_Z, HAS_M, HAS_CURVES = 0x80000000, 0x40000000, 0x20000000
#: the study square of flood_lab.domain, on the grid frame (EPSG:26918 read as the project grid)
SQUARE = (585_500.0, 4_504_500.0, 589_500.0, 4_508_500.0)


def beyond_vertices(prefix: Path, row: dict) -> dict:
    """What a row's shape buffer holds after its plain vertices: curved segments, if any.

    The reader takes vertices only, so a curved segment (an arc between two vertices) is read as
    the straight line between them. This reports how many there are and where each starts.
    Layout of ESRI's shape buffer: type, box (4 doubles), part and point counts, part starts,
    points, then for Z the range and one value per point, likewise for M, then for curves a count
    and one record per curved segment beginning with the index of its start point and its kind.
    """
    import pyproj

    data = (prefix.parent / f"{prefix.name}.row{row['oid']}.shape.bin").read_bytes()
    kind = row["shape_type"] & 0xFFFFFFFF
    parts, points = len(row["starts"]), len(row["xy"])
    at = 4 + 32 + 4 + 4 + 4 * parts + 16 * points
    if row["z"]:
        at += 16 + 8 * points
    has_m = bool(kind & HAS_M) or (kind & 0xFF) in (15, 25)
    if has_m and len(data) >= at + 16 + 8 * points:
        at += 16 + 8 * points
    tail = data[at:]
    out = {
        "shape_type_low_byte": kind & 0xFF,
        "flag_curves": bool(kind & HAS_CURVES),
        "bytes_after_vertices": len(tail),
        "tail_hex": tail[:64].hex(),
        "curved_segments": None,
        "segments": [],
    }
    if len(tail) >= 4:
        (count,) = struct.unpack_from("<i", tail, 0)
        out["curved_segments"] = count
        if 0 < count <= 1000 and len(tail) >= 12:
            # only the first record's place is certain without decoding every kind of segment
            start, segment_kind = struct.unpack_from("<ii", tail, 4)
            if 0 <= start < points:
                x, y = (float(v) for v in row["xy"][start])
                to_grid = pyproj.Transformer.from_crs("EPSG:2263", "EPSG:26918", always_xy=True)
                gx, gy = to_grid.transform(x, y)
                nxt = row["xy"][min(start + 1, points - 1)]
                out["segments"].append(
                    {
                        "start_point_index": start,
                        "kind": segment_kind,
                        "start_xy_epsg2263": [x, y],
                        "chord_length_ft": float(np.hypot(nxt[0] - x, nxt[1] - y)),
                        "start_on_grid_frame": [gx, gy],
                        "in_study_square": bool(
                            SQUARE[0] <= gx <= SQUARE[2] and SQUARE[1] <= gy <= SQUARE[3]
                        ),
                    }
                )
    return out


def signed_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))


def assemble(row: dict) -> tuple[shapely.MultiPolygon, dict]:
    """One row's rings as a multipolygon: clockwise rings are outers, the others holes."""
    bounds = [*row["starts"].tolist(), len(row["xy"])]
    rings = [row["xy"][a:b] for a, b in zip(bounds[:-1], bounds[1:], strict=True)]
    unclosed = sum(1 for r in rings if not np.array_equal(r[0], r[-1]))
    areas = [signed_area(r) for r in rings]
    outers = [i for i, a in enumerate(areas) if a < 0]
    holes = [i for i, a in enumerate(areas) if a > 0]
    shells = shapely.polygons([shapely.linearrings(rings[i]) for i in outers])
    tree = shapely.STRtree(shells)
    owned: dict[int, list[int]] = {}
    orphans = 0
    if holes:
        # a point strictly inside the hole, so that a shell which only touches the hole's edge
        # cannot claim it
        probes = shapely.point_on_surface(
            shapely.polygons([shapely.linearrings(rings[i]) for i in holes])
        )
        pairs = tree.query(probes, predicate="within")
        best: dict[int, int] = {}
        for hole_at, shell_at in zip(*pairs, strict=True):
            current = best.get(hole_at)
            if current is None or abs(areas[outers[shell_at]]) < abs(areas[outers[current]]):
                # a hole lies in the smallest outer ring that holds a point of its inside,
                # provided that ring is larger than the hole
                if abs(areas[outers[shell_at]]) > abs(areas[holes[hole_at]]):
                    best[hole_at] = shell_at
        for hole_at, shell_at in best.items():
            owned.setdefault(shell_at, []).append(holes[hole_at])
        orphans = len(holes) - len(best)
    polygons = [
        shapely.Polygon(rings[i], [rings[h] for h in owned.get(at, [])])
        for at, i in enumerate(outers)
    ]
    facts = {
        "rings": len(rings),
        "outer_rings": len(outers),
        "holes": len(holes),
        "holes_without_an_outer_ring": orphans,
        "rings_of_zero_area": len(rings) - len(outers) - len(holes),
        "rings_not_closed": unclosed,
        "points": int(len(row["xy"])),
    }
    return shapely.MultiPolygon(polygons), facts


def through_esri(gdb: Path) -> tuple[gpd.GeoDataFrame, dict]:
    prefix, log = dump(gdb)
    rows = read_rows(prefix.with_suffix(".rows.bin"))
    shapes, facts = [], []
    for row in rows:
        shape, fact = assemble(row)
        shapes.append(shape)
        facts.append(
            {
                "oid": row["oid"],
                "code": row["code"],
                "z": bool(row["z"]),
                **fact,
                "stored_shape_area": row["stored_area"],
                "vertex_area": float(shape.area),
                "relative_area_difference_stored_to_vertices": (
                    abs(shape.area - row["stored_area"]) / row["stored_area"]
                    if row["stored_area"] == row["stored_area"] and row["stored_area"]
                    else None
                ),
                "beyond_vertices": beyond_vertices(prefix, row),
            }
        )
    frame = gpd.GeoDataFrame({FIELD: [r["code"] for r in rows]}, geometry=shapes, crs="EPSG:2263")
    definition = prefix.with_suffix(".def.xml").read_text(errors="replace")
    return frame, {"log": log.strip().splitlines(), "rows": facts, "definition": definition}


def proof() -> dict:
    """The same route on the uncompressed Moderate map against GDAL's open driver."""
    gdb = MAPS / "unzipped" / MODERATE
    ours, detail = through_esri(gdb)
    open_driver = pyogrio.read_dataframe(gdb, columns=[FIELD])
    theirs = {
        int(c): shapely.force_2d(g)
        for c, g in zip(open_driver[FIELD], open_driver.geometry, strict=True)
    }
    codes = {}
    for code, shape in zip(ours[FIELD], ours.geometry, strict=True):
        other = theirs.get(int(code))
        if other is None:
            codes[int(code)] = {"in_open_driver": False}
            continue
        if not other.is_valid:
            other = shapely.make_valid(other)
        mine = shape if shape.is_valid else shapely.make_valid(shape)
        codes[int(code)] = {
            "area_esri_route_sqft": shape.area,
            "area_open_driver_sqft": other.area,
            "relative_area_difference": abs(shape.area - other.area) / other.area,
            "symmetric_difference_over_area": mine.symmetric_difference(other).area / other.area,
        }
    agrees = (
        len(ours) == len(open_driver)
        and set(codes) == set(theirs)
        and all(
            c.get("relative_area_difference", 1) <= PROOF_TOLERANCE
            and c.get("symmetric_difference_over_area", 1) <= PROOF_TOLERANCE
            for c in codes.values()
        )
    )
    return {
        "layer": "Moderate Flood (2.13 in/hr), current sea levels",
        "rows_esri_route": len(ours),
        "rows_open_driver": len(open_driver),
        "crs_open_driver": str(open_driver.crs),
        "codes": codes,
        "tolerance": PROOF_TOLERANCE,
        "agrees": bool(agrees),
        "rows": detail["rows"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--proof-only", action="store_true")
    args = parser.parse_args()
    build()
    result: dict = {
        "made_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": "uv run python tools/flood/limited_flood_map/export.py",
        "publisher_zip_sha256": sha256(MAPS / "NYCFloodStormwaterFloodMaps.zip"),
        "library": {
            "name": "ESRI File Geodatabase API 1.5.5, macOS arm64",
            "url": SDK_URL,
            "sha256": sha256(SDK_ZIP) if SDK_ZIP.exists() else "archive not kept",
            "licence": "Apache License 2.0 (license/ folder of the archive)",
        },
        "proof": proof(),
    }
    print(json.dumps({k: v for k, v in result["proof"].items() if k != "rows"}, indent=1))
    if not result["proof"]["agrees"]:
        sys.exit("the proof on the Moderate map does not agree: the Limited map is not written")
    if args.proof_only:
        return
    frame, detail = through_esri(MAPS / "unzipped" / LIMITED)
    valid = frame.geometry.is_valid
    result["limited"] = {
        "rows": len(frame),
        "codes": sorted(int(c) for c in frame[FIELD]),
        "area_sqft_by_code": {
            int(c): g.area for c, g in zip(frame[FIELD], frame.geometry, strict=True)
        },
        "bounds_epsg2263": [float(v) for v in frame.total_bounds],
        "valid_rows": int(valid.sum()),
        "geometry": "as read: rings assembled by orientation, Z dropped, nothing repaired",
        "rows_detail": detail["rows"],
        "library_log": detail["log"],
        "definition_has_epsg_2263": "2263" in detail["definition"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    part = OUT.with_name(OUT.name + ".part")
    part.unlink(missing_ok=True)
    frame.to_file(part, layer="limited_current", driver="GPKG")
    part.replace(OUT)
    result["output"] = {"path": str(OUT.relative_to(CACHE)), "sha256": sha256(OUT)}
    record = OUT.with_suffix(".json")
    staging = record.with_name(record.name + ".part")
    staging.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    staging.replace(record)
    print(json.dumps({k: v for k, v in result["limited"].items() if "detail" not in k}, indent=1))
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
