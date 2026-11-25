"""FP6, FP8, FS7: the gallery shows verdicts as recorded, counts facts, stays escaped, relative."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from flood_lab import check_site, data_cards, gallery
from flood_lab.records import Check, Parameter, Record

FIXTURES = Path(__file__).parent / "fixtures" / "facts"


@pytest.fixture
def layout(tmp_path: Path) -> gallery.Layout:
    layout = gallery.Layout(tmp_path)
    shutil.copytree(FIXTURES, layout.facts)
    layout.records.mkdir(parents=True)
    figure = layout.figures / "f0" / "bars.png"
    figure.parent.mkdir(parents=True)
    figure.write_bytes(b"\x89PNG fake")
    Record(
        id="f0-fails",
        stage="F0",
        title="A check that fails",
        checks=[
            Check("ok", "n is 3", True, 3, 3),
            Check("bad", "n under 2", False, 3, 2, proposed=True),
        ],
        parameters=[Parameter("wet_depth_m", 0.05, "P")],
        numbers={"n": 3},
        tables={"rows": [{"a": "<b>x</b>"}]},
        figures=["docs/flood/figures/f0/bars.png"],
        notes=["Toy data: the limit is that nothing here is real."],
    ).write(layout.records)
    Record(
        id="f1-open",
        stage="F1",
        title="A check not judged",
        checks=[Check("pending", "needs data", None)],
    ).write(layout.records)
    return layout


def card(page: str, record_id: str) -> str:
    match = re.search(rf'<article class="card" id="record-{record_id}">(.*?)</article>', page, re.S)
    assert match, record_id
    return match.group(1)


def test_fail_and_not_judged_badges(layout: gallery.Layout) -> None:
    page = gallery.render(layout)
    failing = card(page, "f0-fails")
    assert '<span class="badge fail">fail</span>' in failing.split("</header>")[0]
    assert "proposed" in failing and "[P]" in failing
    head = card(page, "f1-open").split("</header>")[0]
    assert "not judged" in head and "badge pass" not in head
    assert '<div class="tile" data-count="pass"><b>0</b>' in page
    assert '<div class="tile" data-count="fail"><b>1</b>' in page
    assert '<div class="tile" data-count="not judged"><b>1</b>' in page


def test_captions_from_the_first_note(layout: gallery.Layout) -> None:
    failing = card(gallery.render(layout), "f0-fails")
    assert "<figcaption><b>bars.png.</b> Toy data: the limit" in failing
    assert failing.count("Toy data: the limit") >= 4  # figure, checks, numbers, parameters, table
    assert gallery.NO_NOTE in card(gallery.render(layout), "f1-open")


def test_sources_counted_with_differs(layout: gallery.Layout) -> None:
    page = gallery.render(layout)
    assert '<div class="tile" data-count="sources"><b>2</b>' in page
    assert '<div class="tile" data-count="facts differs"><b>1</b>' in page
    assert '<div class="tile" data-count="facts confirmed"><b>14</b>' in page
    assert "1 fact(s) differ from docs/flood/requirements.md: licence" in page
    assert "facts confirmed; values to be recomputed by a second reader in F2" in page
    assert 'class="o o-differs" title="Toy terms, attribution required"' in page


def test_no_absolute_paths_no_markup_from_data_no_verified(layout: gallery.Layout) -> None:
    page = gallery.render(layout)
    assert str(layout.root) not in page and str(gallery.paths.ROOT) not in page
    assert not re.search(r'(src|href)="/', page)
    assert "verified" not in page.lower()
    assert "<script" not in page.lower()
    assert "&lt;script&gt;" in page and "&lt;b&gt;x&lt;/b&gt;" in page


def test_empty_folders(tmp_path: Path) -> None:
    page = gallery.render(gallery.Layout(tmp_path))
    assert "No sources checked yet." in page and "No records yet." in page


def test_figure_copied_and_site_check(layout: gallery.Layout) -> None:
    gallery.write(layout)
    data_cards.write(layout.facts, layout.records, layout.data_cards)
    copy = layout.tests / "figures" / "f0" / "bars.png"
    assert copy.read_bytes() == b"\x89PNG fake"
    assert 'src="figures/f0/bars.png"' in layout.page.read_text()
    assert check_site.faults(layout.root) == []
    # a stale page fails
    layout.page.write_text(layout.page.read_text() + " ")
    assert any("index.html differs" in f for f in check_site.faults(layout.root))
    gallery.write(layout)
    # a missing figure fails
    path = layout.records / "f1-open.json"
    document = json.loads(path.read_text())
    document["figures"] = ["docs/flood/figures/f1/none.png"]
    path.write_text(json.dumps(document))
    assert any("does not exist" in f for f in check_site.faults(layout.root))
    # a record without a required key fails
    del document["checks"]
    path.write_text(json.dumps(document))
    assert any("missing key 'checks'" in f for f in check_site.faults(layout.root))


def test_site_check_fails_on_broken_facts_and_stale_cards(layout: gallery.Layout) -> None:
    gallery.write(layout)
    assert any("data-cards/README.md" in f for f in check_site.faults(layout.root))
    data_cards.write(layout.facts, layout.records, layout.data_cards)
    facts = layout.facts / "toy-sensors.toml"
    facts.write_text(facts.read_text().replace('level = "facts and second reader"', 'level = "x"'))
    assert any("unknown level" in f for f in check_site.faults(layout.root))
