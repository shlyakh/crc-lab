"""F4: AORC to RainyDay input, RainyDay parameters and outputs, the scenario queue (offline)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from flood_lab.hazard import aorc_rainyday as ar
from flood_lab.hazard import rainyday_run as rr

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("f4_queue", ROOT / "tools" / "flood" / "f4_queue.py")
f4_queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f4_queue)

LAT = np.round(39.0 + 0.5 * np.arange(6), 4)  # 39.0 .. 41.5
LON = np.round(-76.0 + 0.5 * np.arange(7), 4)  # -76.0 .. -73.0


def epoch(y, m, d, h=0) -> int:
    return int((dt.datetime(y, m, d, h) - ar.EPOCH).total_seconds())


def raw_value(stamp: int, iy: int, ix: int) -> int:
    """A deterministic int16 value per AORC stamp and cell (tenths of mm)."""
    return int((stamp // 3600) % 50 + iy * 3 + ix)


def make_store(root: Path, years: list[int], fill_cells=((0, 0),), gap_stamp: int | None = None):
    zarr = pytest.importorskip("zarr")
    for year in years:
        t0, t1 = epoch(year, 1, 1), epoch(year + 1, 1, 1)
        t = np.arange(t0, t1, 3600, dtype=np.int64)
        h = (t // 3600) % 50
        v = (
            h[:, None, None]
            + 3 * np.arange(len(LAT))[None, :, None]
            + np.arange(len(LON))[None, None, :]
        ).astype(np.int16)
        for iy, ix in fill_cells:
            v[:, iy, ix] = ar.FILL
        if gap_stamp is not None and t0 <= gap_stamp < t1:
            v[(gap_stamp - t0) // 3600] = ar.FILL
        g = zarr.open_group(str(root / f"{year}.zarr"), mode="w", zarr_format=2)
        g.create_array("time", data=t.astype(np.float64), chunks=(len(t),))
        g.create_array("latitude", data=LAT, chunks=(len(LAT),))
        g.create_array("longitude", data=LON, chunks=(len(LON),))
        a = g.create_array(
            ar.VAR,
            shape=v.shape,
            dtype="int16",
            chunks=(144, 4, 4),
            fill_value=None,
            chunk_key_encoding={"name": "v2", "separator": "."},
        )
        a[:] = v
        objs = [
            {"key": f"{year}.zarr/{ar.VAR}/{p.name}", "size": p.stat().st_size}
            for p in sorted((root / f"{year}.zarr" / ar.VAR).iterdir())
            if re.fullmatch(r"\d+\.\d+\.\d+", p.name)
        ]
        (root / f"manifest-{year}.json").write_text(json.dumps({"year": year, "objects": objs}))


# --- converter: pure functions ------------------------------------------------------------------


def test_window_is_inclusive_and_needs_ascending_axes():
    ys, xs = ar.window_slices(LAT, LON, (39.5, 40.5), (-75.5, -74.5))
    assert (ys.start, ys.stop, xs.start, xs.stop) == (1, 4, 1, 4)
    with pytest.raises(ValueError):
        ar.window_slices(LAT[::-1], LON, (39.5, 40.5), (-75.5, -74.5))


def test_day_holds_hours_ending_0100_to_2400():
    s = ar.day_end_stamps(dt.date(2021, 9, 1))
    assert len(s) == 24
    assert s[0] == epoch(2021, 9, 1, 1) and s[-1] == epoch(2021, 9, 2, 0)


def test_time_label_maps_to_source_stamps():
    ends = ar.day_end_stamps(dt.date(2021, 9, 1))
    assert (ar.source_stamps(ends, "end") == ends).all()
    assert (ar.source_stamps(ends, "start") == ends - 3600).all()
    with pytest.raises(ValueError):
        ar.source_stamps(ends, "middle")


def test_scaling_and_missing():
    raw = np.array([0, 1, 125, ar.FILL], dtype=np.int16)
    v, miss = ar.scale(raw)
    assert v.dtype == np.float32
    assert np.allclose(v[:3], [0.0, 0.1, 12.5])
    assert v[3] == -9999.0 and miss.tolist() == [False, False, False, True]


def test_days_and_names():
    days = ar.days_of([2004])
    assert len(days) == 366 and ar.file_name(days[0]) == "AORC.20040101.precip.nc"
    assert ar.parse_years("2002-2004") == [2002, 2003, 2004] and ar.parse_years("2021") == [2021]


# --- converter: on a tiny synthetic store --------------------------------------------------------


def test_year_end_hour_comes_from_next_store(tmp_path):
    make_store(tmp_path, [2001, 2002])
    hours = ar.Hours(tmp_path, [2001, 2002], (39.5, 41.0), (-75.0, -73.0))
    d = ar.assemble(hours, dt.date(2001, 12, 31), "end")
    assert d["values"].shape == (24, 4, 5) and d["absent_hours"] == 0
    last = epoch(2002, 1, 1, 0)
    assert d["source_stamps"][-1] == last
    # cell (iy=1, ix=2) of the window is (2, 4) in the store
    assert d["values"][-1, 1, 2] == pytest.approx(raw_value(last, 2, 4) * 0.1, abs=1e-5)
    assert d["missing_values"] == 0


def test_start_label_and_counts(tmp_path):
    make_store(tmp_path, [2001], fill_cells=[(1, 1)], gap_stamp=epoch(2001, 3, 1, 5))
    hours = ar.Hours(tmp_path, [2001], (39.0, 41.5), (-76.0, -73.0))
    d = ar.assemble(hours, dt.date(2001, 3, 1), "start")
    # written stamp 06:00 is AORC stamp 05:00 (the gap): one whole hour missing
    assert d["source_stamps"][5] == epoch(2001, 3, 1, 5)
    assert (d["values"][5] == -9999.0).all()
    ncell = len(LAT) * len(LON)
    assert d["missing_values"] == ncell + 23  # the gap hour, plus the fill cell's other 23 hours
    assert d["cells_missing_all_day"] == 1
    # end label, last day of the only year: D+1 00:00 is in no store
    e = ar.assemble(hours, dt.date(2001, 12, 31), "end")
    assert e["absent_hours"] == 1 and (e["values"][-1] == -9999.0).all()


def test_complete_needs_every_listed_chunk(tmp_path):
    make_store(tmp_path, [2001])
    assert ar.complete(tmp_path, 2001)
    assert not ar.complete(tmp_path, 2002)
    next((tmp_path / "2001.zarr" / ar.VAR).glob("0.*")).unlink()
    assert not ar.complete(tmp_path, 2001)


def test_written_file_sum_equals_store_window(tmp_path):
    pytest.importorskip("netCDF4")
    make_store(tmp_path, [2001, 2002], fill_cells=[(0, 0)])
    out = tmp_path / "out"
    m = ar.convert((39.5, 41.0), (-75.0, -73.0), [2001], out, "end", tmp_path, workers=1)
    assert len(m["files"]) == 365 and m["time_label"] == "end"
    f = out / "AORC.20011231.precip.nc"
    total, nmiss = ar.file_sum(f)
    expected = sum(
        raw_value(s, iy, ix) * 0.1
        for s in ar.day_end_stamps(dt.date(2001, 12, 31))
        for iy in range(1, 5)
        for ix in range(2, 7)
    )
    assert total == pytest.approx(expected, rel=1e-6) and nmiss == 0
    # resumable: a second call writes nothing new
    before = f.stat().st_mtime_ns
    ar.convert((39.5, 41.0), (-75.0, -73.0), [2001], out, "end", tmp_path, workers=1)
    assert f.stat().st_mtime_ns == before
    with pytest.raises(SystemExit):
        ar.convert((39.5, 41.0), (-75.0, -73.0), [2001], out, "start", tmp_path, workers=1)


# --- RainyDay parameters -------------------------------------------------------------------------


def base_params(tmp_path) -> dict:
    return {
        "MAINPATH": tmp_path,
        "SCENARIONAME": "t",
        "CATALOGNAME": "c",
        "CREATECATALOG": True,
        "DURATION": 3,
        "tempscaling": False,
        "VARIABLES": {"rainname": "precrate", "latname": "latitude", "longname": "longitude"},
        "PADSCENARIOS": 1,
    }


def test_write_params_strings_and_required(tmp_path):
    p = tmp_path / "p.json"
    out = rr.write_params(base_params(tmp_path), p)
    back = json.loads(p.read_text())
    assert back == out
    assert back["CREATECATALOG"] == "true" and back["tempscaling"] == "false"
    assert back["MAINPATH"] == str(tmp_path)


def test_write_params_refuses_unknown_or_missing(tmp_path):
    bad = base_params(tmp_path)
    bad["TEMPSCALING"] = "false"
    with pytest.raises(ValueError, match="tempscaling"):
        rr.write_params(bad, tmp_path / "p.json")
    missing = base_params(tmp_path)
    del missing["tempscaling"]
    with pytest.raises(ValueError, match="required"):
        rr.write_params(missing, tmp_path / "p.json")
    notint = base_params(tmp_path)
    notint["PADSCENARIOS"] = 1.0
    with pytest.raises(ValueError, match="integer"):
        rr.write_params(notint, tmp_path / "p.json")


# --- RainyDay outputs ----------------------------------------------------------------------------


def _write(ds, path: Path) -> None:
    engine = "netcdf4" if importlib.util.find_spec("netCDF4") else "h5netcdf"
    ds.to_netcdf(path, engine=engine)


def make_outputs(out: Path) -> None:
    xr = pytest.importorskip("xarray")
    lat = 40.0 + 0.01 * np.arange(10)
    lon = -74.0 + 0.01 * np.arange(12)
    t1 = np.datetime64("2021-09-01T23:00")
    t2 = np.datetime64("2021-07-08T10:00")
    cattime = np.array(
        [t2 + np.timedelta64(h, "h") for h in range(3)]
        + [t1 + np.timedelta64(h, "h") for h in range(3)]
    ).reshape(2, 3)
    gm = np.zeros((10, 12), np.float32)
    gm[4:6, 5:8] = 1.0
    (out / "StormCatalog").mkdir(parents=True)
    for i, n in enumerate((1, 2)):
        ds = xr.Dataset(
            {
                "rain": (("time", "latitude", "longitude"), np.ones((3, 10, 12), np.float32)),
                "basinrainfall": (("storm_dim",), np.array([20.0, 80.0], np.float32)),
                "xlocation": (("storm_dim",), np.array([1, 3], np.int32)),
                "ylocation": (("storm_dim",), np.array([2, 0], np.int32)),
                "cattime": (("storm_dim", "time"), cattime),
                "gridmask": (("latitude", "longitude"), gm),
                "domainmask": (("latitude", "longitude"), np.ones_like(gm)),
                "timeresolution": ((), np.int32(60)),
            },
            coords={"time": cattime[i], "latitude": lat, "longitude": lon},
        )
        date = str(cattime[i, 0])[:10].replace("-", "")
        _write(ds, out / "StormCatalog" / f"c_storm_{n}_{date}.nc")
    rdir = out / "Realizations" / "realization1"
    rdir.mkdir(parents=True)
    for year, parent, rp in ((1, 1, 1.0), (2, 2, 2.0)):
        times = cattime[parent - 1].tolist() + [cattime[parent - 1][-1] + np.timedelta64(1, "h")]
        rain = np.zeros((4, 2, 3), np.float32)
        rain[0] = 10.0
        rain[1] = [[20.0, 20.0, 20.0], [20.0, 20.0, -9999.0 if year == 1 else 20.0]]
        ds = xr.Dataset(
            {
                "rain": (["time", "latitude", "longitude"], rain),
                "xlocation": (["scalar_dim"], np.array([2], np.int32)),
                "ylocation": (["scalar_dim"], np.array([1], np.int32)),
                "returnperiod": (["scalar_dim"], np.array([rp], np.float32)),
                "original_stormnumber": (["scalar_dim"], np.array([parent], np.int16)),
            },
            coords={
                "time": np.array(times),
                "latitude": lat[4:6],
                "longitude": lon[5:8],
                "scalar_dim": [0],
            },
        )
        _write(ds, rdir / f"scenario_t_rlz1year{year}storm1.nc")
    (out / "t_FreqAnalysis.csv").write_text(
        "prob.exceed,returnperiod,minrain,meanrain,maxrain\n  0.50,  2.00, 10.00, 11.00, 12.00\n"
    )


def test_read_outputs_tables(tmp_path):
    make_outputs(tmp_path)
    res = rr.read_outputs(tmp_path)
    cat = res["catalogue"]
    assert [c["storm"] for c in cat] == [1, 2]
    assert cat[1]["areal_depth_mm"] == 80.0 and cat[1]["first_stamp_utc"] == "2021-09-01T23:00Z"
    assert cat[1]["window_start_utc"] == "2021-09-01T22:00Z" and cat[1]["duration_h"] == 3.0
    assert cat[0]["x_index"] == 1 and cat[0]["y_index"] == 2
    assert res["freq"][0]["returnperiod"] == 2.0 and res["freq"][0]["maxrain"] == 12.0
    s1, s2 = res["scenarios"]
    assert (s1["realization"], s1["year_index"], s1["storm_in_year"]) == (1, 1, 1)
    assert s2["parent_storm"] == 2 and s2["return_period_y"] == 2.0 and s2["hours"] == 4
    assert s2["first_stamp_utc"] == "2021-09-01T23:00Z"
    assert s2["total_mm"] == pytest.approx(30.0) and s2["peak_hour_mm"] == pytest.approx(20.0)
    # the -9999 cell is missing, not zero: the mean is over the 5 cells that have rain
    assert s1["box_cells_with_nan"] == 1 and s1["total_mm"] == pytest.approx(30.0)
    # box rows 4-5, columns 5-7; source window at x=2, y=1
    assert (s1["shift_x_cells"], s1["shift_y_cells"]) == (3, 3)
    assert (tmp_path / "scenarios.csv").read_text().splitlines()[0].startswith("realization,")
    assert len((tmp_path / "catalogue.csv").read_text().splitlines()) == 3


def test_box_selects_cells_by_centre(tmp_path):
    make_outputs(tmp_path)
    p = tmp_path / "Realizations" / "realization1" / "scenario_t_rlz1year2storm1.nc"
    row = rr.scenario_summary(p, box=(40.035, 40.045, -73.955, -73.925))
    assert row["box_cells"] == 3


# --- queue ---------------------------------------------------------------------------------------


def test_queue_entry_passes_other_keys_through():
    item = {"label": "cat_r0001", "scenario": "s.nc", "weight": 2.5, "stratum": "T1", "rank": 1}
    rec = {"tref": "20210901 220000", "hours": 4}
    e = f4_queue.entry(item, rec, Path("/f/cat_r0001.nc"))
    assert e == {
        "label": "cat_r0001",
        "qinf": 30,
        "netampr": "/f/cat_r0001.nc",
        "tref": "20210901 220000",
        "rain_h": 4,
        "after_h": 1,
        "weight": 2.5,
        "scenario": "s.nc",
        "stratum": "T1",
        "rank": 1,
    }
    assert f4_queue.entry({**item, "qinf": 20}, rec, Path("x"))["qinf"] == 20


def test_queue_builds_once_and_reports_failures(tmp_path):
    fake = tmp_path / "fake_builder.py"
    fake.write_text(
        "import json,sys,pathlib\n"
        "scen,out=sys.argv[2],pathlib.Path(sys.argv[3])\n"
        "if 'bad' in scen: sys.exit('no such scenario')\n"
        "out.write_text('nc')\n"
        "out.with_suffix('.json').write_text(json.dumps({'tref':'20210901 220000','hours':4}))\n"
    )
    builder = [sys.executable, str(fake)]
    sel = [
        {"label": "a", "scenario": str(tmp_path / "a.nc"), "weight": 1.0},
        {"label": "b", "scenario": str(tmp_path / "bad.nc"), "weight": 1.0},
    ]
    q, failed = f4_queue.make_queue(sel, tmp_path / "forcing", builder)
    assert [x["label"] for x in q] == ["a"] and [f[0] for f in failed] == ["b"]
    # resumable: the forcing exists, the builder is not called again
    q2, _ = f4_queue.make_queue(sel[:1], tmp_path / "forcing", ["false"])
    assert q2 == q
    with pytest.raises(ValueError):
        f4_queue.make_queue(sel[:1] * 2, tmp_path / "forcing", builder)
