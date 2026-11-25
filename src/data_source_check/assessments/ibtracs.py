"""IBTrACS: exploration, and verification of crc-sdk 1.0's ``IBTrACS`` against NOAA's file.

crc-sdk 1.0 reads one file, NOAA's ``ALL`` CSV, and returns two observations per track point
for one agency: its maximum sustained wind and its minimum central pressure. The reference
side downloads the same file and recomputes, with the standard library (and h3 for the
cell), every row crc-sdk returns for each of the ten agencies, by default (no selection).
Every row is compared, value by value; nothing is sampled.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from ..adapters.crc import ibtracs as framework
from ..core import compare
from ..core.records import CheckRecord
from ..reference import ibtracs as reference

SOURCE = "ibtracs"
#: every agency crc-sdk 1.0 offers is assessed; each reads its own pair of NOAA's columns
AGENCIES = reference.AGENCIES
#: positions are compared as numbers: a longitude east of 180 degrees is moved by 360, and
#: the last bit of the result may differ between two correct ways of doing it
TOLERANCE = 1e-9
#: the columns of crc-sdk's output, with their Arrow types, as the statement gives them
OUTPUT_COLUMNS = [
    ("variable_id", "string"),
    ("scenario_id", "string"),
    ("period_id", "string"),
    ("support_id", "string"),
    ("cell_id", "uint64"),
    ("geometry", "binary"),
    ("time", "string"),
    ("value", "double"),
    ("station_id", "string"),
    ("group_id", "string"),
    ("failure", "struct<code: string not null, message: string not null>"),
    (
        "coverage",
        "struct<valid: int64 not null, expected: int64 not null, "
        "minimum_fraction: double not null>",
    ),
]
COMPARED = [*reference.FIELDS, "support_hash_matches_point"]
#: rules of the reference reader that a test may make deliberately wrong
POINT_RULES = ("wrap_longitude", "time_separator", "resolution", "empty_as_null", "pressure_first")

Rules = dict[str, Any]


def _input(role: str, provenance: dict[str, Any]) -> dict[str, Any]:
    keys = ("url", "sha256", "retrieved_at", "etag", "last_modified", "bytes")
    return {"role": role} | {key: provenance.get(key) for key in keys if key in provenance}


def _framework_row(row: dict[str, Any]) -> list[Any]:
    """One crc-sdk row in the order of ``COMPARED``: the point decoded from its WKB, the
    support_id split at '@', and whether the part after '@' is the hash of that WKB."""
    geometry = row["geometry"] or b""
    position, _, digest = str(row["support_id"]).partition("@")
    lon = lat = None
    if len(geometry) == 21:
        lon, lat = struct.unpack("<dd", geometry[5:])
    failure = row["failure"] or {}
    return [
        row["variable_id"],
        row["scenario_id"],
        row["period_id"],
        position,
        row["cell_id"],
        geometry[:5].hex() if len(geometry) == 21 else geometry.hex(),
        lon,
        lat,
        row["time"],
        row["value"],
        row["station_id"],
        row["group_id"],
        failure.get("code"),
        failure.get("message"),
        row["coverage"],
        digest == hashlib.sha256(geometry).hexdigest()[:20],
    ]


def _compare_agency(
    agency: str, ref_path: Path, reading: framework.Reading, rules: Rules
) -> dict[str, Any]:
    """Every row crc-sdk gives for an agency against the reference's rows, in order."""
    point_rules = {key: rules[key] for key in POINT_RULES if key in rules}
    identical = [0, 0]  # rows whose WKB point is byte-identical to the reference's, rows
    pending: list[bytes] = []

    def ours() -> Iterator[list[Any]]:
        for expected in reference.agency_points(ref_path, agency, **point_rules):
            pending.append(expected.pop("wkb"))
            yield [expected[name] for name in reference.FIELDS] + [True]

    def theirs() -> Iterator[list[Any]]:
        for row in reading.rows:
            values = _framework_row(row)
            if pending:
                identical[1] += 1
                identical[0] += pending.pop(0) == (row["geometry"] or b"")
            yield values

    result = compare.compare_rows(COMPARED, ours(), theirs(), tolerance=TOLERANCE)
    result["rows_point_bytes_identical"] = identical[0]
    result["rows_point_bytes_compared"] = identical[1]
    return result


