"""NEX-GDDP-CMIP6 assessment on small constructed NetCDF files, offline.

The files hold what NASA's do not: a missing day, grid cells just above and just below the
90 per cent line, a 365-day calendar in a leap year, and a cell centre exactly on the edge
of the grown box. A temperature file declares kelvin as a one-character attribute, as the
real files do.
"""

import io
import json
import threading
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError

import h5netcdf
import numpy as np
import pytest

from data_source_check import build
from data_source_check.adapters.crc import nex as framework
from data_source_check.assessments import nex as assessment
from data_source_check.core import inventory
from data_source_check.reference import nex as reference

VERSIONS = {"crc-sdk": "test"}
BOUNDS = (-98.0, 30.5, -97.0, 31.0)  # grown by half a cell, its south edge is a cell centre
LATS = 30.125 + 0.25 * np.arange(6)  # 30.125 ... 31.375
LONS = 261.625 + 0.25 * np.arange(8)  # 0-360 convention: -98.375 ... -96.625
CASES = [
    {"recipe": "rx1day", "scenario": "historical", "year": 2014, "version": "1.0"},
    {"recipe": "rx5day", "scenario": "historical", "year": 2014, "version": "1.0"},
    {"recipe": "rx1day", "scenario": "ssp585", "year": 2052, "version": "1.1"},
    {"recipe": "rx5day", "scenario": "ssp585", "year": 2052, "version": "1.1"},
    {"recipe": "txx", "scenario": "historical", "year": 2014, "version": "1.0"},
]


def write(path: Path, variable: str, scenario: str, year: int, version: str, calendar: str,
          units: object, values: np.ndarray, days: np.ndarray) -> None:  # fmt: skip
    with h5netcdf.File(path, "w") as file:
        file.dimensions = {"time": len(days), "lat": len(LATS), "lon": len(LONS)}
        file.attrs.update(cmip6_source_id="ACCESS-CM2", scenario=scenario,
                          variant_label="r1i1p1f1", version=version,
                          cmip6_license="CC-BY-SA 4.0", cmip6_institution_id="CSIRO")  # fmt: skip
        time = file.create_variable("time", ("time",), dtype="f8", data=days + 0.5)
        time.attrs.update(units=f"days since {year}-01-01", calendar=calendar)
        file.create_variable("lat", ("lat",), dtype="f8", data=LATS)
        file.create_variable("lon", ("lon",), dtype="f8", data=LONS)
        data = file.create_variable(variable, ("time", "lat", "lon"), dtype="f4",
                                    fillvalue=np.float32(1e20))  # fmt: skip
        data[:] = values.astype("f4")
        data.attrs["units"] = units
        data.attrs["missing_value"] = np.float32(1e20)


@pytest.fixture(scope="module")
def bucket(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("nex")
    rng = np.random.default_rng(7)
    shape = (365, len(LATS), len(LONS))
    rain = rng.gamma(0.4, 6.0, shape) / 86400
    rain[:, 2, 2] = 1e20  # an ocean cell: no day at all
    # with day 202 absent from the 2014 file, these two cells straddle the 90 per cent line
    rain[10:45, 3, 3] = 1e20  # 329 days left in 2014: exactly on the line, kept
    rain[10:46, 3, 4] = 1e20  # 328 days left in 2014: just under it, no value
    rain[200, :, :] *= 30  # the wettest day; five-day windows around the gap below must not use it
    keep = np.delete(np.arange(365), 202)  # day 202 is absent from the time axis
    write(root / "pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014.nc", "pr", "historical", 2014,
          "1.0", "proleptic_gregorian", "kg m-2 s-1", rain[keep], keep)  # fmt: skip
    write(root / "pr_day_ACCESS-CM2_ssp585_r1i1p1f1_gn_2052_v1.1.nc", "pr", "ssp585", 2052,
          "1.1", "365_day", "kg m-2 s-1", rain, np.arange(365))  # fmt: skip
    heat = 290 + 15 * rng.random(shape)
    write(root / "tasmax_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014.nc", "tasmax", "historical",
          2014, "1.0", "proleptic_gregorian", np.bytes_("K"), heat, np.arange(365))  # fmt: skip
    return root


class Response(io.BytesIO):
    status = 200

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"ETag": '"x"', "Last-Modified": "now", "Content-Length": str(len(data))}


