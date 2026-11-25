"""FG3, FS7: cards name the level, warn of facts that differ, and are the same bytes on re-run."""

from __future__ import annotations

import json
from pathlib import Path

from flood_lab import data_cards
from flood_lab.facts import load

FIXTURES = Path(__file__).parent / "fixtures" / "facts"


def test_level_wording(tmp_path: Path) -> None:
    maps = data_cards.card(load(FIXTURES / "toy-flood-maps.toml"), tmp_path)
    sensors = data_cards.card(load(FIXTURES / "toy-sensors.toml"), tmp_path)
    # one fact differs and one was not checked: not "facts confirmed"; not applicable is not counted
    assert "Level of check (FS7): **facts checked: 6 confirmed, 1 differ, 1 not checked**." in maps
    assert "facts confirmed" not in maps
    assert "**facts confirmed; values to be recomputed by a second reader in F2**" in sensors
    for text in (maps, sensors):
        assert "verified" not in text.lower()


def test_level_wording_once_a_second_reader_record_exists(tmp_path: Path) -> None:
    (tmp_path / "second-reader-toy-sensors.json").write_text(
        json.dumps({"stage": "F2", "passed": True})
    )
    sensors = data_cards.card(load(FIXTURES / "toy-sensors.toml"), tmp_path)
    assert "values recomputed by a second reader in F2 (passed)" in sensors
    assert "to be recomputed" not in sensors


def test_differs_warning_in_first_lines(tmp_path: Path) -> None:
    maps = data_cards.card(load(FIXTURES / "toy-flood-maps.toml"), tmp_path).splitlines()
    assert any("1 fact(s) differ" in line and "Licence" in line for line in maps[:6])
    sensors = data_cards.card(load(FIXTURES / "toy-sensors.toml"), tmp_path)
    assert "differ from" not in sensors


def test_card_content_and_escaping(tmp_path: Path) -> None:
    maps = data_cards.card(load(FIXTURES / "toy-flood-maps.toml"), tmp_path)
    assert "Toy publisher" in maps and "FS1, FH3" in maps
    assert "1,234,567" in maps and "toy-flood-maps/maps.zip" in maps
    assert "<script>" not in maps and "&lt;script&gt;" in maps
    # a | in a fact must not break the table into extra columns
    assert "Toy data \\| made up" in maps
    assert "<details><summary>Passage: Licence</summary>" in maps


def test_byte_identical_on_second_run(tmp_path: Path) -> None:
    out = tmp_path / "cards"
    data_cards.write(FIXTURES, tmp_path, out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    data_cards.write(FIXTURES, tmp_path, out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == first
    assert sorted(first) == ["README.md", "toy-flood-maps.md", "toy-sensors.md"]
    index = first["README.md"].decode()
    assert (
        "| [Toy flood maps](toy-flood-maps.md) | facts checked: 6 confirmed, 1 differ, "
        "1 not checked | 6 | 1 | 1 | 1 | F0 |"
    ) in index


def test_stale_generated_card_removed_and_empty_folder(tmp_path: Path) -> None:
    out = tmp_path / "cards"
    data_cards.write(FIXTURES, tmp_path, out)
    (out / "handwritten.md").write_text("kept\n")
    data_cards.write(tmp_path / "no-facts", tmp_path, out)
    assert sorted(p.name for p in out.iterdir()) == ["README.md", "handwritten.md"]
    assert "No sources checked yet." in (out / "README.md").read_text()


def test_second_reader_level_keeps_the_facts_counts(tmp_path: Path) -> None:
    from dataclasses import replace

    from flood_lab.facts import level_words

    maps = replace(
        load(FIXTURES / "toy-flood-maps.toml"),
        level="facts and second reader",
        second_reader_stage="F2",
    )
    assert level_words(maps, tmp_path) == (
        "facts checked: 6 confirmed, 1 differ, 1 not checked; "
        "values to be recomputed by a second reader in F2"
    )
    only_unread = replace(maps, facts=tuple(f for f in maps.facts if f.outcome != "differs"))
    assert level_words(only_unread, tmp_path).startswith(
        "facts checked: 6 confirmed, 1 not checked;"
    )