def assess(
    cache: Path,
    *,
    live: bool,
    versions: dict[str, str],
    log: Callable[[str], None] = lambda _: None,
    agencies: Sequence[str] = AGENCIES,
    rules: Rules | None = None,
) -> dict[str, Any]:
    """The records of one run: checks for each agency, and exploration of NOAA's file.

    ``cache`` holds the reference download (``reference/``) and crc-sdk's own cache
    (``crc-sdk/``). ``live`` downloads both afresh; otherwise both caches are read only.
    ``rules`` overrides reference rules, for the tests that must end as ``differs``.
    """
    rules = dict(rules or {})
    unit_names = rules.get("unit_names", reference.UNIT_NAMES)
    doi = rules.get("doi", reference.DOI)
    sdk_cache = cache / "crc-sdk"
    log("reference download")
    ours = reference.download("ALL", cache / "reference", live=live)
    ref_path = Path(ours["path"])
    address = reference.url("ALL")
    columns, units = reference.header(ref_path)
    unit_of = dict(zip(columns, units, strict=True))
    their_inputs: dict[str, Any] = {}

    def make(
        check: str, category: str, method: str, agrees: bool | None, **more: Any
    ) -> CheckRecord:
        return compare.record(
            source=SOURCE,
            check=check,
            tier="verification",
            category=category,
            method=method,
            agrees=agrees,
            versions=versions,
            inputs=(_input("reference download", ours), dict(their_inputs)),
            **more,
        )

    checks: list[CheckRecord] = []
    readings: dict[str, dict[str, Any]] = {}
    for number, agency in enumerate(agencies):
        mode = ("refresh" if number == 0 else "reuse") if live else "offline"
        log(f"{agency}: every row, crc-sdk against the reference ({mode})")
        result, after = framework.read(
            agency,
            sdk_cache,
            mode=mode,
            consume=lambda reading, a=agency: (
                reading.columns,
                reading.types,
                _compare_agency(a, ref_path, reading, rules),
            ),
        )
        names, types, values = result
        readings[agency] = after
        source = after["source"] or {}
        resources = source.get("resources") or [{}]
        their_inputs.clear()
        their_inputs.update(
            {
                "role": "crc-sdk resource",
                "url": resources[0].get("uri"),
                "sha256": str(resources[0].get("sha256") or "").removeprefix("sha256:"),
                "retrieved_at": resources[0].get("retrieved_at"),
            }
        )

        expected_units = {
            f"ibtracs:{agency}:maximum_sustained_wind": unit_names.get(
                unit_of[f"{agency}_WIND"].strip()
            ),
            f"ibtracs:{agency}:minimum_central_pressure": unit_names.get(
                unit_of[f"{agency}_PRES"].strip()
            ),
        }
        declared = {v["id"]: v for v in after["variables"]}
        declared_units = {key: value["unit"] for key, value in declared.items()}
        expected_fields = {
            f"ibtracs:{agency}:maximum_sustained_wind": {"agency": agency}
            | ({"averaging_duration_seconds": 60} if agency == "USA" else {}),
            f"ibtracs:{agency}:minimum_central_pressure": {"agency": agency},
        }
        declared_fields = {key: value["fields"] for key, value in declared.items()}
        schema = list(zip(names, types, strict=True))
        checks.append(
            make(
                f"declaration[{agency}]",
                "consistency",
                "The variables crc-sdk declares for the agency against the file: their names, "
                "the unit NOAA gives on line 2 for the agency's wind and pressure columns, read "
                "through the reference's own table of unit names, and the measurement fields; "
                "the output columns and their types against the statement.",
                declared_units == expected_units
                and declared_fields == expected_fields
                and schema == OUTPUT_COLUMNS,
                result={
                    "file_units": {
                        f"{agency}_WIND": unit_of[f"{agency}_WIND"].strip(),
                        f"{agency}_PRES": unit_of[f"{agency}_PRES"].strip(),
                    },
                    "declared_units": declared_units,
                    "expected_units": expected_units,
                    "declared_fields": declared_fields,
                    "expected_fields": expected_fields,
                    "output_columns_as_stated": schema == OUTPUT_COLUMNS,
                    "output_columns": [f"{n}: {t}" for n, t in schema],
                },
                tolerance={"names, units, fields, columns": "identical"},
                steps=("units", "schema"),
            )
        )

        checks.append(
            make(
                f"values[{agency}]",
                "fidelity",
                "Every data row of NOAA's file, read with Python's csv module, turned into the two "
                "rows the statement describes (wind, then pressure, at the combined position), "
                "against every row crc-sdk yields, in order, field by field. The point is decoded "
                "from crc-sdk's WKB; the part of support_id after '@' is checked against the "
                "SHA-256 of that WKB.",
                compare.rows_agree(values) if values["values_compared"] else None,
                result=values,
                sample={"rows": "all", "agency": agency, "selection": "none (the default)"},
                tolerance={
                    "numbers": f"within {TOLERANCE} (longitude, latitude); others exact",
                    "text": "exact; null equals null only",
                },
                steps=(
                    "columns",
                    "trim",
                    "time",
                    "position",
                    "cell",
                    "identifiers",
                    "values",
                    "missing",
                    "rows",
                ),
                note="" if values["values_compared"] else "the file has no data rows",
            )
        )

        resource = resources[0]
        report_sources = after["report_sources"]
        batch = after["first_batch"].get("resources_in_batch_metadata", [])
        expected_release = reference.release_digest([(address, "sha256:" + ours["sha256"])])
        facts = {
            "provider_is_ibtracs": source.get("provider") == "ibtracs",
            "member_is_the_agency": source.get("member") == agency,
            "one_resource": len(source.get("resources") or []) == 1,
            "resource_uri_is_the_address": resource.get("uri") == address,
            "resource_sha256_is_the_file": resource.get("sha256") == "sha256:" + ours["sha256"],
            "licence_present": bool(resource.get("license")),
            "attribution_names_the_doi": doi in str(resource.get("attribution") or ""),
            "retrieved_at_with_zone": bool(resource.get("retrieved_at_has_zone")),
            "release_sha256_recomputed": source.get("release_sha256") == expected_release,
            "report_carries_the_source": source in report_sources,
            "batch_metadata_carries_the_resource": any(
                r.get("sha256") == resource.get("sha256")
                and r.get("license") == resource.get("license")
                and r.get("attribution") == resource.get("attribution")
                for r in batch
            ),
            "report_complete_and_valid": after["report"]["complete"] is True
            and after["report"]["valid"] is True,
        }
        checks.append(
            make(
                f"provenance[{agency}]",
                "consistency",
                "The source identity crc-sdk attaches to the output (metadata, report and the "
                "schema metadata of the first batch) against the reference download: address, "
                "checksum, licence text present, attribution naming NOAA's DOI for v04r01, "
                "retrieval time with a time zone, and the release checksum recomputed from the "
                "(address, checksum) pair.",
                all(facts.values()),
                result={
                    "facts": facts,
                    "product": source.get("product"),
                    "release_id": source.get("release_id"),
                    "release_sha256": source.get("release_sha256"),
                    "expected_release_sha256": expected_release,
                    "license": resource.get("license"),
                    "attribution": resource.get("attribution"),
                    "retrieved_at": resource.get("retrieved_at"),
                    "schema_metadata_keys": after["first_batch"].get("schema_metadata_keys"),
                    "report": after["report"],
                },
                tolerance={"facts": "all true"},
                steps=("provenance",),
            )
        )

    first = readings[agencies[0]]["source"] or {}
    resources = first.get("resources") or [{}]
    every = [((r["source"] or {}).get("resources") or [{}])[0] for r in readings.values()]
    checks.insert(
        0,
        make(
            "bytes",
            "fidelity",
            "SHA-256 of an independent download of NOAA's file against the checksum crc-sdk "
            "records for the file it read, for every agency read.",
            all(r.get("sha256") == "sha256:" + ours["sha256"] for r in every),
            result={
                "reference_sha256": ours["sha256"],
                "framework_sha256": sorted({str(r.get("sha256")) for r in every}),
                "bytes": ours.get("bytes"),
            },
            tolerance={"bytes": "identical"},
            steps=("bytes",),
        ),
    )
    checks.insert(
        0,
        make(
            "address",
            "fidelity",
            "The address crc-sdk records for the file it read against the documented address "
            "of NOAA's ALL file, which the reference downloads.",
            all(r.get("uri") == address for r in every) and len(resources) == 1,
            result={
                "documented": address,
                "framework": sorted({str(r.get("uri")) for r in every}),
                "resources_per_read": len(resources),
            },
            tolerance={"address": "identical"},
            steps=("address",),
        ),
    )

    log("exploration")
    explored = reference.explore(ref_path)
    explored["file"] = _input("reference download", ours)
    counts = reference.agency_counts(ref_path)
    for agency in agencies:
        counts[agency]["framework_rows"] = readings[agency]["report"]["produced"]
        counts[agency]["framework_no_data"] = readings[agency]["report"]["no_data"]
    return present(
        {
            "source": SOURCE,
            "versions": dict(versions),
            "run_at": compare.now(),
            "agencies_assessed": list(agencies),
            "checks": [check.to_dict() for check in checks],
            "exploration": {"ALL": explored, "agencies": counts},
        }
    )


