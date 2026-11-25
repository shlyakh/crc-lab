# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "rasterio<1.5.2"]
# ///
"""Three figures on crc-sdk 1.0.0, drawn from publisher files and recorded outputs.

1. flood-pixels-left-out.png: GloFAS flood depth pixels in a box around Fremont, California,
   classed as crc-sdk 1.0.0 treats them (returned, or left out with one depth or with a
   depth that is lower at a longer return period). Read from the publisher's GeoTIFFs.
2. ghcnh-complete-days.png: days without all 24 hourly reports per station-year, and whether
   the default coverage gives an annual value. Parsed from a recorded output.
3. nex-calendars.png: NEX-GDDP-CMIP6 models by the calendar their files declare.

    uv run figures.py [output dir]
"""

import math
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import rasterio.windows  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = Path("/Users/yuri/work/crc/crc-lab/local/review-page/figures")
GHCNH_OUTPUT = HERE / "out" / "crc_035_ghcnh_default_coverage.1.0.0.txt"

# Colours (light background): text inks, a quiet context colour and two accents that stay
# apart for colour-blind readers (orange and violet, validated all-pairs).
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
QUIET, ORANGE, VIOLET, BLUE = "#9ec5f4", "#eb6834", "#6250d6", "#2a78d6"
DPI, WIDTH_IN = 160, 10.0  # 1600 px wide

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 12,
        "text.color": INK,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK2,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def save(fig, out_dir: Path, name: str) -> None:
    path = out_dir / name
    part = path.with_suffix(".part.png")
    fig.savefig(part, dpi=DPI)
    plt.close(fig)
    part.replace(path)
    print(f"wrote {path}")


def title_block(fig, title: str, subtitle: str, source: str) -> None:
    fig.text(0.03, 0.965, title, fontsize=16, fontweight="bold", va="top", ha="left")
    fig.text(0.03, 0.905, subtitle, fontsize=12, color=INK2, va="top", ha="left")
    fig.text(0.03, 0.02, source, fontsize=10, color=MUTED, va="bottom", ha="left")


# --- Figure 1: GloFAS pixels left out ---------------------------------------------------------

BOX = dict(west=-122.15, south=37.42, east=-121.85, north=37.62)  # Fremont, California
JRC_BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard"
TILE = "ID18_N40_W130"
PERIODS = (10, 20, 50, 75, 100, 200, 500)
CACHE = Path(tempfile.gettempdir()) / "glofas-repro"
EXPECTED = {"dry": 76398, "returned": 9369, "one depth": 459, "decreasing": 775}


def glofas_file(period: int) -> Path:
    """The publisher's file from the temp-dir cache, downloaded there if missing."""
    path = CACHE / f"{TILE}_RP{period}_depth.tif"
    if path.exists():
        return path
    url = f"{JRC_BASE}/RP{period}/{path.name}"
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "repro-script/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                data = response.read()
            break
        except OSError as error:
            print(f"  ({path.name}: try {attempt} failed: {error})")
            if attempt == 3:
                sys.exit(f"could not download {url}")
            time.sleep(10 * attempt)
    CACHE.mkdir(exist_ok=True)
    path.with_suffix(".part").write_bytes(data)
    path.with_suffix(".part").replace(path)
    return path


def box_window(path: Path):
    """Pixels touched by the box (floor/ceil of the edges) and their extent in degrees."""
    with rasterio.open(path) as source:
        inverse = ~source.transform
        c0, r0 = inverse * (BOX["west"], BOX["north"])
        c1, r1 = inverse * (BOX["east"], BOX["south"])
        window = rasterio.windows.Window.from_slices(
            (math.floor(r0), math.ceil(r1)), (math.floor(c0), math.ceil(c1))
        )
        west, south, east, north = rasterio.windows.bounds(window, source.transform)
        return source.read(1, window=window, masked=True), (west, east, south, north)


