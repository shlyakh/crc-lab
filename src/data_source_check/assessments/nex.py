"""NEX-GDDP-CMIP6: exploration, and verification of crc-sdk 1.0's annual indicators against NASA.

One model and member (ACCESS-CM2, r1i1p1f1), the Texas box, one historical year and one scenario
year, the four indicators, as crc-sdk 1.0 reads them by default. crc-sdk 1.0 takes no file
version: it reads the highest version NASA lists for each year. The reference reader lists NASA's
bucket itself, says which file that should be, downloads the file crc-sdk read, and recomputes
the annual value of every grid cell of the box from the whole file under crc-sdk 1.0's rules
(every day present by default, five-day windows counted for rx5day). The records say which
version each side read.

The sample is that of the run on crc-sdk 0.11.2, so that the two can be put side by side: the
same cells, years and indicators, and, in the exploration, the annual values of every version
already downloaded against the version crc-sdk 1.0 reads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..adapters.crc import nex as framework
from ..core import compare
from ..core.records import CheckRecord
from ..reference import nex as reference

SOURCE = "nex-gddp-cmip6"
BOUNDS = (-106.645646, 25.837377, -93.508292, 36.500704)  # Texas, as in the data explorer
MODEL, MEMBER, GRID = "ACCESS-CM2", "r1i1p1f1", "gn"
PERIODS = (("historical", 2014), ("ssp585", 2050))
#: a year the historical run has no file for (it ends in 2014)
YEAR_WITHOUT_FILE = ("historical", 2015)
#: a model whose files use a 365-day calendar, read for its header only
OTHER_CALENDAR = ("BCC-CSM2-MR", "historical", "r1i1p1f1", 2014)
INDICATORS = framework.INDICATORS  # crc-sdk 1.0 name -> recipe name
BY_RECIPE = {recipe: name for name, recipe in INDICATORS.items()}
TOLERANCE = 1e-9
COLUMNS = ("time", "support_id", "cell_id", "west", "south", "east", "north", "value", "valid",
           "expected", "failure_code")  # fmt: skip
ANNUAL_STEPS = ("time", "area", "missing", "completeness", "output")
RECIPE_STEPS = {
    "rx1day": ("units-rain", "statistic-rain"),
    "rx5day": ("units-rain", "statistic-rain"),
    "txx": ("units-temperature", "statistic-temperature"),
    "tnn": ("units-temperature", "statistic-temperature"),
}
#: what crc-sdk 1.0 records for each recipe: unit of the result, and the unit conversion
EXPECTED = {
    "rx1day": ("mm", {"source_unit": "kg m-2 s-1", "target_unit": "mm/day", "scale": 86400.0}),
    "rx5day": ("mm", {"source_unit": "kg m-2 s-1", "target_unit": "mm/day", "scale": 86400.0}),
    "txx": ("degC", {"source_unit": "K", "target_unit": "degC", "scale": 1.0, "offset": -273.15}),
    "tnn": ("degC", {"source_unit": "K", "target_unit": "degC", "scale": 1.0, "offset": -273.15}),
}
REDUCTION = {"rx1day": "annual_maximum", "rx5day": "annual_maximum", "txx": "annual_maximum",
             "tnn": "annual_minimum"}  # fmt: skip
#: reference calendar name -> crc-sdk 1.0's name for it
CALENDARS = {"proleptic_gregorian": "proleptic_gregorian", "standard": "gregorian",
             "gregorian": "gregorian"}  # fmt: skip
ATTRIBUTION = "NASA Earth Exchange NEX-GDDP-CMIP6"
#: CF calendars crc-sdk reads a NEX series in since 1.1.0 (pull request #62); 1.0 read the
#: Gregorian ones only
READABLE_CALENDARS = frozenset(
    {*CALENDARS, "noleap", "365_day", "all_leap", "366_day", "360_day", "julian"}
)

Runner = Callable[..., None]


def cases() -> list[dict[str, Any]]:
    return [
        {"recipe": recipe, "scenario": scenario, "year": year}
        for scenario, year in PERIODS
        for recipe in ("rx1day", "rx5day", "txx", "tnn")
    ]


def label(case: dict[str, Any]) -> str:
    model = "" if case.get("model", MODEL) == MODEL else f"{case['model']} "
    return f"{model}{case['recipe']} {case['scenario']} {case['year']}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower())


def _request(case: dict[str, Any], bounds: Sequence[float], crc_cache: Path) -> dict[str, Any]:
    return {
        "indicator": BY_RECIPE[case["recipe"]], "model": case.get("model", MODEL),
        "scenario": case["scenario"], "member": case.get("member", MEMBER), "year": case["year"],
        "bounds": list(bounds), "cache": str(crc_cache),
    }  # fmt: skip


def _framework(case: dict[str, Any], folder: Path, *, live: bool, bounds: Sequence[float],
               runner: Runner) -> dict:  # fmt: skip
    """crc-sdk's stored answer for a case; asked for only when it is not stored yet."""
    path = folder / "answers" / f"{_slug(label(case))}.json"
    if not path.exists():
        if not live:
            raise FileNotFoundError(f"no stored crc-sdk answer for {label(case)}; run with --live")
        runner(_request(case, bounds, (folder / "crc-sdk-cache").resolve()), path)
    return json.loads(path.read_text(encoding="utf-8"))


