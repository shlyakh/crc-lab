"""F2 visual test: each loader against its second reader, and what went into CRC (FS1 to FS4).

    uv run --with matplotlib python -m flood_lab.checks.f2_sources

Offline, from the cache. For the city flood maps, FloodNet and Groundsource it runs the loader
(``flood_lab.sources``) and the independent reader (``flood_lab.reference``, written without
sight of the loader), compares them value by value, and then breaks the loader's output on
purpose to show that the comparison notices. It loads the flood-map polygons and the FloodNet
events into CRC and compares what CRC reads back with what was put in.

Writes one record per source, ``second-reader-<source id>.json``, the figures under
``docs/flood/figures/f2/``, and the lab's tables: the depth-class rasters
(``site/flood/data/city_flood_maps/``), the FloodNet event table
(``site/flood/data/floodnet_events.csv``) and, in the cache, the Groundsource dated places.

The outcome words are those of ``docs/validation/method.md``. "confirmed" here means the two
readers agree on every value; it says nothing about whether the publisher's values are right.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import rasterio  # noqa: E402
import shapely  # noqa: E402
from matplotlib.colors import ListedColormap, LogNorm  # noqa: E402
from rasterio.transform import Affine  # noqa: E402

from flood_lab import cache, domain, paths  # noqa: E402
from flood_lab.records import Check, Input, Parameter, Record, sha256_file  # noqa: E402
from flood_lab.reference import compare  # noqa: E402
from flood_lab.reference import floodnet as ref_floodnet  # noqa: E402
from flood_lab.reference import groundsource as ref_groundsource  # noqa: E402
from flood_lab.reference import nyc_flood_maps as ref_maps  # noqa: E402
from flood_lab.sources import floodnet, groundsource, nyc_flood_maps  # noqa: E402
from lab_common.io import write_text_atomic  # noqa: E402

OUT = paths.FIGURES / "f2"
FIG = "docs/flood/figures/f2"
DATA = paths.SITE / "data"
STORMS = {"2021-09-01": "Ida", "2023-09-29": "29 September 2023"}
#: largest relative difference allowed between the two readers' clipped areas [P], proposed
AREA_TOLERANCE = 1e-6
#: largest difference in a depth, metres, and in a centroid, degrees [P], proposed
DEPTH_TOLERANCE_M = 1e-9
DEGREE_TOLERANCE = 1e-9
NUISANCE, DEEP, TIDAL, WRONG = "#93c5fd", "#1d4ed8", "#a7f3d0", "#dc2626"


def _png(figure: Any, name: str) -> str:
    """Write a figure atomically, without the timestamp matplotlib would put in the file."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=130, metadata={"Software": None})
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".png.part")
    part.write_bytes(buffer.getvalue())
    part.replace(path)
    plt.close(figure)
    return f"{FIG}/{name}"


def _confirmed(result: dict[str, Any]) -> bool:
    return compare.outcome(result) == "confirmed"


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """A table as plain rows, missing values as None, for the comparison functions."""
    return [
        {
            key: (None if isinstance(value, float) and np.isnan(value) else value)
            for key, value in row.items()
        }
        for row in frame.to_dict("records")
    ]


# --- city flood maps --------------------------------------------------------------------------


def _write_raster(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".tif.part")
    with rasterio.open(
        part,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype="uint8",
        crs=domain.CRS,
        transform=Affine(*domain.GRID.transform),
        compress="deflate",
    ) as file:
        file.write(array, 1)
    part.replace(path)


