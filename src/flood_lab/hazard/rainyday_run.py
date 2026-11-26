"""F4: run RainyDay (FH5) and read what it writes into plain tables.

RainyDay is pinned at commit ``ff2b80913657b6dfad8380b8bc998ab6362be03e`` in its own environment
(``data/cache/flood/f4/rainyday/SETUP.md``). This module only writes its parameter file, starts it,
and reads its output; it imports nothing from RainyDay.

* :func:`write_params` writes the JSON parameter file. Keys are those that
  ``Source/RainyDay_Py3.py`` reads at the pinned commit (:data:`KNOWN_KEYS`); an unknown key is
  refused, since RainyDay would ignore a misspelt one silently. ``tempscaling`` (lower case) is
  required at this commit. Python booleans are written as the strings ``"true"``/``"false"``
  that RainyDay compares with ``.lower()``.
* :func:`run` starts ``RainyDay_Py3.py <json>`` with ``MPLBACKEND=Agg`` and writes
  ``run_record.json`` beside the output (command, wall time, exit code, whether the log ends with
  RainyDay's success line, peak memory).
* :func:`read_outputs` parses ``StormCatalog/``, the frequency CSV and ``Realizations/`` into
  ``catalogue.csv`` and ``scenarios.csv`` in the output folder.

What RainyDay writes (read from ``RainyDay_functions.py``: ``writecatalog``, ``writescenariofile``,
``Normalized_SST_write``, and ``RainyDay_Py3.py`` from "writing spacetime precipitation
scenarios"):

* ``StormCatalog/<CATALOGNAME>_storm_<n>_<YYYYMMDD>.nc``: storm ``n`` of ``NSTORMS``, ordered by
  rising storm depth (``n = NSTORMS`` is the largest); the date is the first hour's stamp. Each
  file holds its storm's ``rain`` (time, latitude, longitude) over the whole transposition domain
  for the ``DURATION``-hour window (``DURATIONCORRECTION`` false), and the arrays of ALL storms on
  ``storm_dim``: ``basinrainfall`` (mm, mask-weighted mean over the study box at the storm's best
  position), ``xlocation``/``ylocation`` (column/row of that position's lower-left cell in the
  domain grid; rows count from the south), ``cattime`` (storm_dim, time; end-of-hour stamps),
  plus ``gridmask``, ``domainmask`` and ``timeresolution`` (minutes). Missing rain is -9999.
* ``Realizations/realization<r>/scenario_<SCENARIONAME>_rlz<r>year<k>storm<j>.nc``: ``rain``
  (time, latitude, longitude) over the study box's cells only (the bounding cells of the box
  mask, not multiplied by the mask), cut from the parent storm's field at the window whose
  lower-left cell is (``xlocation``, ``ylocation``); ``returnperiod`` (years; -9999. for the
  ``j < NPERYEAR`` storms of a year), ``original_stormnumber`` (``n`` of the parent's catalogue
  file); ``time`` = the parent's own stamps plus ``PADSCENARIOS`` hours of zeros. ``k`` is not a
  chronological year: the synthetic years are sorted by their largest storm and ``k`` is the
  rank from the smallest (return period ``NYEARS / (NYEARS - k + 1)``).
* ``<SCENARIONAME>_FreqAnalysis.csv``: header ``prob.exceed,returnperiod,minrain,meanrain,maxrain``
  (min/mean/max over realizations, mm; ``UNCERTAINTY`` ensemble, the default).
"""

from __future__ import annotations

import csv
import json
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
RAINYDAY = ROOT / "data" / "cache" / "flood" / "f4" / "rainyday"
PYTHON = RAINYDAY / "venv" / "bin" / "python"
SCRIPT = RAINYDAY / "src" / "Source" / "RainyDay_Py3.py"
COMMIT = "ff2b80913657b6dfad8380b8bc998ab6362be03e"
SUCCESS = "RainyDay has successfully finished!"

