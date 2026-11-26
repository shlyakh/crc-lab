"""F4 sensitivity: how much run-on from the 500 m ring around the square changes depths inside it.

F3's model of the square has an outflow boundary on land: no run-on enters it from the
contributing area outside. The ring model (``hazard/sfincs_ring.py``) is F3's model on the square
plus 500 m; its outer edge carries F3's boundaries and the square's edges lie inside it. For each
storm of ``f4/ring/queue_ring.json`` this check sets the ring run beside the square run of the same
storm (same rain on the square, same loss rate):

* **Alignment.** The ring's grid holds the square's 800 x 800 cells at rows and columns 100-899
  (``sfincs_ring.square_window``); its terrain file is identical to F3's and its lowest sub-grid
  level per cell (``zb_5m.tif``) equals F3's on every square cell. The ring run's peak level is cut
  to the square and read by F3's own rules from there on.
* **Depth per 5 m cell** by F3's rule (``calibration.run_depth`` and its ``Frame``); counts of read
  study-area cells (Brooklyn land, centre not in a footprint, no pit, not water, not standing
  water) wet to 0.05 m and to 0.3 m; cells whose depth changes by more than ``CHANGE_M`` and their
  distance to the nearest edge of the square.
* **Assets** by ``at_assets.run_assets``: the lead depth of each kept substation site and the
  buildings wet at the wall.
* **Run-on** from the ring run's inner cross-sections (``balance.json`` of ``sfincs_ring.py
  analyse``): volume entering the square per edge, leaving it, and the inflow as a share of the
  rain on the square. Water balance (continuity) of the outer domain and of the square.

``uv run --with matplotlib python -m flood_lab.checks.f4_ring`` writes
``site/flood/tests/records/f4-ring.json`` and ``docs/flood/figures/f4/ring_*.png``; it stops with a
message, writing nothing, while a ring run is missing or not analysed. ``--square-only`` runs the
alignment proof and the readers on the square runs and draws the model figure, without a record.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from flood_lab import cache, domain, paths
from flood_lab.checks import f3_model
from flood_lab.hazard import at_assets, calibration, sfincs_ring
from flood_lab.records import Check, Input, Parameter, Record, software

RECORD_ID = "f4-ring"
REL = "docs/flood/figures/f4"
#: a cell's depth "changes" when the ring run differs from the square run by more than this, m [P]
CHANGE_M = 0.05
#: the ring run's rain on F3's interior cells equals the square run's within this share [P]
RAIN_MATCH_SHARE = 1e-4
#: distance bins of changed cells to the nearest edge of the square, m [P]
DISTANCE_BINS_M = (0, 50, 100, 250, 500, 1000, 2000)
DIFF_LIMIT_M = 0.3


def ring_dir(root: Path) -> Path:
    return root.joinpath(*sfincs_ring.RING_DIR)


# --- pure helpers --------------------------------------------------------------------------------


def edge_distance(n: int = domain.GRID.height, cell: float = domain.GRID.cell) -> np.ndarray:
    """Distance (m) from each cell centre of an n x n square grid to the nearest edge."""
    i = np.arange(n) + 0.5
    d = np.minimum(i, n - i) * cell
    return np.minimum(d[:, None], d[None, :])


def nearest_edge(n: int = domain.GRID.height) -> np.ndarray:
    """Index into ``sfincs_ring.EDGES`` (south, east, north, west) of each cell's nearest edge, rows
    from the north; a tie goes to the first in that order."""
    i = np.arange(n) + 0.5
    r, c = np.meshgrid(i, i, indexing="ij")
    stack = np.stack([n - r, n - c, r, c])  # south, east, north, west
    return stack.argmin(axis=0)


def wet_counts(depth: np.ndarray, where: np.ndarray) -> dict[str, int]:
    d = depth[where]
    return {
        "wet_005": int((d >= domain.WET_M).sum()),
        "wet_030": int((d >= at_assets.LEAD_DEPTH_M).sum()),
    }


def change_summary(
    square: np.ndarray, ring: np.ndarray, where: np.ndarray, change_m: float = CHANGE_M
) -> dict[str, Any]:
    """Cells of ``where`` whose depth differs by more than ``change_m`` between the runs, their
    distance to the nearest square edge and the edge it is."""
    diff = ring - square
    changed = where & (np.abs(diff) > change_m)
    dist = edge_distance(square.shape[0])
    edge = nearest_edge(square.shape[0])
    d = dist[changed]
    hist, _ = np.histogram(d, bins=[*DISTANCE_BINS_M, np.inf])
    labels = [f"{a}-{b}" for a, b in zip(DISTANCE_BINS_M[:-1], DISTANCE_BINS_M[1:], strict=True)]
    labels.append(f">={DISTANCE_BINS_M[-1]}")
    return {
        "cells_read": int(where.sum()),
        "changed": int(changed.sum()),
        "deeper": int((changed & (diff > 0)).sum()),
        "shallower": int((changed & (diff < 0)).sum()),
        "largest_increase_m": round(float(diff[where].max()), 4) if where.any() else None,
        "largest_decrease_m": round(float(diff[where].min()), 4) if where.any() else None,
        "mean_change_m": round(float(diff[where].mean()), 5) if where.any() else None,
        "distance_m": {
            "median": round(float(np.median(d)), 1) if d.size else None,
            "p90": round(float(np.percentile(d, 90)), 1) if d.size else None,
            "max": round(float(d.max()), 1) if d.size else None,
            "bins": dict(zip(labels, (int(v) for v in hist), strict=True)),
        },
        "by_nearest_edge": {
            e: int((edge[changed] == k).sum()) for k, e in enumerate(sfincs_ring.EDGES)
        },
    }


def site_pairs(square: list[dict], ring: list[dict]) -> list[dict]:
    by = {s["LocNumber"]: s for s in ring}
    if set(by) != {s["LocNumber"] for s in square}:
        raise ValueError("the two runs read different substation sites")
    return [
        {
            "LocNumber": s["LocNumber"],
            "name": s["name"],
            "square_m": s["depth_on_25m2_m"],
            "ring_m": by[s["LocNumber"]]["depth_on_25m2_m"],
            "change_m": round(by[s["LocNumber"]]["depth_on_25m2_m"] - s["depth_on_25m2_m"], 3),
            "square_meets_lead_rule": s["meets_lead_rule"],
            "ring_meets_lead_rule": by[s["LocNumber"]]["meets_lead_rule"],
        }
        for s in square
    ]


def run_on_table(balance: dict) -> dict[str, Any]:
    """Run-on per inner edge from a ring run's ``balance.json``."""
    sq = balance["square"]
    rain = sq["rain_m3"]
    rows = {}
    for e in sfincs_ring.EDGES:
        v = sq["by_edge"][e]
        rows[e] = {
            "inflow_m3": round(v["inflow_m3"], 1),
            "outflow_m3": round(v["outflow_m3"], 1),
            "net_inward_m3": round(v["net_inward_m3"], 1),
            "inflow_share_of_square_rain": v["inflow_m3"] / rain if rain else None,
        }
    return {
        "square_rain_m3": round(rain, 1),
        "inflow_m3": round(sq["inflow_m3"], 1),
        "outflow_m3": round(sq["outflow_m3"], 1),
        "net_inward_m3": round(sq["net_inward_m3"], 1),
        "inflow_share_of_square_rain": sq["inflow_m3"] / rain if rain else None,
        "by_edge": rows,
    }