def _map_figure(title: str, grid: dict[str, Any], differing: np.ndarray, name: str) -> str:
    west, south, east, north = domain.SQUARE
    shown = grid["depth_class"].astype(float)
    shown[(shown == 0) & grid["tidal"]] = 3
    shown[shown == 0] = np.nan
    figure, axis = plt.subplots(figsize=(7.2, 7.0))
    axis.imshow(
        shown,
        extent=(west, east, south, north),
        cmap=ListedColormap([NUISANCE, DEEP, TIDAL]),
        vmin=0.5,
        vmax=3.5,
        interpolation="nearest",
    )
    rows, cols = np.nonzero(differing)
    axis.scatter(
        west + (cols + 0.5) * domain.CELL_M,
        north - (rows + 0.5) * domain.CELL_M,
        s=14,
        color=WRONG,
        label=f"cells where the two readers differ: {len(rows)}",
    )
    axis.set_title(title, fontsize=10)
    axis.set_xlabel("Easting, m (project grid)")
    axis.set_ylabel("Northing, m")
    axis.legend(loc="lower left", fontsize=8)
    figure.text(
        0.01,
        0.01,
        "Light blue: 4 in to under 1 ft. Dark blue: 1 ft and greater. Green: future high tides "
        "(tidal, not rainfall).\nThe city's published map on the project grid, not a result of "
        "this study. Limit: classes, not depths.",
        fontsize=7,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 1))
    return _png(figure, name)


