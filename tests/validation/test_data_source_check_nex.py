"""NEX-GDDP-CMIP6 assessment on crc-sdk 1.0, on small constructed NetCDF files, offline.

The files hold what NASA's do not: a grid cell one day short of complete, a five-day window
broken near the start of the year, a day absent from the time axis, a leap year, two versions of
one year, a cell centre exactly on the edge of the grown box, and a model with a 365-day
calendar. A temperature file declares kelvin as a one-character attribute, as the real files do.

crc-sdk is fed through a small local web server that answers as NASA's S3 bucket does: object
listings (ListObjectsV2, two keys per page so that continuation is exercised), HEAD with
Content-Length and ETag, and exact byte ranges with If-Match. Only crc-sdk's bucket address
(``crc_sdk._climate_sampling.NEX_BUCKET``) is changed; its listing, header, validator, range
reading and cache code run as they do against NASA. The reference reader is pointed at the same
server through ``reference.nex.ARCHIVE``.
"""

import hashlib
import json
import threading
import urllib.parse
from dataclasses import replace
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import h5netcdf
import numpy as np
import pytest

from data_source_check import build
from data_source_check.adapters.crc import nex as framework
from data_source_check.assessments import nex as assessment
from data_source_check.core import inventory
from data_source_check.reference import nex as reference

VERSIONS = {"crc-sdk": "test"}
BOUNDS = (-98.0, 30.5, -97.0, 31.0)  # grown by half a cell, its south edge touches a cell
LATS = 30.125 + 0.25 * np.arange(6)  # 30.125 ... 31.375
LONS = 261.625 + 0.25 * np.arange(8)  # 0-360 convention: -98.375 ... -96.625
PREFIX = "NEX-GDDP-CMIP6"
CASES = [
    {"recipe": "rx1day", "scenario": "historical", "year": 2014},  # v2.0 beside v1.0
    {"recipe": "rx5day", "scenario": "historical", "year": 2014},
    {"recipe": "rx1day", "scenario": "ssp585", "year": 2052},  # leap year, v1.1 only
    {"recipe": "rx5day", "scenario": "ssp585", "year": 2052},
    {"recipe": "txx", "scenario": "historical", "year": 2014},
    {"recipe": "tnn", "scenario": "historical", "year": 2014},  # day 202 absent
]
OTHER = ("OTHER-365", "historical", "r1i1p1f1", 2014)


def write(path: Path, variable: str, scenario: str, year: int, version: str, calendar: str,
          units: object, values: np.ndarray, days: np.ndarray, *, model: str = "ACCESS-CM2",
          member: str = "r1i1p1f1") -> None:  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5netcdf.File(path, "w") as file:
        file.dimensions = {"time": len(days), "lat": len(LATS), "lon": len(LONS)}
        file.attrs.update(cmip6_source_id=model, scenario=scenario, variant_label=member,
                          version=version, cmip6_license="CC-BY-SA 4.0",
                          cmip6_institution_id="CSIRO")  # fmt: skip
        time = file.create_variable("time", ("time",), dtype="f8", data=days + 0.5)
        time.attrs.update(units=f"days since {year}-01-01", calendar=calendar)
        file.create_variable("lat", ("lat",), dtype="f8", data=LATS)
        file.create_variable("lon", ("lon",), dtype="f8", data=LONS)
        data = file.create_variable(variable, ("time", "lat", "lon"), dtype="f4",
                                    fillvalue=np.float32(1e20))  # fmt: skip
        data[:] = values.astype("f4")
        data.attrs["units"] = units
        data.attrs["missing_value"] = np.float32(1e20)


def place(root: Path, variable: str, scenario: str, year: int, version: str,
          model: str = "ACCESS-CM2", member: str = "r1i1p1f1") -> Path:  # fmt: skip
    suffix = "" if version == "1.0" else f"_v{version}"
    name = f"{variable}_day_{model}_{scenario}_{member}_gn_{year}{suffix}.nc"
    return root / PREFIX / model / scenario / member / variable / name