def classify_pixels():
    reads = [box_window(glofas_file(t)) for t in PERIODS]
    extent = reads[0][1]
    stack = np.ma.stack([r[0] for r in reads])  # [period, row, column]
    valid = ~np.ma.getmaskarray(stack) & np.isfinite(stack.filled(np.nan))
    depth = np.where(valid, stack.filled(np.nan), np.nan)
    knots = valid.sum(axis=0)
    decreasing = np.zeros(knots.shape, dtype=bool)
    last = np.full(knots.shape, -np.inf)
    for layer in range(len(PERIODS)):
        decreasing |= valid[layer] & (depth[layer] < last)
        last = np.where(valid[layer], depth[layer], last)
    # 0 dry, 1 returned, 2 one depth only, 3 lower depth at a longer return period
    classes = np.zeros(knots.shape, dtype=np.int8)
    classes[(knots >= 2) & ~decreasing] = 1
    classes[knots == 1] = 2
    classes[(knots >= 2) & decreasing] = 3
    return classes, extent


def densest_window(mask: np.ndarray, size: int) -> tuple[int, int]:
    """Top-left (row, column) of the size x size window holding the most True pixels."""
    summed = np.pad(mask.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    counts = (
        summed[size:, size:]
        - summed[:-size, size:]
        - summed[size:, :-size]
        + summed[:-size, :-size]
    )
    r, c = np.unravel_index(np.argmax(counts), counts.shape)
    return int(r), int(c)


def figure_flood(out_dir: Path) -> None:
    classes, (west, east, south, north) = classify_pixels()
    counts = {name: int((classes == k).sum()) for k, name in enumerate(EXPECTED)}
    total, flooded = classes.size, classes.size - counts["dry"]
    left_out = counts["one depth"] + counts["decreasing"]
    print(f"GloFAS pixels in the box: {total}")
    for name, n in counts.items():
        print(f"  {name:<12}{n:>8}")
    print(f"  left out: {left_out} of {flooded} flooded ({100 * left_out / flooded:.1f}%)")
    assert counts == EXPECTED, counts

    cmap = ListedColormap(["white", QUIET, ORANGE, VIOLET])
    rows, cols = classes.shape
    dx, dy = (east - west) / cols, (north - south) / rows
    aspect = 1 / math.cos(math.radians((south + north) / 2))

    fig = plt.figure(figsize=(WIDTH_IN, 7.9))
    title_block(
        fig,
        f"GloFAS flood depth, Fremont CA: {left_out:,} of {flooded:,} flooded pixels\n"
        "are not returned by crc-sdk 1.0.0",
        "crc-sdk returns a pixel only if its depths at return periods 10 to 500 years rise or stay"
        " level\nwith at least two depths. The others are counted together with the dry pixels.",
        "Source: JRC CEMS-GloFAS river flood hazard maps v2.1.2, tile ID18_N40_W130, "
        "return periods 10, 20, 50, 75, 100, 200, 500 years; read 2026-11-25.",
    )
    fig.texts[0].set_position((0.03, 0.975))
    fig.texts[1].set_position((0.03, 0.87))
    ax = fig.add_axes((0.06, 0.2, 0.5, 0.58))
    zoom = fig.add_axes((0.62, 0.2, 0.35, 0.58))

    size = 60  # pixels, about 5 km
    r0, c0 = densest_window(classes >= 2, size)
    zw, zn = west + c0 * dx, north - r0 * dy
    ze, zs = zw + size * dx, zn - size * dy

    for axis, (x0, x1, y0, y1) in ((ax, (west, east, south, north)), (zoom, (zw, ze, zs, zn))):
        axis.imshow(
            classes,
            cmap=cmap,
            vmin=-0.5,
            vmax=3.5,
            extent=(west, east, south, north),
            interpolation="nearest",
        )
        axis.set_xlim(x0, x1)
        axis.set_ylim(y0, y1)
        axis.set_aspect(aspect)
        axis.tick_params(labelsize=10, length=3)
        for spine in axis.spines.values():
            spine.set_color(MUTED)
            spine.set_linewidth(0.8)
    ax.set_xticks(np.round(np.arange(-122.15, -121.849, 0.1), 2))
    ax.set_yticks(np.round(np.arange(37.45, 37.621, 0.05), 2))
    ax.xaxis.set_major_formatter(lambda v, _: f"{abs(v):.2f}°W")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.2f}°N")
    zoom.set_xticks([])
    zoom.set_yticks([])
    ax.set_title("Whole box (87,001 pixels of about 90 m)", fontsize=12, loc="left", color=INK2)
    zoom.set_title("Zoom on the square, about 5 km across", fontsize=12, loc="left", color=INK2)
    ax.add_patch(Rectangle((zw, zs), ze - zw, zn - zs, fill=False, edgecolor=INK, linewidth=1.4))

    handles = [
        Patch(facecolor=QUIET, label=f"Returned: {counts['returned']:,}"),
        Patch(
            facecolor=ORANGE,
            label=f"Left out, flooded at only one return period: {counts['one depth']:,}",
        ),
        Patch(
            facecolor=VIOLET,
            label=f"Left out, depth lower at a longer return period: {counts['decreasing']:,}",
        ),
        Patch(
            facecolor="white",
            edgecolor=MUTED,
            label=f"Dry at every return period: {counts['dry']:,}",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.03, 0.055),
        ncol=2,
        frameon=False,
        fontsize=11.5,
        handlelength=1.4,
        handleheight=1.0,
        columnspacing=2.0,
    )
    save(fig, out_dir, "flood-pixels-left-out.png")