def flood_maps(root: Path) -> Record:
    found = sha256_file(root / nyc_flood_maps.ZIP)
    if found != nyc_flood_maps.ZIP_SHA256:
        raise SystemExit(
            f"{nyc_flood_maps.ZIP}: sha256 {found} is not the file whose facts were read "
            f"({nyc_flood_maps.ZIP_SHA256}); stop (FS6)"
        )
    record = Record(
        id=f"second-reader-{nyc_flood_maps.SOURCE_ID}",
        stage="F2",
        title="City flood maps: loader against the second reader, and the CRC layer",
        inputs=[Input.of(root / nyc_flood_maps.ZIP, root=root)],
        parameters=[
            Parameter(
                "cell rule", "a cell takes the class its centre lies in; class 2 over 1", "I"
            ),
            Parameter(
                "grid frame",
                "EPSG:2263 to EPSG:26918, used as project-grid coordinates (as the terrain)",
                "I",
            ),
            Parameter("area tolerance, relative", AREA_TOLERANCE, "P"),
        ],
    )
    table = []
    for scenario in nyc_flood_maps.SCENARIOS.values():
        path = nyc_flood_maps.source_path(scenario, root)
        try:
            polygons = nyc_flood_maps.on_grid_frame(nyc_flood_maps.read_polygons(path))
        except nyc_flood_maps.UnreadableLayer:
            record.checks.append(
                Check(
                    f"{scenario.id}: read",
                    "the scenario can be read",
                    None,
                    note="Stored in ESRI's compressed format; the open reader refuses it and no "
                    "export exists yet (tools/flood/limited_flood_map). Not compared, not loaded.",
                )
            )
            table.append({"scenario": scenario.id, "read": "no"})
            continue
        if path.suffix == ".gpkg":
            record.inputs.append(Input.of(path, root=root))
        ours = nyc_flood_maps.classes_on_grid(polygons)
        theirs = ref_maps.classes_on_grid(path)
        depth = compare.compare_grids(ours["depth_class"], theirs["depth_class"])
        tidal = compare.compare_grids(ours["tidal"], np.asarray(theirs["tidal"], dtype=bool))
        areas = {
            int(code): abs(ours["area_m2"][code] - theirs["area_m2"][code])
            / max(theirs["area_m2"][code], 1.0)
            for code in ours["area_m2"]
        }
        same_codes = set(ours["area_m2"]) == {int(c) for c in theirs["area_m2"]}
        differing = (ours["depth_class"] != theirs["depth_class"]) | (
            ours["tidal"] != np.asarray(theirs["tidal"], dtype=bool)
        )
        record.checks += [
            Check(
                f"{scenario.id}: depth class per cell",
                "zero cells differ between loader and second reader",
                _confirmed(depth),
                value=int(differing.sum()),
                threshold=0,
            ),
            Check(
                f"{scenario.id}: tidal mask per cell",
                "zero cells differ",
                _confirmed(tidal),
                value=int((ours["tidal"] != np.asarray(theirs["tidal"], dtype=bool)).sum()),
                threshold=0,
            ),
            Check(
                f"{scenario.id}: area per class in the square",
                "the two readers' clipped areas agree",
                bool(same_codes and max(areas.values(), default=0.0) <= AREA_TOLERANCE),
                value=max(areas.values(), default=0.0),
                threshold=AREA_TOLERANCE,
                proposed=True,
            ),
        ]
        # deliberate faults: the comparison must notice each
        shifted = polygons.assign(geometry=polygons.geometry.translate(xoff=domain.CELL_M))
        moved = nyc_flood_maps.classes_on_grid(shifted)["depth_class"]
        dropped = nyc_flood_maps.classes_on_grid(polygons[polygons["code"] != 2])["depth_class"]
        # two metres is under half a cell and about the size of the datum question (statement 2)
        nudged = polygons.assign(geometry=polygons.geometry.translate(xoff=2.0))
        slightly = nyc_flood_maps.classes_on_grid(nudged)["depth_class"]
        record.checks += [
            Check(
                f"{scenario.id}: fault, polygons shifted by two metres",
                "the comparison reports a difference",
                not _confirmed(compare.compare_grids(slightly, theirs["depth_class"])),
                value=int((slightly != theirs["depth_class"]).sum()),
            ),
            Check(
                f"{scenario.id}: fault, polygons shifted by one cell",
                "the comparison reports a difference",
                not _confirmed(compare.compare_grids(moved, theirs["depth_class"])),
                value=int((moved != theirs["depth_class"]).sum()),
            ),
            Check(
                f"{scenario.id}: fault, the class-2 row dropped",
                "the comparison reports a difference",
                not _confirmed(compare.compare_grids(dropped, theirs["depth_class"])),
                value=int((dropped != theirs["depth_class"]).sum()),
            ),
        ]
        rows = nyc_flood_maps.layer_table(scenario, polygons)
        back = nyc_flood_maps.read_back_differences(rows, nyc_flood_maps.to_crc(scenario, rows))
        unequal = sum(
            v for k, v in back.items() if k not in ("rows_in", "rows_back", "geometry_bytes_differ")
        )
        record.checks.append(
            Check(
                f"{scenario.id}: CRC layer reads back equal",
                "every polygon, class and label read from CRC equals what was put in",
                unequal == 0 and back["rows_in"] == back["rows_back"],
                value=back,
            )
        )
        _write_raster(DATA / "city_flood_maps" / f"{scenario.id}.tif", ours["depth_class"])
        if ours["tidal"].any():
            _write_raster(
                DATA / "city_flood_maps" / f"{scenario.id}-tidal.tif", ours["tidal"].astype("uint8")
            )
        record.figures.append(
            _map_figure(scenario.title, ours, differing, f"flood_map_{scenario.id}.png")
        )
        depth_cells = ours["depth_class"]
        table.append(
            {
                "scenario": scenario.id,
                "read": "yes",
                "cells class 1": int((depth_cells == 1).sum()),
                "cells class 2": int((depth_cells == 2).sum()),
                "cells tidal": int(ours["tidal"].sum()),
                "cells tidal and in a class": int((ours["tidal"] & (depth_cells > 0)).sum()),
                "ha class 1": round(ours["area_m2"].get(1, 0.0) / 1e4, 2),
                "ha class 2": round(ours["area_m2"].get(2, 0.0) / 1e4, 2),
                "ha tidal": round(ours["area_m2"].get(3, 0.0) / 1e4, 2),
                "polygons in CRC": back["rows_in"],
            }
        )
    record.tables["scenarios"] = table
    record.numbers["scenarios_read"] = sum(1 for row in table if row["read"] == "yes")
    record.numbers["scenarios"] = len(table)
    record.notes += [
        "Two readers that agree show the loader does what its statement says. For three "
        "scenarios both open the publisher's geodatabase with the same GDAL driver, the only "
        "open reader of that format, so a fault in that driver would be shared.",
        "The Limited Flood map is different: both readers open the same export, made through "
        "ESRI's library (tools/flood/limited_flood_map). The second reader therefore recomputes "
        "only the step from that export to the grid. The step from the publisher's geodatabase "
        "to the export rests on the export's own proof: the same route reproduces the Moderate "
        "map as GDAL reads it. The export takes vertices only; the map's one curved segment lies "
        "outside the study square (F2 report, section 1).",
        "Both readers also share the choice of grid frame (EPSG:2263 to EPSG:26918, read as the "
        "project grid), which is the project's convention and not something a comparison of "
        "the two can test.",
        "The square holds water and Manhattan as well as the study area; cell counts are for the "
        "whole 4 km square.",
    ]
    return record