# --- readers -------------------------------------------------------------------------------------


def _read(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        return src.read(1), src.transform, src.crs


def _ring_transform():
    from rasterio.transform import from_origin

    w, _, _, n = sfincs_ring.RING
    return from_origin(w, n, sfincs_ring.CELL, sfincs_ring.CELL)


def alignment(root: Path) -> dict[str, Any]:
    """Proof that the ring's cells at ``square_window`` are F3's cells: grids, transforms, terrain
    and the lowest sub-grid level per cell."""
    from rasterio.transform import Affine

    rd = ring_dir(root) / "model"
    base = json.loads((rd / "base" / "base.json").read_text())
    g = base["grid"]
    rows, cols = sfincs_ring.square_window()
    zb_r, tr_r, _ = _read(rd / "zb_5m.tif")
    zb_s, tr_s, _ = _read(root / "f3" / "model" / "zb_5m.tif")
    square_tr = Affine(*domain.GRID.transform)
    cut_origin = tr_r * (cols.start, rows.start)
    diff = np.abs(zb_r[rows, cols].astype("float64") - zb_s.astype("float64"))
    out = {
        "ring_grid": g,
        "window_rows_cols": [rows.start, rows.stop, cols.start, cols.stop],
        "ring_transform_is_ring": tr_r == _ring_transform(),
        "square_transform_is_project_grid": tr_s == square_tr,
        "cut_origin": [float(cut_origin[0]), float(cut_origin[1])],
        "cut_shape": list(zb_r[rows, cols].shape),
        "zb_largest_abs_difference_m": float(diff.max()),
        "zb_cells_differing": int((diff > 0).sum()),
        "terrain_identical_to_f3": bool(base["terrain"].get("identical_to_f3_dem_model_1m")),
        "square_cells_all_interior": bool(base["square_cells_in_model"]["all_interior"]),
    }
    out["aligned"] = bool(
        out["ring_transform_is_ring"]
        and out["square_transform_is_project_grid"]
        and out["cut_origin"] == [domain.GRID.west, domain.GRID.north]
        and out["cut_shape"] == [domain.GRID.height, domain.GRID.width]
        and out["zb_largest_abs_difference_m"] == 0.0
        and out["terrain_identical_to_f3"]
    )
    return out


def cut_to_square(ring_run: Path, out_folder: Path) -> Path:
    """The ring run's ``zsmax.tif`` cut to the square, written as ``out_folder/zsmax.tif`` on the
    project grid, so that F3's readers take it as they take a square run."""
    import os

    import rasterio
    from rasterio.transform import Affine

    z, tr, crs = _read(ring_run / "zsmax.tif")
    if tr != _ring_transform() or z.shape != sfincs_ring.grid_shape():
        raise ValueError(
            f"{ring_run}/zsmax.tif is not on the ring's grid: run "
            "`sfincs_ring.py analyse` on it (the batch's analyse assumes the square)"
        )
    rows, cols = sfincs_ring.square_window()
    cut = z[rows, cols]
    out_folder.mkdir(parents=True, exist_ok=True)
    path = out_folder / "zsmax.tif"
    tmp = out_folder / "zsmax.tmp.tif"
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=cut.shape[0],
        width=cut.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=Affine(*domain.GRID.transform),
        nodata=float("nan"),
        compress="deflate",
    ) as dst:
        dst.write(cut.astype("float32"), 1)
    os.replace(tmp, path)
    return path


