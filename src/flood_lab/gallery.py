"""The gallery of visual tests (requirements FP6, FS6, FS7): ``site/flood/tests/index.html``.

    python -m flood_lab.gallery

One static page, generated from committed files only: one card per record in
``site/flood/tests/records/*.json`` and a table of the source facts in ``src/flood_lab/facts/``.
No network, no crc-sdk, no build step; the page loads no script.

Figures. A record names its figures by path from the repository root, and the plan puts them in
``docs/flood/figures/``, which the site server (rooted at ``site/``) cannot reach. The generator
therefore copies each figure to ``site/flood/tests/figures/<path below docs/flood/figures/>`` and
the page refers to the copy by a relative address; copies no record names any more are removed.
A figure outside ``docs/flood/figures/`` is refused. PNG (and other images) show as ``<img>``,
plotly HTML in an ``<iframe>``. ``flood_lab.check_site`` checks that every copy matches its
original.

Every string from a record or a facts file is escaped before it reaches the page.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from lab_common.io import write_text_atomic

from . import paths
from .facts import REQUIRED, Source, level_words, load_all, summary
from .records import OUTCOMES, SCHEMA, TAGS

REQUIRED_KEYS = (
    "schema",
    "id",
    "stage",
    "title",
    "inputs",
    "parameters",
    "numbers",
    "tables",
    "checks",
    "figures",
    "software",
    "notes",
    "passed",
)
CHECK_KEYS = ("name", "rule", "passed", "value", "threshold", "proposed")
IMAGE = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")
FRAME = (".html", ".htm")
NO_NOTE = "No note in the record: the limit of this result is not stated."
SHORT = {
    "identifier": "id",
    "address": "address",
    "licence": "licence",
    "fields": "fields",
    "coverage_space": "space",
    "coverage_time": "time",
    "release": "release",
    "checksum": "checksum",
}


@dataclass(frozen=True)
class Layout:
    """Where things are, from one repository root (``paths`` for the real one)."""

    root: Path

    @property
    def facts(self) -> Path:
        return self.root / paths.FACTS.relative_to(paths.ROOT)

    @property
    def records(self) -> Path:
        return self.root / paths.RECORDS.relative_to(paths.ROOT)

    @property
    def figures(self) -> Path:
        return self.root / paths.FIGURES.relative_to(paths.ROOT)

    @property
    def data_cards(self) -> Path:
        return self.root / paths.DATA_CARDS.relative_to(paths.ROOT)

    @property
    def tests(self) -> Path:
        return self.records.parent

    @property
    def page(self) -> Path:
        return self.tests / "index.html"

    @property
    def copies(self) -> Path:
        return self.tests / "figures"


# records ---------------------------------------------------------------------------------------


def record_faults(document: Any, name: str) -> list[str]:
    """What is wrong with a record's shape; empty when it can be shown."""
    if not isinstance(document, dict):
        return [f"{name}: not a JSON object"]
    faults = [f"{name}: missing key {key!r}" for key in REQUIRED_KEYS if key not in document]
    if faults:
        return faults
    if document["schema"] != SCHEMA:
        faults.append(f"{name}: schema {document['schema']!r}, expected {SCHEMA!r}")
    for key, kind in (
        ("checks", list),
        ("parameters", list),
        ("figures", list),
        ("notes", list),
        ("inputs", list),
        ("numbers", dict),
        ("tables", dict),
        ("software", dict),
    ):
        if not isinstance(document[key], kind):
            faults.append(f"{name}: {key!r} must be a {kind.__name__}")
    if faults:
        return faults
    if document["passed"] not in (True, False, None):
        faults.append(f"{name}: 'passed' must be true, false or null")
    for i, check in enumerate(document["checks"]):
        missing = [key for key in CHECK_KEYS if not isinstance(check, dict) or key not in check]
        if missing:
            faults.append(f"{name}: check {i + 1} lacks {', '.join(missing)}")
    for i, parameter in enumerate(document["parameters"]):
        if not isinstance(parameter, dict) or parameter.get("tag") not in TAGS:
            faults.append(f"{name}: parameter {i + 1} has no tag of {', '.join(TAGS)}")
    if not faults:
        verdicts = [check["passed"] for check in document["checks"]]
        expected = False if False in verdicts else None if None in verdicts else True
        if document["passed"] != expected:
            faults.append(
                f"{name}: 'passed' is {document['passed']!r}, its checks give {expected!r}"
            )
    for figure in document["figures"]:
        if not isinstance(figure, str):
            faults.append(f"{name}: figure {figure!r} is not a path")
    return faults


