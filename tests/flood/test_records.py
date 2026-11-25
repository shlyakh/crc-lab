"""FG2: the record format and the shared atomic writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flood_lab.records import Check, Input, Parameter, Record
from lab_common.io import write_json_atomic, write_text_atomic


def test_record_round_trip_and_verdict(tmp_path: Path) -> None:
    source = tmp_path / "in.txt"
    source.write_text("abc")
    record = Record(
        id="t1",
        stage="F0",
        title="a test",
        inputs=[Input.of(source, root=tmp_path)],
        parameters=[Parameter("wet_depth_m", 0.05, "P")],
        numbers={"n": 3},
        checks=[Check("a", "n equals 3", True, 3, 3)],
    )
    document = json.loads(record.write(tmp_path / "records").read_text())
    assert document["schema"] == "flood_lab/0.1"
    assert document["passed"] is True
    assert document["inputs"][0]["sha256"].startswith("ba7816bf")
    assert document["software"]["crc-sdk"] == "1.0.0"


def test_verdict_is_unknown_when_a_rule_could_not_be_judged() -> None:
    record = Record("t2", "F0", "x", checks=[Check("a", "r", True), Check("b", "r", None)])
    assert record.passed is None
    record.checks.append(Check("c", "r", False))
    assert record.passed is False


def test_a_stated_value_must_name_its_source() -> None:
    with pytest.raises(ValueError):
        Parameter("x", 1, "S")
    with pytest.raises(ValueError):
        Parameter("x", 1, "Q")


def test_a_failed_write_leaves_the_old_file(tmp_path: Path) -> None:
    target = tmp_path / "a.json"
    write_json_atomic(target, {"a": 1})
    with pytest.raises(TypeError):
        write_json_atomic(target, {"a": object()})
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
    write_text_atomic(tmp_path / "b" / "c.txt", "x")
    assert (tmp_path / "b" / "c.txt").read_text() == "x"