def read_run(folder: Path, root: Path, frame, footprints) -> dict[str, Any]:
    """Depth per 5 m cell (F3's rule), the substation sites and the buildings of one run folder
    holding a square ``zsmax.tif``."""
    depth = calibration.run_depth(folder, frame)
    assets = at_assets.run_assets(folder, root, paths.SITE, footprints)
    walls = assets.pop("_wall_depths")
    return {"depth": depth, "assets": assets, "walls": walls}


def ring_status(runs: Path, queue: list[dict]) -> tuple[list[str], list[str]]:
    """(missing, not analysed by sfincs_ring) ring runs of the queue in ``runs``."""
    missing, raw = [], []
    for item in queue:
        bal = runs / item["label"] / "balance.json"
        if not bal.exists():
            missing.append(item["label"])
        elif json.loads(bal.read_text()).get("analysed_by") != sfincs_ring.ANALYSED_BY:
            raw.append(item["label"])
    return missing, raw


# --- figures -------------------------------------------------------------------------------------


def _png(figure, name: str, out: Path) -> str:
    import io

    plt = f3_model._plt()
    buffer = io.BytesIO()
    figure.savefig(
        buffer, format="png", dpi=f3_model.DPI, metadata={"Software": None}, facecolor="white"
    )
    path = out / name
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".png.part")
    part.write_bytes(buffer.getvalue())
    part.replace(path)
    plt.close(figure)
    return f"{REL}/{name}"


