"""GHCNh assessment on constructed station files, offline (crc-sdk 1.0).

The files are built to sit on every rule's boundary (23 against 24 hours, 364 of 365 days,
329 of 365 against 329 of 366 days at a 0.9 fraction, 61.8 against 61.9 degrees, listed
against unlisted source codes, a station that moves, reports that stop crc-sdk's read),
written in both of NOAA's formats and served to both sides: to the reference through a fake
``urlopen``, to crc-sdk through a stand-in for its one download function,
``crc_sdk._source_io._download``. A second run replays crc-sdk's cache with ``Cache.offline``.
"""

import csv
import io
import math
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from shutil import copyfile
from urllib.error import HTTPError

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_source_check import build
from data_source_check.assessments import ghcnh as assessment
from data_source_check.core import inventory
from data_source_check.reference import ghcnh as reference

A, B = "USW00099901", "USW00099902"  # a station with every edge case; one that moves in 2001
C, D, E, F = "USW00099903", "USW00099904", "USW00099905", "USW00099906"  # refused by crc-sdk
STATIONS = [A, B, C, D, E, F]
YEARS = (2001, 2007)
VERSIONS = {"crc-sdk": "test"}
#: days with 23 hours in each year of station A (2005 has no file; 2006 is an empty file)
SHORT = {2001: 0, 2002: 1, 2003: 36, 2004: 37, 2007: 0}


def reports(station: str, year: int) -> list[tuple]:
    """Hourly reports for one station-year with the edge cases placed by the year."""
    rows = []
    start = datetime(year, 1, 1)
    days = 366 if year % 4 == 0 else 365
    short = SHORT.get(year, 0) if station == A else 0
    for d in range(days):
        # short days lose the last UTC hour; they alternate with full days
        hours = 23 if (d % 2 == 0 and d < 2 * short) else 24
        for h in range(hours):
            t = start + timedelta(days=d, hours=h, minutes=51)
            value = 20.0 + 10 * math.sin(d / 58.0) + 5 * math.sin(h / 3.8)
            lat = 30.0 + (0.06 if station == B and year == 2001 and d > 200 else 0.0)
            quality = "5" if h % 2 else ""
            rows.append(
                (station, t.isoformat(), lat, -97.5, 204.2, round(value, 1), quality, "343")
            )
    day = lambda d, h, m=10: (start + timedelta(days=d, hours=h, minutes=m)).isoformat()  # noqa: E731
    step = (year - 2001) * 0.7  # extremes differ by year
    extra = [
        (61.8 - step, "", "343", 100),  # in 2001 the upper limit itself: accepted
        (61.9, "", "343", 100),  # just above it is not
        (-93.2 + step, " 1 ", "220", 101),  # code 1 from a listed source, with padding
        (-93.3, "1", "220", 101),  # below the lower limit
        (60.5, "A", "343", 102),  # a quality code that is not accepted
        (60.6, "5", "999", 102),  # code 5 from an unlisted source
        (60.7, "1", "999", 102),  # code 1 from an unlisted source
        (60.8, "5", "220", 102),  # code 5 from a source listed only for code 1
        (None, "", "343", 103),  # no temperature: kept with no value
    ]
    if short:  # the year's extremes on its first day, which has 23 hours
        extra += [(61.7, "", "343", 0), (-93.1, "", "343", 0)]
    for minute, (value, quality, code, d) in enumerate(extra, start=10):  # each at its own time
        rows.append((station, day(d, 5, minute), 30.0, -97.5, 204.2, value, quality, code))
    rows.append((station, day(0, 3, 5), 30.0, -97.5, 204.2, 21.0, "", "343"))  # a second report
    rows.append((station, day(0, 3, 6), 30.0, -97.5, 204.2, 21.0, "", "343"))  # in the same hour
    if station == C:
        rows.append(("USW00000000", day(50, 5), 30.0, -97.5, 204.2, 21.5, "", "343"))
    if station == D:
        rows.append(rows[10])  # two reports at one time and position
    if station == E:
        rows.append((station, f"{year - 1}-12-31T23:59:00", 30.0, -97.5, 204.2, 21.5, "", "343"))
    if station == F:
        rows.append((station, day(60, 5), 30.0, -97.5, 204.2, float("inf"), "", "343"))
    return rows


def has_file(station: str, year: int) -> bool:
    if year == 2005:
        return False
    if station == B:
        return year <= 2003
    return station == A or year == 2001


