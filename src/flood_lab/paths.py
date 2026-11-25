"""Where the flood lab keeps things (requirements FG1, FG7)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: downloads and runs; git-ignored
CACHE = ROOT / "data" / "cache" / "flood"
DOCS = ROOT / "docs" / "flood"
FIGURES = DOCS / "figures"
DATA_CARDS = DOCS / "data-cards"
SITE = ROOT / "site" / "flood"
#: one JSON record per check; the gallery is generated from these
RECORDS = SITE / "tests" / "records"
FACTS = Path(__file__).resolve().parent / "facts"