def figure_model(root: Path, out: Path) -> str:
    """The ring model: lowest level per cell, boundary cells, the square and the cross-sections."""
    from matplotlib.colors import ListedColormap

    plt = f3_model._plt()
    rd = ring_dir(root) / "model"
    zb, _, _ = _read(rd / "zb_5m.tif")
    msk, _, _ = _read(rd / "mask_5m.tif")
    w, s, e, n = sfincs_ring.RING
    extent = (w, e, s, n)
    figure, axis = plt.subplots(figsize=(8.6, 7.8))
    image = axis.imshow(
        zb, extent=extent, cmap="terrain", vmin=-3, vmax=30, interpolation="nearest"
    )
    bar = figure.colorbar(image, ax=axis, shrink=0.75)
    bar.set_label("lowest sub-grid level of the 5 m cell, m NAVD88", fontsize=8)
    for value, colour, label in (
        (2, "#2563eb", "water-level boundary (0 m)"),
        (3, "#dc2626", "outflow boundary"),
    ):
        axis.imshow(
            np.where(msk == value, 1.0, np.nan),
            extent=extent,
            cmap=ListedColormap([colour]),
            interpolation="nearest",
        )
        axis.plot([], [], color=colour, lw=4, label=f"{label}: {int((msk == value).sum())} cells")
    sw, ss, se, sn = sfincs_ring.SQUARE
    axis.plot(
        [sw, se, se, sw, sw],
        [ss, ss, sn, sn, ss],
        color="black",
        lw=1.2,
        label="F3's square: inner cross-sections (50 m pieces)",
    )
    for pts in sfincs_ring.outer_lines().values():
        (x0, y0), (x1, y1) = pts
        axis.plot([x0, x1], [y0, y1], color="#f59e0b", lw=0.8, ls="--")
    axis.plot(
        [], [], color="#f59e0b", lw=0.8, ls="--", label="outer cross-sections (water balance)"
    )
    axis.set_xlim(w - 50, e + 50)
    axis.set_ylim(s - 50, n + 50)
    axis.set_aspect("equal")
    axis.tick_params(labelsize=7)
    axis.set_xlabel("UTM 18N easting, m", fontsize=8)
    axis.set_ylabel("northing, m", fontsize=8)
    axis.legend(loc="lower left", fontsize=7, framealpha=0.9)
    axis.set_title(
        "Ring model: F3's square plus 500 m, 1000 x 1000 cells of 5 m\n"
        "the square's edges are inside the model, so run-on across them is computed",
        fontsize=9,
    )
    figure.tight_layout()
    return _png(figure, "ring_model.png", out)


def figure_difference(
    rows: list[dict], diffs: dict[str, np.ndarray], read: np.ndarray, out: Path
) -> str:
    from matplotlib.colors import ListedColormap

    plt = f3_model._plt()
    g = domain.GRID
    extent = (g.west, g.east, g.south, g.north)
    k = len(rows)
    ncol = 2
    nrow = (k + 1) // 2
    figure, axes = plt.subplots(
        nrow, ncol, figsize=(10, 4.9 * nrow), squeeze=False, layout="constrained"
    )
    image = None
    for ax, row in zip(axes.ravel(), rows, strict=False):
        d = diffs[row["label"]]
        ax.imshow(
            np.where(read, np.nan, 1.0),
            extent=extent,
            cmap=ListedColormap(["#d9d9d9"]),
            interpolation="nearest",
        )
        image = ax.imshow(
            np.where(read, d, np.nan),
            extent=extent,
            cmap="RdBu_r",
            vmin=-DIFF_LIMIT_M,
            vmax=DIFF_LIMIT_M,
            interpolation="nearest",
        )
        c = row["change"]
        ax.set_title(
            f"{row['label']}: {c['changed']} cells change by > {CHANGE_M} m\n"
            f"({c['deeper']} deeper, {c['shallower']} shallower)",
            fontsize=8,
        )
        ax.set_aspect("equal")
        ax.tick_params(labelsize=6)
    for ax in axes.ravel()[k:]:
        ax.axis("off")
    if image is not None:
        bar = figure.colorbar(image, ax=axes.ravel().tolist(), shrink=0.6, extend="both")
        bar.set_label("depth with the ring less depth on the square alone, m", fontsize=8)
    figure.suptitle(
        "Change of the maximum inundation depth per 5 m cell when run-on from the ring is "
        "modelled\n"
        "read study-area cells only (F3's rule); grey: not read",
        fontsize=9,
    )
    return _png(figure, "ring_difference.png", out)


