"""F4: AORC v1.1 hourly rainfall to RainyDay's daily input files (FH5).

Reads the AORC v1.1 Zarr copy (``data/cache/flood/f4/aorc/store/<year>.zarr``, window 38-44 N,
78.5-69.5 W) and writes one NetCDF per UTC day in the layout of RainyDay's own AORC files (the
ten in ``data/cache/flood/f4/rainyday/aorc_sample/``, read by RainyDay at commit ``ff2b809``)::

    uv run --no-project --python 3.12 --with numpy --with numcodecs --with zarr --with netcdf4 \\
        python -I src/flood_lab/hazard/aorc_rainyday.py convert --lat 39.0 41.5 --lon -76.0 -72.0 \\
        --years 2002-2025 --out data/cache/flood/f4/rainyday/input [--time-label end|start]

**Layout** (as in RainyDay's sample files): file ``AORC.YYYYMMDD.precip.nc``, NETCDF4_CLASSIC;
dimensions ``time`` (24), ``latitude``, ``longitude``, both ascending; ``time`` float64 "minutes
since 1970-01-01", calendar gregorian; ``latitude``/``longitude`` float64 (AORC's own centres);
``precrate`` float32 (time, latitude, longitude) in "mm hr^-1", zlib with shuffle; global attribute
``missing = "-9999."``. RainyDay names the variables through ``VARIABLES``
(``{"rainname": "precrate", "latname": "latitude", "longname": "longitude"}``).

**Hours.** RainyDay's sample files and its tutorial stamp each hour at the END of its accumulation;
the file for day D holds the stamps D 01:00 ... D+1 00:00 (RainyDay's sample 19790201 runs
1979-02-01T01:00 to 1979-02-02T00:00). The written stamp is therefore always the hour's end.
``--time-label`` says how AORC stamps its hours: ``end`` (default; NOAA OWP's AORC v1.1 methods,
section 4.1: accumulation "ending at the top of each hour") takes the AORC stamps D 01:00 ...
D+1 00:00, the last one from the next year's store; ``start`` takes D 00:00 ... D 23:00 and writes
each at stamp + 1 h. An hour absent from every complete store (e.g. D+1 00:00 after the last year)
is written as missing.

**Values.** AORC ``APCP_surface`` is int16, scale 0.1, fill -32767, kg m-2 per hour = mm/h. Values
are written as float32 ``raw * float32(0.1)``. Missing values (AORC's fill: open sea, and any gap)
are written as -9999., as RainyDay's own files do; RainyDay sets every value below 0 to NaN after
reading. int16 with a scale factor is not used: RainyDay reads with netCDF4's automatic masking,
under which a masked fill becomes a masked element that its ``inrain[inrain<0.]=np.nan`` does not
reach, and the masked array's data is then copied into its float buffer unchanged.

Resumable: a day whose file exists and is listed in ``manifest.json`` with no absent hour is
skipped; files are written
to a temporary name and moved into place (``os.replace``). ``manifest.json`` is rewritten after each
year with each file's sha256, hours, missing counts, the domain, source years and time label.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "cache" / "flood" / "f4" / "aorc" / "store"
VAR = "APCP_surface"
FILL = -32767
SCALE = np.float32(0.1)
MISSING_OUT = np.float32(-9999.0)
RAIN_NAME = "precrate"
EPOCH = dt.datetime(1970, 1, 1)
HOUR = 3600


# --- pure helpers ---------------------------------------------------------------------------------


def window_slices(lat: np.ndarray, lon: np.ndarray, lat_b, lon_b) -> tuple[slice, slice]:
    """Index slices of the cells whose centres lie in the bounds (inclusive); axes ascending."""
    if not (np.all(np.diff(lat) > 0) and np.all(np.diff(lon) > 0)):
        raise ValueError("latitude and longitude must be ascending")
    la = np.where((lat >= lat_b[0]) & (lat <= lat_b[1]))[0]
    lo = np.where((lon >= lon_b[0]) & (lon <= lon_b[1]))[0]
    if la.size == 0 or lo.size == 0:
        raise ValueError(f"no cells in lat {lat_b}, lon {lon_b}")
    return slice(int(la[0]), int(la[-1]) + 1), slice(int(lo[0]), int(lo[-1]) + 1)


def day_end_stamps(day: dt.date) -> np.ndarray:
    """The 24 end-of-hour stamps (epoch s) of RainyDay's file for ``day``: D 01:00 .. D+1 00:00."""
    t0 = int((dt.datetime(day.year, day.month, day.day) - EPOCH).total_seconds())
    return t0 + HOUR * np.arange(1, 25, dtype=np.int64)


