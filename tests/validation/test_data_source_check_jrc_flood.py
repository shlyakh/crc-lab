"""JRC flood on crc-sdk 1.x: the assessment on small constructed publisher folders, offline."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import jrc_publisher as made  # noqa: E402

from data_source_check import build  # noqa: E402
from data_source_check.assessments import jrc_flood as assessment  # noqa: E402
from data_source_check.core import inventory  # noqa: E402
from data_source_check.reference import jrc_flood as reference  # noqa: E402

VERSIONS = {"crc-sdk": "test"}
AREA = assessment.Area("glofas-test", "glofas", made.BOX, "constructed box")
EUROPE = assessment.Area(
    "efas-test",
    "efas",
    (
        8.0 + 3.6 * made.STEP,
        50.0 - 20.6 * made.STEP,
        8.0 + 30.4 * made.STEP,
        50.0 - 2.4 * made.STEP,
    ),
    "constructed box",
)
FAR = assessment.Area("efas-far", "efas", made.FAR, "a box outside the raster")


@pytest.fixture
def publisher(tmp_path: Path) -> dict[str, Path]:
    return made.build_publisher(tmp_path / "publisher")


def run(tmp_path: Path, publisher: dict[str, Path], **more: object) -> dict:
    return assessment.assess(
        tmp_path / "cache",
        live=True,
        versions=VERSIONS,
        areas=(AREA, EUROPE),
        outside=(FAR,),
        publisher=publisher,
        strip_rows=7,  # strips that do not line up with anything
        **more,  # type: ignore[arg-type]
    )


def outcomes(records: dict) -> dict[str, str]:
    return {check["check"]: check["outcome"] for check in records["checks"]}


def test_every_check_is_confirmed_on_the_constructed_files(
    tmp_path: Path, publisher: dict[str, Path]
) -> None:
    records = run(tmp_path, publisher)
    got = outcomes(records)
    assert got.pop("transport") == "not checked"  # crc-sdk read local files, not a server
    assert set(got.values()) == {"confirmed"}, {k: v for k, v in got.items() if v != "confirmed"}
    assert {name.split("[")[0] for name in got} == {
        "area", "delivered", "values", "cells", "shape", "files", "provenance", "release",
        "licence", "overlap", "coverage",
    }  # fmt: skip
    glofas = next(a for a in records["exploration"]["areas"] if a["area"] == "glofas-test")
    assert glofas["tiles"] == ["ID1_N31_W100", "ID2_N31_W099"]  # the box crosses the seam
    assert glofas["decreasing"] >= 1 and glofas["dry"] >= 1 and glofas["one_depth"] >= 1
    assert glofas["equal_depths"] >= 1 and glofas["fewer_than_four"] >= 1
    assert glofas["rows"] == glofas["deliverable"] > 100
    values = next(c for c in records["checks"] if c["check"] == "values[glofas-test]")
    assert values["result"]["values_compared"] > glofas["rows"] * 2
    far = records["exploration"]["outside"][0]
    assert far["rows"] == 0 and not far["error"]


def test_the_placed_pixels_are_delivered_or_left_out_as_the_statement_says(
    tmp_path: Path, publisher: dict[str, Path]
) -> None:
    run(tmp_path, publisher)
    from data_source_check.adapters.crc import jrc_flood as framework

    table = framework.rows(tmp_path / "cache" / "framework" / "glofas-test")
    rows = {r["support_id"]: r for r in table.to_pylist()}
    name = "jrc:glofas:ID1_N31_W100:{}:{}".format
    assert len(rows[name(*made.THREE)]["values"]) == 3  # 0.11 needed four depths for a curve
    assert len(rows[name(*made.FOUR)]["values"]) == 4
    assert set(rows[name(*made.FLAT)]["values"]) == {1.0}  # equal depths are delivered
    assert name(*made.DOWN) not in rows and name(*made.DRY) not in rows
    assert rows[name(*made.THREE)]["probabilities"] == pytest.approx(
        [1 - 1 / period for period in made.GLOFAS_PERIODS[-3:]]
    )


@pytest.mark.parametrize(
    ("wrong", "differing"),
    [
        ({"nodata_is_missing": False}, {"delivered", "values"}),
        ({"touched_pixels": False}, {"area"}),
    ],
    ids=["nodata-kept-as-a-depth", "pixels-by-rounding"],
)
def test_a_wrong_reference_rule_ends_as_differs(
    tmp_path: Path, publisher: dict[str, Path], wrong: dict[str, bool], differing: set[str]
) -> None:
    """A check that cannot fail proves nothing: break one rule and the comparison must differ."""
    got = outcomes(run(tmp_path, publisher, rules=replace(reference.Rules(), **wrong)))
    differs = {name.split("[")[0] for name, value in got.items() if value == "differs"}
    assert differing <= differs, differs


def test_a_second_run_from_the_stored_reads_gives_the_same_outcomes(
    tmp_path: Path, publisher: dict[str, Path]
) -> None:
    first = run(tmp_path, publisher)
    again = assessment.assess(
        tmp_path / "cache", live=False, versions=VERSIONS, areas=(AREA, EUROPE), outside=(FAR,),
        publisher=publisher, strip_rows=7,
    )  # fmt: skip
    assert outcomes(first) == outcomes(again)
    assert [c["result"] for c in first["checks"]] == [c["result"] for c in again["checks"]]


def test_every_check_bears_on_a_step_of_the_statement(
    tmp_path: Path, publisher: dict[str, Path]
) -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "jrc-flood")
    steps = {step.id for step in source.statement}
    records = run(tmp_path, publisher)
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used == steps, (used - steps, steps - used)


def test_committed_records_match_the_inventory() -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "jrc-flood")
    records = build.load_records("jrc-flood")
    assert records is not None
    assert sorted(source.assessed_options["product"]) == records["options_assessed"]["product"]
    used = {step for check in records["checks"] for step in check["steps"]}
    assert used <= {step.id for step in source.statement}