def _listings(cache: Path, *, live: bool, wanted: Sequence[tuple[str, str]],
              model: str = MODEL, member: str = MEMBER) -> dict[str, dict]:  # fmt: skip
    """NASA's listing of each (variable, scenario) folder, stored on first use."""
    stored = cache / "listing.json"
    known = json.loads(stored.read_text(encoding="utf-8")) if stored.exists() else {}
    for variable, scenario in wanted:
        prefix = reference.folder(variable, model, scenario, member)
        if prefix in known:
            continue
        if not live:
            raise FileNotFoundError(f"no stored listing of {prefix}; run with --live")
        known[prefix] = reference.listing(prefix)
        cache.mkdir(parents=True, exist_ok=True)
        temporary = stored.with_suffix(".tmp")
        temporary.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")
        temporary.replace(stored)
    return known


def _latest(objects: dict[str, Any], year: int) -> tuple[str, str] | None:
    """(version, key) of the highest version listed for the year, by the reference's rule."""
    versions = reference.versions_by_year(objects).get(year)
    if not versions:
        return None
    top = versions[-1]
    key = next(k for k in objects if reference.file_version(k.rsplit("/", 1)[-1]) == (year, top))
    return top, key


def _address(key: str) -> str:
    return f"{reference.bucket()}/{key}"


def _window_resource(got: dict[str, Any]) -> dict[str, Any] | None:
    return next((r for r in got.get("labels", {}).get("resources", [])
                 if "#crc-variable=" in (r.get("uri") or "")), None)  # fmt: skip


def _expected_rows(cells: list[dict[str, Any]]) -> list[list[Any]]:
    return [[f"{c['year']:04d}", f"nex:0p25:{c['row']}:{c['column']}", c["cell_id"], c["west"],
             c["south"], c["east"], c["north"], c["value"], c["valid"], c["expected"],
             None if c["value"] is not None else "incomplete_year"] for c in cells]  # fmt: skip


def _framework_rows(got: dict[str, Any]) -> list[list[Any]]:
    return [[row.get(c) for c in COLUMNS] for row in got["rows"]]