def load_records(folder: Path) -> list[dict[str, Any]]:
    """Every record in the folder, by stage then id; a malformed one raises ``ValueError``."""
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        faults = record_faults(document, path.name)
        if faults:
            raise ValueError("; ".join(faults))
        found.append(document)
    return sorted(found, key=lambda d: (_stage_key(d["stage"]), d["id"]))


def _stage_key(stage: str) -> tuple[int, str]:
    digits = stage[1:] if stage[:1] == "F" else ""
    return (int(digits), stage) if digits.isdigit() else (10**6, stage)


def figure_copy(figure: str, layout: Layout) -> tuple[Path, str]:
    """The original of a record's figure and the page-relative address of its copy."""
    relative = Path(figure)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"figure {figure!r}: give a path from the repository root")
    below = paths.FIGURES.relative_to(paths.ROOT)
    try:
        inside = relative.relative_to(below)
    except ValueError:
        raise ValueError(f"figure {figure!r} is not under {below.as_posix()}/") from None
    return layout.root / relative, (Path("figures") / inside).as_posix()


def figure_copies(records: list[dict[str, Any]], layout: Layout) -> dict[str, Path]:
    """Address below ``site/flood/tests/`` to original, for every figure of every record."""
    return dict(
        (address, original)
        for record in records
        for original, address in (figure_copy(f, layout) for f in record["figures"])
    )


# HTML ------------------------------------------------------------------------------------------


def e(value: Any) -> str:
    return escape(str(value), quote=True)


def show(value: Any) -> str:
    """A value as compact text: strings as they are, everything else as JSON."""
    if value is None:
        return "–"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def badge(verdict: bool | None, checks: int = 1) -> str:
    if checks == 0 or verdict is None:
        return '<span class="badge none">not judged</span>'
    if verdict:
        return '<span class="badge pass">pass</span>'
    return '<span class="badge fail">fail</span>'


def href(url: str) -> str:
    url = url.strip()
    if url.startswith(("https://", "http://")):
        return f'<a href="{e(url)}" rel="noopener noreferrer">{e(url)}</a>'
    return e(url) if url else "–"


def _caption(text: str, what: str) -> str:
    return f'<p class="caption"><b>{e(what)}.</b> {e(text)}</p>'