# --- FloodNet -----------------------------------------------------------------------------------


def _sensor_figure(sensors: dict[str, pd.DataFrame]) -> str:
    import pyproj

    to_lonlat = pyproj.Transformer.from_crs(domain.CRS, "EPSG:4326", always_xy=True)
    west, south, east, north = domain.SQUARE
    corner_x = [west, east, east, west, west]
    corner_y = [south, south, north, north, south]
    square_lon, square_lat = to_lonlat.transform(corner_x, corner_y)
    figure, axes = plt.subplots(1, len(sensors), figsize=(12, 6.2), sharex=True, sharey=True)
    for axis, (day, frame) in zip(np.atleast_1d(axes), sensors.items(), strict=True):
        quiet, wet = frame[~frame["recorded"]], frame[frame["recorded"]]
        axis.scatter(
            quiet["longitude"],
            quiet["latitude"],
            s=22,
            facecolor="white",
            edgecolor="#6b7280",
            label=f"in service, no event: {len(quiet)}",
        )
        axis.scatter(
            wet["longitude"],
            wet["latitude"],
            s=30,
            color=DEEP,
            label=f"recorded an event: {len(wet)}",
        )
        axis.plot(square_lon, square_lat, color="#b91c1c", linewidth=1.2, label="study square")
        axis.set_title(f"{STORMS[day]} ({day}, local day)", fontsize=10)
        axis.set_xlabel("Longitude")
        axis.legend(loc="lower left", fontsize=8)
        axis.set_aspect(1 / np.cos(np.radians(40.7)))
    np.atleast_1d(axes)[0].set_ylabel("Latitude")
    figure.text(
        0.01,
        0.01,
        "FloodNet sensors in service on each day, all five boroughs. Limit: a sensor with no "
        "event may have been dry, offline, or mounted above the water; the tables do not say "
        "which.",
        fontsize=7,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    return _png(figure, "floodnet_sensors_by_storm.png")


def flood_net(root: Path) -> list[Record]:
    events_csv, sensors_csv = root / floodnet.EVENTS, root / floodnet.SENSORS
    ours = floodnet.events(events_csv, sensors_csv)
    theirs = ref_floodnet.events(events_csv, sensors_csv)
    key = ("sensor_id", "start_utc")
    exact = ("end_utc", "local_day", "duration_min")
    close = {
        "peak_depth_m": DEPTH_TOLERANCE_M,
        "longitude": DEGREE_TOLERANCE,
        "latitude": DEGREE_TOLERANCE,
    }

    def against(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return compare.compare_tables(rows, theirs, key=key, exact=exact, close=close)

    rows = _records(ours)
    result = against(rows)
    events_record = Record(
        id="second-reader-floodnet-flood-events",
        stage="F2",
        title="FloodNet events: loader against the second reader, and the CRC observations",
        inputs=[Input.of(events_csv, root=root), Input.of(sensors_csv, root=root)],
        parameters=[
            Parameter("inch", floodnet.INCH_M, "S", "exact by definition, metres"),
            Parameter("local day", domain.TIMEZONE, "I"),
            Parameter("depth tolerance, m", DEPTH_TOLERANCE_M, "P"),
        ],
    )
    events_record.checks.append(
        Check(
            "events table",
            "zero rows differ between loader and second reader",
            _confirmed(result),
            value={k: v for k, v in result.items() if not isinstance(v, list) or len(v) < 6},
            threshold=0,
        )
    )
    # deliberate faults
    dropped = rows[:100] + rows[101:]
    deeper = [dict(r) for r in rows]
    deeper[7]["peak_depth_m"] += 0.001
    # 03:30 GMT is the evening before in New York: a reader that takes the GMT date is wrong
    late = next(i for i, r in enumerate(rows) if r["local_day"] != r["start_utc"][:10])
    gmt_day = [dict(r) for r in rows]
    gmt_day[late]["local_day"] = gmt_day[late]["start_utc"][:10]
    for name, broken in (
        ("one row dropped", dropped),
        ("one depth off by a millimetre", deeper),
        ("one event given its GMT date as the local day", gmt_day),
    ):
        events_record.checks.append(
            Check(
                f"fault, {name}",
                "the comparison reports a difference",
                not _confirmed(against(broken)),
            )
        )
    crc_rows = floodnet.crc_table(ours)
    back = floodnet.read_back_differences(crc_rows, floodnet.to_crc(crc_rows))
    events_record.checks.append(
        Check(
            "CRC observations read back equal",
            "every sensor, time, depth and position read from CRC equals what was put in",
            sum(v for k, v in back.items() if k not in ("rows_in", "rows_back")) == 0
            and back["rows_in"] == back["rows_back"],
            value=back,
        )
    )
    consistency = ref_floodnet.consistency(events_csv, sensors_csv)
    events_record.numbers |= {
        "events": len(ours),
        "sensors_with_an_event": int(ours["sensor_id"].nunique()),
        "events_whose_local_day_is_not_the_gmt_date": int(
            (ours["local_day"] != ours["start_utc"].str.slice(0, 10)).sum()
        ),
        "first_event_utc": ours["start_utc"].min(),
        "last_event_utc": ours["start_utc"].max(),
    }
    events_record.tables["publisher's own consistency (second reader's counts)"] = [
        {"count": name, "events": value}
        for name, value in consistency.items()
        if isinstance(value, int)
    ]
    events_record.notes += [
        "Peak depth and duration are the publisher's columns, converted; neither reader "
        "recomputes them from the depth profile. The consistency table says how often the "
        "publisher's profile and its own summary columns disagree.",
        "Duration and end time are not in CRC: an observation there is one value at one time.",
    ]
    buffer = io.StringIO()
    ours.to_csv(buffer, index=False, lineterminator="\n")
    write_text_atomic(DATA / "floodnet_events.csv", buffer.getvalue())

    sensors_record = Record(
        id="second-reader-floodnet-sensors",
        stage="F2",
        title="FloodNet sensors in service on the two storm days",
        inputs=[Input.of(sensors_csv, root=root), Input.of(events_csv, root=root)],
        parameters=[
            Parameter("in service", "installed on or before the day and not removed before it", "I")
        ],
    )
    by_day, table = {}, []
    for day in STORMS:
        mine = floodnet.storm_sensors(ours, sensors_csv, day)
        other = ref_floodnet.storm_sensors(events_csv, sensors_csv, day)
        by_day[day] = mine
        result = compare.compare_tables(
            _records(mine),
            other,
            key=("sensor_id",),
            exact=("borough", "recorded"),
            close={
                "peak_depth_m": DEPTH_TOLERANCE_M,
                "longitude": DEGREE_TOLERANCE,
                "latitude": DEGREE_TOLERANCE,
            },
        )
        sensors_record.checks.append(
            Check(
                f"{day}: sensors in service and whether each recorded",
                "zero rows differ between loader and second reader",
                _confirmed(result),
                value={k: v for k, v in result.items() if not isinstance(v, list) or len(v) < 6},
                threshold=0,
            )
        )
        flipped = _records(mine)
        flipped[0]["recorded"] = not flipped[0]["recorded"]
        sensors_record.checks.append(
            Check(
                f"{day}: fault, one sensor's flag flipped",
                "the comparison reports a difference",
                not _confirmed(
                    compare.compare_tables(
                        flipped, other, key=("sensor_id",), exact=("borough", "recorded")
                    )
                ),
            )
        )
        x, y = _to_grid(mine["longitude"].to_numpy(), mine["latitude"].to_numpy())
        west, south, east, north = domain.SQUARE
        inside = (x >= west) & (x <= east) & (y >= south) & (y <= north)
        two = mine["borough"].isin(["Brooklyn", "Queens"])
        table.append(
            {
                "local day": day,
                "in service, city": len(mine),
                "recorded, city": int(mine["recorded"].sum()),
                "in service, Brooklyn and Queens": int(two.sum()),
                "recorded, Brooklyn and Queens": int(mine.loc[two, "recorded"].sum()),
                "in service, study square": int(inside.sum()),
                "recorded, study square": int(mine.loc[inside, "recorded"].sum()),
            }
        )
    sensors_record.tables["sensors by storm"] = table
    sensors_record.figures.append(_sensor_figure(by_day))
    sensors_record.notes.append(
        "The count of sensors with an event is mostly a count of where sensors stood: the "
        "network had nine sensors at Ida. A sensor in service with no event is not evidence "
        "that its street stayed dry."
    )
    return [events_record, sensors_record]


def _to_grid(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import pyproj

    return pyproj.Transformer.from_crs("EPSG:4326", domain.CRS, always_xy=True).transform(lon, lat)


# --- Groundsource -------------------------------------------------------------------------------


def _ground_figures(table: pd.DataFrame, end_dates: pd.Series) -> list[str]:
    west, south, east, north = groundsource.BOXES["nyc"]
    figure, axes = plt.subplots(1, 2, figsize=(12.5, 6.2), sharex=True, sharey=True)
    norm = LogNorm(vmin=0.01, vmax=1000)
    for axis, day in zip(axes, ("2021-09-01", "2021-09-02"), strict=True):
        rows = groundsource.covering(table, "nyc", day).sort_values("area_km2", ascending=False)
        for wkb, area in zip(rows["geometry_wkb"], rows["area_km2"], strict=True):
            shape = shapely.from_wkb(wkb)
            for part in getattr(shape, "geoms", [shape]):
                xs, ys = part.exterior.xy
                axis.fill(
                    xs,
                    ys,
                    facecolor=plt.cm.viridis(norm(max(area, 0.01))),
                    edgecolor="#111827",
                    linewidth=0.2,
                    alpha=0.55,
                )
        axis.plot(
            [west, east, east, west, west],
            [south, south, north, north, south],
            color="#b91c1c",
            linewidth=1.0,
        )
        axis.set_xlim(west - 0.15, east + 0.15)
        axis.set_ylim(south - 0.1, north + 0.1)
        axis.set_title(f"Rows whose dates hold {day}: {len(rows)}", fontsize=10)
        axis.set_xlabel("Longitude")
        axis.set_aspect(1 / np.cos(np.radians(40.7)))
    axes[0].set_ylabel("Latitude")
    figure.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap="viridis"),
        ax=axes,
        shrink=0.8,
        label="area_km2 of the named place (not of the flood)",
    )
    figure.text(
        0.01,
        0.01,
        "Groundsource rows that intersect the New York box (red). Each polygon is the place a "
        "news report named, largest drawn first.\nLimit: a polygon is not a flood extent; the "
        "publisher found 60% of 400 reviewed rows accurate in place and dates.",
        fontsize=7,
    )
    maps = _png(figure, "groundsource_ida_rows.png")

    last = pd.to_datetime(end_dates)
    newest = last.max()
    recent = last[last >= newest - pd.Timedelta(days=120)]
    counts = recent.dt.strftime("%Y-%m-%d").value_counts().sort_index()
    figure, axis = plt.subplots(figsize=(11, 4.2))
    axis.bar(pd.to_datetime(counts.index), counts.to_numpy(), width=0.9, color=DEEP)
    axis.set_ylabel("Rows ending that day, whole file")
    axis.set_title(
        f"Latest dates in the file: the last 120 days before {newest:%Y-%m-%d}", fontsize=10
    )
    figure.text(
        0.01,
        0.01,
        "Rows of the whole Groundsource file by end date. Limit: the fall at the end is where the "
        "file stops being filled, not a fall in flooding.",
        fontsize=7,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 1))
    return [maps, _png(figure, "groundsource_latest_dates.png")]