# --- Figure 2: GHCNh complete days ------------------------------------------------------------

ROW = re.compile(
    r"^(USW\d{8})\s+(.+?)\s+(\d{4})\s+(\S+)\s+(\S+)\s+(\d+) of (\d+)\s*$"
)  # station, name, year, default value, value at 0.9, complete days, days


def figure_ghcnh(out_dir: Path) -> None:
    rows = []
    for line in GHCNH_OUTPUT.read_text().splitlines():
        if match := ROW.match(line):
            station, name, year, default, at90, complete, days = match.groups()
            rows.append(
                dict(
                    name=name,
                    year=int(year),
                    default=None if default == "-" else float(default),
                    at90=None if at90 == "-" else float(at90),
                    missing=int(days) - int(complete),
                )
            )
    assert len(rows) == 20, len(rows)
    with_default = sum(r["default"] is not None for r in rows)
    with_90 = sum(r["at90"] is not None for r in rows)
    print(f"GHCNh station-years: {len(rows)}; default value {with_default}; at 0.9 {with_90}")

    fig = plt.figure(figsize=(WIDTH_IN, 9.6))
    title_block(
        fig,
        "GHCNh, five Texas airports: a year missing even one complete day\n"
        "gets no annual value by default",
        "Annual maximum of daily maximum temperature, 2019 to 2022, read with crc-sdk 1.0.0. "
        "A day is complete\nwhen it has a report in all 24 hours; the default coverage needs "
        "every day of the year complete.\nWith Coverage.minimum_fraction(0.9), "
        f"{with_90} of {len(rows)} station-years have a value (right column).",
        "Source: NOAA Global Historical Climatology Network hourly (GHCNh), read through "
        "crc-sdk 1.0.0; recorded 2026-11-25.",
    )
    fig.texts[0].set_position((0.03, 0.975))
    fig.texts[1].set_position((0.03, 0.885))
    ax = fig.add_axes((0.24, 0.15, 0.46, 0.6))

    y, ticks, labels, group_mid = 0.0, [], [], []
    for i, r in enumerate(rows):
        if i and rows[i - 1]["name"] != r["name"]:
            y += 0.8
        r["y"] = y
        ticks.append(y)
        labels.append(str(r["year"]))
        y += 1
    for name in dict.fromkeys(r["name"] for r in rows):
        ys = [r["y"] for r in rows if r["name"] == name]
        group_mid.append((name, sum(ys) / len(ys)))

    for r in rows:
        colour = BLUE if r["default"] is not None else ORANGE
        width = r["missing"]
        if width:
            ax.barh(r["y"], width, height=0.68, color=colour, linewidth=0)
        else:
            ax.plot([0.08], [r["y"]], marker="o", markersize=8, color=colour, clip_on=False)
        note = "0: every day complete" if width == 0 else f"{width}"
        ax.text(width + 0.3, r["y"], note, va="center", fontsize=10.5, color=INK2)
        default = "no value" if r["default"] is None else f"{r['default']:.1f} °C"
        ax.text(
            10.8,
            r["y"],
            default,
            va="center",
            ha="left",
            fontsize=10.5,
            color=INK if r["default"] is not None else ORANGE,
            fontweight="bold",
        )
        ax.text(
            13.6, r["y"], f"{r['at90']:.1f} °C", va="center", ha="left", fontsize=10.5, color=INK2
        )

    ax.set_yticks(ticks, labels, fontsize=10.5)
    ax.tick_params(axis="y", length=0)
    for name, mid in group_mid:
        ax.text(
            -0.17,
            mid,
            name,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=12,
            fontweight="bold",
        )
    ax.invert_yaxis()
    ax.set_xlim(0, 10)
    ax.set_xticks(range(0, 11, 2))
    ax.set_xlabel("Days in the year without all 24 hourly reports", fontsize=11.5)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    top = -1.0
    ax.text(
        10.8,
        top,
        "Value,\ndefault",
        ha="left",
        va="bottom",
        fontsize=11,
        color=INK,
        fontweight="bold",
        clip_on=False,
    )
    ax.text(
        13.6,
        top,
        "Value with\nminimum_\nfraction(0.9)",
        ha="left",
        va="bottom",
        fontsize=11,
        color=INK2,
        clip_on=False,
    )
    ax.set_ylim(y - 0.4, top - 0.1)

    handles = [
        Patch(facecolor=BLUE, label=f"Default read gives a value ({with_default} of {len(rows)})"),
        Patch(
            facecolor=ORANGE,
            label=f"Default read gives no value ({len(rows) - with_default} of {len(rows)})",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.03, 0.045),
        ncol=2,
        frameon=False,
        fontsize=11.5,
    )
    save(fig, out_dir, "ghcnh-complete-days.png")