def record_card(record: dict[str, Any], layout: Layout) -> str:
    caption = record["notes"][0] if record["notes"] else NO_NOTE
    checks = record["checks"]
    parts = [
        f'<article class="card" id="record-{e(record["id"])}">',
        '<header class="card-head">',
        f"<h3>{e(record['title'])}</h3>",
        f'<span class="stage">{e(record["stage"])}</span>',
        badge(record["passed"], len(checks)),
        "</header>",
        f'<p class="mute small">Record <code>{e(record["id"])}</code>, written '
        f"{e(record.get('created_at', '–'))}.</p>",
    ]
    if len(record["notes"]) > 1:
        parts.append(
            '<ul class="notes">'
            + "".join(f"<li>{e(n)}</li>" for n in record["notes"][1:])
            + "</ul>"
        )
    for figure in record["figures"]:
        original, address = figure_copy(figure, layout)
        suffix = original.suffix.lower()
        if suffix in IMAGE:
            body = f'<img src="{e(address)}" alt="{e(original.name)}" loading="lazy">'
        else:
            body = f'<iframe src="{e(address)}" title="{e(original.name)}" loading="lazy"></iframe>'
        parts.append(
            f"<figure>{body}<figcaption><b>{e(original.name)}.</b> {e(caption)}"
            f' <a href="{e(address)}">Open</a></figcaption></figure>'
        )
    if checks:
        rows = "".join(
            f'<tr><td class="l">{e(c["name"])}</td><td class="l">{e(c["rule"])}</td>'
            f"<td>{e(show(c['value']))}</td><td>{e(show(c['threshold']))}"
            f"{' <span class="proposed">proposed</span>' if c['proposed'] else ''}</td>"
            f"<td>{badge(c['passed'])}</td><td class='l mute'>{e(c.get('note', ''))}</td></tr>"
            for c in checks
        )
        parts += [
            _caption(caption, "Checks"),
            '<div class="scroll"><table class="data"><thead><tr><th class="l">Check</th>'
            '<th class="l">Rule</th><th>Value</th><th>Threshold</th><th>Verdict</th>'
            f'<th class="l">Note</th></tr></thead><tbody>{rows}</tbody></table></div>',
        ]
    else:
        parts.append('<p class="mute">No checks in this record, so it is not judged.</p>')
    if record["numbers"]:
        rows = "".join(
            f'<tr><td class="l">{e(k)}</td><td>{e(show(v))}</td></tr>'
            for k, v in sorted(record["numbers"].items())
        )
        parts += [
            _caption(caption, "Numbers"),
            '<div class="scroll"><table class="data kv"><thead><tr><th class="l">Number</th>'
            f"<th>Value</th></tr></thead><tbody>{rows}</tbody></table></div>",
        ]
    if record["parameters"]:
        rows = "".join(
            f'<tr><td class="l">{e(p["name"])}</td><td>{e(show(p["value"]))}</td>'
            f'<td><span class="tag">[{e(p["tag"])}]</span></td>'
            f'<td class="l mute">{e(p.get("source", ""))}</td></tr>'
            for p in record["parameters"]
        )
        parts += [
            _caption(caption, "Parameters"),
            '<div class="scroll"><table class="data"><thead><tr><th class="l">Parameter</th>'
            '<th>Value</th><th>Tag</th><th class="l">Source</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>",
        ]
    for name, table in sorted(record["tables"].items()):
        parts.append(
            f'<details class="table"><summary>Table <code>{e(name)}</code></summary>'
            f"{_caption(caption, 'Table ' + name)}"
            f"<pre>{e(json.dumps(table, indent=1, sort_keys=True, ensure_ascii=False))}</pre>"
            "</details>"
        )
    if record["inputs"]:
        rows = "".join(
            f'<tr><td class="l">{e(i.get("path", ""))}</td><td>{e(show(i.get("bytes")))}</td>'
            f'<td class="l"><code>{e(i.get("sha256", ""))}</code></td></tr>'
            for i in record["inputs"]
        )
        parts.append(
            '<details class="table"><summary>Inputs</summary>'
            f"{_caption(caption, 'Inputs')}"
            '<div class="scroll"><table class="data"><thead><tr><th class="l">Path</th>'
            '<th>Bytes</th><th class="l">SHA-256</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div></details>"
        )
    software = ", ".join(f"{k} {v}" for k, v in sorted(record["software"].items()))
    parts += [f'<p class="mute small">Software: {e(software or "–")}</p>', "</article>"]
    return "\n".join(parts)


def _fact_cell(source: Source, name: str) -> str:
    fact = source.fact(name)
    if fact is None:  # load() refuses this; kept for safety
        return '<td class="o o-missing">–</td>'
    slug = fact.outcome.replace(" ", "-")
    return f'<td class="o o-{slug}" title="{e(fact.observed or fact.outcome)}">{e(fact.shown)}</td>'


def _fact_rows(source: Source) -> str:
    rows = []
    for fact in source.facts:
        passage = (
            f"<details><summary>passage</summary><pre>{e(fact.passage.strip())}</pre></details>"
            if fact.passage.strip()
            else ""
        )
        note = " ".join(p for p in (fact.note.strip(), fact.verdict_note.strip()) if p)
        slug = fact.outcome.replace(" ", "-")
        rows.append(
            f'<tr><td class="l">{e(fact.name)}{"" if fact.required else " <small>further</small>"}'
            f'</td><td class="o o-{slug}">{e(fact.shown)}</td>'
            f'<td class="l wrap">{e(fact.claimed or "–")}</td>'
            f'<td class="l wrap">{e(fact.observed or "–")}</td>'
            f'<td class="l wrap">{href(fact.source_url)}{passage}</td>'
            f'<td class="l wrap mute">{e(note)}</td></tr>'
        )
    return "".join(rows)


