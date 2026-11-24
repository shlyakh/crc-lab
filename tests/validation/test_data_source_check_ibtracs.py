"""IBTrACS assessment on fixed excerpts of NOAA's ALL file (three storms, 2023-2025), offline.

The reference side downloads through a fake ``urlopen``; crc-sdk downloads through its one
download function, ``crc_sdk._source_io._download``, replaced by one that writes the excerpt
(crc-sdk's own tests replace the same function). Everything after the bytes runs as it would
live: crc-sdk's cache index and object store, its decoder and checks, the reference reader,
the comparison and the records. A second run reads crc-sdk's cache with ``Cache.offline``.
One storm of ``ibtracs_sample.csv`` crosses 180 degrees east; ``ibtracs_dateline.csv`` is the
same excerpt with three more longitudes moved to 180.0, 181.3 and 200.1, where the wrap to
-180..180 and the last bit of the result matter.
"""

import io
import json
from pathlib import Path

import pytest

from data_source_check import build
from data_source_check.assessments import ibtracs as assessment
from data_source_check.core import compare, inventory
from data_source_check.core.records import RecordError
from data_source_check.reference import ibtracs as reference

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "ibtracs_sample.csv"
DATELINE = FIXTURES / "ibtracs_dateline.csv"
VERSIONS = {"crc-sdk": "test"}
FEW = ("USA", "TOKYO")


class Response(io.BytesIO):
    status = 200
    headers = {"ETag": '"sample"', "Last-Modified": "Tue, 10 Nov 2026 10:03:02 GMT"}


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Serve a fixture as NOAA's ALL file to both sides; the test may change ``["file"]``."""
    serving = {"file": DATELINE}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001, ANN202
        assert request.full_url == reference.url("ALL")
        return Response(serving["file"].read_bytes())

    def fake_download(uri: str, path: Path) -> int:
        assert uri == reference.url("ALL"), uri
        path.write_bytes(serving["file"].read_bytes())
        return 200

    monkeypatch.setattr("data_source_check.reference.ibtracs.urlopen", fake_urlopen)
    monkeypatch.setattr("crc_sdk._source_io._download", fake_download)
    return serving


def run(tmp_path: Path, *, live: bool = True, **more: object) -> dict:
    return assessment.assess(tmp_path, live=live, versions=VERSIONS, **more)  # type: ignore[arg-type]


def outcomes(records: dict) -> dict[str, str]:
    return {check["check"]: check["outcome"] for check in records["checks"]}


def test_reference_reader_applies_its_rules() -> None:
    columns, units = reference.header(SAMPLE)
    assert columns[:3] == ["SID", "SEASON", "NUMBER"] and len(columns) == len(units) == 174
    rows = list(reference.rows(SAMPLE))
    raw = list(reference.rows(SAMPLE, trim=False, empty_as_null=False))
    assert len(rows) == len(raw) > 20
    assert any(value == " " for value in raw[0]) and None in rows[0]
    points = list(reference.agency_points(DATELINE, "USA"))
    assert len(points) == 2 * len(rows)
    assert [p["variable_id"].rsplit(":", 1)[1] for p in points[:2]] == [
        "maximum_sustained_wind",
        "minimum_central_pressure",
    ]
    longitudes = [p["longitude"] for p in points[::2][:3]]
    assert longitudes == [-180.0, -178.7, -159.9]  # 180.0, 181.3, 200.1 in the file
    assert points[0]["time"] == "2023-06-08T12:00:00" and points[0]["value"] == 30.0
    missing = next(p for p in reference.agency_points(SAMPLE, "TOKYO"))
    assert missing["value"] is None and missing["failure_code"] == "source_no_data"
    assert reference.wrapped("266.9") == -93.1 and reference.wrapped("92.1") == 92.1


def test_assessment_confirms_every_step_on_the_excerpt(
    tmp_path: Path, served: dict[str, Path]
) -> None:
    records = run(tmp_path)
    got = outcomes(records)
    assert set(got.values()) == {"confirmed"}, got
    assert len(got) == 2 + 3 * len(reference.AGENCIES)
    assert records["agencies_assessed"] == list(reference.AGENCIES)
    values = next(c for c in records["checks"] if c["check"] == "values[USA]")["result"]
    points = len(list(reference.rows(DATELINE)))
    assert values["rows_framework"] == values["rows_reference"] == 2 * points
    assert values["values_compared"] == 2 * points * len(assessment.COMPARED)
    # crc-sdk computes (lon + 180) % 360 - 180 for every longitude, so 92.1 becomes
    # 92.10000000000002 and 200.1 becomes -159.89999999999998: within the tolerance
    assert 0 < values["largest_difference"] <= assessment.TOLERANCE
    assert 0 < values["rows_point_bytes_identical"] < values["rows_point_bytes_compared"]
    provenance = next(c for c in records["checks"] if c["check"] == "provenance[USA]")["result"]
    assert provenance["license"] and "10.25921/82ty-9e16" in provenance["attribution"]
    assert records["exploration"]["ALL"]["storms"] == 3
    assert records["exploration"]["agencies"]["USA"]["framework_rows"] == 2 * points