def assess(
    cache: Path,
    *,
    live: bool,
    versions: dict[str, str],
    rules: reference.Rules | None = None,
    todo: list[dict[str, Any]] | None = None,
    bounds: tuple[float, float, float, float] = BOUNDS,
    runner: Runner = framework.annual,
    log: Callable[[str], None] = lambda _: None,
    other_calendar: tuple[str, str, str, int] | None = OTHER_CALENDAR,
    year_without_file: tuple[str, int] | None = YEAR_WITHOUT_FILE,
) -> dict[str, Any]:
    """The records of one run. ``rules`` overrides the reference rules (for fault tests)."""
    rules = rules or reference.RULES_1_0
    todo = cases() if todo is None else todo
    extra: list[dict[str, Any]] = []
    if year_without_file is not None:
        extra.append({"recipe": "rx1day", "scenario": year_without_file[0],
                      "year": year_without_file[1], "role": "year-without-file"})  # fmt: skip
    if other_calendar is not None:
        model, scenario, member, year = other_calendar
        extra.append({"recipe": "rx1day", "scenario": scenario, "year": year, "model": model,
                      "member": member, "role": "other-calendar"})  # fmt: skip

    log("crc-sdk: installed version")
    folder = cache / "framework" / "installed"
    every = [*todo, *extra]

    def ask(case: dict[str, Any]) -> dict[str, Any]:
        return _framework(case, folder, live=live, bounds=bounds, runner=runner)

    # One case per NASA file first, side by side; the cases that read a file already read
    # come after, from crc-sdk's own cache, so that no file is read twice at the same time.
    # The year without a file reads the nearest year's file, so it always comes after.
    first: dict[tuple, int] = {}
    for number, case in enumerate(every):
        if case.get("role") != "year-without-file":
            key = (case.get("model", MODEL), case["scenario"], case["year"],
                   reference.RECIPES[case["recipe"]][0])  # fmt: skip
            first.setdefault(key, number)
    waves = [sorted(first.values()), [n for n in range(len(every)) if n not in first.values()]]
    answers: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for wave in waves:
            answers |= dict(zip(wave, pool.map(lambda n: ask(every[n]), wave), strict=True))
    pinned = [answers[n] for n in range(len(todo))]
    others = [answers[n] for n in range(len(todo), len(every))]

    log("reference: NASA's listing")
    wanted = sorted({(reference.RECIPES[c["recipe"]][0], c["scenario"]) for c in [*todo, *extra]
                     if "model" not in c})  # fmt: skip
    listed = _listings(cache, live=live, wanted=wanted)

    def objects(variable: str, scenario: str) -> dict[str, Any]:
        return listed[reference.folder(variable, MODEL, scenario, MEMBER)]

    log("reference: files")
    plans = []
    for case, got in zip(todo, pinned, strict=True):
        variable = reference.RECIPES[case["recipe"]][0]
        latest = _latest(objects(variable, case["scenario"]), case["year"])
        read = got["files_read"][0] if got.get("files_read") else None
        address = read or (None if latest is None else _address(latest[1]))
        plans.append((case, got, variable, latest, read, address))
    addresses = sorted({p[5] for p in plans if p[5]})
    with ThreadPoolExecutor(max_workers=4) as pool:
        files = dict(zip(addresses, pool.map(
            lambda a: reference.download(a, cache / "reference", live=live), addresses),
            strict=True))  # fmt: skip

    checks: list[CheckRecord] = []
    boxes: dict[str, dict[str, Any]] = {}
    summaries: list[dict[str, Any]] = []

    def box_of(address: str, variable: str, year: int) -> dict[str, Any]:
        if address not in boxes:
            boxes[address] = reference.read_box(Path(files[address]["path"]), variable, bounds,
                                                year, rules)  # fmt: skip
        return boxes[address]

    def make(check: str, category: str, method: str, agrees: bool | None, *,
             inputs: Sequence[dict[str, Any]], **more: Any) -> CheckRecord:  # fmt: skip
        return compare.record(source=SOURCE, check=check, tier="verification", category=category,
                              method=method, agrees=agrees, versions=versions, inputs=inputs,
                              **more)  # fmt: skip

    for case, got, variable, latest, read, address in plans:
        name = label(case)
        log(f"compare: {name}")
        provenance = files.get(address, {}) if address else {}
        window = _window_resource(got)
        inputs = (
            {"role": "reference download", **{k: provenance.get(k) for k in
             ("url", "sha256", "retrieved_at", "etag", "last_modified", "bytes")}},
            {"role": "crc-sdk answer (range requests)", "url": read,
             "crc_sdk_view_sha256": None if window is None else window.get("sha256")},
            {"role": "publisher listing", "url": reference.bucket() + "/?list-type=2&prefix="
             + reference.folder(variable, MODEL, case["scenario"], MEMBER)},
        )  # fmt: skip
        listed_versions = reference.versions_by_year(objects(variable, case["scenario"]))
        read_version = None if read is None else reference.file_version(read.rsplit("/", 1)[-1])
        listed_etag = None
        if latest is not None:
            listed_etag = objects(variable, case["scenario"])[latest[1]].get("etag")
        checks.append(make(
            f"file[{name}]", "fidelity",
            "The file crc-sdk read (from its provenance) against the highest version NASA lists "
            "for the year (the reference's own listing of the bucket); and the ETag NASA lists "
            "for that file against the ETag of the reference's download.",
            read is not None and latest is not None and read == _address(latest[1])
            and listed_etag == provenance.get("etag"),
            inputs=inputs,
            result={"file_read_by_crc_sdk": read,
                    "version_read_by_crc_sdk": None if read_version is None else read_version[1],
                    "highest_version_listed": None if latest is None else latest[0],
                    "versions_listed": listed_versions.get(case["year"], []),
                    "etag_listed": listed_etag, "etag_downloaded": provenance.get("etag")},
            tolerance={"file": "identical address", "etag": "identical text"},
            steps=("files", "versions"),
        ))  # fmt: skip
        if address is None or provenance.get("missing"):
            continue
        box = box_of(address, variable, case["year"])
        attrs = box["attrs"]
        cells = reference.annual_cells(box, case["recipe"], case["year"], rules)
        with_value = [c for c in cells if c["value"] is not None]
        source_unit = reference.RECIPES[case["recipe"]][1]
        summaries.append({
            "case": name, "file": address.rsplit("/", 1)[-1],
            "file_version": attrs.get("version"), "licence_in_file": attrs.get("cmip6_license"),
            "calendar": box["calendar"], "days": len(box["day_offsets"]),
            "cells_in_box": len(cells), "cells_with_a_value": len(with_value),
            "lowest": min((c["value"] for c in with_value), default=None),
            "highest": max((c["value"] for c in with_value), default=None),
            "unit": EXPECTED[case["recipe"]][0],
            "units_in_file": box["variable_attrs"].get("units"),
        })  # fmt: skip
        steps = ANNUAL_STEPS + RECIPE_STEPS[case["recipe"]]
        if got["error"]:
            declared = box["variable_attrs"].get("units")
            checks.append(make(
                f"annual[{name}]", "fidelity",
                "crc-sdk raised instead of returning rows. Refusing is right only when the file "
                "declares a unit other than the one the indicator requires, or a calendar other "
                "than a Gregorian one.",
                declared != source_unit or box["calendar"] not in CALENDARS, inputs=inputs,
                result={"unit_in_file": declared, "unit_required": source_unit,
                        "calendar_in_file": box["calendar"], "cells_in_box": len(cells),
                        "crc_sdk_error": f"{got['error_type']}: {got['error']}"[:400]},
                tolerance={"behaviour": "rows unless the file is refused for a stated reason"},
                steps=steps,
            ))  # fmt: skip
            continue
        result = compare.compare_rows(COLUMNS, _expected_rows(cells), _framework_rows(got),
                                      tolerance=TOLERANCE)  # fmt: skip
        result |= {"cells_in_box": len(cells), "cells_with_a_value": len(with_value),
                   "crc_sdk_path": got["crc_sdk_path"], "transport_retries": got.get(
                       "transport_retries", 0)}  # fmt: skip
        checks.append(make(
            f"annual[{name}]", "fidelity",
            "Every grid cell of the box: the annual value, its coverage (days or five-day windows "
            "present, of those expected), the cell's edges, its H3 cell and its place in the file, "
            "recomputed in Python from the whole NASA file crc-sdk read, against crc-sdk's rows, "
            "in order. A cell with no value must carry the failure incomplete_year.",
            compare.rows_agree(result) if result["values_compared"] else None, inputs=inputs,
            result=result, sample={"cells": "all in the box", "bounds": list(bounds)},
            tolerance={"numbers": f"within {TOLERANCE}", "order": "identical",
                       "labels": "identical text"},
            steps=steps, note="" if result["values_compared"] else "no cell to compare",
        ))  # fmt: skip

        labels = got["labels"]
        rows = got["rows"]
        unit, conversion = EXPECTED[case["recipe"]]
        wanted_labels = {
            "variable_id": f"nex:{BY_RECIPE[case['recipe']]}",
            "unit": unit,
            "scenario": case["scenario"],
            "model": MODEL,
            "member": MEMBER,
            "release_id": f"{MODEL}/{case['scenario']}/{MEMBER}/{variable}",
            "calendar": CALENDARS.get(box["calendar"], box["calendar"]),
        }
        wrong = {k: labels.get(k) for k, v in wanted_labels.items() if labels.get(k) != v}
        on_rows = {
            "variable_id": sorted({r.get("variable_id") for r in rows}
                                  - {wanted_labels["variable_id"]}),
            "scenario_id": sorted({r.get("scenario_id") for r in rows} - {case["scenario"]}),
        }  # fmt: skip
        on_rows = {k: v for k, v in on_rows.items() if v}
        got_conversion = {k: v for k, v in (labels.get("unit_conversion") or {}).items()
                          if v is not None and k in conversion}  # fmt: skip
        reductions = labels.get("reductions", [])
        annual_reduction = next((r for r in reductions if r["operation"].startswith("annual")), {})
        # crc-sdk 1.0.1 (pull request #54): `license`, else `licence`, else `cmip6_license`
        licence_attr = attrs.get("license") or attrs.get("licence") or attrs.get("cmip6_license")
        checks.append(make(
            f"labels[{name}]", "consistency",
            "The labels crc-sdk puts on its result against the request and the file's own "
            "attributes: variable, unit, scenario, model, member, release, calendar, the unit "
            "conversion and the annual reduction recorded in the provenance (with its coverage "
            "rule), the licence on the file's resource against the file's global `license` "
            "attribute, else `licence`, else `cmip6_license`, the attribution, and a retrieval "
            "time.",
            not wrong and not on_rows and got_conversion == conversion
            and annual_reduction.get("operation") == REDUCTION[case["recipe"]]
            and annual_reduction.get("coverage_fraction") == rules.minimum_valid_fraction
            and window is not None and window.get("license") == licence_attr
            and window.get("attribution") == ATTRIBUTION and bool(window.get("retrieved_at")),
            inputs=inputs,
            result={"labels_wrong": wrong, "row_labels_wrong": on_rows,
                    "unit_conversion": labels.get("unit_conversion"), "reductions": reductions,
                    "licence_on_resource": None if window is None else window.get("license"),
                    "license_attribute_in_file": licence_attr,
                    "cmip6_license_in_file": attrs.get("cmip6_license"),
                    "attribution": None if window is None else window.get("attribution"),
                    "retrieved_at": None if window is None else window.get("retrieved_at"),
                    "columns": got["columns"], "diagnostics": labels.get("diagnostics", []),
                    "counts": labels.get("counts")},
            tolerance={"labels": "identical text", "numbers": "identical"},
            steps=("labels", "provenance", "licence"),
        ))  # fmt: skip
        identity = {
            "model": (attrs.get("cmip6_source_id"), labels.get("model")),
            "member": (attrs.get("variant_label"), labels.get("member")),
            "scenario": (attrs.get("scenario"), labels.get("scenario")),
            "version": (attrs.get("version"), None if read_version is None else read_version[1]),
        }
        checks.append(make(
            f"identity[{name}]", "consistency",
            "The identity the file states in its own attributes (cmip6_source_id, variant_label, "
            "scenario, version) against the model, member and scenario crc-sdk labels its result "
            "with and the version in the name of the file it read.",
            all(a == b for a, b in identity.values()), inputs=inputs,
            result={key: {"file": a, "crc_sdk": b} for key, (a, b) in identity.items()},
            tolerance={"identity": "identical text"}, steps=("identity",),
        ))  # fmt: skip

    for case, got in zip(extra, others, strict=True):
        name = label(case)
        if case["role"] == "year-without-file":
            variable = reference.RECIPES[case["recipe"]][0]
            listed_years = sorted(reference.versions_by_year(objects(variable, case["scenario"])))
            nearest = (
                min(listed_years, key=lambda y: abs(y - case["year"])) if listed_years else None
            )
            latest = (
                None if nearest is None else _latest(objects(variable, case["scenario"]), nearest)
            )
            address = None if latest is None else _address(latest[1])
            expected_rows: list[list[Any]] = []
            if address in files:  # the cells are those of the nearest year's file
                box = box_of(address, variable, nearest)  # type: ignore[arg-type]
                days = reference._days_in_year(box["calendar"], case["year"])
                empty = dict(box, day_offsets=[], values=[], days_expected=days)
                expected_rows = _expected_rows(
                    reference.annual_cells(empty, case["recipe"], case["year"], rules)
                )
            result = compare.compare_rows(COLUMNS, expected_rows, _framework_rows(got),
                                          tolerance=TOLERANCE)  # fmt: skip
            result |= {"year_listed": case["year"] in listed_years, "nearest_year": nearest,
                       "files_read_by_crc_sdk": got.get("files_read", []),
                       "crc_sdk_error": f"{got['error_type']}: {got['error']}"[:300]
                       if got["error"] else "",
                       "diagnostics": (got.get("labels") or {}).get("diagnostics", [])}  # fmt: skip
            checks.append(make(
                f"year-without-file[{name}]", "completeness",
                f"Ask crc-sdk for {name}, a year NASA has no file for: crc-sdk must return one row "
                "per grid cell of the box (the cells of the nearest year's file) with no value, "
                "0 days present and the failure incomplete_year, and a source_year_unavailable "
                "warning (crc-sdk 1.0.1, pull request #56).",
                compare.rows_agree(result)
                and "source_year_unavailable" in result["diagnostics"]
                if expected_rows else None,
                inputs=({"role": "crc-sdk answer", "url": address},),
                result=result, tolerance={"numbers": f"within {TOLERANCE}", "order": "identical"},
                steps=("year-without-file",),
                note="" if expected_rows else "the nearest year's file was not read",
            ))  # fmt: skip
        else:
            model, scenario, member = case["model"], case["scenario"], case["member"]
            variable = reference.RECIPES[case["recipe"]][0]
            header = _other_header(cache, model, scenario, member, variable, live=live)
            refuses = header["calendar"] not in READABLE_CALENDARS
            checks.append(make(
                f"calendar[{name}]", "consistency",
                f"Ask crc-sdk for {name}. The reference reads the calendar of that model's first "
                "file (its header only, by range requests). crc-sdk must read the series, with "
                "rows, when the calendar is one CF names (Gregorian, 365-day, 366-day, 360-day, "
                "Julian), and refuse it otherwise.",
                bool(got["error"]) == refuses and not (refuses and got["rows"])
                and (refuses or bool(got["rows"])),
                inputs=({"role": "reference header", "url": header["url"]},),
                result={"calendar_in_file": header["calendar"],
                        "crc_sdk_refuses": bool(got["error"]),
                        "crc_sdk_error": f"{got['error_type']}: {got['error']}"[:300],
                        "rows_returned": len(got["rows"])},
                tolerance={"behaviour": "read if and only if a CF calendar"},
                steps=("calendar",),
            ))  # fmt: skip

    served = [
        {"variable": variable, "scenario": scenario, "year": year,
         "versions": reference.versions_by_year(objects(variable, scenario)).get(year, [])}
        for scenario, year in PERIODS for variable in ("tasmax", "tasmin", "pr")
        if reference.folder(variable, MODEL, scenario, MEMBER) in listed
    ]  # fmt: skip
    older = [row | {"not_requestable": row["versions"][:-1]} for row in served
             if len(row["versions"]) > 1]  # fmt: skip
    checks.append(make(
        "versions-served", "completeness",
        "For each variable and year assessed, the file versions NASA lists (the reference's own "
        "listing) against the versions a crc-sdk user can request: crc-sdk 1.0 takes no version "
        "and reads only the highest one.",
        not older, inputs=({"role": "publisher listing", "url": reference.bucket()},),
        result={"by_file": served, "served_but_not_requestable": older},
        tolerance={"versions": "every version served can be requested"},
        steps=("versions-offered",),
    ))  # fmt: skip

    return present({
        "source": SOURCE,
        "versions": dict(versions),
        "run_at": compare.now(),
        "selection": {"model": MODEL, "member": MEMBER, "grid": GRID, "bounds": list(bounds),
                      "periods": [list(p) for p in PERIODS], "coverage": "crc-sdk default",
                      "file_version": "crc-sdk default (highest listed)"},
        "options_assessed": {
            "indicator": sorted({BY_RECIPE[c["recipe"]] for c, got in zip(todo, pinned, strict=True)
                                 if not got["error"]}),
        },
        "checks": [check.to_dict() for check in checks],
        "exploration": {"cases": summaries, "versions_served": served,
                        "version_differences": _version_differences(cache, rules, listed, bounds)},
    })  # fmt: skip