def figure_run_on(rows: list[dict], out: Path) -> str:
    plt = f3_model._plt()
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    labels = [r["label"] for r in rows]
    x = np.arange(len(labels))
    width = 0.2
    colours = ("#2563eb", "#16a34a", "#f59e0b", "#dc2626")
    for k, (e, colour) in enumerate(zip(sfincs_ring.EDGES, colours, strict=True)):
        inflow = [r["run_on"]["by_edge"][e]["inflow_m3"] for r in rows]
        outflow = [-r["run_on"]["by_edge"][e]["outflow_m3"] for r in rows]
        axes[0].bar(x + (k - 1.5) * width, inflow, width, color=colour, label=e)
        axes[0].bar(x + (k - 1.5) * width, outflow, width, color=colour, alpha=0.45)
    axes[0].axhline(0, color="black", lw=0.6)
    axes[0].set_xticks(x, labels, fontsize=7)
    axes[0].set_ylabel(
        "m3 (above 0: run-on into the square; below: outflow leaving it)", fontsize=8
    )
    axes[0].legend(fontsize=7, title="edge", title_fontsize=7)
    axes[0].set_title("Flow across the square's edges, per edge", fontsize=9)
    share = [100 * (r["run_on"]["inflow_share_of_square_rain"] or 0.0) for r in rows]
    axes[1].bar(x, share, 0.5, color="#475569")
    axes[1].set_xticks(x, labels, fontsize=7)
    axes[1].set_ylabel("run-on as % of the rain on the square", fontsize=8)
    axes[1].set_title("Run-on into the square, all edges", fontsize=9)
    for a in axes:
        a.tick_params(labelsize=7)
    figure.tight_layout()
    return _png(figure, "ring_run_on.png", out)


def figure_distance(rows: list[dict], out: Path) -> str:
    plt = f3_model._plt()
    figure, axis = plt.subplots(figsize=(8.6, 4.4))
    bins = list(rows[0]["change"]["distance_m"]["bins"])
    x = np.arange(len(bins))
    width = 0.8 / max(len(rows), 1)
    for k, r in enumerate(rows):
        axis.bar(
            x + (k - (len(rows) - 1) / 2) * width,
            list(r["change"]["distance_m"]["bins"].values()),
            width,
            label=r["label"],
        )
    axis.set_xticks(x, bins, fontsize=7)
    axis.set_xlabel("distance of the cell centre to the nearest edge of the square, m", fontsize=8)
    axis.set_ylabel(f"read cells changing by > {CHANGE_M} m", fontsize=8)
    axis.legend(fontsize=7)
    axis.set_title("Where depth changes when run-on is modelled", fontsize=9)
    figure.tight_layout()
    return _png(figure, "ring_change_distance.png", out)


# --- main ----------------------------------------------------------------------------------------


def _context(root: Path) -> dict[str, Any]:
    import geopandas as gpd

    study = gpd.read_file(f3_model.STUDY_AREA).to_crs(domain.CRS).geometry.union_all()
    return {
        "frame": calibration.Frame.load(root, f3_model.STUDY_AREA),
        "footprints": f3_model.study_footprints(root, study),
    }


def square_only(root: Path, queue: list[dict], figures: Path) -> int:
    al = alignment(root)
    print(json.dumps(al, indent=1))
    ctx = _context(root)
    for item in queue:
        folder = Path(item["square_run"])
        r = read_run(folder, root, ctx["frame"], ctx["footprints"])
        print(
            item["label"],
            folder.name,
            wet_counts(r["depth"], ctx["frame"].compared),
            [(s["LocNumber"], s["depth_on_25m2_m"]) for s in r["assets"]["substations"]],
            r["assets"]["buildings"],
        )
    print(figure_model(root, figures))
    return 0 if al["aligned"] else 1