@pytest.mark.parametrize(
    ("rules", "differing"),
    [
        ({"wrap_longitude": False}, {"values[USA]", "values[TOKYO]"}),
        ({"time_separator": " "}, {"values[USA]", "values[TOKYO]"}),
        ({"resolution": 8}, {"values[USA]", "values[TOKYO]"}),
        ({"empty_as_null": False}, {"values[USA]", "values[TOKYO]"}),
        ({"pressure_first": True}, {"values[USA]", "values[TOKYO]"}),
        ({"unit_names": {"kts": "knots", "mb": "Pa"}}, {"declaration[USA]", "declaration[TOKYO]"}),
        ({"doi": "10.0000/not-ibtracs"}, {"provenance[USA]", "provenance[TOKYO]"}),
    ],
)
def test_a_wrong_reference_rule_ends_as_differs(
    tmp_path: Path, served: dict[str, Path], rules: dict, differing: set[str]
) -> None:
    """A check that cannot fail proves nothing: break one rule and the comparison must differ."""
    got = outcomes(run(tmp_path, agencies=FEW, rules=rules))
    assert {name for name, value in got.items() if value == "differs"} == differing


def test_a_changed_file_ends_as_differs(tmp_path: Path, served: dict[str, Path]) -> None:
    run(tmp_path, agencies=FEW)
    cached = tmp_path / "reference" / "ALL.csv"
    text = cached.read_text(encoding="utf-8")
    cached.write_text(text.replace("2023160N20092", "2023160N20093", 1), encoding="utf-8")
    sidecar = tmp_path / "reference" / "ALL.json"
    record = json.loads(sidecar.read_text())
    sidecar.write_text(json.dumps(record | {"sha256": reference.sha256(cached)}))
    got = outcomes(run(tmp_path, live=False, agencies=FEW))
    assert got["bytes"] == "differs" and got["values[USA]"] == "differs"
    assert got["provenance[USA]"] == "differs"  # crc-sdk's checksum is not the file's


def test_a_second_run_gives_the_same_records_apart_from_run_times(
    tmp_path: Path, served: dict[str, Path]
) -> None:
    def stable(records: dict) -> str:
        records = json.loads(json.dumps(records))
        records.pop("run_at")
        for check in records["checks"]:
            check.pop("run_at")
        return json.dumps(records, sort_keys=True)

    first = run(tmp_path, agencies=FEW)
    assert stable(run(tmp_path, live=False, agencies=FEW)) == stable(first)


def test_offline_without_crc_sdks_cache_raises(tmp_path: Path, served: dict[str, Path]) -> None:
    run(tmp_path, agencies=("USA",))
    for path in sorted((tmp_path / "crc-sdk").rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    with pytest.raises(FileNotFoundError, match="offline cache"):
        run(tmp_path, live=False, agencies=("USA",))


def test_step_outcomes_follow_the_checks() -> None:
    checks = [
        {"steps": ["a", "b"], "outcome": "confirmed"},
        {"steps": ["b"], "outcome": "differs"},
        {"steps": ["c"], "outcome": "not checked"},
    ]
    assert compare.step_outcomes(["a", "b", "c", "d"], checks) == {
        "a": "confirmed",
        "b": "differs",
        "c": "not checked",
        "d": "not checked",
    }


def test_an_empty_comparison_is_not_a_confirmation() -> None:
    result = compare.compare_rows(["x"], [], [])
    assert result["values_compared"] == 0  # the assessment records this as "not checked"


def test_every_step_of_the_statement_is_borne_by_a_check_or_says_why(
    tmp_path: Path, served: dict[str, Path]
) -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "ibtracs")
    records = run(tmp_path, agencies=FEW)
    by_step = {step.id: step.outcome for step in build.with_outcomes(source, records).statement}
    assert by_step.pop("cache") == "not checked"
    assert set(by_step.values()) == {"confirmed"}
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used == set(by_step)  # no check points at a step the statement lacks


@pytest.mark.skip(reason="until the first 1.0.0 run is accepted")
def test_committed_records_match_the_inventory() -> None:
    """The source file, the committed records and the generated page data agree."""
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "ibtracs")
    records = build.load_records("ibtracs")
    assert records is not None
    assert records["versions"]["crc-sdk"].startswith("1.")
    assert sorted(source.assessed_options["agency"]) == sorted(records["agencies_assessed"])
    assessed = build.with_outcomes(source, records)
    by_step = {step.id: step.outcome for step in assessed.statement}
    assert by_step["cache"] == "not checked"
    assert all(v == "confirmed" for k, v in by_step.items() if k != "cache")
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used <= set(by_step)  # no check points at a step the statement lacks


def test_a_step_left_unchecked_must_say_why() -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "ibtracs")
    with pytest.raises(RecordError, match="say why"):
        build.with_outcomes(source, {"checks": []})