def source_stamps(end_stamps: np.ndarray, time_label: str) -> np.ndarray:
    """AORC stamps to read for the given end-of-hour stamps."""
    if time_label == "end":
        return end_stamps.copy()
    if time_label == "start":
        return end_stamps - HOUR
    raise ValueError(f"time_label must be 'end' or 'start', not {time_label!r}")


def scale(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """int16 AORC values to float32 mm/h, -9999. where missing; returns (values, missing mask)."""
    miss = raw == FILL
    out = raw.astype(np.float32) * SCALE
    out[miss] = MISSING_OUT
    return out, miss


def days_of(years: list[int]) -> list[dt.date]:
    first, last = dt.date(min(years), 1, 1), dt.date(max(years), 12, 31)
    days = []
    d = first
    while d <= last:
        if d.year in years:
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def file_name(day: dt.date) -> str:
    return f"AORC.{day:%Y%m%d}.precip.nc"


def parse_years(text: str) -> list[int]:
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --- the store ------------------------------------------------------------------------------------


def complete(store: Path, year: int) -> bool:
    """A year is usable when its manifest exists and every listed APCP chunk object is on disk at
    the listed size."""
    man = store / f"manifest-{year}.json"
    if not man.exists() or not (store / f"{year}.zarr").exists():
        return False
    m = json.loads(man.read_text())
    chunk = re.compile(rf"/{VAR}/\d+\.\d+\.\d+$")
    want = [o for o in m["objects"] if chunk.search(o["key"])]
    if not want:
        return False
    for o in want:
        p = store / o["key"]
        if not p.exists() or p.stat().st_size != o["size"]:
            return False
    return True


@dataclass
class Hours:
    """Reads hours by epoch stamp across year stores, one time chunk of the window at a time."""

    store: Path
    years: list[int]
    lat_b: tuple[float, float]
    lon_b: tuple[float, float]
    _open: dict = field(default_factory=dict)
    _cache: dict = field(default_factory=dict)

    def _year(self, year: int):
        if year not in self._open:
            if year not in self.years:
                self._open[year] = None
            else:
                import zarr

                g = zarr.open_group(str(self.store / f"{year}.zarr"), mode="r")
                t = np.asarray(g["time"][:]).astype(np.int64)
                if np.any(np.diff(t) != HOUR):
                    raise ValueError(f"{year}: time steps are not hourly")
                lat, lon = np.asarray(g["latitude"][:]), np.asarray(g["longitude"][:])
                ys, xs = window_slices(lat, lon, self.lat_b, self.lon_b)
                self._open[year] = {
                    "arr": g[VAR],
                    "t0": int(t[0]),
                    "nt": len(t),
                    "ys": ys,
                    "xs": xs,
                    "lat": lat[ys],
                    "lon": lon[xs],
                }
        return self._open[year]

    def grid(self) -> tuple[np.ndarray, np.ndarray]:
        y = self._year(self.years[0])
        return y["lat"], y["lon"]

    def hour(self, stamp: int) -> np.ndarray | None:
        """Raw int16 window for the AORC stamp, or None when no complete store holds it."""
        year = (EPOCH + dt.timedelta(seconds=int(stamp))).year
        y = self._year(year)
        if y is None:
            return None
        i = (int(stamp) - y["t0"]) // HOUR
        if not 0 <= i < y["nt"]:
            return None
        step = y["arr"].chunks[0]
        c = i // step
        key = (year, c)
        if key not in self._cache:
            if len(self._cache) >= 2:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = np.asarray(
                y["arr"][c * step : min((c + 1) * step, y["nt"]), y["ys"], y["xs"]]
            )
        return self._cache[key][i - c * step]


def assemble(hours: Hours, day: dt.date, time_label: str) -> dict:
    """One day's values (24, ny, nx) float32 with -9999. as missing, and its counts."""
    lat, lon = hours.grid()
    ends = day_end_stamps(day)
    srcs = source_stamps(ends, time_label)
    out = np.full((24, len(lat), len(lon)), MISSING_OUT, np.float32)
    absent = 0
    missing_values = 0
    for k, s in enumerate(srcs):
        raw = hours.hour(int(s))
        if raw is None:
            absent += 1
            missing_values += out[k].size
            continue
        out[k], miss = scale(raw)
        missing_values += int(miss.sum())
    never = int((out == MISSING_OUT).all(axis=0).sum())
    valid = out[out != MISSING_OUT]
    return {
        "values": out,
        "end_stamps": ends,
        "source_stamps": srcs,
        "lat": lat,
        "lon": lon,
        "absent_hours": absent,
        "missing_values": int(missing_values),
        "cells_missing_all_day": never,
        "sum_mm": float(valid.astype(np.float64).sum()),
    }


def write_day(path: Path, day: dict, time_label: str, complevel: int = 4) -> None:
    """Write one day file atomically in RainyDay's AORC layout."""
    import netCDF4

    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    lat, lon, v = day["lat"], day["lon"], day["values"]
    with netCDF4.Dataset(tmp, "w", format="NETCDF4_CLASSIC") as nc:
        first = EPOCH + dt.timedelta(seconds=int(day["end_stamps"][0]))
        nc.title = f"AORC v1.1 {first:%Y-%m-%dT%H:%M}"
        nc.description = (
            "NOAA AORC v1.1 APCP_surface (kg m-2 per hour = mm/h), hourly, 30 arc-second grid, "
            "converted to RainyDay's daily layout. Each time stamp is the END of its one-hour "
            f"accumulation; AORC time label taken as '{time_label}' "
            "(end: AORC stamp = hour end; start: AORC stamp = hour start, written at stamp + 1 h). "
            "Missing values (AORC fill, e.g. open sea, or an hour absent from the store) are -9999."
        )
        nc.Conventions = "CF-1.8"
        nc.history = f"Created {dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ}"
        nc.source = "https://noaa-nws-aorc-v1-1-1km.s3.amazonaws.com/ (Zarr, APCP_surface)"
        nc.missing = "-9999."
        nc.createDimension("time", v.shape[0])
        nc.createDimension("latitude", len(lat))
        nc.createDimension("longitude", len(lon))
        t = nc.createVariable("time", "f8", ("time",), fill_value=np.nan)
        t.long_name = "time"
        t.units = "minutes since 1970-01-01"
        t.calendar = "gregorian"
        t[:] = day["end_stamps"].astype(np.float64) / 60.0
        la = nc.createVariable("latitude", "f8", ("latitude",), fill_value=np.nan)
        la.long_name, la.units, la.standard_name, la.axis = (
            "latitude",
            "degrees_north",
            "latitude",
            "Y",
        )
        la[:] = lat
        lo = nc.createVariable("longitude", "f8", ("longitude",), fill_value=np.nan)
        lo.long_name, lo.units = "longitude", "degrees_east"
        lo[:] = lon
        p = nc.createVariable(
            RAIN_NAME,
            "f4",
            ("time", "latitude", "longitude"),
            fill_value=np.nan,
            zlib=True,
            shuffle=True,
            complevel=complevel,
            chunksizes=(6, len(lat), len(lon)),
        )
        p.long_name = "precipitation rate"
        p.units = "mm hr^-1"
        p[:] = v
    os.replace(tmp, path)


def file_sum(path: Path) -> tuple[float, int]:
    """Sum of the non-missing values of a written day file, and its count of missing values."""
    import netCDF4

    with netCDF4.Dataset(path) as nc:
        nc.set_auto_mask(False)
        v = np.asarray(nc[RAIN_NAME][:])
    ok = v >= 0
    return float(v[ok].astype(np.float64).sum()), int((~ok).sum())


# --- the conversion -------------------------------------------------------------------------------


def _year_job(args) -> tuple[int, dict, float]:
    store, years, lat_b, lon_b, year, out, time_label, done = args
    started = time.perf_counter()
    hours = Hours(Path(store), years, tuple(lat_b), tuple(lon_b))
    entries = {}
    for day in days_of([year]):
        name = file_name(day)
        path = Path(out) / name
        if name in done and path.exists():
            continue
        d = assemble(hours, day, time_label)
        first = EPOCH + dt.timedelta(seconds=int(d["end_stamps"][0]))
        write_day(path, d, time_label)
        entries[name] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "hours": 24,
            "first_end_stamp": f"{first:%Y-%m-%dT%H:%M}Z",
            "absent_hours": d["absent_hours"],
            "missing_values": d["missing_values"],
            "cells_missing_all_day": d["cells_missing_all_day"],
            "sum_mm": round(d["sum_mm"], 3),
        }
    return year, entries, time.perf_counter() - started


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def convert(
    lat_b,
    lon_b,
    years: list[int],
    out: Path,
    time_label: str = "end",
    store: Path = STORE,
    workers: int = 4,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    usable = [y for y in years if complete(store, y)]
    skipped = [y for y in years if y not in usable]
    if not usable:
        raise SystemExit(f"no complete year store among {years}")
    # the next year's store holds the last hour of 31 December (end label): any complete
    # neighbour is read, requested or not
    near = range(min(years) - 1, max(years) + 2)
    readable = sorted(set(usable) | {y for y in near if y not in years and complete(store, y)})
    hours = Hours(store, readable, tuple(lat_b), tuple(lon_b))
    lat, lon = hours.grid()
    domain = {
        "lat_bounds": list(lat_b),
        "lon_bounds": list(lon_b),
        "ny": int(len(lat)),
        "nx": int(len(lon)),
        "lat_first": float(lat[0]),
        "lat_last": float(lat[-1]),
        "lon_first": float(lon[0]),
        "lon_last": float(lon[-1]),
        "res_deg": float(np.mean(np.diff(lat))),
    }
    man_path = out / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
    if manifest and (manifest.get("domain") != domain or manifest.get("time_label") != time_label):
        raise SystemExit(
            f"{man_path} was written for another domain or time label; use a new --out folder"
        )
    manifest.setdefault("files", {})
    manifest.update(
        {
            "source": "NOAA AORC v1.1 APCP_surface, Zarr copy " + str(store),
            "rainyday_variables": {
                "rainname": RAIN_NAME,
                "latname": "latitude",
                "longname": "longitude",
            },
            "domain": domain,
            "time_label": time_label,
            "stamp_rule": "written stamp = end of the hour; day D holds D 01:00 .. D+1 00:00 UTC",
            "units": "mm hr^-1 (AORC kg m-2 per hour)",
            "missing_value_written": -9999.0,
            "years_requested": years,
            "years_skipped_incomplete": skipped,
        }
    )
    manifest.setdefault("seconds_per_year", {})
    # a file with absent hours is made again: a neighbouring store may have become complete since
    done = {k for k, e in manifest["files"].items() if e["absent_hours"] == 0}
    jobs = [
        (str(store), readable, list(lat_b), list(lon_b), y, str(out), time_label, done)
        for y in usable
    ]
    with ProcessPoolExecutor(max(1, min(workers, len(jobs)))) as ex:
        for year, entries, seconds in ex.map(_year_job, jobs):
            manifest["files"].update(entries)
            manifest["files"] = dict(sorted(manifest["files"].items()))
            if entries:
                manifest["seconds_per_year"][str(year)] = round(seconds, 1)
            years_done = sorted({int(k[5:9]) for k in manifest["files"]})
            manifest["source_years"] = years_done
            manifest["total_bytes"] = int(sum(e["bytes"] for e in manifest["files"].values()))
            manifest["total_absent_hours"] = int(
                sum(e["absent_hours"] for e in manifest["files"].values())
            )
            _write_json(man_path, manifest)
            print(
                f"{year}: {len(entries)} files written in {seconds:.0f} s; "
                f"total {manifest['total_bytes'] / 1e9:.2f} GB",
                flush=True,
            )
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--lat", type=float, nargs=2, required=True)
    c.add_argument("--lon", type=float, nargs=2, required=True)
    c.add_argument("--years", required=True, help="e.g. 2002-2025")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--time-label", choices=("end", "start"), default="end")
    c.add_argument("--store", type=Path, default=STORE)
    c.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    if a.command == "convert":
        m = convert(a.lat, a.lon, parse_years(a.years), a.out, a.time_label, a.store, a.workers)
        if m["years_skipped_incomplete"]:
            print(f"skipped, store incomplete: {m['years_skipped_incomplete']}", file=sys.stderr)


if __name__ == "__main__":
    main()