def main(argv: list[str] | None = None) -> int:
    root = cache.root()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queue", type=Path, default=ring_dir(root) / "queue_ring.json")
    ap.add_argument("--figures", type=Path, default=paths.FIGURES / "f4")
    ap.add_argument("--records", type=Path, default=paths.RECORDS)
    ap.add_argument("--runs", type=Path, default=ring_dir(root) / "runs")
    ap.add_argument("--square-only", action="store_true", help="alignment and readers only")
    args = ap.parse_args(argv)
    started = time.perf_counter()
    if not args.queue.exists():
        print(f"f4_ring: no queue at {args.queue}; build it with `sfincs_ring.py queue`")
        return 1
    queue = json.loads(args.queue.read_text())
    if args.square_only:
        return square_only(root, queue, args.figures)
    runs = args.runs.resolve()
    missing, raw = ring_status(runs, queue)
    if missing or raw:
        if missing:
            print(
                f"f4_ring: ring runs missing in {runs}: {', '.join(missing)}\n"
                f"  run: FLOOD_RUNS={runs} caffeinate -i python3 tools/flood/f3_batch.py "
                f"{args.queue}"
            )
        if raw:
            print(
                f"f4_ring: ring runs not analysed by sfincs_ring: {', '.join(raw)}\n"
                "  run `sfincs_ring.py analyse <run>` on each (builder's environment)"
            )
        print("f4_ring: nothing written")
        return 1
    al = alignment(root)
    if not al["aligned"]:
        print(
            "f4_ring: the ring's cells do not align with the square's:\n" + json.dumps(al, indent=1)
        )
        return 1
    ctx = _context(root)
    read = ctx["frame"].compared
    rows, diffs = [], {}
    inputs = [
        Input.of(args.queue, root=root),
        Input.of(ring_dir(root) / "model" / "base" / "base.json", root=root),
        Input.of(ring_dir(root) / "model" / "zb_5m.tif", root=root),
        Input.of(root / "f3" / "model" / "zb_5m.tif", root=root),
    ]
    for item in queue:
        ring_run = runs / item["label"]
        square_run = Path(item["square_run"])
        for f in ("balance.json", "zsmax.tif"):
            if not (square_run / f).exists():
                print(f"f4_ring: square run {square_run} has no {f}; nothing written")
                return 1
        cut = cut_to_square(ring_run, runs.parent / "compare" / item["label"])
        a = read_run(square_run, root, ctx["frame"], ctx["footprints"])
        b = read_run(cut.parent, root, ctx["frame"], ctx["footprints"])
        bal = json.loads((ring_run / "balance.json").read_text())
        sq_bal = json.loads((square_run / "balance.json").read_text())
        f3c = bal["square"].get("f3_interior_cells") or {}
        rain_match = (
            abs(f3c["rain_m3"] - sq_bal["rain_m3"]) / sq_bal["rain_m3"]
            if f3c.get("rain_m3") and sq_bal.get("rain_m3")
            else None
        )
        diffs[item["label"]] = b["depth"] - a["depth"]
        wa, wb = a["walls"], b["walls"]
        rows.append(
            {
                "label": item["label"],
                "square_run": square_run.name,
                "wet_square": wet_counts(a["depth"], read),
                "wet_ring": wet_counts(b["depth"], read),
                "change": change_summary(a["depth"], b["depth"], read),
                "substations": site_pairs(a["assets"]["substations"], b["assets"]["substations"]),
                "buildings_square": a["assets"]["buildings"],
                "buildings_ring": b["assets"]["buildings"],
                "buildings_wall_change_gt_005": int((np.abs(wb - wa) > CHANGE_M).sum()),
                "run_on": run_on_table(bal),
                "outer_balance_residual_share": bal["residual_share_of_rain"],
                "square_balance_residual_share": bal["square"]["residual_share_of_rain"],
                "rain_on_f3_interior_ring_m3": f3c.get("rain_m3"),
                "rain_on_f3_interior_square_m3": sq_bal.get("rain_m3"),
                "rain_match_share": rain_match,
            }
        )
        inputs += [
            Input.of(ring_run / "balance.json", root=root),
            Input.of(ring_run / "zsmax.tif", root=root),
            Input.of(square_run / "zsmax.tif", root=root),
        ]
    figures = [
        figure_model(root, args.figures),
        figure_difference(rows, diffs, read, args.figures),
        figure_run_on(rows, args.figures),
        figure_distance(rows, args.figures),
    ]
    outer = [abs(r["outer_balance_residual_share"]) for r in rows]
    inner = [abs(r["square_balance_residual_share"]) for r in rows]
    rain = [r["rain_match_share"] for r in rows]
    checks = [
        Check(
            "the ring's cells are the square's cells",
            "grid offsets whole cells, same terrain file, lowest sub-grid level equal on all "
            "640000 cells",
            al["aligned"],
            value={"zb_largest_abs_difference_m": al["zb_largest_abs_difference_m"]},
            threshold=0.0,
        ),
        Check(
            "water balance (continuity) of the outer domain within 1%",
            "|rain - drained - stored - out| / rain over the ring model's interior cells (FH8)",
            max(outer) <= f3_model.BALANCE_MAX_SHARE,
            value=max(outer),
            threshold=f3_model.BALANCE_MAX_SHARE,
        ),
        Check(
            "water balance (continuity) of the square within 1%",
            "|rain + net inflow across the inner cross-sections - drained - stored| / rain on "
            "the square",
            max(inner) <= f3_model.BALANCE_MAX_SHARE,
            value=max(inner),
            threshold=f3_model.BALANCE_MAX_SHARE,
            proposed=True,
        ),
        Check(
            "same rain on the square in both runs",
            "rain on F3's interior cells, ring run against the square run's balance.json",
            None if any(v is None for v in rain) else max(rain) <= RAIN_MATCH_SHARE,
            value=rain,
            threshold=RAIN_MATCH_SHARE,
            proposed=True,
        ),
    ]
    record = Record(
        id=RECORD_ID,
        stage="F4",
        title="Run-on from a 500 m ring around the square: ring model against the square model",
        inputs=inputs,
        parameters=[
            Parameter("ring_extent", list(sfincs_ring.RING), "P", "sfincs_ring.RING"),
            Parameter("inner_piece_m", sfincs_ring.SECTION_M, "P", "sfincs_ring.SECTION_M"),
            Parameter("change_m", CHANGE_M, "P", "f4_ring.CHANGE_M"),
            Parameter("rain_match_share", RAIN_MATCH_SHARE, "P", "f4_ring.RAIN_MATCH_SHARE"),
            Parameter("balance_max_share", f3_model.BALANCE_MAX_SHARE, "P", "FH8"),
            Parameter(
                "loss_rate_qinf_mm_h", sorted({i["qinf"] for i in queue}), "P", "CH-16, frozen"
            ),
        ],
        numbers={"alignment": al, "seconds": round(time.perf_counter() - started, 1)},
        tables={"storms": rows},
        checks=checks,
        figures=figures,
        software=software("numpy", "rasterio", "geopandas", "matplotlib"),
        notes=[
            "Run-on (a convention: water flowing onto an area from upslope) is the volume "
            "entering the square across its edges; inflow and outflow per "
            f"edge are integrated per {sfincs_ring.SECTION_M:g} m piece and 10 s output step, so "
            "both are lower bounds of the gross fluxes and their difference is exact.",
            "Both runs have the same rain on the square: the ring's forcing keeps every pixel of "
            "the square run's forcing file and adds pixels around it by the same nearest-cell "
            "rule.",
            "The ring's outer edge is an outflow boundary on land, as F3's: run-on from beyond "
            "500 m is still left out.",
        ],
    )
    path = record.write(args.records)
    print(f"f4_ring: wrote {path} and {len(figures)} figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
