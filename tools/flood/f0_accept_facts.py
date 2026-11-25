"""F0, step 4: turn the fact drafts in the cache into the committed facts files.

The drafts were written by lookup agents from the publishers' own pages and files
(``data/cache/flood/f0/facts-draft/<id>.toml``, each fact with the address read and the passage).
The coordinator reviews them and gives every fact its outcome. This script applies that review: the
outcome the draft proposed stands unless ``VERDICTS`` below says otherwise, and each change carries
its reason. It also adds what the lab uses the source for, the stage and the level of check
(requirements FS4, FS6, section 7).

    uv run python tools/flood/f0_accept_facts.py

It refuses to write a file that ``flood_lab.facts`` does not accept.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flood_lab import facts  # noqa: E402
from lab_common.io import write_text_atomic  # noqa: E402

DRAFTS = ROOT / "data" / "cache" / "flood" / "f0" / "facts-draft"
READER = "facts and second reader"

#: id -> (level, second-reader stage, requirement ids)
SOURCES: dict[str, tuple[str, str, list[str]]] = {
    "nyc-stormwater-flood-maps": (READER, "F2", ["FS1", "FH3"]),
    "floodnet-flood-events": (READER, "F2", ["FS3", "FV2", "FT1"]),
    "floodnet-sensors": (READER, "F2", ["FS3", "FV2", "FT1"]),
    "groundsource": (READER, "F2", ["FS2", "FS5", "FV5", "FT5"]),
    "usgs-ida-high-water-marks": (READER, "F5", ["FV1"]),
    "usgs-ida-depth-rasters": ("facts", "", ["FV1"]),
    "jamaica-bay-ida-depth-map": ("facts", "", ["FV3", "FH3"]),
    "nyc-building-elevation-subgrade": ("facts", "", ["FD5"]),
    "usace-national-structure-inventory": ("facts", "", ["FD5"]),
    "osm-substations": ("facts", "", ["FD3"]),
    "lidar-terrain": ("facts", "", ["FD2"]),
    "noaa-storm-events": ("facts", "", ["FV5", "FT5"]),
    "nyc-311": ("facts", "", ["FV5", "FT5"]),
    "nfip-redacted-claims": ("facts", "", ["FT5"]),
    "deluge-claim-date-rule": ("facts", "", ["FT5"]),
    "rainfall-aorc": ("facts", "", ["FH5", "FT5"]),
    "rainfall-stage-iv": ("facts", "", ["FH4", "FH5"]),
    "rainfall-mrms": (READER, "F5", ["FH4"]),
    "noaa-atlas-14": ("facts", "", ["FH6"]),
    "rainyday": ("facts", "", ["FH5"]),
    "sfincs-release": ("facts", "", ["FH2"]),
    "substation-curves-nirandjan": ("facts", "", ["FR2"]),
    "substation-curves-other": ("facts", "", ["FR2"]),
    "hazus-flood-functions": ("facts", "", ["FR2", "FR3", "FM5"]),
    "ice-calculator": ("facts", "", ["FM5"]),
    "fema-bca": ("facts", "", ["FM4"]),
}

#: (source id, fact name) -> (outcome, reason). Everything else keeps the proposed outcome.
VERDICTS: dict[tuple[str, str], tuple[str, str]] = {
    ("floodnet-flood-events", "address"): (
        "confirmed",
        "The identifier is as the requirements give it. The retired bulk-download address was not "
        "a claim of the requirements; the reader uses the resource address.",
    ),
    ("floodnet-sensors", "address"): (
        "confirmed",
        "As for the events table: the identifier is right; only the bulk address is retired.",
    ),
    ("nfip-redacted-claims", "identifier"): (
        "confirmed",
        "The requirements name the dataset and no version. The current version is 3; version 2, "
        "which the claim-date preprint used, is no longer served. Recorded so that F8 reads 3.",
    ),
    ("deluge-claim-date-rule", "data_version_used"): (
        "not applicable",
        "No claim in the requirements to compare; kept as a note for F8.",
    ),
    ("groundsource", "rows_bq_2021-09-01"): (
        "confirmed",
        "Requirements section 9, item 2 asked whether rows exist for New York on this date.",
    ),
    ("groundsource", "rows_bq_2021-09-02"): (
        "confirmed",
        "Requirements section 9, item 2 asked whether rows exist for New York on this date.",
    ),
    ("groundsource", "rows_bq_2023-09-29"): (
        "confirmed",
        "Requirements section 9, item 2 asked whether rows exist for New York on this date.",
    ),
    ("noaa-storm-events", "fields"): (
        "differs",
        "Here it is the publisher's documentation that differs from the publisher's files; the "
        "requirements make no claim about the fields.",
    ),
}

#: sources whose publisher states a checksum that our copy was compared with
PUBLISHER_CHECKSUM = {
    "groundsource",
    "usgs-ida-depth-rasters",
    "usgs-ida-high-water-marks",
    "jamaica-bay-ida-depth-map",
    "substation-curves-nirandjan",
}

FACT_KEYS = ("name", "claimed", "observed", "outcome", "source_url", "passage", "note")
FILE_KEYS = ("path", "url", "bytes", "sha256", "fetched_at")


def _quote(text: str) -> str:
    """A TOML basic string, single line or multi-line, with everything escaped."""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = "".join(
        ch if ch in "\n\t" or ord(ch) >= 32 else f"\\u{ord(ch):04x}" for ch in escaped
    )
    if "\n" in escaped:
        return '"""\n' + escaped + '"""'
    return '"' + escaped.replace("\t", "\\t") + '"'


def _render(draft: dict, level: str, reader_stage: str, used_for: list[str]) -> str:
    lines = [
        f"id = {_quote(draft['id'])}",
        f"title = {_quote(draft['title'])}",
        f"publisher = {_quote(draft['publisher'])}",
        f"checked_on = {_quote(draft['checked_on'])}",
        'stage = "F0"',
        f"level = {_quote(level)}",
        f"second_reader_stage = {_quote(reader_stage)}",
        "used_for = [" + ", ".join(_quote(item) for item in used_for) + "]",
        f"known_biases = {_quote(draft.get('known_biases', 'not assessed'))}",
    ]
    present = {fact["name"] for fact in draft["fact"]}
    missing = [name for name in facts.REQUIRED if name not in present]
    padded = [
        {
            "name": name,
            "claimed": "",
            "observed": "A publication or a rule, not a data file: it has no such fact.",
            "outcome_proposed": "not applicable",
        }
        for name in missing
    ]
    for fact in [*draft["fact"], *padded]:
        outcome, reason = VERDICTS.get((draft["id"], fact["name"]), (fact["outcome_proposed"], ""))
        no_publisher_sum = fact["name"] == "checksum" and draft["id"] not in PUBLISHER_CHECKSUM
        if no_publisher_sum and outcome == "confirmed":
            outcome, reason = (
                "not applicable",
                "The publisher gives no checksum to compare with; the checksum of our copy is "
                "recorded with the file.",
            )
        extra = {k: v for k, v in fact.items() if k not in (*FACT_KEYS, "outcome_proposed")}
        note = fact.get("note", "")
        if extra:
            note = (note + " " + "; ".join(f"{k}: {v}" for k, v in extra.items())).strip()
        lines += [
            "",
            "[[fact]]",
            f"name = {_quote(fact['name'])}",
            f"claimed = {_quote(fact.get('claimed', ''))}",
            f"observed = {_quote(fact.get('observed', ''))}",
            f"outcome = {_quote(outcome)}",
            f"source_url = {_quote(fact.get('source_url', ''))}",
            f"passage = {_quote(fact.get('passage', ''))}",
            f"note = {_quote(note)}",
            f"verdict_note = {_quote(reason)}",
        ]
    for item in draft.get("file", []):
        lines += ["", "[[file]]"]
        for key in FILE_KEYS:
            value = item.get(key, 0 if key == "bytes" else "")
            lines.append(f"{key} = {int(value)}" if key == "bytes" else f"{key} = {_quote(value)}")
    return "\n".join(lines) + "\n"


def main() -> None:
    target = ROOT / "src" / "flood_lab" / "facts"
    seen, problems = [], []
    for path in sorted(DRAFTS.glob("*.toml")):
        draft = tomllib.loads(path.read_text(encoding="utf-8"))
        if draft["id"] not in SOURCES:
            problems.append(f"{path.name}: no entry in SOURCES")
            continue
        text = _render(draft, *SOURCES[draft["id"]])
        out = target / f"{draft['id']}.toml"
        write_text_atomic(out, text)
        try:
            source = facts.load(out)
        except ValueError as error:
            out.unlink()
            problems.append(str(error))
            continue
        seen.append((source.id, facts.summary(source)))
    for name, counts in seen:
        print(f"{name:36s} {counts}")
    unused = sorted(k for k in VERDICTS if k[0] not in {name for name, _ in seen})
    if unused:
        problems.append(f"verdicts for sources that were not written: {unused}")
    if problems:
        raise SystemExit("\n".join(["NOT ACCEPTED:", *problems]))
    print(f"{len(seen)} sources written to {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