# --- Figure 3: NEX-GDDP-CMIP6 calendars -------------------------------------------------------

# Calendar attribute of one historical file per model folder for the year 2000 (tasmax; hurs for
# CESM2, CESM2-WACCM and IITM-ESM), read 2026-11-25 from the NEX-GDDP-CMIP6 bucket.
NEX_CALENDARS = {
    "ACCESS-CM2": "proleptic_gregorian",
    "ACCESS-ESM1-5": "proleptic_gregorian",
    "BCC-CSM2-MR": "365_day",
    "CESM2-WACCM": "365_day",
    "CESM2": "365_day",
    "CMCC-CM2-SR5": "365_day",
    "CMCC-ESM2": "365_day",
    "CNRM-CM6-1": "standard",
    "CNRM-ESM2-1": "standard",
    "CanESM5": "365_day",
    "EC-Earth3-Veg-LR": "proleptic_gregorian",
    "EC-Earth3": "proleptic_gregorian",
    "FGOALS-g3": "365_day",
    "GFDL-CM4": "365_day",
    "GFDL-CM4_gr2": "365_day",
    "GFDL-ESM4": "365_day",
    "GISS-E2-1-G": "365_day",
    "HadGEM3-GC31-LL": "360_day",
    "HadGEM3-GC31-MM": "360_day",
    "IITM-ESM": "standard",
    "INM-CM4-8": "365_day",
    "INM-CM5-0": "365_day",
    "IPSL-CM6A-LR": "standard",
    "KACE-1-0-G": "360_day",
    "KIOST-ESM": "365_day",
    "MIROC-ES2L": "standard",
    "MIROC6": "standard",
    "MPI-ESM1-2-HR": "proleptic_gregorian",
    "MPI-ESM1-2-LR": "proleptic_gregorian",
    "MRI-ESM2-0": "proleptic_gregorian",
    "NESM3": "standard",
    "NorESM2-LM": "365_day",
    "NorESM2-MM": "365_day",
    "TaiESM1": "365_day",
    "UKESM1-0-LL": "360_day",
}
SECOND_GRID = {"GFDL-CM4_gr2": "GFDL-CM4"}  # a second grid of a model, not another model
GREGORIAN = {"standard", "proleptic_gregorian"}