def ground_source(root: Path) -> Record:
    path = root / groundsource.FILE
    checksum = groundsource.md5(path)
    if checksum != groundsource.MD5:
        raise SystemExit(
            f"{groundsource.FILE}: md5 {checksum} is not the publisher's {groundsource.MD5}; stop"
        )
    started = time.perf_counter()
    ours = groundsource.dated_places(path)
    seconds = time.perf_counter() - started
    theirs = ref_groundsource.dated_places(path)
    key = ("box", "uuid")
    exact = ("start_date", "end_date", "area_km2", "centroid_in_box")
    close = {"centroid_lon": DEGREE_TOLERANCE, "centroid_lat": DEGREE_TOLERANCE}

    def against(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return compare.compare_tables(
            rows, theirs, key=key, exact=exact, close=close, geometry=("geometry_wkb",)
        )

    rows = _records(ours)
    result = against(rows)
    record = Record(
        id="second-reader-groundsource",
        stage="F2",
        title="Groundsource dated places: loader against the second reader",
        inputs=[Input.of(path, root=root)],
        parameters=[
            Parameter(
                "md5 of the publisher's file", groundsource.MD5, "S", "Zenodo record 18647054"
            ),
            *[
                Parameter(f"box {name} (west, south, east, north)", list(box), "I")
                for name, box in groundsource.BOXES.items()
            ],
            Parameter("row kept when", "its polygon intersects the box, touching included", "I"),
        ],
    )
    record.checks += [
        Check(
            "checksum",
            "the file's md5 equals the publisher's, by both readers",
            checksum == groundsource.MD5 and ref_groundsource.checksum(path) == groundsource.MD5,
            value=checksum,
            threshold=groundsource.MD5,
        ),
        Check(
            "dated places",
            "zero rows differ between loader and second reader",
            _confirmed(result),
            value={k: v for k, v in result.items() if not isinstance(v, list) or len(v) < 6},
            threshold=0,
        ),
    ]
    dropped = rows[:50] + rows[51:]
    redated = [dict(r) for r in rows]
    redated[3]["end_date"] = "2099-01-01"
    moved = [dict(r) for r in rows]
    moved[5]["geometry_wkb"] = shapely.transform(
        shapely.from_wkb(moved[5]["geometry_wkb"]), lambda xy: xy + np.array([0.001, 0.0])
    ).wkb
    for name, broken in (
        ("one row dropped", dropped),
        ("one end date changed", redated),
        ("one polygon shifted by 0.001 degree", moved),
    ):
        record.checks.append(
            Check(
                f"fault, {name}",
                "the comparison reports a difference",
                not _confirmed(against(broken)),
            )
        )
    by_day = [
        {
            "box": box,
            "day": day,
            "rows whose dates hold the day": len(groundsource.covering(ours, box, day)),
            "of them with the centroid in the box": int(
                groundsource.covering(ours, box, day)["centroid_in_box"].sum()
            ),
        }
        for box in groundsource.BOXES
        for day in ("2021-09-01", "2021-09-02", "2023-09-29")
    ]
    record.tables["rows by day"] = by_day
    end_dates = pq.read_table(path, columns=["end_date"])["end_date"].to_pandas()
    record.numbers |= {
        "rows_in_the_file": int(len(end_dates)),
        "latest_end_date": str(end_dates.max()),
        "loader_seconds": round(seconds, 1),
        **{f"rows_{box}": int((ours["box"] == box).sum()) for box in groundsource.BOXES},
        **{
            f"median_area_km2_{box}": float(ours.loc[ours["box"] == box, "area_km2"].median())
            for box in groundsource.BOXES
        },
    }
    record.figures += _ground_figures(ours, end_dates)
    record.notes += [
        "A row is a place named in a news report with the days the report gave. area_km2 is the "
        "area of that place, not of any flood.",
        "Not loaded into CRC: 1.0.0 has no record holding a date range and a polygon (D8).",
    ]
    out = root / "f2" / "groundsource_places.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".parquet.part")
    pq.write_table(pa.Table.from_pandas(ours, preserve_index=False), part)
    part.replace(out)
    return record


def main() -> None:
    root = cache.root()
    records = [flood_maps(root), *flood_net(root), ground_source(root)]
    for record in records:
        record.software |= {
            name: __import__(name).__version__
            for name in ("pyogrio", "rasterio", "shapely", "pyarrow", "pandas", "duckdb")
        }
        path = record.write(paths.RECORDS)
        verdict = {True: "passed", False: "FAILED", None: "not judged"}[record.passed]
        print(f"{path.name}: {verdict} ({len(record.checks)} checks)")


if __name__ == "__main__":
    main()
