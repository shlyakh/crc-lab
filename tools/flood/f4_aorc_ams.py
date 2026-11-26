"""F4: annual maximum 1-, 3- and 6-hour rainfall per AORC pixel over the downloaded window (FH5).

The evidence for choosing the transposition domain: storms may be moved only within a region where
their statistics are alike. Reads the AORC v1.1 Zarr copy made by
``data/cache/flood/f4/aorc/scripts/download.py`` (window 38-44 N, 78.5-69.5 W) one spatial
tile at a time and writes, per year,
``data/cache/flood/f4/ams/ams_<year>.npz`` with arrays ``max1``, ``max3``, ``max6`` (mm, float32,
NaN where every hour of the year is missing; a missing hour inside a year counts as no rain and
is counted in ``missing_hours``), ``lat``, ``lon`` (ascending) and ``missing_hours``.

    uv run --no-project --python 3.12 --with numpy --with numcodecs --with zarr \\
        python -I tools/flood/f4_aorc_ams.py --years 2002-2025

Rules: values are AORC's hourly accumulations (kg m-2 = mm, scale 0.1, fill -32767). A running sum
over k hours is taken inside one year's file only, so a burst that straddles New Year is cut
(stated as a limit). A year file that is incomplete (fewer chunk objects than the
manifest lists) is skipped and named on stdout. Resumable: a year with its npz is skipped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import zarr

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data" / "cache" / "flood" / "f4" / "aorc" / "store"
OUT = ROOT / "data" / "cache" / "flood" / "f4" / "ams"
WINDOW = (38.0, 44.0, -78.5, -69.5)
FILL = -32767
SCALE = 0.1
DURS = (1, 3, 6)


def window_index(lat: np.ndarray, lon: np.ndarray) -> tuple[slice, slice]:
    la = np.where((lat >= WINDOW[0]) & (lat <= WINDOW[1]))[0]
    lo = np.where((lon >= WINDOW[2]) & (lon <= WINDOW[3]))[0]
    return slice(la[0], la[-1] + 1), slice(lo[0], lo[-1] + 1)


def running_max(x: np.ndarray, k: int) -> np.ndarray:
    """Max over time of the k-hour running sum; x is (time, y, x) float32 with NaN as missing."""
    if k == 1:
        return np.nanmax(x, axis=0)
    c = np.cumsum(np.nan_to_num(x), axis=0, dtype=np.float64)
    s = c[k - 1 :].copy()
    s[1:] -= c[:-k]
    return s.max(axis=0).astype(np.float32)


def tile(args: tuple[int, int, int, int, int]) -> tuple[int, int, dict]:
    """Stream one spatial tile through the year one time chunk at a time (memory ~ one chunk)."""
    year, y0, y1, x0, x1 = args
    arr = zarr.open_group(str(STORE / f"{year}.zarr"), mode="r")["APCP_surface"]
    nt, step = arr.shape[0], arr.chunks[0]
    kmax = max(DURS)
    shape = (y1 - y0, x1 - x0)
    best = {k: np.zeros(shape, np.float32) for k in DURS}
    nmiss = np.zeros(shape, np.int32)
    carry = np.zeros((0, *shape), np.float32)
    for t0 in range(0, nt, step):
        raw = arr[t0 : min(t0 + step, nt), y0:y1, x0:x1]
        miss = raw == FILL
        nmiss += miss.sum(axis=0, dtype=np.int32)
        x = raw.astype(np.float32) * np.float32(SCALE)
        x[miss] = 0.0
        xx = np.concatenate([carry, x], axis=0)
        for k in DURS:
            if xx.shape[0] < k:
                continue
            s = xx[k - 1 :].copy()
            for j in range(1, k):
                s += xx[k - 1 - j : xx.shape[0] - j]
            # sums whose last hour lies in the carry were already counted
            s = s[max(0, carry.shape[0] - (k - 1)) :]
            np.maximum(best[k], s.max(axis=0), out=best[k])
        carry = xx[-(kmax - 1) :]
    out = {f"max{k}": best[k] for k in DURS}
    for k in DURS:
        out[f"max{k}"][nmiss >= nt] = np.nan  # no data at all (open sea); partial gaps are counted
    out["missing_hours"] = nmiss
    return y0, x0, out


def complete(year: int) -> bool:
    man = STORE / f"manifest-{year}.json"
    if not man.exists():
        return False
    m = json.loads(man.read_text())
    chunk = re.compile(r"/APCP_surface/\d+\.\d+\.\d+$")
    want = [o["key"] for o in m["objects"] if chunk.search(o["key"])]
    have = {
        p.name
        for p in (STORE / f"{year}.zarr" / "APCP_surface").glob("*.*.*")
        if p.stat().st_size > 0
    }
    return len(want) > 0 and all(k.rsplit("/", 1)[1] in have for k in want)


def one_year(year: int, workers: int) -> None:
    dest = OUT / f"ams_{year}.npz"
    if dest.exists():
        print(f"{year}: done before", flush=True)
        return
    if not complete(year):
        print(f"{year}: store incomplete, skipped", flush=True)
        return
    g = zarr.open_group(str(STORE / f"{year}.zarr"), mode="r")
    lat = g["latitude"][:]
    lon = g["longitude"][:]
    ys, xs = window_index(lat, lon)
    ch = g["APCP_surface"].chunks
    # tiles aligned to the store's chunks so each object is decompressed once
    yb = list(range((ys.start // ch[1]) * ch[1], ys.stop, ch[1]))
    xb = list(range((xs.start // ch[2]) * ch[2], xs.stop, ch[2]))
    jobs = []
    for a in yb:
        for b in xb:
            jobs.append(
                (
                    year,
                    max(a, ys.start),
                    min(a + ch[1], ys.stop),
                    max(b, xs.start),
                    min(b + ch[2], xs.stop),
                )
            )
    ny, nx = ys.stop - ys.start, xs.stop - xs.start
    res = {f"max{k}": np.full((ny, nx), np.nan, np.float32) for k in DURS}
    res["missing_hours"] = np.zeros((ny, nx), np.int32)
    with ProcessPoolExecutor(workers) as ex:
        for y0, x0, out in ex.map(tile, jobs):
            for key, v in out.items():
                res[key][
                    y0 - ys.start : y0 - ys.start + v.shape[0],
                    x0 - xs.start : x0 - xs.start + v.shape[1],
                ] = v
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, lat=lat[ys], lon=lon[xs], hours=np.int32(g["time"].shape[0]), **res)
    tmp.rename(dest)
    print(
        f"{year}: {ny}x{nx} px, hours {g['time'].shape[0]}, "
        f"median max1 {np.nanmedian(res['max1']):.1f} mm, "
        f"max3 {np.nanmedian(res['max3']):.1f} mm, "
        f"px with missing hours {(res['missing_hours'] > 0).sum()}",
        flush=True,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2002-2025")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    y0, _, y1 = a.years.partition("-")
    for y in range(int(y0), int(y1 or y0) + 1):
        try:
            one_year(y, a.workers)
        except Exception as e:  # report and go on; a rerun resumes
            print(f"{y}: failed: {e!r}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
