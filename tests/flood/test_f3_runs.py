"""F3: the run folder (``sfincs_model.make_run``) and the helpers of the F3 check
(``flood_lab.checks.f3_model``), on dummy files in a temporary folder. No solver, no cache."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flood_lab.checks import f3_model
from flood_lab.hazard import sfincs_model
from flood_lab.hazard.sfincs_model import BASE_FILES, _parse_inp, make_run

FIXTURES = Path(__file__).parent / "fixtures" / "f3"
BASE_INP = """\
mmax                 = 800
tref                 = 20260101 000000
tstart               = 20260101 000000
tstop                = 20260101 020000
dtmaxout             = 7200.0
qinf                 = 0.0
qinf_zmin            = -1.0
zsini                = 0.0
bzsfile              = sfincs.bzs
prcfile              = sfincs.precip
"""


@pytest.fixture
def base(tmp_path: Path) -> Path:
    folder = tmp_path / "base"
    folder.mkdir()
    for name in BASE_FILES:
        (folder / name).write_text(f"dummy {name}\n")
    (folder / "sfincs.inp").write_text(BASE_INP)
    (folder / "sfincs.bzs").write_text("   0.0   0.000   0.000\n7200.0   0.000   0.000\n")
    return folder


def _rows(path: Path) -> list[list[float]]:
    return [[float(v) for v in line.split()] for line in path.read_text().splitlines()]


def test_uniform_run_writes_inp_rain_and_links(base: Path, tmp_path: Path) -> None:
    out = tmp_path / "runs" / "lim_q25"
    spec = make_run(base, out, 25.0, 44.958, rain_h=1.0, after_h=1.5)
    inp = _parse_inp((out / "sfincs.inp").read_text())
    assert inp["qinf"] == "25.0"
    assert inp["tstart"] == "20260101 000000"
    assert inp["tstop"] == "20260101 023000"
    assert inp["dtmaxout"] == "9000.0"
    assert inp["prcfile"] == "sfincs.precip"
    assert "netamprfile" not in inp and "dtwnd" not in inp
    assert inp["mmax"] == "800"  # the base's other settings are kept
    assert _rows(out / "sfincs.precip") == [
        [0.0, 44.958],
        [3600.0, 44.958],
        [3601.0, 0.0],
        [9000.0, 0.0],
    ]
    for name in BASE_FILES:
        if name == "sfincs.bzs":
            continue
        assert (out / name).stat().st_ino == (base / name).stat().st_ino, name
    # the boundary series is rewritten to cover the run, at the base's level, for each point
    assert _rows(out / "sfincs.bzs") == [[0.0, 0.0, 0.0], [9000.0, 0.0, 0.0]]
    assert (base / "sfincs.bzs").read_text().startswith("   0.0")  # the base is untouched
    assert spec["rain"] == {"kind": "uniform", "mm_per_h": 44.958, "hours": 1.0}
    assert json.loads((out / "spec.json").read_text()) == spec
    assert f3_model.scenario_of(spec) == "limited"


def test_a_run_folder_is_never_overwritten(base: Path, tmp_path: Path) -> None:
    out = tmp_path / "run"
    make_run(base, out, 30.0, 54.102, 1.0, 1.0)
    before = (out / "sfincs.inp").read_text()
    with pytest.raises(FileExistsError):
        make_run(base, out, 40.0, 54.102, 1.0, 1.0)
    assert (out / "sfincs.inp").read_text() == before


def test_gridded_rain_writes_netamprfile_and_dtwnd(base: Path, tmp_path: Path) -> None:
    rain = tmp_path / "ida_2021.nc"
    rain.write_bytes(b"not really netcdf")
    out = tmp_path / "ida"
    spec = make_run(base, out, 30.0, None, 17.0, 1.0, netampr=rain, tref="20210901 170000")
    inp = _parse_inp((out / "sfincs.inp").read_text())
    assert inp["netamprfile"] == "precip_2d.nc"
    assert inp["dtwnd"] == "3600.0"
    assert "prcfile" not in inp
    assert not (out / "sfincs.precip").exists()
    assert (out / "precip_2d.nc").read_bytes() == rain.read_bytes()
    assert inp["tref"] == "20210901 170000"
    assert inp["tstop"] == "20210902 110000"
    assert spec["rain"]["kind"] == "gridded"
    assert f3_model.scenario_of(spec) == "replay"


def test_boundary_level_sets_zsini_and_the_series(base: Path, tmp_path: Path) -> None:
    out = tmp_path / "lvl"
    spec = make_run(base, out, 30.0, 54.102, 1.0, 1.0, level=1.0)
    assert _parse_inp((out / "sfincs.inp").read_text())["zsini"] == "1.0"
    assert _rows(out / "sfincs.bzs") == [[0.0, 1.0, 1.0], [7200.0, 1.0, 1.0]]
    assert spec["boundary_level_m"] == 1.0


def test_inp_round_trip() -> None:
    values = {"qinf": "30.0", "tref": "20260101 000000"}
    assert sfincs_model._parse_inp(sfincs_model._format_inp(values)) == values


# --- the check's helpers -------------------------------------------------------------------------


def test_scenario_is_read_from_the_rain_not_the_label() -> None:
    def spec(rate):
        return {"rain": {"kind": "uniform", "mm_per_h": rate, "hours": 1.0}}

    assert f3_model.scenario_of(spec(44.958)) == "limited"
    assert f3_model.scenario_of(spec(54.102)) == "moderate"
    assert f3_model.scenario_of(spec(92.964)) == "extreme"
    assert f3_model.scenario_of(spec(50.0)) == "other"
    assert f3_model.scenario_of({"rain": {"kind": "gridded", "file": "x.nc"}}) == "replay"


def test_freeze_file_is_read_and_every_label_listed_once() -> None:
    freeze = f3_model.load_freeze(FIXTURES / "allowance.toml")
    assert freeze["allowance_mm_per_h"] == 30.0
    labels = f3_model.referenced_labels(freeze["runs"])
    assert labels[:4] == ["lim_q20", "mod_q20", "lim_q30", "mod_q30"]
    assert len(labels) == len(set(labels)) == 10
    assert {"ext_q30", "mod_q30_d05", "mod_q30_d2", "mod_q30_lvl1", "ida_q30", "sep_q30"} <= set(
        labels
    )


def test_optional_tables_may_be_missing() -> None:
    freeze = f3_model.load_freeze(FIXTURES / "allowance_minimal.toml")
    assert f3_model.referenced_labels(freeze["runs"]) == ["lim_q30"]


def test_freeze_file_missing_or_incomplete(tmp_path: Path) -> None:
    with pytest.raises(f3_model.FreezeError, match="not frozen"):
        f3_model.load_freeze(tmp_path / "allowance.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text('allowance_mm_per_h = 30.0\ntag = "P"\n[runs]\ncalibration = []\n')
    with pytest.raises(f3_model.FreezeError, match="runs.frozen"):
        f3_model.load_freeze(bad)


def test_main_without_freeze_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(f3_model, "FREEZE", tmp_path / "allowance.toml")
    monkeypatch.setattr(f3_model, "OUT", tmp_path / "figures")
    monkeypatch.setattr(f3_model.paths, "RECORDS", tmp_path / "records")
    assert f3_model.main() == 1
    assert "not frozen" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def _finished_run(folder: Path, spec: dict, balance: dict, solver: dict | None) -> None:
    folder.mkdir(parents=True)
    (folder / "spec.json").write_text(json.dumps(spec))
    (folder / "balance.json").write_text(json.dumps(balance))
    (folder / "zsmax.tif").write_bytes(b"")
    if solver is not None:
        (folder / "run_run.json").write_text(json.dumps(solver))


def test_a_run_without_output_is_not_run(tmp_path: Path) -> None:
    assert f3_model.load_run(tmp_path, "absent") is None
    (tmp_path / "started").mkdir()
    (tmp_path / "started" / "spec.json").write_text("{}")
    assert f3_model.load_run(tmp_path, "started") is None
    check = f3_model.not_run("water balance started", "rule", "started")
    assert check.passed is None and "not run" in check.note


def test_run_row_takes_every_value_from_the_files(tmp_path: Path) -> None:
    spec = {
        "qinf_mm_per_h": 30.0,
        "rain": {"kind": "gridded", "file": "/somewhere/sep29_2023.nc"},
        "after_h": 2.0,
        "boundary_level_m": 0.0,
        "simulated_s": 108000.0,
    }
    balance = {
        "rain_m3": 1000.0,
        "drained_m3": 600.0,
        "stored_m3": 300.0,
        "out_m3": 95.0,
        "residual_m3": 5.0,
        "residual_share_of_rain": 0.005,
    }
    solver = {"wall_time_s": 12.5, "parsed": {"average_time_step_s": 0.4, "finished": True}}
    _finished_run(tmp_path / "sep", spec, balance, solver)
    run = f3_model.load_run(tmp_path, "sep")
    row = f3_model.run_row(run)
    assert row["scenario"] == "replay"
    assert row["rain_file"] == "sep29_2023.nc"
    assert row["rain_h"] == 28.0  # 30 h simulated less 2 h after
    assert row["wall_time_s"] == 12.5 and row["average_time_step_s"] == 0.4
    assert row["residual_share_of_rain"] == 0.005
    _finished_run(
        tmp_path / "bare",
        spec | {"rain": {"kind": "uniform", "mm_per_h": 1.0, "hours": 1.0}},
        balance,
        None,
    )
    row = f3_model.run_row(f3_model.load_run(tmp_path, "bare"))
    assert row["wall_time_s"] is None and row["average_time_step_s"] is None


def test_return_period_from_the_printed_labels() -> None:
    assert f3_model.return_period("10") == 10.0
    assert f3_model.return_period("'1/10") == 10.0
    assert f3_model.return_period("'1/2") == 2.0


def test_bracket_places_without_interpolating() -> None:
    labels, depths = ["1", "2", "5"], ["1.00", "1.50", "2.00"]
    assert f3_model.bracket(0.9, labels, depths)["placement"] == "below 1"
    assert f3_model.bracket(1.0, labels, depths)["placement"] == "between 1 and 2"
    r = f3_model.bracket(1.77, labels, depths)
    assert r["between"] == ["2", "5"] and r["depths"] == ["1.50", "2.00"]
    assert f3_model.bracket(2.0, labels, depths)["placement"] == "above 5"
    assert "not placed" in f3_model.bracket(1.2, labels, ["1", "0.5", "2"])["placement"]


def test_atlas14_placement_holds_the_intensity_for_each_duration() -> None:
    def row(*depths):
        cols = ("1", "10", "100")
        return {
            c: {"depth": d, "lower90": d, "upper90": d} for c, d in zip(cols, depths, strict=True)
        }

    table = {
        "units": "inches",
        "series": {
            "pds": {
                "return_period_label": "ARI years",
                "return_periods": ["1", "10", "100"],
                "csv_header": ["x", "NOAA Atlas 14 Volume 10 Version 3"],
                "durations": {"60-min": row("1.0", "2.0", "4.0"), "2-hr": row("2.0", "4.0", "8.0")},
            }
        },
    }
    out = f3_model.atlas14_placement(table)["series"]["pds"]
    assert out["version"] == "NOAA Atlas 14 Volume 10 Version 3"
    by = {(r["duration"], r.get("scenario")): r for r in out["rows"]}
    assert by[("30-min", None)]["placement"] == "row not in the table"
    assert by[("60-min", "limited")]["placement"] == "between 1 and 10"  # 1.77 in
    assert by[("60-min", "extreme")]["placement"] == "between 10 and 100"  # 3.66 in
    assert by[("2-hr", "moderate")]["depth_in"] == 4.26
    assert by[("2-hr", "moderate")]["placement"] == "between 10 and 100"


def test_wet_areas_and_depth_classes() -> None:
    depth = np.array([[0.0, 0.05, 0.1016], [0.3048, 0.2, 0.04]])
    where = np.array([[True, True, True], [True, False, True]])
    a = f3_model.wet_areas(depth, where)
    assert a == {"ge_0.05_m_ha": 0.0075, "ge_0.1016_m_ha": 0.005, "ge_0.3048_m_ha": 0.0025}
    assert f3_model.depth_class_map(depth).tolist() == [[0, 1, 2], [3, 2, 0]]


def test_radar_totals_sum_the_steps() -> None:
    forcing = {"tref": "20210901 170000", "hours": 3, "mean_rate_by_step_mm_h": [1.0, 4.0, 2.5]}
    summary = {
        "unit": "mm",
        "hours": [
            {"end_utc": "a", "box_mean_mm": 1.0, "box_max_mm": 3.0},
            {"end_utc": "b", "box_mean_mm": 2.0, "box_max_mm": 5.0},
        ],
        "storm_total_mm": {"point": {"value": 144.5}},
    }
    out = f3_model.radar_totals(forcing, summary)
    assert out["forcing"]["square_mean_total_mm"] == 7.5
    assert out["forcing"]["square_mean_peak_rate_mm_h"] == 4.0
    assert out["radar_box"]["box_mean_total_mm"] == 3.0
    assert out["radar_box"]["box_max_hour_mm"] == 5.0
    assert out["radar_box"]["storm_total_mm"] == {"point": 144.5}
    assert f3_model.radar_totals(None, None) == {}