@pytest.fixture
def served(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def local(address: str) -> Path:
        path = bucket / address.rsplit("/", 1)[-1]
        if not path.exists():
            raise HTTPError(address, 404, "Not Found", None, None)  # type: ignore[arg-type]
        return path

    def fake_urlopen(request, timeout=None):  # noqa: ANN001, ANN202
        path = local(request.full_url)
        return Response(b"" if request.get_method() == "HEAD" else path.read_bytes())

    def fake_backend(address: str, cache_dir: object):  # noqa: ANN202
        path = bucket / address.rsplit("/", 1)[-1]
        if not path.exists():
            raise FileNotFoundError(address)
        return h5netcdf.File(path, "r")

    monkeypatch.setattr("data_source_check.reference.nex.urlopen", fake_urlopen)
    monkeypatch.setattr("crc_sdk.workflows.nex._open_backend", fake_backend)


LOCK = threading.Lock()  # recording warnings is not safe across threads


def in_process(request: dict, output: Path, *, crc_sdk_source: Path | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        output.write_text(json.dumps(framework._run(request)))


def run(tmp_path: Path, rules: reference.Rules | None = None, live: bool = True) -> dict:
    return assessment.assess(tmp_path, live=live, versions=VERSIONS, rules=rules, todo=CASES,
                             bounds=BOUNDS, runner=in_process)  # fmt: skip


def outcomes(records: dict) -> dict[str, str]:
    return {check["check"]: check["outcome"] for check in records["checks"]}


def test_reference_reader_on_the_constructed_file(bucket: Path) -> None:
    box = reference.read_box(bucket / "pr_day_ACCESS-CM2_historical_r1i1p1f1_gn_2014.nc", "pr",
                             BOUNDS, 2014)  # fmt: skip
    assert box["lat"] == [30.375, 30.625, 30.875, 31.125]  # 30.375 sits exactly on the edge
    assert box["lon"] == [-98.125, -97.875, -97.625, -97.375, -97.125, -96.875]
    assert box["days_expected"] == 365 and len(box["day_offsets"]) == 364
    assert 202 not in box["day_offsets"] and box["attrs"]["version"] == "1.0"
    rows = reference.annual_rows(box, "rx1day", 2014)
    cells = {(row["latitude"], row["longitude"]) for row in rows}
    assert len(rows) == 4 * 6 - 2  # the ocean cell and the cell under the 90 per cent line
    assert (30.875, -97.625) in cells and (30.875, -97.375) not in cells
    assert reference.annual_value([1.0, None, 1.0, 1.0, 1.0, 1.0, 1.0, 9.0, 1.0, 1.0], "rx5day",
                                  10) == pytest.approx(13.0 * 86400)  # fmt: skip
    assert reference.annual_value([None] * 2 + [1.0] * 8, "rx1day", 10) is None  # under 90 %


def test_assessment_on_the_constructed_files(tmp_path: Path, served: None) -> None:
    records = run(tmp_path)
    got = outcomes(records)
    # kelvin written as one character is accepted since crc-sdk 0.11.2 (CRC-001-NEX)
    assert not [name for name in got if name.startswith("units[")]
    assert got.pop("versions-served") == "confirmed"  # nothing beyond 1.0-1.2 in this bucket
    bad = [(c["check"], c["summary"]) for c in records["checks"] if c["outcome"] != "confirmed"]
    assert not bad, bad
    assert len(got) == 11 and got["missing-version"] == "confirmed"
    hottest = next(c for c in records["checks"] if c["check"] == "annual[txx historical 2014 v1.0]")
    assert {"units-temperature", "statistic-temperature"} <= set(hottest["steps"])
    assert hottest["result"]["values_compared"] > 0
    assert "txx" in records["options_assessed"]["recipe"]
    annual = next(
        c for c in records["checks"] if c["check"] == "annual[rx5day historical 2014 v1.0]"
    )
    assert annual["result"]["rows_reference"] == 22 and annual["result"]["cells_in_box"] == 24
    leap = next(c for c in records["exploration"]["cases"] if c["case"].startswith("rx1day ssp585"))
    assert (leap["calendar"], leap["days"]) == ("365_day", 365)


@pytest.mark.parametrize(
    "wrong",
    [
        {"seconds_per_day": 86000.0},
        {"minimum_valid_fraction": 0.89},
        {"minimum_valid_fraction": 0.91},
        {"window_days": 4},
        {"half_cell_margin": False},
    ],
    ids=lambda wrong: "-".join(f"{k}={v}" for k, v in wrong.items()),
)
def test_a_wrong_reference_rule_ends_as_differs(
    tmp_path: Path, served: None, wrong: dict[str, object]
) -> None:
    got = outcomes(run(tmp_path, rules=replace(reference.Rules(), **wrong)))
    assert "differs" in {v for k, v in got.items() if k.startswith("annual[")}


def test_a_second_run_from_the_stored_answers_gives_the_same_records(
    tmp_path: Path, served: None
) -> None:
    def stable(records: dict) -> list:
        return [{k: v for k, v in check.items() if k != "run_at"} for check in records["checks"]]

    assert stable(run(tmp_path)) == stable(run(tmp_path, live=False))


def test_committed_records_match_the_inventory() -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "nex-gddp-cmip6")
    records = build.load_records("nex-gddp-cmip6")
    assert records is not None
    for name, values in records["options_assessed"].items():
        assert sorted(source.assessed_options[name]) == values
    steps = {step.id: step.outcome for step in build.with_outcomes(source, records).statement}
    # the temperature steps differed or went unchecked until crc-sdk 0.11.2 (CRC-001-NEX);
    # NASA's version 2.0 files still cannot be requested (CRC-012-NEX)
    assert steps["versions-offered"] == "differs"
    assert all(v == "confirmed" for k, v in steps.items() if k != "versions-offered")
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used <= set(steps)
    assert all(" " not in c["versions"]["crc-sdk"] for c in records["checks"])  # no labelled runs