KNOWN_KEYS = frozenset(
    {
        "AREA_EXTENT",
        "ARFANALYSIS",
        "BOX_XMAX",
        "BOX_XMIN",
        "BOX_YMAX",
        "BOX_YMIN",
        "CALCTYPE",
        "CATALOGACCELERATOR",
        "CATALOGNAME",
        "CREATECATALOG",
        "DIAGNOSTICPLOTS",
        "DOMAINFILE",
        "DOMAINSHP",
        "DOMAINTYPE",
        "DURATION",
        "DURATIONCORRECTION",
        "ENHANCEDSST",
        "EXCLUDEMONTHS",
        "EXCLUDESTORMS",
        "FREQANALYSIS",
        "INCLUDEYEARS",
        "INTENSDISTR",
        "MAINPATH",
        "NPERYEAR",
        "NREALIZATIONS",
        "NSTORMS",
        "NYEARS",
        "PADSCENARIOS",
        "POINTAREA",
        "POINTLAT",
        "POINTLIST",
        "POINTLON",
        "RAINDISTRIBUTIONFILE",
        "RAINPATH",
        "RESAMPLING",
        "RETURNLEVELS",
        "RETURNTHRESHOLD",
        "ROTATIONANGLE",
        "SCENARIONAME",
        "SCENARIOS",
        "SEASONALSAMPLING",
        "TIMERESOLUTION",
        "TIMESEPARATION",
        "TRANSPOSITION",
        "UNCERTAINTY",
        "VARIABLES",
        "WATERSHEDSHP",
        "tempscaling",
    }
)  # every cardinfo[...] key in Source/RainyDay_Py3.py at COMMIT
REQUIRED = (
    "MAINPATH",
    "SCENARIONAME",
    "CATALOGNAME",
    "CREATECATALOG",
    "DURATION",
    "tempscaling",
    "VARIABLES",
)
INT_KEYS = ("PADSCENARIOS", "NSTORMS", "NYEARS", "NREALIZATIONS", "NPERYEAR")

SCENARIO_RE = re.compile(
    r"^scenario_(?P<name>.+)_rlz(?P<rlz>\d+)year(?P<year>\d+)storm(?P<storm>\d+)\.nc$"
)
CATALOG_RE = re.compile(r"_storm_(?P<n>\d+)_(?P<date>\d{8})\.nc$")


# --- parameters -----------------------------------------------------------------------------------