def _other_header(cache: Path, model: str, scenario: str, member: str, variable: str, *,
                  live: bool) -> dict[str, Any]:  # fmt: skip
    """The calendar of a model's first file for the variable, stored on first use."""
    stored = cache / f"header-{_slug(model)}.json"
    if stored.exists():
        return json.loads(stored.read_text(encoding="utf-8"))
    if not live:
        raise FileNotFoundError(f"no stored header of {model}; run with --live")
    objects = reference.listing(reference.folder(variable, model, scenario, member))
    first = min(reference.versions_by_year(objects))
    _, key = _latest(objects, first)  # type: ignore[misc]
    out = {"url": _address(key)} | reference.header(_address(key))
    cache.mkdir(parents=True, exist_ok=True)
    stored.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def _version_differences(cache: Path, rules: reference.Rules, listed: dict[str, Any],
                         bounds: Sequence[float] = BOUNDS) -> list[dict[str, Any]]:  # fmt: skip
    """How the annual values of each version already downloaded differ from those of the version
    crc-sdk 1.0 reads (the highest listed); reference reader only."""
    out = []
    for scenario, year in PERIODS:
        for recipe in ("rx1day", "txx"):
            variable = reference.RECIPES[recipe][0]
            objects = listed.get(reference.folder(variable, MODEL, scenario, MEMBER), {})
            latest = _latest(objects, year)
            if latest is None:
                continue
            values: dict[str, dict] = {}
            for version in reference.versions_by_year(objects).get(year, []):
                address = reference.url(variable, MODEL, scenario, MEMBER, GRID, year, version)
                path = cache / "reference" / address.rsplit("/", 1)[-1]
                if path.exists():
                    box = reference.read_box(path, variable, tuple(bounds), year, rules)
                    values[version] = {(c["row"], c["column"]): c["value"]
                                       for c in reference.annual_cells(box, recipe, year, rules)
                                       if c["value"] is not None}  # fmt: skip
            base = values.get(latest[0])
            for version, cells in values.items():
                if version == latest[0] or base is None:
                    continue
                shared = sorted(set(base) & set(cells))
                gaps = [abs(base[k] - cells[k]) for k in shared]
                out.append({
                    "recipe": recipe, "scenario": scenario, "year": year, "version": version,
                    "against": latest[0], "cells": len(shared),
                    "cells_differing": sum(1 for g in gaps if g > TOLERANCE),
                    "largest_difference": max(gaps, default=0.0),
                    "cells_only_in_one": len(set(base) ^ set(cells)),
                })  # fmt: skip
    return out