def sources_section(sources: list[Source], layout: Layout) -> str:
    legend = "".join(f'<span class="o o-{o.replace(" ", "-")} key">{e(o)}</span>' for o in OUTCOMES)
    head = (
        '<section id="sources"><div class="sec-head"><h2>Sources</h2>'
        f'<div class="legend">{legend}</div></div>'
    )
    if not sources:
        return head + '<p class="empty">No sources checked yet.</p></section>'
    columns = "".join(f"<th>{e(SHORT[name])}</th>" for name in REQUIRED)
    rows = "".join(
        f'<tr><td class="l"><a href="#source-{e(s.id)}">{e(s.title)}</a>'
        f"<small>{e(level_words(s, layout.records))}</small></td>"
        f"<td>{e(s.stage)}</td>{''.join(_fact_cell(s, name) for name in REQUIRED)}"
        f"<td>{len(s.further)}</td></tr>"
        for s in sources
    )
    blocks = []
    for s in sources:
        counts = summary(s)
        warning = (
            f'<p class="notice">{len(s.differs)} fact(s) differ from docs/flood/requirements.md: '
            f"{e(', '.join(f.name for f in s.differs))}. Under FS6 the stage stops until the "
            "requirements are corrected.</p>"
            if s.differs
            else ""
        )
        blocks.append(
            f'<details class="source" id="source-{e(s.id)}"><summary><b>{e(s.title)}</b> '
            f'<span class="mute">{e(s.publisher)}; {e(level_words(s, layout.records))}; '
            + ", ".join(f"{counts[o]} {o}" for o in OUTCOMES)
            + "</span></summary>"
            + warning
            + f'<p class="small">Checked on {e(s.checked_on)} in {e(s.stage)}. Used for '
            f"{e(', '.join(s.used_for) or '–')}. Known biases: {e(s.known_biases or '–')}</p>"
            + _caption(
                "Each fact as read from the primary source on the date shown; claimed is what "
                "the requirements say. Facts are not a recomputation of values.",
                f"Facts of {s.title}",
            )
            + '<div class="scroll"><table class="data facts"><thead><tr><th class="l">Fact</th>'
            '<th>Outcome</th><th class="l">Claimed</th><th class="l">Observed</th>'
            '<th class="l">Address and passage</th><th class="l">Note</th></tr></thead>'
            f"<tbody>{_fact_rows(s)}</tbody></table></div></details>"
        )
    return (
        head
        + _caption(
            "One row per facts file, one column per fact that FS6 requires; hover a cell for what "
            "the source says. The level is named as in FS7: facts confirmed means every fact of "
            "the source was read from the primary source and agrees with the requirements (or does "
            "not apply); otherwise the level reads facts checked, with how many facts were "
            "confirmed, differ or were not checked. Either is a reading of the primary source, "
            'not a recomputation of its values. A cell reading "read, no claim" is a fact the '
            "requirements said nothing about: it was read from the source, with nothing to "
            "confirm it against.",
            "Source facts",
        )
        + '<div class="scroll"><table class="data grid"><thead><tr><th class="l">Source</th>'
        f"<th>Stage</th>{columns}<th>Further</th></tr></thead><tbody>{rows}</tbody></table></div>"
        + "".join(blocks)
        + "</section>"
    )


def _tile_row(label: str, items: list[tuple[str, str, int]]) -> str:
    """One labelled row of count tiles; each item is (data-count key, shown label, count)."""
    return (
        f'<div class="tile-row"><span class="row-label">{e(label)}</span>'
        + "".join(
            f'<div class="tile" data-count="{e(key)}"><b>{count}</b><span>{e(shown)}</span></div>'
            for key, shown, count in items
        )
        + "</div>"
    )


def tiles(records: list[dict[str, Any]], sources: list[Source]) -> str:
    required = dict.fromkeys(OUTCOMES, 0)
    further = dict.fromkeys(OUTCOMES, 0)
    for source in sources:
        for fact in source.facts:
            (required if fact.required else further)[fact.outcome] += 1
    verdicts = {"pass": 0, "fail": 0, "not judged": 0}
    for record in records:
        if not record["checks"] or record["passed"] is None:
            verdicts["not judged"] += 1
        else:
            verdicts["pass" if record["passed"] else "fail"] += 1
    items = [("records", len(records)), *verdicts.items(), ("sources", len(sources))]
    return (
        '<section class="tiles" aria-label="Counts">'
        + _tile_row("Records and sources", [(k, k, v) for k, v in items])
        + _tile_row(
            f"Required facts (FS6, {len(REQUIRED)} per source), by outcome",
            [(f"required {k}", k, v) for k, v in required.items()],
        )
        + _tile_row(
            "Further facts, by outcome", [(f"further {k}", k, v) for k, v in further.items()]
        )
        + "</section>"
    )