@pytest.fixture(scope="module")
def bucket(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("bucket")
    for station in STATIONS:
        for year in range(YEARS[0], YEARS[1] + 1):
            if not has_file(station, year):
                continue  # NOAA has no file: 404
            rows = [] if (station, year) == (A, 2006) else reports(station, year)
            columns = {name: [row[i] for row in rows] for i, name in enumerate(reference.COLUMNS)}
            types = [pa.string(), pa.string()] + [pa.float64()] * 4 + [pa.string(), pa.string()]
            table = pa.table(
                {
                    name: pa.array(columns[name], type=t)
                    for name, t in zip(columns, types, strict=True)
                }
                | {"wind_speed": pa.array([1.0] * len(rows), type=pa.float64())}
            )
            pq.write_table(table, root / f"GHCNh_{station}_{year}.parquet")
            with (root / f"GHCNh_{station}_{year}.psv").open("w", encoding="utf-8") as out:
                out.write("|".join(("Station_name", *reference.COLUMNS, "wind_speed")) + "\n")
                for row in rows:
                    cells = ["" if v is None else str(v) for v in row]
                    out.write("|".join(("TEST AP", *cells, "1.0")) + "\n")
    with (root / "ghcnh-station-list.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["GHCN_ID", "LATITUDE", "LONGITUDE", "ELEVATION", "STATE", "NAME"])
        writer.writerow(["USW00099900", "30.0", "10.0", "1", "", "OUTSIDE THE BOX"])
        for station in STATIONS:
            writer.writerow([station, "30.0", "-97.5", "204.2", "TX", f"TEST {station[-1]} AP"])
        writer.writerow(["USW00099907", "", "", "", "TX", "NO POSITION"])
        writer.writerow(["USW00099908", "31.0", "-98.0", "", "TX", ""])  # blank name
        writer.writerow(["USW00099909", "36.500704", "-93.508292", "", "", "ON THE CORNER"])
    return root


class Response(io.BytesIO):
    status = 200

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"ETag": '"x"', "Last-Modified": "now", "Content-Length": str(len(data))}


@pytest.fixture
def served(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def local(address: str) -> Path | None:
        path = bucket / address.rsplit("/", 1)[-1]
        return path if path.exists() else None

    def fake_urlopen(request, timeout=None):  # noqa: ANN001, ANN202
        path = local(request.full_url)
        if path is None:
            raise HTTPError(request.full_url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        return Response(path.read_bytes())

    def fake_download(uri: str, path: Path) -> int:  # crc-sdk's only download function
        found = local(uri)
        if found is None:
            return 404
        copyfile(found, path)
        return 200

    monkeypatch.setattr("data_source_check.reference.ghcnh.urlopen", fake_urlopen)
    monkeypatch.setattr("crc_sdk._source_io._download", fake_download)


#: crc-sdk's answers do not depend on the reference rules; the fault tests reuse them
_ANSWERS: dict[tuple, dict] = {}


@pytest.fixture
def remembered(monkeypatch: pytest.MonkeyPatch, served: None) -> None:
    real = assessment.framework.annual

    def annual(indicator, stations, years, cache_dir, *, live, fraction=None, log=None):  # noqa: ANN001, ANN202
        key = (indicator, tuple(stations), years, fraction)
        if key not in _ANSWERS:
            _ANSWERS[key] = real(
                indicator, stations, years, cache_dir, live=live, fraction=fraction
            )
        return _ANSWERS[key]

    monkeypatch.setattr(assessment.framework, "annual", annual)


def run(tmp_path: Path, rules: reference.Rules1 | None = None, live: bool = True) -> dict:
    return assessment.assess(
        tmp_path,
        live=live,
        versions=VERSIONS,
        rules=rules,
        stations=STATIONS,
        years=YEARS,
        psv_sample=4,
    )


def outcomes(records: dict) -> dict[str, str]:
    return {check["check"]: check["outcome"] for check in records["checks"]}


def rows_of(bucket: Path, station: str, year: int, fraction: float | None = None, kind="parquet"):
    found = reference.read_reports(bucket / f"GHCNh_{station}_{year}.{kind}", kind)
    return reference.annual_rows(found, station, year, fraction=fraction)


def test_reference_rules_on_the_constructed_years(bucket: Path) -> None:
    first = rows_of(bucket, A, 2001)
    (row,) = first["rows"]
    assert (row["value_max"], row["value_min"]) == (61.8, -93.2)  # the limits, nothing beyond
    assert (row["valid_days"], row["complete"], row["minimum_fraction"]) == (365, True, 1.0)
    assert row["support_id"] == reference.support_id(A, -97.5, 30.0)
    assert first["excluded"] == {
        "no temperature": 1,
        "outside the physical range": 2,
        "quality code 1 from a source not accepted": 1,
        "quality code 5 from a source not accepted": 2,
        "quality code not accepted": 1,
    }
    assert rows_of(bucket, A, 2001, kind="psv") == first  # NOAA's two formats give the same rows
    one_short = rows_of(bucket, A, 2002)["rows"][0]
    assert (one_short["valid_days"], one_short["complete"]) == (364, False)  # every day, by default
    relaxed = rows_of(bucket, A, 2002, 0.9)["rows"][0]
    assert relaxed["complete"] and relaxed["value_max"] == 61.8 - 0.7  # the 23-hour day is ignored
    assert rows_of(bucket, A, 2003, 0.9)["rows"][0]["complete"]  # 329 of 365 >= 0.9
    assert not rows_of(bucket, A, 2004, 0.9)["rows"][0]["complete"]  # 329 of 366 < 0.9
    assert rows_of(bucket, A, 2006)["unavailable"]  # a file with no report: no row
    moved = rows_of(bucket, B, 2001)["rows"]
    assert [(r["latitude"], r["valid_days"], r["complete"]) for r in moved] == [
        (30.0, 201, False),
        (30.06, 164, False),
    ]
    for station, reason in (
        (C, "a report of another station"),
        (D, "two reports at one time and position"),
        (E, "a report of another year"),
        (F, "a temperature that is not a finite number"),
    ):
        assert rows_of(bucket, station, 2001)["error"] == reason


def test_assessment_confirms_every_check_on_the_constructed_files(
    tmp_path: Path, served: None
) -> None:
    records = run(tmp_path)
    bad = [(c["check"], c["result"]) for c in records["checks"] if c["outcome"] != "confirmed"]
    assert not bad, bad
    assert len(records["checks"]) == 13
    annual = next(c for c in records["checks"] if c["check"] == "annual[temperature_max]")
    result = annual["result"]
    assert result["stations_refused_reference"] == [C, D, E, F]
    assert result["stations_refused_framework"] == [C, D, E, F]  # crc-sdk refuses them too
    assert result["rows_with_a_value_reference"] == 4  # A 2001, A 2007, B 2002, B 2003
    assert result["station_years_without_a_row_reference"] == 6  # A 2005 and 2006, B 2004-2007
    relaxed = next(
        c for c in records["checks"] if c["check"] == "annual[temperature_min, coverage 0.9]"
    )
    assert relaxed["result"]["rows_with_a_value_reference"] == 6  # and A 2002, A 2003
    stations = next(c for c in records["checks"] if c["check"] == "stations[box]")
    assert stations["result"]["rows_reference"] == 8  # the six, the blank name and the corner
    explored = records["exploration"]
    assert explored["station_years_with_more_than_one_position"] == 1
    assert explored["station_years_complete_by_0.11_rules"] >= explored["station_years_complete"]
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "ghcnh")
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used == {step.id for step in source.statement}  # every step has a check
    assert records["options_assessed"]["indicator"] == sorted(source.assessed_options["indicator"])


@pytest.mark.parametrize(
    "wrong",
    [
        {"hours_per_day": 23},
        {"complete_fraction": 0.99},
        {"day_offset_hours": -6},
        {"highest": 62.0},
        {"lowest": -93.3},
        {"quality_codes": ("", "1", "5", "A")},
        {"sources_for_5": (*reference.Rules1().sources_for_5, "999")},
        {"sources_for_1": (*reference.Rules1().sources_for_1, "999")},
        {"split_positions": False},
        {"refuse_bad_reports": False},
        {"cell_resolution": 8},
    ],
    ids=lambda wrong: next(iter(wrong)),
)
def test_a_wrong_reference_rule_ends_as_differs(
    tmp_path: Path, remembered: None, wrong: dict[str, object]
) -> None:
    """Each rule, broken on its own, must be caught by the comparison with crc-sdk."""
    got = outcomes(run(tmp_path, rules=replace(reference.Rules1(), **wrong)))
    annual = {name: outcome for name, outcome in got.items() if name.startswith("annual[")}
    assert "differs" in annual.values(), annual


def test_a_second_run_from_the_caches_gives_the_same_records(
    tmp_path: Path, served: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stable(records: dict) -> list:
        out = []
        for check in records["checks"]:
            check = {k: v for k, v in check.items() if k != "run_at"}
            check["inputs"] = [
                {k: v for k, v in i.items() if k != "retrieved_at"} for i in check["inputs"]
            ]
            out.append(check)
        return out

    first = run(tmp_path)

    def no_download(uri: str, path: Path) -> int:
        raise AssertionError(f"an offline run downloaded {uri}")

    monkeypatch.setattr("crc_sdk._source_io._download", no_download)
    second = run(tmp_path, live=False)  # crc-sdk reads with Cache.offline
    assert stable(first) == stable(second)
    assert first["exploration"]["stations"] == second["exploration"]["stations"]


@pytest.mark.skip(reason="until the first 1.0.0 run is accepted")
def test_committed_records_match_the_inventory() -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "ghcnh")
    records = build.load_records("ghcnh")
    assert records is not None
    assert records["versions"]["crc-sdk"].startswith("1.")
    assert sorted(source.assessed_options["indicator"]) == records["options_assessed"]["indicator"]
    steps = {step.id: step.outcome for step in build.with_outcomes(source, records).statement}
    assert set(steps.values()) == {"confirmed"}
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used == set(steps)  # every step has a check and every check names a real step
