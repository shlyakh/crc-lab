"""GHCNh: exploration, and verification of crc-sdk 1.0's annual samples against NOAA's files.

What is verified is crc-sdk's default output of an annual indicator, ``GHCNh(indicator=...)``
selected by station and years and read with ``read()``: one annual value per station position
and year, or a missing value with its coverage and reason. No curve is fitted by default, and
none is fitted here. The default completeness rule (``Coverage.complete()``) is checked, and so
is one explicit relaxation, ``Coverage.minimum_fraction(0.9)``, without which few station-years
of these airports carry a value to compare.

The population is the sample assessed at crc-sdk 0.11.2, so that the two versions can be put
side by side: the first forty ``USW`` stations of the station list in the Texas box, years 2000
to 2024. Every station-year NOAA has a file for is recomputed from the Parquet file; a seeded
subset is recomputed again from NOAA's pipe-separated file with the standard library only.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..adapters.crc import ghcnh as framework
from ..core import compare
from ..core.records import CheckRecord
from ..reference import ghcnh as reference

SOURCE = "ghcnh"
SEED = 20261111
BOUNDS = (-106.645646, 25.837377, -93.508292, 36.500704)  # Texas, as in the data explorer
#: the stations assessed at crc-sdk 0.11.2: the first forty USW stations of the box
SAMPLE = (
    "USW00000127", "USW00000129", "USW00000130", "USW00000134", "USW00000137",
    "USW00000166", "USW00000172", "USW00000175", "USW00000176", "USW00000177",
    "USW00000181", "USW00000188", "USW00000208", "USW00000209", "USW00000213",
    "USW00000214", "USW00000215", "USW00000223", "USW00000225", "USW00000229",
    "USW00000230", "USW00000239", "USW00000246", "USW00000247", "USW00000255",
    "USW00000259", "USW00000260", "USW00000262", "USW00000263", "USW00000270",
    "USW00000272", "USW00000276", "USW00000306", "USW00000308", "USW00000313",
    "USW00000349", "USW00000351", "USW00000357", "USW00000362", "USW00000364",
)  # fmt: skip
YEARS = (2000, 2024)
PSV_SAMPLE = 8
#: indicator, as crc-sdk names it -> the short name used in check names since 0.11
INDICATORS = {
    "annual_maximum_daily_maximum_temperature": "temperature_max",
    "annual_minimum_daily_minimum_temperature": "temperature_min",
}
VALUE = {"temperature_max": "value_max", "temperature_min": "value_min"}
#: None is crc-sdk's default, Coverage.complete(); 0.9 is Coverage.minimum_fraction(0.9)
COVERAGES: tuple[float | None, ...] = (None, 0.9)
FIELDS = (
    "station",
    "year",
    "support_id",
    "longitude",
    "latitude",
    "cell_id",
    "valid_days",
    "expected_days",
    "minimum_fraction",
    "value",
    "failure",
)
EXACT = {"values": "exact equality, numbers included"}
ANNUAL_STEPS = (
    "files",
    "columns",
    "refusal",
    "quality",
    "range",
    "day",
    "valid-day",
    "valid-year",
    "annual-value",
    "location",
    "output",
)


def _coverage_name(fraction: float | None) -> str:
    return (
        "Coverage.complete() (default)"
        if fraction is None
        else (f"Coverage.minimum_fraction({fraction:g})")
    )


def _check_name(name: str, label: str, fraction: float | None) -> str:
    return f"{name}[{label}]" if fraction is None else f"{name}[{label}, coverage {fraction:g}]"


def _reference_rows(
    results: Sequence[dict[str, Any]], value: str
) -> tuple[list[list[Any]], list[tuple[str, int]]]:
    """Rows in the compared order, and the station-years with no row."""
    rows, unavailable = [], []
    for item in results:
        if item["unavailable"]:
            unavailable.append((item["station"], item["year"]))
        for row in item["rows"]:
            rows.append(
                [
                    item["station"],
                    item["year"],
                    row["support_id"],
                    row["longitude"],
                    row["latitude"],
                    row["cell_id"],
                    row["valid_days"],
                    row["expected_days"],
                    row["minimum_fraction"],
                    row[value],
                    "" if row["complete"] else "incomplete_year",
                ]
            )
    return sorted(rows, key=lambda r: (r[0], r[1], r[2])), sorted(unavailable)


def _framework_rows(rows: Sequence[dict[str, Any]], keep: set[tuple[str, int]] | None = None):
    chosen = [r for r in rows if keep is None or (r["station"], r["year"]) in keep]
    out = [[row[name] for name in FIELDS] for row in chosen]
    return sorted(out, key=lambda r: (r[0], r[1], r[2]))


def _expected_counts(rows: Sequence[Sequence[Any]], unavailable: int) -> dict[str, int]:
    """The report counts crc-sdk states for these rows: a station-year with no file is
    requested and incomplete; a row with no value is incomplete and has no data."""
    missing = sum(1 for row in rows if row[-1])
    return {
        "requested": len(rows) + unavailable,
        "produced": len(rows),
        "no_data": missing,
        "usable_years": len(rows) - missing,
        "incomplete_years": missing + unavailable,
    }


def _files_summary(role: str, files: Sequence[dict[str, Any]]) -> dict[str, Any]:
    present = [item for item in files if not item["missing"]]
    listing = "".join(sorted(f"{item['url']} {item['sha256']}\n" for item in present))
    return {
        "role": role,
        "url": f"{reference.ROOT} ({len(present)} files)",
        "sha256": hashlib.sha256(listing.encode()).hexdigest(),
        "retrieved_at": max((item["retrieved_at"] for item in files), default=""),
        "files": len(present),
        "files_absent_at_publisher": len(files) - len(present),
        "bytes": sum(item["bytes"] for item in present),
    }


def _operations(provenance: Sequence[dict[str, Any]] | None) -> list[str]:
    out = []
    for step in provenance or ():
        name = step.get("kind", "")
        if name == "temporal_reduction":
            name = f"{name}:{step.get('operation')}@{step.get('coverage')}"
        out.append(name)
    return out


def assess(
    cache: Path,
    *,
    live: bool,
    versions: dict[str, str],
    log: Callable[[str], None] = lambda _: None,
    rules: reference.Rules1 | None = None,
    stations: Sequence[str] | None = None,
    years: tuple[int, int] = YEARS,
    psv_sample: int = PSV_SAMPLE,
) -> dict[str, Any]:
    """The records of one run. crc-sdk's own cache is ``cache / "crc-sdk"``; the reference's
    copies of NOAA's files are under ``cache / "reference"``. ``rules`` overrides the
    reference rules (for fault tests); ``stations`` replaces the sample (for tests)."""
    sdk_cache = cache / "crc-sdk"
    ref_cache = cache / "reference"
    rules = rules or reference.Rules1()
    checks: list[CheckRecord] = []

    log("stations: NOAA's station list against crc-sdk's inventory for the box")
    listed, list_file = reference.station_list(ref_cache, live=live)
    ours_box = reference.in_box(listed, BOUNDS)
    theirs_box = framework.catalogue(BOUNDS, years, sdk_cache, live=live)
    station_fields = ("station", "name", "longitude", "latitude")
    result = compare.compare_rows(
        station_fields,
        [[item[k] for k in station_fields] for item in ours_box],
        [[item[k] for k in station_fields] for item in theirs_box],
    )
    first_usw = [item["station"] for item in theirs_box if item["station"].startswith("USW")]
    result |= {"stations_listed": len(listed)}
    list_input = {
        "role": "reference download (station list)",
        "url": reference.STATION_LIST,
        "sha256": list_file.get("sha256", ""),
        "retrieved_at": list_file["retrieved_at"],
    }
    checks.append(
        compare.record(
            source=SOURCE,
            check="stations[box]",
            tier="verification",
            category="fidelity",
            method="Stations of NOAA's station list whose position lies in the Texas box, read "
            "with the standard library, against the stations crc-sdk's inspect() returns for "
            "the same box: identifier, name and position, in order.",
            agrees=compare.rows_agree(result),
            versions=versions,
            inputs=(list_input, {"role": "crc-sdk inspect()", "url": reference.STATION_LIST}),
            result=result,
            sample={"bounds": list(BOUNDS)},
            tolerance=EXACT,
            steps=("stations",),
        )
    )
    chosen = list(stations) if stations is not None else list(SAMPLE)
    names = {item["station"]: item["name"] for item in listed}
    span = range(years[0], years[1] + 1)
    jobs = [(station, year) for station in chosen for year in span]

    log(f"reference: {len(jobs)} station-years from Parquet")
    with ThreadPoolExecutor(max_workers=8) as pool:
        files = list(
            pool.map(lambda job: reference.download(*job, "parquet", ref_cache, live=live), jobs)
        )
    ours: dict[float | None, list[dict[str, Any]]] = {fraction: [] for fraction in COVERAGES}
    old: list[dict[str, Any]] = []
    for (station, year), item in zip(jobs, files, strict=True):
        reports = [] if item["missing"] else reference.read_reports(Path(item["path"]), "parquet")
        for fraction in COVERAGES:
            ours[fraction].append(reference.annual_rows(reports, station, year, rules, fraction))
        old.append(
            reference.empty_row(station, year)
            if item["missing"]
            else reference.annual_row(reports, station, year)
        )
    default = ours[None]
    failed = sorted({item["station"] for item in default if item["error"]})
    parquet_input = _files_summary("reference download (Parquet)", files)

    with_file = [
        (item["station"], item["year"])
        for item in default
        if item["reports"] and item["station"] not in failed
    ]
    picked = compare.sample(with_file, psv_sample, SEED)
    log(f"reference: {len(picked)} station-years from pipe-separated files")
    psv: dict[float | None, list[dict[str, Any]]] = {fraction: [] for fraction in COVERAGES}
    psv_files = []
    for station, year in picked:
        item = reference.download(station, year, "psv", ref_cache, live=live)
        psv_files.append(item)
        reports = [] if item["missing"] else reference.read_reports(Path(item["path"]), "psv")
        for fraction in COVERAGES:
            psv[fraction].append(reference.annual_rows(reports, station, year, rules, fraction))
    psv_input = _files_summary("reference download (pipe-separated)", psv_files)

    by_url = {item["url"]: item for item in files}
    framework_seen: dict[str, Any] = {}
    for indicator, label in INDICATORS.items():
        value = VALUE[label]
        for fraction in COVERAGES:
            log(f"crc-sdk: {indicator}, {_coverage_name(fraction)}")
            got = framework.annual(
                indicator, chosen, years, sdk_cache, live=live, fraction=fraction, log=log
            )
            sdk_input = {
                "role": "crc-sdk read() of the annual indicator",
                "url": reference.ROOT,
                "retrieved_at": compare.now() if live else "",
            }
            kept = [item for item in ours[fraction] if item["station"] not in failed]
            expected, absent = _reference_rows(kept, value)
            theirs = _framework_rows(got["rows"])
            result = compare.compare_rows(FIELDS, expected, theirs)
            counts_expected = _expected_counts(expected, len(absent))
            counts_got = {key: got["counts"].get(key, 0) for key in counts_expected}
            result |= {
                "stations": len(chosen),
                "station_years": len(jobs),
                "station_years_with_a_file": sum(1 for item in files if not item["missing"]),
                "rows_with_a_value_reference": sum(1 for row in expected if not row[-1]),
                "station_years_without_a_row_reference": len(absent),
                "station_years_without_a_row_framework": len(got["unavailable"]),
                "unavailable_differing": sorted(
                    [list(key) for key in set(absent) ^ set(got["unavailable"])]
                )[: compare.MAX_EXAMPLES],
                "counts_reference": counts_expected,
                "counts_framework": counts_got,
                "stations_refused_reference": failed,
                "stations_refused_framework": sorted(got["errors"]),
                "refusals_framework": got["errors"],
                "coverage": _coverage_name(fraction),
            }
            agrees = (
                compare.rows_agree(result)
                and failed == sorted(got["errors"])
                and absent == got["unavailable"]
                and counts_expected == counts_got
            )
            checks.append(
                compare.record(
                    source=SOURCE,
                    check=_check_name("annual", label, fraction),
                    tier="verification",
                    category="fidelity",
                    method="Every station-year: the annual rows (one per station position) "
                    "recomputed in Python from NOAA's Parquet file, read without crc-sdk or "
                    f"pyarrow, against crc-sdk's read() with {_coverage_name(fraction)}, field "
                    "by field; and the station-years with no row, the refused stations and "
                    "the report's counts.",
                    agrees=agrees if result["values_compared"] or absent or failed else None,
                    versions=versions,
                    inputs=(parquet_input, sdk_input),
                    result=result,
                    sample={"stations": f"all {len(chosen)}", "years": list(years)},
                    tolerance=EXACT,
                    steps=ANNUAL_STEPS,
                    note="" if result["values_compared"] else "no station-year to compare",
                )
            )

            keys = set(picked)
            expected_psv, _ = _reference_rows(psv[fraction], value)
            result = compare.compare_rows(FIELDS, expected_psv, _framework_rows(got["rows"], keys))
            checks.append(
                compare.record(
                    source=SOURCE,
                    check=_check_name("second-format", label, fraction),
                    tier="verification",
                    category="fidelity",
                    method="A seeded sample of station-years recomputed from NOAA's "
                    "pipe-separated file with the standard library only, against crc-sdk's "
                    f"read() with {_coverage_name(fraction)}.",
                    agrees=compare.rows_agree(result) if result["values_compared"] else None,
                    versions=versions,
                    inputs=(psv_input, sdk_input),
                    result=result,
                    sample={"seed": SEED, "station_years": [list(key) for key in picked]},
                    tolerance=EXACT,
                    steps=ANNUAL_STEPS,
                    note="" if result["values_compared"] else "no station-year to compare",
                )
            )
            if fraction is not None:
                continue
            framework_seen[label] = got

            meta = got["metadata"]
            tail = "upper" if label == "temperature_max" else "lower"
            extreme = "maximum" if label == "temperature_max" else "minimum"
            variable = f"noaa:ghcnh:{indicator}"
            wanted = {
                "kind": "samples",
                "variables": [
                    {"id": variable, "measurement": {"kind": "temperature", "unit": "degC"}}
                ],
                "probability": [{"kind": "annual", "tail": tail}],
                "sampling_step": {"unit": "yr", "value": 1.0},
                "operations": [
                    "observation_time_selection",
                    f"temporal_reduction:daily_{extreme}@1.0",
                    f"temporal_reduction:annual_{extreme}@1.0",
                    "rename",
                ],
                "row_variables": [variable],
            }
            have = {
                "kind": meta.get("kind"),
                "variables": [
                    {"id": v.get("id"), "measurement": v.get("measurement")}
                    for v in meta.get("variables") or ()
                ],
                "probability": [s.get("probability") for s in meta.get("series") or ()],
                "sampling_step": (meta.get("sampling") or {}).get("step"),
                "operations": _operations(meta.get("provenance")),
                "row_variables": sorted({row["variable_id"] for row in got["rows"]}),
            }
            checks.append(
                compare.record(
                    source=SOURCE,
                    check=f"metadata[{label}]",
                    tier="verification",
                    category="consistency",
                    method="The kind, variable, unit, probability convention, sampling and the "
                    "list of operations in the metadata of crc-sdk's default read(), against "
                    "the values the statement gives; a fit among the operations would differ.",
                    agrees=have == wanted if meta else None,
                    versions=versions,
                    inputs=(sdk_input,),
                    result={
                        "expected": wanted,
                        "framework": have,
                        "differing": sorted(k for k in wanted if wanted[k] != have.get(k)),
                        "source": meta.get("source"),
                    },
                    tolerance={"fields": "identical to the statement"},
                    steps=("units", "output"),
                    note="" if meta else "no station could be read",
                )
            )

            resources = {item["uri"]: item for item in got["resources"]}
            readable = [(s, y) for s, y in jobs if s not in failed]
            payload = {reference.url(s, y, "parquet") for s, y in readable}
            listed_uris = set(resources) - {reference.STATION_LIST}
            on_file = [by_url[u] for u in sorted(payload) if not by_url[u]["missing"]]
            checksum_differs = [
                item["url"]
                for item in on_file
                if item["url"] in resources
                and resources[item["url"]]["sha256"] != f"sha256:{item['sha256']}"
            ]
            list_differs = (
                reference.STATION_LIST not in resources
                or resources[reference.STATION_LIST]["sha256"] != f"sha256:{list_file['sha256']}"
            )
            absent_digests = sorted(
                {resources[u]["sha256"] for u in payload & set(resources) if by_url[u]["missing"]}
            )
            fields = ("sha256", "license", "attribution", "retrieved_at")
            incomplete = sorted(
                uri for uri, item in resources.items() if not all(item.get(k) for k in fields)
            )
            result = {
                "resources": len(resources),
                "files_reference": len(payload),
                "files_framework": len(listed_uris),
                "files_missing_in_framework": sorted(payload - listed_uris)[: compare.MAX_EXAMPLES],
                "files_not_requested": sorted(listed_uris - payload)[: compare.MAX_EXAMPLES],
                "checksums_compared": len(on_file),
                "checksums_differing": checksum_differs[: compare.MAX_EXAMPLES],
                "station_list_checksum_differs": list_differs,
                "absent_files_recorded": len(payload & set(resources)) - len(on_file),
                "absent_file_digests": absent_digests,
                "resources_lacking_a_field": incomplete[: compare.MAX_EXAMPLES],
                "licences": sorted({str(item.get("license")) for item in resources.values()}),
                "attributions": sorted(
                    {str(item.get("attribution")) for item in resources.values()}
                ),
                "release": (meta.get("source") or {}).get("release"),
            }
            checks.append(
                compare.record(
                    source=SOURCE,
                    check=f"provenance[{label}]",
                    tier="verification",
                    category="consistency",
                    method="The resources crc-sdk records with its output: every station-year "
                    "file requested, absent ones included, and the station list; the SHA-256 of "
                    "each against the reference's own download of the same address; and a "
                    "licence, attribution and retrieval time on each.",
                    agrees=(
                        payload == listed_uris
                        and not checksum_differs
                        and not list_differs
                        and not incomplete
                        and len(absent_digests) <= 1
                    )
                    if resources
                    else None,
                    versions=versions,
                    inputs=(parquet_input, list_input, sdk_input),
                    result=result,
                    tolerance={
                        "files": "identical sets of addresses",
                        "checksums": "identical",
                        "fields": "all present (their wording is recorded, not judged)",
                    },
                    steps=("provenance", "files"),
                    note="" if resources else "no station could be read",
                )
            )

    excluded: Counter[str] = Counter()
    for item in default:
        excluded.update(item["excluded"])

    def complete(item: dict[str, Any]) -> bool:
        return any(row["complete"] for row in item["rows"])

    by_station = []
    for station in chosen:
        mine = [item for item in default if item["station"] == station]
        relaxed = [item for item in ours[0.9] if item["station"] == station]
        before = [row for row in old if row["station"] == station]
        have = [item["year"] for item in mine if item["reports"]]
        by_station.append(
            {
                "station": station,
                "name": names.get(station, ""),
                "first_year": min(have, default=None),
                "last_year": max(have, default=None),
                "years_with_a_file": sum(
                    1
                    for (s, _), f in zip(jobs, files, strict=True)
                    if s == station and not f["missing"]
                ),
                "positions": len({row["support_id"] for item in mine for row in item["rows"]}),
                "complete_years": sum(1 for item in mine if complete(item)),
                "complete_years_at_0.9": sum(1 for item in relaxed if complete(item)),
                "complete_years_by_0.11_rules": sum(1 for row in before if row["complete"]),
                "reports": sum(item["reports"] for item in mine),
                "accepted_reports": sum(item["accepted_reports"] for item in mine),
                "refused": next((item["error"] for item in mine if item["error"]), ""),
            }
        )
    exploration = {
        "selection": {
            "bounds": list(BOUNDS),
            "rule": "the 40 stations assessed at crc-sdk 0.11.2 (the first forty USW "
            "stations of the station list in the box)"
            if stations is None
            else f"{len(chosen)} stations given to the run",
            "stations_in_catalogue_selection": len(theirs_box),
            "first_usw_in_catalogue_selection_equal_sample": first_usw[: len(SAMPLE)]
            == list(SAMPLE),
            "years": list(years),
            "coverages": [_coverage_name(fraction) for fraction in COVERAGES],
        },
        "stations": by_station,
        "station_years": len(jobs),
        "station_years_with_a_file": sum(1 for item in files if not item["missing"]),
        "station_years_complete": sum(1 for item in default if complete(item)),
        "station_years_complete_at_0.9": sum(1 for item in ours[0.9] if complete(item)),
        "station_years_complete_by_0.11_rules": sum(1 for row in old if row["complete"]),
        "station_years_with_more_than_one_position": sum(
            1 for item in default if len(item["rows"]) > 1
        ),
        "reports": sum(item["reports"] for item in by_station),
        "accepted_reports": sum(item["accepted_reports"] for item in by_station),
        "excluded_by_rule": dict(sorted(excluded.items())),
        "stations_refused": failed,
        "framework_rules": framework.defaults(),
        "framework_diagnostics": {
            label: got["diagnostics"] for label, got in framework_seen.items()
        },
    }
    return present(
        {
            "source": SOURCE,
            "seed": SEED,
            "versions": dict(versions),
            "run_at": compare.now(),
            "options_assessed": {"indicator": sorted(INDICATORS)},
            "checks": [check.to_dict() for check in checks],
            "exploration": exploration,
            "files": [
                {
                    key: item.get(key)
                    for key in (
                        "url",
                        "sha256",
                        "etag",
                        "last_modified",
                        "bytes",
                        "missing",
                        "retrieved_at",
                    )
                }
                for item in [list_file, *files, *psv_files]
            ],
        }
    )


def _summary(check: dict[str, Any]) -> str:
    result = check["result"]
    if check["check"].startswith("stations["):
        return (
            f"{compare.number(result['rows_reference'])} stations in the box by NOAA's list, "
            f"{compare.number(result['rows_framework'])} by crc-sdk; "
            f"{compare.number(result['values_differing'])} values differ"
        )
    if "values_compared" in result:
        text = compare.rows_summary(result).replace(" rows ", " station-year rows ", 1)
        if "rows_with_a_value_reference" in result:
            text += (
                f"; {compare.number(result['rows_with_a_value_reference'])} rows carry a value; "
                f"{compare.number(result['station_years_without_a_row_reference'])} "
                "station-years have no file"
            )
        return text
    if "operations" in result.get("expected", {}):
        differing = result["differing"]
        return "metadata as stated" if not differing else "differs in " + ", ".join(differing)
    if "checksums_compared" in result:
        return (
            f"{compare.number(result['files_framework'])} files recorded for "
            f"{compare.number(result['files_reference'])} requested; "
            f"{compare.number(result['checksums_compared'])} checksums compared, "
            f"{len(result['checksums_differing'])} differ; licence "
            f"{'; '.join(result['licences'])}"
        )
    return check.get("note", "")


def present(run: dict[str, Any]) -> dict[str, Any]:
    """Add what the page and the report show: summaries, headline numbers, tables, a chart."""
    for check in run["checks"]:
        check["summary"] = _summary(check)
    explored = run["exploration"]
    selection = explored["selection"]
    annual = [c["result"] for c in run["checks"] if c["check"].startswith("annual[")]
    count = compare.tally(run["checks"])
    run["headline"] = [
        [explored["reports"], "hourly reports read from the publisher"],
        [explored["station_years"], "station-years recomputed"],
        [sum(r["values_differing"] for r in annual), "values that differ"],
        [f"{count.get('confirmed', 0)} of {len(run['checks'])}", "checks confirmed"],
        [count.get("differs", 0), "checks that differ"],
    ]
    reports = explored["reports"] or 1
    run["tables"] = [
        {
            "title": "From stations to annual values",
            "note": f"Selection: {selection['rule']}, years {selection['years'][0]} to "
            f"{selection['years'][1]}. Counted from NOAA's files by the reference reader. No "
            "curve is fitted by default.",
            "head": ["Stage", "Count"],
            "rows": [
                [
                    "Stations crc-sdk's inventory selects in the box",
                    selection["stations_in_catalogue_selection"],
                ],
                ["Stations assessed", len(explored["stations"])],
                ["Station-years requested", explored["station_years"]],
                ["Station-years NOAA has a file for", explored["station_years_with_a_file"]],
                [
                    "Station-years with a value by default (every day has 24 hours)",
                    explored["station_years_complete"],
                ],
                [
                    "Station-years with a value at Coverage.minimum_fraction(0.9)",
                    explored["station_years_complete_at_0.9"],
                ],
                [
                    "Station-years complete by the rules of crc-sdk 0.11 (18 hours, 90 % of days)",
                    explored["station_years_complete_by_0.11_rules"],
                ],
                [
                    "Station-years with more than one reported position",
                    explored["station_years_with_more_than_one_position"],
                ],
            ],
        },
        {
            "title": "Hourly reports and the rules that exclude them",
            "note": "A rule with no row excluded nothing in these files.",
            "head": ["Reports", "Count", "Share"],
            "rows": [
                ["All reports", explored["reports"], "100 %"],
                [
                    "Accepted",
                    explored["accepted_reports"],
                    f"{100 * explored['accepted_reports'] / reports:.2f} %",
                ],
                *[
                    [f"Excluded: {reason}", n, f"{100 * n / reports:.4f} %"]
                    for reason, n in explored["excluded_by_rule"].items()
                ],
            ],
        },
        {
            "title": "Stations",
            "note": "Complete years: by default, at Coverage.minimum_fraction(0.9), and by the "
            "rules of crc-sdk 0.11.",
            "head": [
                "Station",
                "Name",
                "First year",
                "Last year",
                "Years with a file",
                "Complete (default)",
                "Complete (0.9)",
                "Complete (0.11 rules)",
                "Reports",
                "Accepted",
            ],
            "rows": [
                [
                    item["station"],
                    item["name"],
                    str(item["first_year"] or ""),
                    str(item["last_year"] or ""),
                    item["years_with_a_file"],
                    item["complete_years"],
                    item["complete_years_at_0.9"],
                    item["complete_years_by_0.11_rules"],
                    item["reports"],
                    f"{100 * item['accepted_reports'] / item['reports']:.1f} %"
                    if item["reports"]
                    else "",
                ]
                for item in explored["stations"]
            ],
        },
    ]
    run["chart"] = {
        "title": "Years with a value per station",
        "unit": "years",
        "x": "Station",
        "select": "Completeness rule",
        "default": "default",
        "series": {
            "default": [[i["station"], i["complete_years"]] for i in explored["stations"]],
            "0.9": [[i["station"], i["complete_years_at_0.9"]] for i in explored["stations"]],
            "0.11 rules": [
                [i["station"], i["complete_years_by_0.11_rules"]] for i in explored["stations"]
            ],
        },
    }
    return run