STYLE = """
:root {
  --ink: #0b0b0b; --ink-2: #52514e; --mute: #898781;
  --rule: #e1e0d9; --rule-2: #c3c2b7;
  --page: #f9f9f7; --surface: #fcfcfb; --hover: #f1f0ec;
  --accent: #1c5cab; --warn: #b45309; --ok: #1f7a4d; --bad: #b42318;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px;
  --f-xs: 11px; --f-s: 12px; --f-m: 13px; --f-l: 15px; --f-xl: 20px;
  --o-confirmed: #d9efe2; --o-differs: #f9d9d2; --o-not-checked: #f6e7c8;
  --o-not-applicable: #ebeae5;
}
* { box-sizing: border-box; }
body { margin: 0; font: var(--f-m)/1.5 Inter, "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: var(--ink); background: var(--page); -webkit-font-smoothing: antialiased; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
code, pre { font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
code { background: var(--hover); padding: 0 3px; border-radius: 2px; overflow-wrap: anywhere; }
pre { background: var(--surface); border: 1px solid var(--rule); padding: var(--s2);
  overflow: auto; max-height: 420px; white-space: pre-wrap; overflow-wrap: anywhere; }
.mute { color: var(--mute); } .small { font-size: var(--f-s); }
.top { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2) var(--s5);
  padding: var(--s2) var(--s4); border-bottom: 2px solid var(--ink); }
.brand { display: flex; flex-direction: column; line-height: 1.2; }
.brand b { font-size: var(--f-l); font-weight: 650; }
.brand small { font-size: var(--f-xs); color: var(--mute); }
.top nav { margin-left: auto; display: flex; gap: var(--s4); font-size: var(--f-s); }
main { max-width: 1120px; margin: 0 auto; padding: var(--s4) var(--s4) 64px; }
section { margin-top: var(--s5); }
h1 { font-size: var(--f-xl); font-weight: 650; margin: 0 0 var(--s2); }
h2 { font-size: var(--f-xs); letter-spacing: .06em; text-transform: uppercase;
  color: var(--ink-2); font-weight: 600; margin: 0; }
h3 { font-size: var(--f-l); margin: 0; font-weight: 650; }
.intro p { max-width: 76ch; margin: 0 0 var(--s2); }
.sec-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2) var(--s4);
  padding-bottom: var(--s2); border-bottom: 1px solid var(--rule-2); margin-bottom: var(--s3); }
.tiles { display: flex; flex-direction: column; gap: var(--s2); }
.tile-row { display: flex; flex-wrap: wrap; align-items: stretch; gap: var(--s2); }
.row-label { flex: 0 0 100%; font-size: var(--f-xs); color: var(--ink-2); }
.tile { border: 1px solid var(--rule-2); background: var(--surface); padding: var(--s2) var(--s3);
  min-width: 96px; display: flex; flex-direction: column; }
.tile b { font-size: var(--f-xl); font-variant-numeric: tabular-nums; }
.tile span { font-size: var(--f-xs); color: var(--ink-2); text-transform: uppercase;
  letter-spacing: .04em; }
.card { border: 1px solid var(--rule-2); background: var(--surface); padding: var(--s3) var(--s4);
  margin-bottom: var(--s4); }
.card-head { display: flex; align-items: center; gap: var(--s3); }
.stage { font-size: var(--f-xs); color: var(--ink-2); border: 1px solid var(--rule-2);
  padding: 0 var(--s1); }
.badge { font-size: var(--f-xs); font-weight: 650; text-transform: uppercase; letter-spacing: .04em;
  padding: 1px 6px; border-radius: 2px; white-space: nowrap; }
.badge.pass { background: var(--ok); color: #fff; }
.badge.fail { background: var(--bad); color: #fff; }
.badge.none { background: var(--hover); color: var(--ink-2); border: 1px solid var(--rule-2); }
.proposed { font-size: var(--f-xs); color: var(--warn); font-style: italic; }
.tag { font: 12px ui-monospace, Menlo, monospace; }
.caption { font-size: var(--f-s); color: var(--ink-2); margin: var(--s3) 0 var(--s1); }
.scroll { overflow-x: auto; }
table.data { width: 100%; border-collapse: collapse; font-size: var(--f-s); }
table.data th, table.data td { padding: 4px var(--s2); text-align: right; vertical-align: top;
  border-bottom: 1px solid var(--rule); font-variant-numeric: tabular-nums; }
table.data th { font-size: var(--f-xs); letter-spacing: .04em; text-transform: uppercase;
  color: var(--ink-2); font-weight: 600; border-bottom-color: var(--rule-2); }
table.data .l { text-align: left; }
table.data td.wrap { max-width: 36ch; overflow-wrap: anywhere; }
table.data td small { display: block; color: var(--mute); font-size: var(--f-xs); }
table.grid td.o { text-align: center; cursor: help; }
.o-confirmed { background: var(--o-confirmed); } .o-differs { background: var(--o-differs); }
.o-not-checked { background: var(--o-not-checked); }
.o-not-applicable { background: var(--o-not-applicable); }
.legend { display: flex; flex-wrap: wrap; gap: var(--s2); font-size: var(--f-xs); }
.legend .key { padding: 1px 6px; border: 1px solid var(--rule-2); }
details { margin: var(--s2) 0; } summary { cursor: pointer; }
details.source { border-top: 1px solid var(--rule); padding-top: var(--s2); }
.notice { color: var(--warn); font-weight: 600; }
.empty { color: var(--mute); font-style: italic; }
figure { margin: var(--s3) 0; }
figure img { max-width: 100%; border: 1px solid var(--rule); }
figure iframe { width: 100%; height: 480px; border: 1px solid var(--rule); background: #fff; }
figcaption { font-size: var(--f-s); color: var(--ink-2); margin-top: var(--s1); }
ul.notes { margin: var(--s1) 0; padding-left: var(--s5); font-size: var(--f-s); }
"""


