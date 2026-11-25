"""FS6: a facts file loads, and each rule refuses a file broken on purpose."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from flood_lab.facts import REQUIRED, load, load_all, summary

FIXTURES = Path(__file__).parent / "fixtures" / "facts"
GOOD = FIXTURES / "toy-sensors.toml"


def broken(
    tmp_path: Path, old: str, new: str, *, count: int = 1, name: str = "toy-sensors"
) -> Path:
    text = GOOD.read_text(encoding="utf-8")
    assert old in text, old
    path = tmp_path / f"{name}.toml"
    path.write_text(text.replace(old, new, count), encoding="utf-8")
    return path


def refused(path: Path, *words: str) -> None:
    with pytest.raises(ValueError) as caught:
        load(path)
    message = str(caught.value)
    assert message.startswith(path.name), message
    for word in words:
        assert word in message, message


def test_fixtures_load() -> None:
    sources = load_all(FIXTURES)
    assert [s.id for s in sources] == ["toy-flood-maps", "toy-sensors"]
    maps = sources[0]
    assert summary(maps) == {"confirmed": 6, "differs": 1, "not checked": 1, "not applicable": 1}
    assert [f.name for f in maps.further] == ["row_count"]
    assert maps.files[0].bytes == 1234567
    assert summary(sources[1])["confirmed"] == len(REQUIRED)


def test_absent_folder_has_no_sources(tmp_path: Path) -> None:
    assert load_all(tmp_path / "nothing") == []


def test_unknown_outcome(tmp_path: Path) -> None:
    refused(broken(tmp_path, 'outcome = "confirmed"', 'outcome = "verified"'), "unknown outcome")


def test_unknown_level(tmp_path: Path) -> None:
    refused(
        broken(tmp_path, 'level = "facts and second reader"', 'level = "recomputed"'),
        "unknown level",
    )


def test_required_fact_missing(tmp_path: Path) -> None:
    text = GOOD.read_text(encoding="utf-8")
    without = re.sub(r'\[\[fact\]\]\nname = "release".*?(?=\[\[fact\]\])', "", text, flags=re.S)
    assert without != text
    path = tmp_path / "toy-sensors.toml"
    path.write_text(without, encoding="utf-8")
    refused(path, "required fact(s) missing", "release")


@pytest.mark.parametrize("outcome", ["confirmed", "differs"])
def test_confirmed_or_differs_needs_source_url(tmp_path: Path, outcome: str) -> None:
    path = broken(tmp_path, 'outcome = "confirmed"', f'outcome = "{outcome}"')
    path.write_text(
        path.read_text().replace('source_url = "https://example.org/source"', 'source_url = ""', 1)
    )
    refused(path, "identifier", "source_url")


@pytest.mark.parametrize("outcome", ["confirmed", "differs"])
def test_confirmed_or_differs_needs_passage(tmp_path: Path, outcome: str) -> None:
    path = broken(tmp_path, 'outcome = "confirmed"', f'outcome = "{outcome}"')
    path.write_text(path.read_text().replace('"""identifier=value"""', '""""""', 1))
    refused(path, "identifier", "passage")


def test_differs_needs_observed(tmp_path: Path) -> None:
    path = broken(tmp_path, 'outcome = "confirmed"', 'outcome = "differs"')
    path.write_text(
        path.read_text().replace('observed = "identifier as the source states it"', 'observed = ""')
    )
    refused(path, "identifier", "observed")


def test_duplicate_fact_names(tmp_path: Path) -> None:
    refused(broken(tmp_path, 'name = "release"', 'name = "fields"'), "duplicate", "fields")


def test_second_reader_needs_a_stage(tmp_path: Path) -> None:
    refused(
        broken(tmp_path, 'second_reader_stage = "F2"', 'second_reader_stage = ""'),
        "second_reader_stage",
    )


def test_not_checked_needs_no_passage(tmp_path: Path) -> None:
    path = broken(tmp_path, 'outcome = "confirmed"', 'outcome = "not checked"')
    path.write_text(path.read_text().replace('"""identifier=value"""', '""""""', 1))
    assert load(path).fact("identifier").outcome == "not checked"


def test_id_must_match_file_name(tmp_path: Path) -> None:
    refused(broken(tmp_path, "x", "x", name="other-name"), "does not match")


def test_a_fact_with_no_claim_is_shown_as_read_not_confirmed() -> None:
    from flood_lab.facts import READ, Fact, read_without_claim

    claimed = Fact("licence", "Open terms", "Open terms", "confirmed", "https://x", "passage")
    unclaimed = Fact("fields", "", "three fields", "confirmed", "https://x", "passage")
    differs = Fact("release", "", "v2", "differs", "https://x", "passage")
    assert claimed.shown == "confirmed"
    assert unclaimed.shown == READ and unclaimed.outcome == "confirmed"
    assert differs.shown == "differs"
    maps = load(FIXTURES / "toy-flood-maps.toml")
    assert read_without_claim(maps) == sum(
        1 for fact in maps.facts if fact.outcome == "confirmed" and not fact.claimed.strip()
    )
