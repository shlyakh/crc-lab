"""``just site-flood``: the gallery of visual tests is complete and up to date.

    python -m flood_lab.check_site

Fails when the gallery is missing, a record lacks a required key, a record names a figure that does
not exist (or whose copy under ``site/flood/tests/figures/`` is missing or differs), a facts
file does not load, or the committed gallery or data cards differ from what the generators would
write now.
Stands alone like the other projects' ``check_site`` modules; offline, from committed files only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import data_cards, paths
from .facts import load
from .gallery import Layout, figure_copy, record_faults, render


def faults(root: Path = paths.ROOT) -> list[str]:
    layout = Layout(root)
    found: list[str] = []
    if not layout.page.exists():
        found.append("missing: site/flood/tests/index.html (run `python -m flood_lab.gallery`)")
    records_ok = True
    for path in sorted(layout.records.glob("*.json")) if layout.records.is_dir() else []:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            found.append(f"record {path.name}: not valid JSON ({error})")
            records_ok = False
            continue
        problems = record_faults(document, f"record {path.name}")
        if problems:
            found += problems
            records_ok = False
            continue
        for figure in document["figures"]:
            try:
                original, address = figure_copy(figure, layout)
            except ValueError as error:
                found.append(f"record {path.name}: {error}")
                records_ok = False
                continue
            if not original.is_file():
                found.append(f"record {path.name}: figure {figure} does not exist")
                records_ok = False
                continue
            copy = layout.tests / address
            if not copy.is_file() or copy.read_bytes() != original.read_bytes():
                found.append(
                    f"stale: site/flood/tests/{address} is missing or differs from {figure}"
                )
    facts_ok = True
    for path in sorted(layout.facts.glob("*.toml")) if layout.facts.is_dir() else []:
        try:
            load(path)
        except ValueError as error:
            found.append(f"facts {error}")
            facts_ok = False
    if records_ok and facts_ok:
        if layout.page.exists() and layout.page.read_text(encoding="utf-8") != render(layout):
            found.append(
                "stale: site/flood/tests/index.html differs from what `python -m "
                "flood_lab.gallery` writes now"
            )
        expected = data_cards.documents(layout.facts, layout.records)
        for name, text in expected.items():
            card = layout.data_cards / name
            if not card.exists() or card.read_text(encoding="utf-8") != text:
                found.append(
                    f"stale: docs/flood/data-cards/{name} is missing or differs from what "
                    "`python -m flood_lab.data_cards` writes now"
                )
        for name in data_cards.stale(layout.data_cards, expected):
            found.append(f"stale: docs/flood/data-cards/{name} has no facts file any more")
    return found


def main(root: Path = paths.ROOT) -> int:
    found = faults(root)
    for line in found:
        print(line)
    if found:
        print(f"Flood lab: site check failed ({len(found)} problem(s))")
        return 1
    layout = Layout(root)
    records = len(list(layout.records.glob("*.json"))) if layout.records.is_dir() else 0
    sources = len(list(layout.facts.glob("*.toml"))) if layout.facts.is_dir() else 0
    print(f"Flood lab: gallery complete and current, {records} record(s), {sources} source(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