def render(layout: Layout) -> str:
    """The whole page as text; depends on the committed records and facts files only."""
    records = load_records(layout.records)
    sources = load_all(layout.facts)
    cards = (
        "\n".join(record_card(record, layout) for record in records)
        if records
        else '<p class="empty">No records yet.</p>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flood lab: visual tests</title>
<style>{STYLE}</style>
</head>
<body>
<!-- generated by python -m flood_lab.gallery from site/flood/tests/records/ and
src/flood_lab/facts/; do not edit -->
<header class="top">
  <div class="brand"><b>Flood Loss &amp; Trigger Lab</b>
  <small>visual tests, generated from records</small></div>
  <nav><a href="../../">crc-lab</a></nav>
</header>
<main>
<section class="intro">
  <h1>Visual tests and source facts</h1>
  <p>One card per check record: what ran, the rules and whether each passed. Thresholds marked
  <i>proposed</i> are starting values. Parameters carry their tags [S] [I] [P] [V]
  (docs/flood/requirements.md, section 4). Sources list the outcome of each fact read from the
  primary source (FS6), with the level of check named as in FS7.</p>
</section>
{tiles(records, sources)}
<section id="records"><div class="sec-head"><h2>Records</h2></div>
{cards}
</section>
{sources_section(sources, layout)}
</main>
</body>
</html>
"""


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write(layout: Layout | None = None) -> Path:
    layout = layout or Layout(paths.ROOT)
    text = render(layout)
    copies = figure_copies(load_records(layout.records), layout)
    for address, original in copies.items():
        if not original.is_file():
            raise ValueError(f"figure {original.relative_to(layout.root)} does not exist")
        target = layout.tests / address
        data = original.read_bytes()
        if not target.exists() or target.read_bytes() != data:
            _write_bytes_atomic(target, data)
    if layout.copies.is_dir():
        for path in sorted(layout.copies.rglob("*"), reverse=True):
            if path.is_file() and path.relative_to(layout.tests).as_posix() not in copies:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    write_text_atomic(layout.page, text)
    return layout.page


def main() -> int:
    page = write()
    print(f"Flood gallery: wrote {page.relative_to(paths.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