def _summary(check: dict[str, Any]) -> str:
    result = check["result"]
    name = check["check"]
    if name.startswith("year-without-file["):
        names = [f.rsplit("/", 1)[-1] for f in result["files_read_by_crc_sdk"]]
        return f"{compare.rows_summary(result)}; crc-sdk read {', '.join(names) or 'no file'}"
    if "values_compared" in result:
        return (
            f"{compare.number(result['cells_with_a_value'])} cells with a value of "
            f"{compare.number(result['cells_in_box'])} in the box; "
            f"{compare.number(result['rows_reference'])} rows against "
            f"{compare.number(result['rows_framework'])}; "
            f"{compare.number(result['values_differing'])} values differ; largest difference "
            f"{result['largest_difference']:.1e}"
        )
    if "unit_in_file" in result:
        return (
            f"crc-sdk raises: {result['crc_sdk_error'][:160]} (the file declares "
            f"{result['unit_in_file']!r} and calendar {result['calendar_in_file']!r})"
        )
    if "file_read_by_crc_sdk" in result:
        read = result["file_read_by_crc_sdk"]
        return (
            f"crc-sdk read version {result['version_read_by_crc_sdk']} "
            f"({read.rsplit('/', 1)[-1] if read else 'no file'}); highest listed "
            f"{result['highest_version_listed']} of {', '.join(result['versions_listed'])}"
        )
    if "labels_wrong" in result:
        return (
            f"{len(result['labels_wrong']) + len(result['row_labels_wrong'])} labels wrong; "
            f"licence on the resource: {result['licence_on_resource']}; `license` in the "
            f"file: {result['license_attribute_in_file']}; cmip6_license in the file: "
            f"{result['cmip6_license_in_file']}"
        )
    if "calendar_in_file" in result:
        said = "refuses: " + result["crc_sdk_error"][:120] if result["crc_sdk_refuses"] else "reads"
        return f"calendar {result['calendar_in_file']}; crc-sdk {said}"
    if "served_but_not_requestable" in result:
        extra = (
            "; ".join(
                f"{r['variable']} {r['scenario']} {r['year']}: {', '.join(r['not_requestable'])}"
                for r in result["served_but_not_requestable"]
            )
            or "none"
        )
        return f"served by NASA but not requestable through crc-sdk: {extra}"
    if "model" in result and "version" in result:
        wrong = [k for k, v in result.items() if v["file"] != v["crc_sdk"]]
        return f"{len(wrong)} of {len(result)} identity attributes differ" + (
            f": {', '.join(wrong)}" if wrong else ""
        )
    return check.get("note", "")


