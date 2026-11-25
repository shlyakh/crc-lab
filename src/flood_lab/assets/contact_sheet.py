"""The substation contact sheet (requirement FD3, plan F1 step 2).

For each substation asset one picture of the ground from above, with its outlines and a 50 m scale
bar, laid out as one PNG, ``docs/flood/figures/f1/substation_contact_sheet.png``. The committed
sheet uses USGS NAIP (0.6 m; public domain per the service description, facts file
``usgs-naip-imagery``); its year is read from that facts file (``naip_date``), because the service
returns its current mosaic and the year was read at one point on the day the facts were checked.
The sharper New York State 2018 orthoimagery of the same views is saved to
the cache only, for the person reviewing (``assets/review/<LocNumber>_nys2018.png``): its terms have
not been read, so nothing from it enters the repository.

Each image is fetched once with curl and cached with its request in a JSON beside it, so a rerun is
offline. Needs matplotlib (``uv run --with matplotlib``).
"""

from __future__ import annotations

import io
import json
import math
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import shapely  # noqa: E402

from flood_lab import domain, paths  # noqa: E402
from flood_lab import facts as facts_module  # noqa: E402
from lab_common.io import write_json_atomic  # noqa: E402

#: margin around the outlines of an asset, metres [P]
MARGIN_M = 60.0
#: width and height of each picture, pixels [P]
PIXELS = 800
#: length of the scale bar, metres [P]
SCALE_BAR_M = 50.0
USER_AGENT = "data-source-check/0.1"
SERVICES = {
    "naip2019": "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage",
    "nys2018": "https://orthos.its.ny.gov/arcgis/rest/services/2018_4Band/ImageServer/exportImage",
}
EPSG = domain.CRS.split(":")[1]
#: the facts file that holds what was read about the imagery services
FACTS_ID = "usgs-naip-imagery"


@dataclass(frozen=True)
class ImageryDate:
    """The NAIP year and acquisition day as read from the catalogue, and the day it was read."""

    year: int
    acquired: str  # YYYY-MM-DD
    read_on: str  # YYYY-MM-DD, the facts file's checked_on


def naip_date(path: Path | None = None) -> ImageryDate:
    """The NAIP year at the centre point, from the facts file (facts naip_years_resolution and
    coverage_time). The service returns its current mosaic, so this is the year it held at one
    point when it was read, not a property of the request."""
    source = facts_module.load(path or paths.FACTS / f"{FACTS_ID}.toml")
    years = source.fact("naip_years_resolution")
    when = source.fact("coverage_time")
    year = re.search(r"\bYear (\d{4})\b", years.passage if years else "")
    day = re.search(r"NAIP at the point: (\d{4}-\d{2}-\d{2})", when.observed if when else "")
    if not (year and day):
        raise ValueError(f"facts file {FACTS_ID}: no NAIP year or acquisition day found")
    if not day.group(1).startswith(year.group(1)):
        raise ValueError(
            f"facts file {FACTS_ID}: year {year.group(1)} and day {day.group(1)} differ"
        )
    return ImageryDate(int(year.group(1)), day.group(1), source.checked_on)


@dataclass(frozen=True)
class View:
    west: float
    south: float
    east: float
    north: float

    @property
    def bbox(self) -> str:
        return ",".join(f"{v:.2f}" for v in (self.west, self.south, self.east, self.north))


def view_of(geometries: list[Any], margin: float = MARGIN_M) -> View:
    """Bounds of the outlines plus the margin, widened to a square about their centre."""
    west, south, east, north = shapely.union_all(geometries).bounds
    side = max(east - west, north - south) + 2 * margin
    cx, cy = (west + east) / 2, (south + north) / 2
    return View(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)


def request_url(service: str, view: View, pixels: int = PIXELS) -> str:
    return (
        f"{SERVICES[service]}?bbox={view.bbox}&bboxSR={EPSG}&imageSR={EPSG}"
        f"&size={pixels},{pixels}&format=png&f=image"
    )


def fetch(service: str, view: View, path: Path, pixels: int = PIXELS) -> Path:
    """The image of one view, from the cache when its request is the same, else from the service."""
    url = request_url(service, view, pixels)
    meta = path.with_suffix(".json")
    if path.is_file() and meta.is_file() and json.loads(meta.read_text())["url"] == url:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.part")
    subprocess.run(
        ["curl", "-sL", "--fail", "-A", USER_AGENT, "-o", str(temporary), url],
        check=True,
        timeout=180,
    )
    data = temporary.read_bytes()
    if not data.startswith(b"\x89PNG"):
        temporary.unlink()
        raise RuntimeError(f"{url} did not return a PNG")
    temporary.replace(path)
    write_json_atomic(
        meta,
        {
            "url": url,
            "service": service,
            "bbox_epsg32618": [view.west, view.south, view.east, view.north],
            "pixels": pixels,
            "user_agent": USER_AGENT,
            "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bytes": len(data),
        },
        indent=1,
        separators=(",", ": "),
    )
    return path


def _draw(axis, geometry, **style) -> None:
    if geometry.geom_type in ("Polygon", "LineString"):
        parts = [geometry]
    else:
        parts = list(geometry.geoms)
    for part in parts:
        line = part.exterior if part.geom_type == "Polygon" else part
        xs, ys = line.xy
        axis.plot(xs, ys, **style)


def sheet(panels: list[dict[str, Any]], path: Path, *, columns: int = 3, title: str = "") -> None:
    """Draw the sheet: each panel has ``image``, ``view``, ``outlines`` and ``label``."""
    rows = max(1, math.ceil(len(panels) / columns))
    figure, axes = plt.subplots(rows, columns, figsize=(4.2 * columns, 4.8 * rows + 0.4))
    axes = [axes] if rows * columns == 1 else list(getattr(axes, "flat", axes))
    for axis in axes:
        axis.set_axis_off()
    for axis, panel in zip(axes, panels, strict=False):
        view: View = panel["view"]
        axis.imshow(
            mpimg.imread(panel["image"]),
            extent=(view.west, view.east, view.south, view.north),
            interpolation="nearest",
        )
        for outline in panel["outlines"]:
            _draw(axis, outline, color="#facc15", linewidth=1.6)
        x0 = view.west + 0.06 * (view.east - view.west)
        y0 = view.south + 0.06 * (view.north - view.south)
        axis.plot(
            [x0, x0 + SCALE_BAR_M], [y0, y0], color="white", linewidth=4, solid_capstyle="butt"
        )
        axis.plot(
            [x0, x0 + SCALE_BAR_M], [y0, y0], color="black", linewidth=2, solid_capstyle="butt"
        )
        axis.text(
            x0,
            y0 + 0.025 * (view.north - view.south),
            f"{SCALE_BAR_M:.0f} m",
            color="white",
            fontsize=8,
            fontweight="bold",
        )
        axis.set_xlim(view.west, view.east)
        axis.set_ylim(view.south, view.north)
        axis.set_title(panel["label"], fontsize=8, loc="left")
    if title:
        figure.suptitle(title, fontsize=9, x=0.01, ha="left")
    figure.tight_layout(rect=(0, 0, 1, 1 - 0.35 / (4.8 * rows + 0.4)))
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=110, metadata={"Software": None})
    plt.close(figure)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.part")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(path)