@pytest.fixture(scope="module")
def bucket(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("nex-bucket")
    rng = np.random.default_rng(7)
    shape = (365, len(LATS), len(LONS))
    rain = rng.gamma(0.4, 6.0, shape) / 86400
    rain[200, :, :] *= 30  # the wettest day
    rain[:, 2, 2] = 1e20  # an ocean cell: no day at all
    rain[100, 3, 3] = 1e20  # one day short: 364 of 365, no value under "every day present"
    rain[2, 3, 4] = 1e20  # breaks three five-day windows at the start of the year
    days = np.arange(365)
    write(place(root, "pr", "historical", 2014, "2.0"), "pr", "historical", 2014, "2.0",
          "proleptic_gregorian", "kg m-2 s-1", rain, days)  # fmt: skip
    write(place(root, "pr", "historical", 2014, "1.0"), "pr", "historical", 2014, "1.0",
          "proleptic_gregorian", "kg m-2 s-1", rain * 0.5, days)  # fmt: skip
    leap = np.concatenate([rain, rain[:1]])  # 366 days
    write(place(root, "pr", "ssp585", 2052, "1.1"), "pr", "ssp585", 2052, "1.1", "standard",
          "kg m-2 s-1", leap, np.arange(366))  # fmt: skip
    heat = 290 + 15 * rng.random(shape)
    heat[:, 2, 2] = 1e20
    write(place(root, "tasmax", "historical", 2014, "1.0"), "tasmax", "historical", 2014, "1.0",
          "proleptic_gregorian", np.bytes_("K"), heat, days)  # fmt: skip
    keep = np.delete(days, 202)  # day 202 is absent from the time axis
    write(place(root, "tasmin", "historical", 2014, "1.0"), "tasmin", "historical", 2014, "1.0",
          "proleptic_gregorian", np.bytes_("K"), heat[keep] - 10, keep)  # fmt: skip
    model, scenario, member, year = OTHER
    write(place(root, "pr", scenario, year, "1.0", model, member), "pr", scenario, year, "1.0",
          "365_day", "kg m-2 s-1", rain, days, model=model, member=member)  # fmt: skip
    return root


class Bucket(BaseHTTPRequestHandler):
    """Enough of S3 for crc-sdk and the reference reader: listings, HEAD, byte ranges."""

    root: Path
    page_size = 2

    def log_message(self, *args: object) -> None:
        pass

    def _etag(self, path: Path) -> str:
        return '"' + hashlib.md5(path.read_bytes()).hexdigest() + '"'  # noqa: S324

    def _listing(self, query: dict[str, list[str]]) -> None:
        prefix = query.get("prefix", [""])[0]
        delimiter = query.get("delimiter", [None])[0]
        keys = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*.nc"))
        keys = [k for k in keys if k.startswith(prefix)]
        if delimiter:
            keys = [k for k in keys if delimiter not in k[len(prefix) :]]
        start = int(query.get("continuation-token", ["0"])[0])
        page = keys[start : start + self.page_size]
        more = start + self.page_size < len(keys)
        body = "".join(
            f"<Contents><Key>{k}</Key><ETag>{self._etag(self.root / k)}</ETag>"
            f"<Size>{(self.root / k).stat().st_size}</Size>"
            "<LastModified>2025-07-01T19:45:55.000Z</LastModified></Contents>"
            for k in page
        )
        token = f"<NextContinuationToken>{start + self.page_size}</NextContinuationToken>"
        xml = ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult '
               'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
               f"<Prefix>{prefix}</Prefix>{body}{token if more else ''}"
               f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"
               "</ListBucketResult>").encode()  # fmt: skip
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(xml)))
        self.end_headers()
        self.wfile.write(xml)

    def _object(self, *, body: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if "list-type" in query:
            return self._listing(query)
        path = self.root / urllib.parse.unquote(parsed.path).lstrip("/")
        if not path.is_file():
            self.send_error(404)
            return None
        data, etag = path.read_bytes(), self._etag(path)
        wanted = self.headers.get("If-Match")
        if wanted is not None and wanted != etag:
            self.send_error(412)
            return None
        status, first, last = 200, 0, len(data) - 1
        if self.headers.get("Range"):
            a, b = self.headers["Range"].removeprefix("bytes=").split("-")
            status, first, last = 206, int(a), min(int(b), len(data) - 1)
        self.send_response(status)
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", formatdate(1751399155, usegmt=True))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {first}-{last}/{len(data)}")
        self.send_header("Content-Length", str(last - first + 1 if body else len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data[first : last + 1])
        return None

    def do_GET(self) -> None:  # noqa: N802
        self._object(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._object(body=False)


@pytest.fixture
def served(bucket: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    handler = type("Handler", (Bucket,), {"root": bucket})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}"
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    monkeypatch.setattr("crc_sdk._climate_sampling.NEX_BUCKET", address)
    monkeypatch.setattr(reference, "ARCHIVE", f"{address}/{PREFIX}")
    yield address
    server.shutdown()
    server.server_close()


LOCK = threading.Lock()  # one crc-sdk call at a time: warnings and the retry hook are global


def in_process(request: dict, output: Path, *, crc_sdk_source: Path | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        output.write_text(json.dumps(framework._run(request)))


def run(tmp_path: Path, rules: reference.Rules | None = None, live: bool = True) -> dict:
    return assessment.assess(tmp_path, live=live, versions=VERSIONS, rules=rules, todo=CASES,
                             bounds=BOUNDS, runner=in_process, other_calendar=OTHER)  # fmt: skip


def outcomes(records: dict) -> dict[str, str]:
    return {check["check"]: check["outcome"] for check in records["checks"]}


def check(records: dict, name: str) -> dict:
    return next(c for c in records["checks"] if c["check"] == name)


def test_reference_reader_on_the_constructed_file(bucket: Path) -> None:
    path = place(bucket, "pr", "historical", 2014, "2.0")
    box = reference.read_box(path, "pr", BOUNDS, 2014, reference.RULES_1_0)
    assert box["lat"] == [30.375, 30.625, 30.875, 31.125]  # 30.375 sits exactly on the edge
    assert box["lon"] == [-98.125, -97.875, -97.625, -97.375, -97.125, -96.875]
    assert box["row_index"] == [1, 2, 3, 4] and box["column_index"] == [1, 2, 3, 4, 5, 6]
    cells = reference.annual_cells(box, "rx1day", 2014, reference.RULES_1_0)
    assert len(cells) == 24
    by_place = {(c["row"], c["column"]): c for c in cells}
    assert by_place[(2, 2)]["value"] is None and by_place[(2, 2)]["valid"] == 0  # ocean
    assert by_place[(3, 3)]["value"] is None and by_place[(3, 3)]["valid"] == 364
    assert by_place[(3, 4)]["value"] is None  # rx1day: one day missing
    five = {
        (c["row"], c["column"]): c
        for c in reference.annual_cells(box, "rx5day", 2014, reference.RULES_1_0)
    }
    assert (five[(3, 4)]["valid"], five[(3, 4)]["expected"]) == (358, 361)
    assert by_place[(1, 1)]["south"] == 30.25 and by_place[(1, 1)]["north"] == 30.5
    # the 0.11 rules (90 per cent of days) still give the cell one day short a value
    old = {(c["row"], c["column"]): c for c in reference.annual_cells(box, "rx1day", 2014)}
    assert old[(3, 3)]["value"] is not None
    half = replace(reference.RULES_1_0, minimum_valid_fraction=0.5)
    series = [1.0, None, 1.0, 1.0, 1.0, 1.0, 1.0, 9.0, 1.0, 1.0]
    outcome = reference.annual_outcome(series, "rx5day", 10, half)
    assert outcome == {"value": pytest.approx(13.0 * 86400), "valid": 4, "expected": 6}


def test_reference_listing_and_versions(served: str) -> None:
    objects = reference.listing(reference.folder("pr", "ACCESS-CM2", "historical", "r1i1p1f1"))
    assert len(objects) == 2  # one page of two keys, then an empty continuation is not asked
    assert reference.versions_by_year(objects) == {2014: ["1.0", "2.0"]}
    everything = reference.listing(f"{PREFIX}/")
    assert len(everything) == 6  # three pages
    header = reference.header(reference.url("pr", OTHER[0], OTHER[1], OTHER[2], "gn", 2014, "1.0"))
    assert header["calendar"] == "365_day"


def test_assessment_on_the_constructed_files(tmp_path: Path, served: str) -> None:
    # an older version already in the reference cache, as in the main checkout
    older = reference.url("pr", "ACCESS-CM2", "historical", "r1i1p1f1", "gn", 2014, "1.0")
    reference.download(older, tmp_path / "reference", live=True)
    records = run(tmp_path)
    got = outcomes(records)
    assert got.pop("versions-served") == "differs"  # version 1.0 of pr 2014 cannot be requested
    bad = [(c["check"], c["summary"]) for c in records["checks"]
           if c["outcome"] != "confirmed" and c["check"] in got]  # fmt: skip
    assert not bad, bad
    assert len(got) == 4 * len(CASES) + 2
    first = check(records, "file[rx1day historical 2014]")["result"]
    assert first["version_read_by_crc_sdk"] == "2.0" and first["versions_listed"] == ["1.0", "2.0"]
    annual = check(records, "annual[rx5day historical 2014]")["result"]
    assert annual["cells_in_box"] == 24 and annual["cells_with_a_value"] == 21
    assert annual["values_compared"] == 24 * len(assessment.COLUMNS)
    gap = check(records, "annual[tnn historical 2014]")["result"]
    assert gap["cells_with_a_value"] == 0 and gap["rows_framework"] == 24  # one day absent
    hottest = check(records, "annual[txx historical 2014]")
    assert {"units-temperature", "statistic-temperature"} <= set(hottest["steps"])
    assert hottest["result"]["cells_with_a_value"] == 23
    leap = next(c for c in records["exploration"]["cases"] if c["case"] == "rx1day ssp585 2052")
    assert (leap["calendar"], leap["days"], leap["file_version"]) == ("standard", 366, "1.1")
    labels = check(records, "labels[rx1day historical 2014]")["result"]
    assert labels["licence_on_resource"] is None and labels["cmip6_license_in_file"]
    assert check(records, "calendar[OTHER-365 rx1day historical 2014]")["result"]["crc_sdk_refuses"]
    empty = check(records, "year-without-file[rx1day historical 2015]")["result"]
    assert empty["rows_framework"] == 24 and not empty["year_listed"]
    differences = records["exploration"]["version_differences"]
    assert any(d["version"] == "1.0" and d["against"] == "2.0" and d["cells_differing"]
               for d in differences)  # fmt: skip
    assert records["options_assessed"] == {"indicator": sorted(framework.INDICATORS)}


@pytest.mark.parametrize(
    "wrong",
    [
        {"seconds_per_day": 86000.0},
        {"kelvin_offset": -273.0},
        {"minimum_valid_fraction": 0.99},
        {"count_windows": False},
        {"window_days": 4},
        {"half_cell_margin": False},
    ],
    ids=lambda wrong: "-".join(f"{k}={v}" for k, v in wrong.items()),
)
def test_a_wrong_reference_rule_ends_as_differs(
    tmp_path: Path, served: str, wrong: dict[str, object]
) -> None:
    got = outcomes(run(tmp_path, rules=replace(reference.RULES_1_0, **wrong)))
    assert "differs" in {v for k, v in got.items() if k.startswith("annual[")}


def test_a_wrong_version_rule_ends_as_differs(
    tmp_path: Path, served: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def oldest(objects: dict, year: int) -> tuple[str, str] | None:
        versions = reference.versions_by_year(objects).get(year)
        if not versions:
            return None
        key = next(
            k
            for k in objects
            if reference.file_version(k.rsplit("/", 1)[-1]) == (year, versions[0])
        )
        return versions[0], key  # fmt: skip

    monkeypatch.setattr(assessment, "_latest", oldest)
    assert outcomes(run(tmp_path))["file[rx1day historical 2014]"] == "differs"


def test_a_file_that_names_another_member_is_read_without_a_check(
    tmp_path: Path, bucket: Path, served: str
) -> None:
    """crc-sdk 1.0 takes the identity from the file's address, not from the file."""
    path = place(bucket, "tasmax", "historical", 2014, "1.0")
    original = path.read_bytes()
    try:
        with h5netcdf.File(path, "a") as file:
            file.attrs["variant_label"] = "r9i1p1f1"
        records = assessment.assess(
            tmp_path, live=True, versions=VERSIONS, todo=[CASES[4]], bounds=BOUNDS,
            runner=in_process, other_calendar=None, year_without_file=None)  # fmt: skip
    finally:
        path.write_bytes(original)
    got = outcomes(records)
    assert got["identity[txx historical 2014]"] == "differs"
    assert got["annual[txx historical 2014]"] == "confirmed"


def test_a_second_run_from_the_stored_answers_gives_the_same_records(
    tmp_path: Path, served: str
) -> None:
    def stable(records: dict) -> list:
        return [{k: v for k, v in check.items() if k != "run_at"} for check in records["checks"]]

    assert stable(run(tmp_path)) == stable(run(tmp_path, live=False))


def test_committed_records_match_the_inventory() -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "nex-gddp-cmip6")
    records = build.load_records("nex-gddp-cmip6")
    assert records is not None
    assert records["versions"]["crc-sdk"].startswith("1.")
    for name, values in records["options_assessed"].items():
        assert sorted(source.assessed_options[name]) == values
    steps = {step.id: step.outcome for step in build.with_outcomes(source, records).statement}
    # NASA's older file versions cannot be requested at 1.0 (crc-sdk reads the highest)
    assert steps["versions-offered"] == "differs"
    assert all(v == "confirmed" for k, v in steps.items() if k != "versions-offered")
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used <= set(steps)
    assert all(" " not in c["versions"]["crc-sdk"] for c in records["checks"])  # no labelled runs