def present(run: dict[str, Any]) -> dict[str, Any]:
    """Add what the page and the report show: summaries, headline numbers, tables."""
    for check in run["checks"]:
        check["summary"] = _summary(check)
    count = compare.tally(run["checks"])
    annual = [c["result"] for c in run["checks"]
              if c["check"].startswith("annual[") and "values_compared" in c["result"]]  # fmt: skip
    explored = run["exploration"]
    run["headline"] = [
        [sum(r["cells_with_a_value"] for r in annual), "cell values compared, installed version"],
        [sum(r["values_differing"] for r in annual), "values that differ"],
        [f"{count.get('confirmed', 0)} of {len(run['checks'])}", "checks confirmed"],
        [count.get("differs", 0), "checks that differ"],
    ]
    fmt = lambda v: "" if v is None else f"{v:.2f}"  # noqa: E731
    run["tables"] = [
        {
            "title": "What was read",
            "note": f"Model {run['selection']['model']}, member {run['selection']['member']}, "
            "the Texas box, the file crc-sdk read. Counted from NASA's files by the reference "
            "reader.",
            "head": ["Case", "File", "File version", "Licence in the file", "Calendar", "Days",
                     "Cells in box", "Cells with a value", "Lowest", "Highest", "Unit"],
            "rows": [
                [c["case"], c["file"], c["file_version"], c["licence_in_file"], c["calendar"],
                 c["days"], c["cells_in_box"], c["cells_with_a_value"], fmt(c["lowest"]),
                 fmt(c["highest"]), c["unit"]]
                for c in explored["cases"]
            ],
        },
        {
            "title": "File versions NASA serves",
            "note": "Versions in NASA's listing for each variable and year. crc-sdk 1.0 reads "
            "the highest and offers no way to ask for another.",
            "head": ["Variable", "Scenario", "Year", "Versions listed", "Read by crc-sdk 1.0"],
            "rows": [
                [row["variable"], row["scenario"], str(row["year"]), ", ".join(row["versions"]),
                 row["versions"][-1] if row["versions"] else ""]
                for row in explored["versions_served"]
            ],
        },
        {
            "title": "Do the file versions give different annual values?",
            "note": "Annual values from each other version already downloaded against the "
            "version crc-sdk 1.0 reads, in the box (reference reader only; crc-sdk is not "
            "involved). crc-sdk 0.11 read version 1.0 by default.",
            "head": ["Recipe", "Scenario", "Year", "Version", "Against", "Cells",
                     "Cells that differ", "Largest difference"],
            "rows": [
                [d["recipe"], d["scenario"], str(d["year"]), d["version"], d["against"],
                 d["cells"], d["cells_differing"], f"{d['largest_difference']:.3g}"]
                for d in explored["version_differences"]
            ],
        },
    ]  # fmt: skip
    return run