def _jsonable(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    return v


def write_params(params: dict, path: Path) -> dict:
    """Write RainyDay's JSON parameter file atomically; returns what was written."""
    unknown = sorted(set(params) - KNOWN_KEYS)
    lowered = {k.lower(): k for k in KNOWN_KEYS}
    if unknown:
        hints = {k: lowered.get(k.lower()) for k in unknown}
        raise ValueError(f"keys RainyDay does not read at {COMMIT[:7]}: {hints}")
    missing = [k for k in REQUIRED if k not in params]
    if missing:
        raise ValueError(f"required keys missing: {missing}")
    for k in INT_KEYS:
        if k in params and not isinstance(params[k], int | np.integer):
            raise ValueError(f"{k} must be an integer (RainyDay checks isinstance(..., int))")
    out = _jsonable(dict(params))
    if str(out["tempscaling"]).lower() not in ("true", "false"):
        raise ValueError("tempscaling must be 'true' or 'false'")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return out


def output_dir(params: dict) -> Path:
    return Path(params["MAINPATH"]) / params["SCENARIONAME"]


# --- running --------------------------------------------------------------------------------------


def run(param_file: Path, log: Path, threads: int = 4, timeout: float | None = None) -> dict:
    """Run RainyDay on ``param_file``; the log goes to ``log``; ``run_record.json`` goes to the
    output folder (MAINPATH/SCENARIONAME)."""
    param_file = Path(param_file).resolve()
    params = json.loads(param_file.read_text())
    out = output_dir(params)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "MPLBACKEND": "Agg",
            "NUMBA_NUM_THREADS": str(threads),
            "OMP_NUM_THREADS": str(threads),
            "PYTHONUNBUFFERED": "1",
        }
    )
    cmd = [str(PYTHON), str(SCRIPT), str(param_file)]
    started = time.time()
    t0 = time.perf_counter()
    with Path(log).open("w", encoding="utf-8") as f:
        try:
            proc = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=str(out.parent),
                timeout=timeout,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = None
    wall = time.perf_counter() - t0
    text = Path(log).read_text(encoding="utf-8", errors="replace")
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    record = {
        "command": cmd,
        "env": {
            k: env[k]
            for k in ("MPLBACKEND", "NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "PYTHONUNBUFFERED")
        },
        "rainyday_commit": COMMIT,
        "param_file": str(param_file),
        "params": params,
        "log": str(Path(log).resolve()),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "wall_time_s": round(wall, 1),
        "exit_code": code,
        "timed_out": code is None,
        "finished": SUCCESS in text,
        "peak_memory_bytes_children": int(peak if sys.platform == "darwin" else peak * 1024),
        "log_tail": text.splitlines()[-15:],
    }
    tmp = out / "run_record.json.tmp"
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    os.replace(tmp, out / "run_record.json")
    return record


# --- reading --------------------------------------------------------------------------------------


def _open(path: Path):
    import xarray as xr

    return xr.open_dataset(path)


def _iso(t) -> str:
    return str(np.datetime64(t, "m")) + "Z"


def read_catalogue(out_dir: Path) -> tuple[list[dict], dict]:
    files = sorted(
        (Path(out_dir) / "StormCatalog").glob("*_storm_*.nc"),
        key=lambda p: int(CATALOG_RE.search(p.name)["n"]),
    )
    if not files:
        return [], {}
    with _open(files[-1]) as ds:
        lat = ds["latitude"].values.astype(float)
        lon = ds["longitude"].values.astype(float)
        cattime = ds["cattime"].values
        depth = ds["basinrainfall"].values.astype(float)
        cx = ds["xlocation"].values.astype(int)
        cy = ds["ylocation"].values.astype(int)
        gm = ds["gridmask"].values
        tres = int(ds["timeresolution"].values) if "timeresolution" in ds else None
    rows_m = np.where(np.nansum(gm, axis=1) > 0)[0]
    cols_m = np.where(np.nansum(gm, axis=0) > 0)[0]
    grid = {
        "lat": lat,
        "lon": lon,
        "box_y0": int(rows_m[0]),
        "box_x0": int(cols_m[0]),
        "mask_h": int(rows_m[-1] - rows_m[0] + 1),
        "mask_w": int(cols_m[-1] - cols_m[0] + 1),
        "timeres_min": tres,
    }
    res = float(np.mean(np.diff(lat)))
    rows = []
    for f in files:
        m = CATALOG_RE.search(f.name)
        n = int(m["n"])
        i = n - 1
        t = cattime[i]
        y, x = cy[i], cx[i]
        rows.append(
            {
                "storm": n,
                "file": str(f),
                "file_date": m["date"],
                "first_stamp_utc": _iso(t[0]),
                "last_stamp_utc": _iso(t[-1]),
                "window_start_utc": _iso(t[0] - np.timedelta64(tres or 60, "m")),
                "duration_h": len(t) * (tres or 60) / 60.0,
                "areal_depth_mm": round(float(depth[i]), 3),
                "x_index": int(x),
                "y_index": int(y),
                "window_lat_center": round(float(lat[y] + (grid["mask_h"] - 1) * res / 2), 5),
                "window_lon_center": round(float(lon[x] + (grid["mask_w"] - 1) * res / 2), 5),
            }
        )
    return rows, grid


def read_freq(out_dir: Path) -> list[dict]:
    files = sorted(Path(out_dir).glob("*_FreqAnalysis*.csv"))
    rows = []
    for f in files:
        with f.open() as fh:
            reader = csv.reader(fh)
            header = [h.strip().lstrip("#").strip() for h in next(reader)]
            for line in reader:
                if line:
                    rows.append(
                        {"file": f.name, **{h: float(v) for h, v in zip(header, line, strict=True)}}
                    )
    return rows


def _box_cells(lat: np.ndarray, lon: np.ndarray, box) -> tuple[np.ndarray, np.ndarray]:
    if box is None:
        return np.ones(lat.shape, bool), np.ones(lon.shape, bool)
    lat_min, lat_max, lon_min, lon_max = box
    return (lat >= lat_min) & (lat <= lat_max), (lon >= lon_min) & (lon <= lon_max)


def scenario_summary(path: Path, box=None, grid: dict | None = None) -> dict:
    """One scenario file as a row. ``box`` = (lat_min, lat_max, lon_min, lon_max): the areal mean
    is over the scenario's cells whose centres lie in it (all its cells when None)."""
    m = SCENARIO_RE.match(Path(path).name)
    if not m:
        raise ValueError(f"not a RainyDay scenario file name: {path}")
    with _open(path) as ds:
        rain = ds["rain"].values.astype(np.float64)
        rain[rain < 0] = np.nan
        t = ds["time"].values
        lat = ds["latitude"].values.astype(float)
        lon = ds["longitude"].values.astype(float)
        rp = float(np.asarray(ds["returnperiod"].values).ravel()[0])
        parent = int(np.asarray(ds["original_stormnumber"].values).ravel()[0])
        sx = int(np.asarray(ds["xlocation"].values).ravel()[0])
        sy = int(np.asarray(ds["ylocation"].values).ravel()[0])
    iy, ix = _box_cells(lat, lon, box)
    sub = rain[:, iy][:, :, ix]
    nan_cells = int(np.isnan(sub).any(axis=0).sum())
    with np.errstate(invalid="ignore"):
        mean_t = np.nanmean(sub.reshape(sub.shape[0], -1), axis=1) if sub.size else np.array([])
    row = {
        "realization": int(m["rlz"]),
        "year_index": int(m["year"]),
        "storm_in_year": int(m["storm"]),
        "return_period_y": rp,
        "parent_storm": parent,
        "source_x_index": sx,
        "source_y_index": sy,
        "first_stamp_utc": _iso(t[0]),
        "last_stamp_utc": _iso(t[-1]),
        "hours": int(len(t)),
        "box_cells": int(sub.shape[1] * sub.shape[2]),
        "box_cells_with_nan": nan_cells,
        "total_mm": round(float(np.nansum(mean_t)), 3),
        "peak_hour_mm": round(float(np.nanmax(mean_t)), 3) if mean_t.size else float("nan"),
        "path": str(path),
    }
    if grid:
        res = float(np.mean(np.diff(grid["lat"])))
        y0 = int(np.argmin(np.abs(grid["lat"] - lat[0])))
        x0 = int(np.argmin(np.abs(grid["lon"] - lon[0])))
        row["shift_x_cells"] = x0 - sx  # east, from the source window to the box
        row["shift_y_cells"] = y0 - sy  # north
        row["shift_lon_deg"] = round((x0 - sx) * res, 5)
        row["shift_lat_deg"] = round((y0 - sy) * res, 5)
    return row


def _write_csv(path: Path, rows: list[dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    os.replace(tmp, path)


def read_outputs(out_dir: Path, box=None) -> dict:
    """Catalogue, frequency table and scenarios of one RainyDay output folder; writes
    ``catalogue.csv`` and ``scenarios.csv`` there."""
    out_dir = Path(out_dir)
    catalogue, grid = read_catalogue(out_dir)
    freq = read_freq(out_dir)
    paths = sorted(
        (out_dir / "Realizations").glob("realization*/scenario_*.nc"),
        key=lambda p: tuple(
            int(v) for v in SCENARIO_RE.match(p.name).group("rlz", "year", "storm")
        ),
    )
    scenarios = [scenario_summary(p, box, grid) for p in paths]
    _write_csv(out_dir / "catalogue.csv", catalogue)
    _write_csv(out_dir / "scenarios.csv", scenarios)
    return {"catalogue": catalogue, "freq": freq, "scenarios": scenarios}


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("params", type=Path)
    r.add_argument("--log", type=Path, required=True)
    r.add_argument("--threads", type=int, default=4)
    o = sub.add_parser("read")
    o.add_argument("out_dir", type=Path)
    o.add_argument(
        "--box", type=float, nargs=4, metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX")
    )
    a = p.parse_args()
    if a.command == "run":
        rec = run(a.params, a.log, a.threads)
        print(json.dumps({k: rec[k] for k in ("wall_time_s", "exit_code", "finished")}))
        raise SystemExit(0 if rec["finished"] and rec["exit_code"] == 0 else 1)
    res = read_outputs(a.out_dir, a.box)
    print(
        json.dumps(
            {
                "storms": len(res["catalogue"]),
                "freq_rows": len(res["freq"]),
                "scenarios": len(res["scenarios"]),
            }
        )
    )


if __name__ == "__main__":
    main()