def figure_nex(out_dir: Path) -> None:
    def models(calendars: set[str]) -> list[str]:
        names = [m for m, c in NEX_CALENDARS.items() if c in calendars]
        return sorted(names, key=str.lower)

    blocks = [
        ("Gregorian calendar", "standard or proleptic_gregorian", models(GREGORIAN), True),
        ("365-day calendar", "no 29 February", models({"365_day"}), False),
        ("360-day calendar", "twelve 30-day months", models({"360_day"}), False),
    ]

    def count(names: list[str]) -> int:
        return sum(n not in SECOND_GRID for n in names)

    read = count(blocks[0][2])
    refused = count(blocks[1][2]) + count(blocks[2][2])
    print(
        f"NEX models: {read + refused} ({read} read, {refused} refused); "
        f"folders {len(NEX_CALENDARS)}"
    )
    assert (read, refused, count(blocks[1][2]), count(blocks[2][2])) == (14, 20, 16, 4)

    height = 7.3
    fig = plt.figure(figsize=(WIDTH_IN, height))
    title_block(
        fig,
        f"NEX-GDDP-CMIP6: {refused} of {read + refused} models use a 365- or 360-day calendar\n"
        "and are refused by crc-sdk 1.0.0",
        "crc-sdk 1.0.0 reads a model only if its files declare a Gregorian calendar. "
        "Calendar read from one historical\nfile per model (year 2000).",
        "Source: NASA NEX-GDDP-CMIP6 v2.0 files on AWS Open Data (nex-gddp-cmip6 bucket), "
        "calendar attribute read 2026-11-25.",
    )
    fig.texts[0].set_position((0.03, 0.975))
    fig.texts[1].set_position((0.03, 1 - 1.1 / height))
    lefts = (0.04, 0.37, 0.70)
    top, line = 1 - 2.05 / height, 0.235 / height
    for (head, sub, names, ok), x in zip(blocks, lefts, strict=True):
        colour = BLUE if ok else ORANGE
        n = count(names)
        verdict = "READ" if ok else "REFUSED"
        fig.patches.append(
            Rectangle((x, top - 0.045), 0.012, 0.09, transform=fig.transFigure, color=colour)
        )
        fig.text(
            x + 0.02,
            top + 0.045,
            f"{n} models: {verdict}",
            fontsize=14,
            fontweight="bold",
            va="top",
            color=INK,
        )
        fig.text(x + 0.02, top + 0.005, f"{head}\n{sub}", fontsize=10.5, va="top", color=INK2)
        y = top - 0.09
        for name in names:
            fig.patches.append(
                Rectangle(
                    (x + 0.02, y - 0.011), 0.008, 0.016, transform=fig.transFigure, color=colour
                )
            )
            label = name
            if name in SECOND_GRID:
                label = f"{name} (2nd grid, not counted)"
            fig.text(
                x + 0.035,
                y,
                label,
                fontsize=11,
                va="center",
                color=INK2 if name in SECOND_GRID else INK,
            )
            y -= line
    save(fig, out_dir, "nex-calendars.png")


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    figure_flood(out_dir)
    figure_ghcnh(out_dir)
    figure_nex(out_dir)


if __name__ == "__main__":
    main()