def _summary(check: dict[str, Any]) -> str:
    result = check["result"]
    if "values_compared" in result:
        return (
            compare.rows_summary(result)
            + f"; largest numeric difference {result['largest_difference']:.1e}"
        )
    if "reference_sha256" in result:
        same = check["outcome"] == "confirmed"
        return (
            f"{compare.number(result['bytes'])} bytes; SHA-256 {result['reference_sha256'][:12]}… "
            + ("on both sides" if same else f"crc-sdk: {', '.join(result['framework_sha256'])}")
        )
    if "documented" in result:
        return (
            "the documented address"
            if check["outcome"] == "confirmed"
            else (f"crc-sdk read {', '.join(result['framework'])}")
        )
    if "declared_units" in result:
        units = ", ".join(sorted(set(result["declared_units"].values())))
        stated = result["output_columns_as_stated"]
        return f"declared units {units}; output columns as stated: {stated}"
    if "facts" in result:
        facts = result["facts"]
        missing = [name for name, value in facts.items() if not value]
        return f"{sum(facts.values())} of {len(facts)} facts hold" + (
            f"; not: {', '.join(missing)}" if missing else ""
        )
    return check.get("note", "")


def present(run: dict[str, Any]) -> dict[str, Any]:
    """Add what the page and the report show: summaries, headline numbers, tables, a chart."""
    for check in run["checks"]:
        check["summary"] = _summary(check)
    values = [c["result"] for c in run["checks"] if c["check"].startswith("values[")]
    count = compare.tally(run["checks"])
    whole = run["exploration"]["ALL"]
    agencies = run["exploration"]["agencies"]
    run["headline"] = [
        [len(run["agencies_assessed"]), "agencies read"],
        [sum(r["values_compared"] for r in values), "values compared one by one"],
        [sum(r["values_differing"] for r in values), "values that differ"],
        [f"{count.get('confirmed', 0)} of {len(run['checks'])}", "checks confirmed"],
        [count.get("differs", 0), "checks that differ"],
    ]
    run["tables"] = [
        {
            "title": "What is in the publisher's file",
            "note": "Counted from NOAA's ALL file by the reference reader.",
            "head": [
                "File",
                "Rows",
                "Storms",
                "Seasons",
                "Columns",
                "Values missing",
                "Last modified by publisher",
            ],
            "rows": [
                [
                    "ALL",
                    whole["rows"],
                    whole["storms"],
                    f"{whole['seasons'][0]} to {whole['seasons'][1]}" if whole["seasons"] else "",
                    whole["columns"],
                    f"{100 * whole['values_empty_after_trim'] / whole['values_total']:.1f} %"
                    if whole["values_total"]
                    else "",
                    whole["file"].get("last_modified") or "",
                ]
            ],
        },
        {
            "title": "What crc-sdk returns for each agency",
            "note": "Points and values counted from NOAA's file by the reference reader; rows "
            "and rows without a value as crc-sdk's report gives them. crc-sdk returns two rows "
            "per point of the file for every agency, with or without a value.",
            "head": [
                "Agency",
                "Points in the file",
                "Points with a wind",
                "Points with a pressure",
                "Storms with a value",
                "Rows from crc-sdk",
                "Rows without a value",
            ],
            "rows": [
                [
                    agency,
                    agencies[agency]["points"],
                    agencies[agency]["wind"],
                    agencies[agency]["pressure"],
                    agencies[agency]["storms_with_a_value"],
                    agencies[agency]["framework_rows"],
                    agencies[agency]["framework_no_data"],
                ]
                for agency in run["agencies_assessed"]
            ],
        },
    ]
    run["chart"] = {
        "title": "Storms per season",
        "unit": "storms",
        "x": "Season",
        "select": "File",
        "default": "ALL",
        "series": {"ALL": whole["storms_by_season"]},
    }
    return run
