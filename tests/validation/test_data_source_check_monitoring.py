"""Monitoring: stale assessments are found, a re-run is compared, nothing is published."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from data_source_check import build, monitor
from data_source_check.core import inventory, monitoring
from data_source_check.core.records import RecordError, Source

RECORDS = {
    "source": "demo",
    "run_at": "2026-11-12T00:00:00Z",
    "versions": {"crc-sdk": "0.11.1 with the fix of CRC-001-NEX (local clone)"},
    "files": [
        {"url": "https://x/a", "etag": '"1"', "last_modified": "Mon", "missing": False},
        {"url": "https://x/gone", "etag": '"2"', "last_modified": "Mon", "missing": False},
        {"url": "https://x/absent", "missing": True},
    ],
    "checks": [
        {"check": "values[A]", "outcome": "confirmed", "summary": "10 rows",
         "inputs": [{"role": "reference", "url": "https://x/b", "etag": '"3"',
                     "last_modified": "Mon"},
                    {"role": "summary", "url": "https://x (5 files)", "sha256": "s"}]},
        {"check": "header[A]", "outcome": "confirmed", "summary": "3 columns", "inputs": []},
    ],
}  # fmt: skip


@pytest.fixture
def as_assessed(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The installed versions reported as those the committed records were assessed at, so
    that these tests say the same thing whichever version is pinned."""
    offered = monitor.crc.offered()
    versions = dict(build.load_records("ghcnh")["versions"])
    monkeypatch.setattr(monitor.crc, "offered", lambda: offered | {"versions": versions})
    return versions


def copy_of_the_page(tmp_path: Path) -> Path:
    page = tmp_path / "page"
    (page / "records").mkdir(parents=True)
    for path in (build.PAGE_DATA / "records").glob("*.json"):
        (page / "records" / path.name).write_bytes(path.read_bytes())
    return page


def test_recorded_inputs_are_the_publisher_files_once() -> None:
    urls = [item["url"] for item in monitoring.recorded_inputs(RECORDS)]
    assert urls == ["https://x/a", "https://x/absent", "https://x/b", "https://x/gone"]


def test_a_file_is_classified_by_etag_then_date() -> None:
    old = {"etag": '"1"', "last_modified": "Mon", "missing": False}
    assert (
        monitoring.classify(old, {"status": 200, "etag": '"1"', "last_modified": "Tue"})
        == "unchanged"
    )
    assert (
        monitoring.classify(old, {"status": 200, "etag": '"9"', "last_modified": "Mon"})
        == "changed"
    )
    assert monitoring.classify(old, {"status": 404}) == "gone"
    assert monitoring.classify({"missing": True}, {"status": 200, "etag": '"1"'}) == "appeared"
    assert monitoring.classify({"missing": True}, {"status": 404}) == "unchanged"
    no_etag = {"last_modified": "Mon", "missing": False}
    assert monitoring.classify(no_etag, {"status": 200, "last_modified": "Tue"}) == "changed"


def test_source_state_names_every_reason() -> None:
    same = {
        "https://x/a": {"status": 200, "etag": '"1"'},
        "https://x/b": {"status": 200, "etag": '"3"'},
        "https://x/gone": {"status": 200, "etag": '"2"'},
        "https://x/absent": {"status": 404},
    }
    assert not monitoring.source_state(RECORDS, same, {"crc-sdk": "0.11.1"})["stale"]
    moved = same | {
        "https://x/a": {"status": 200, "etag": '"7"'},
        "https://x/gone": {"status": 404},
        "https://x/absent": {"status": 200, "etag": '"8"'},
    }
    state = monitoring.source_state(
        RECORDS, moved, {"crc-sdk": "0.12.0"}, revalidate={"crc-sdk": ["0.12.0"]}
    )
    assert state["stale"] and len(state["reasons"]) == 2
    assert {item["change"] for item in state["files_changed"]} == {"changed", "gone", "appeared"}
    assert state["versions_changed"] == {"crc-sdk": {"assessed": "0.11.1", "installed": "0.12.0"}}
    down = same | {"https://x/a": {"status": None, "error": "timeout"}}
    quiet = monitoring.source_state(RECORDS, down, {"crc-sdk": "0.11.1"})
    assert not quiet["stale"] and quiet["files_unreachable"] == ["https://x/a"]  # not a change


def test_a_rerun_is_compared_check_by_check() -> None:
    new = {"source": "demo", "checks": [
        {"check": "values[A]", "outcome": "differs", "summary": "10 rows"},
        {"check": "header[A]", "outcome": "confirmed", "summary": "4 columns"},
        {"check": "new[A]", "outcome": "confirmed", "summary": ""},
    ]}  # fmt: skip
    diff = monitoring.diff_records(RECORDS, new)
    assert diff["newly_differing"] == ["values[A]"] and diff["checks_added"] == ["new[A]"]
    assert [item["check"] for item in diff["summaries_changed"]] == ["header[A]"]
    report = {"run_at": "now", "installed": {"crc-sdk": "0.11.1"}, "sources": [],
              "gaps": {"unclaimed_symbols": [], "new_options": []}, "needs_attention": True,
              "reruns": [diff | {"staged": "staging/demo.json"}]}  # fmt: skip
    text = monitoring.markdown(report)
    assert "confirmed to **differs**" in text and "is not published" in text


LIVING = {
    "rewritten_in_place": ["a"],
    "reason": "rewritten every few days at the same address",
    "rerun_after_days": 30,
}
SAME = {
    "https://x/a": {"status": 200, "etag": '"1"'},
    "https://x/b": {"status": 200, "etag": '"3"'},
    "https://x/gone": {"status": 200, "etag": '"2"'},
    "https://x/absent": {"status": 404},
}


def publisher(changed: tuple[str, ...] = (), down: tuple[str, ...] = ()):
    """A publisher answering for the committed records: the files of ``changed`` (addresses)
    carry another ETag and Last-Modified, those of ``down`` do not answer."""
    known = {item["url"]: item for name in build.ASSESSMENTS
             for item in monitoring.recorded_inputs(build.load_records(name))}  # fmt: skip

    def ask(url: str) -> dict:
        item = known.get(url)
        if url in down:
            return {"status": None, "error": "timed out"}
        if item is None or item.get("missing"):
            return {"status": 404}
        if url in changed:
            return {"status": 200, "etag": '"changed"', "last_modified": "Thu, 26 Nov 2026",
                    "length": 1}  # fmt: skip
        return {"status": 200, "etag": item.get("etag"), "last_modified": item.get("last_modified")}

    return ask


def test_a_new_copy_of_a_declared_file_is_reported_and_does_not_fail() -> None:
    changed = SAME | {"https://x/a": {"status": 200, "etag": '"7"', "last_modified": "Thu",
                                      "length": 12}}  # fmt: skip
    state = monitoring.source_state(RECORDS, changed, {"crc-sdk": "0.11.1"}, LIVING,
                                    today="2026-11-20T00:00:00Z")  # fmt: skip
    assert not state["stale"] and state["state"] == monitoring.NEW_COPY
    assert state["files_changed"] == [] and not monitoring.needs_attention(
        [state], {"unclaimed_symbols": [], "new_options": []}
    )
    living = state["living"]
    assert [item["url"] for item in living["new_copies"]] == ["https://x/a"]
    assert living["new_copies"][0]["bytes_now"] == 12 and living["new_copies"][0]["now"] == "Thu"
    assert living["rerun_due_on"] == "2026-12-12" and not living["rerun_due"]
    assert [copy["url"] for copy in living["assessed_copies"]] == ["https://x/a"]
    report = {"run_at": "2026-11-20T00:00:00Z", "installed": {"crc-sdk": "0.11.1"},
              "sources": [state], "gaps": {"unclaimed_symbols": [], "new_options": []},
              "needs_attention": False, "reruns": []}  # fmt: skip
    text = monitoring.markdown(report)
    assert "| current (new copy) |" in text and "## Files rewritten in place" in text
    assert "yes, last modified Thu" in text and "due on 2026-12-12 (every 30 days)" in text


def test_a_rerun_is_due_once_the_declared_cadence_has_passed_and_still_does_not_fail() -> None:
    state = monitoring.source_state(RECORDS, SAME, {"crc-sdk": "0.11.1"}, LIVING,
                                    today="2026-12-12T06:17:00Z")  # fmt: skip
    assert not state["stale"] and state["state"] == monitoring.CURRENT
    assert state["living"]["rerun_due"]
    assert monitoring.state_text(state) == "current; re-run due"


def test_an_undeclared_file_that_changed_still_fails() -> None:
    changed = SAME | {"https://x/a": {"status": 200, "etag": '"7"'},
                      "https://x/b": {"status": 200, "etag": '"9"'}}  # fmt: skip
    state = monitoring.source_state(RECORDS, changed, {"crc-sdk": "0.11.1"}, LIVING)
    assert state["stale"] and state["state"] == monitoring.STALE
    assert [item["url"] for item in state["files_changed"]] == ["https://x/b"]
    assert [item["url"] for item in state["living"]["new_copies"]] == ["https://x/a"]
    gone = SAME | {"https://x/a": {"status": 404}}  # a declared file that is gone is a change
    assert monitoring.source_state(RECORDS, gone, {"crc-sdk": "0.11.1"}, LIVING)["stale"]


def test_a_framework_change_on_a_living_file_source_fails() -> None:
    changed = SAME | {"https://x/a": {"status": 200, "etag": '"7"'}}
    state = monitoring.source_state(
        RECORDS, changed, {"crc-sdk": "0.12.0"}, LIVING, revalidate={"crc-sdk": ["0.12.0"]}
    )
    assert state["stale"] and state["reasons"] == [
        "the framework version changed to a release listed for re-validation: "
        "crc-sdk 0.11.1 to 0.12.0"
    ]
    framework = monitoring.source_state(
        RECORDS,
        SAME,
        {"crc-sdk": "0.11.1", "crc-framework": "1.0.0"},
        LIVING,
        revalidate={"crc-framework": ["1.0.0"]},
    )
    assert framework["stale"] and "crc-framework None to 1.0.0" in framework["reasons"][0]


def test_an_unreachable_living_file_fails() -> None:
    down = SAME | {"https://x/a": {"status": None, "error": "timeout"}}
    state = monitoring.source_state(RECORDS, down, {"crc-sdk": "0.11.1"}, LIVING)
    assert state["stale"] and state["files_unreachable"] == ["https://x/a"]
    assert state["reasons"] == ["1 file rewritten in place could not be reached"]


def test_the_monitoring_table_is_checked_where_the_inventory_is_loaded() -> None:
    def source(**monitoring_table: object) -> Source:
        ibtracs = next(s for s in inventory.load_sources("crc_sdk") if s.id == "ibtracs")
        return replace(ibtracs, monitoring=dict(monitoring_table))

    source(rewritten_in_place=["*.csv"], reason="why").validate()
    for bad in (
        {"rewritten_in_place": [], "reason": "why"},
        {"rewritten_in_place": ["a/b.csv"], "reason": "why"},
        {"rewritten_in_place": ["a.csv"], "reason": ""},
        {"rewritten_in_place": ["a.csv"], "reason": "why", "rerun_after_days": 0},
        {"rewritten_in_place": ["a.csv"], "reason": "why", "rerun_cadence": "monthly"},
    ):
        with pytest.raises(RecordError, match="monitoring"):
            source(**bad).validate()


def test_only_ibtracs_declares_a_file_rewritten_in_place_and_it_matches_its_record() -> None:
    declared = {s.id: s.monitoring for s in inventory.load_sources("crc_sdk") if s.monitoring}
    assert list(declared) == ["ibtracs"]
    inputs = monitoring.recorded_inputs(build.load_records("ibtracs"))
    living = [item for item in inputs
              if monitoring.rewritten_in_place(item["url"], declared["ibtracs"])]  # fmt: skip
    assert living and all(len(item["sha256"]) == 64 for item in living)


def test_a_monitoring_run_reports_and_leaves_the_records_alone(
    tmp_path: Path, as_assessed: dict[str, str]
) -> None:
    """Against the committed records: NOAA rewrote the IBTrACS file, and one GHCNh file changed."""
    before = {p.name: p.read_bytes() for p in (build.PAGE_DATA / "records").glob("*.json")}
    noaa = monitoring.recorded_inputs(build.load_records("ibtracs"))[0]["url"]
    station = next(item["url"] for item in monitoring.recorded_inputs(build.load_records("ghcnh"))
                   if not item.get("missing"))  # fmt: skip
    page = copy_of_the_page(tmp_path)
    report = monitor.run(page_data=page, docs=tmp_path / "docs", ask=publisher((noaa, station)))
    states = {state["source"]: state for state in report["sources"]}
    assert states["ibtracs"]["state"] == "current (new copy)" and not states["ibtracs"]["stale"]
    assert states["ibtracs"]["files_changed"] == []
    assert states["ghcnh"]["stale"] and len(states["ghcnh"]["files_changed"]) == 1
    assert not states["nex-gddp-cmip6"]["stale"]
    assert report["needs_attention"]
    text = (tmp_path / "docs" / "monitoring.md").read_text()
    assert f"stale: the publisher changed 1 of {states['ghcnh']['files']} files" in text
    assert "| ibtracs | ibtracs.ALL.list.v04r01.csv |" in text
    assert states["ibtracs"]["living"]["assessed_copies"][0]["sha256"] in text
    after = {p.name: p.read_bytes() for p in (build.PAGE_DATA / "records").glob("*.json")}
    assert after == before  # the published records are untouched


def test_a_new_ibtracs_copy_alone_does_not_need_attention(
    tmp_path: Path, as_assessed: dict[str, str]
) -> None:
    noaa = monitoring.recorded_inputs(build.load_records("ibtracs"))[0]["url"]
    page = copy_of_the_page(tmp_path)
    report = monitor.run(page_data=page, docs=tmp_path / "docs", ask=publisher((noaa,)))
    assert not report["needs_attention"]
    assert (
        "Nothing needs attention; new copies" in (tmp_path / "docs" / "monitoring.md").read_text()
    )
    down = monitor.run(page_data=page, docs=tmp_path / "docs", ask=publisher(down=(noaa,)))
    assert down["needs_attention"]  # an unreachable living file is not a new copy


def test_a_rerun_is_staged_and_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_assessed: dict[str, str]
) -> None:
    before = {p.name: p.read_bytes() for p in (build.PAGE_DATA / "records").glob("*.json")}
    page = tmp_path / "page"
    (page / "records").mkdir(parents=True)
    for name, data in before.items():
        (page / "records" / name).write_bytes(data)
    calls = []

    def fake_assess(source_id: str, *, live: bool, page_data: Path, cache: Path) -> dict:
        calls.append((source_id, live, page_data, cache))
        fresh = build.load_records(source_id)
        fresh["checks"][1]["outcome"] = "differs"
        return fresh

    monkeypatch.setattr(build, "assess_source", fake_assess)
    monkeypatch.setattr(monitor, "STAGING", tmp_path / "staging")
    ask = lambda url: {"status": 200, "etag": '"other"'}  # noqa: E731  every file changed
    report = monitor.run(rerun=True, page_data=page, docs=tmp_path / "docs", ask=ask)
    # IBTrACS's file is declared rewritten in place: a new copy alone does not re-run it
    assert [call[0] for call in calls] == ["ghcnh", "nex-gddp-cmip6"]
    assert all(live and str(tmp_path / "staging") in str(where) and "staging" in str(cache)
               for _, live, where, cache in calls)  # fmt: skip
    assert all(len(diff["newly_differing"]) == 1 for diff in report["reruns"])
    after = {p.name: p.read_bytes() for p in (build.PAGE_DATA / "records").glob("*.json")}
    assert after == before


def test_a_source_that_fails_is_reported_and_the_others_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_assessed: dict[str, str]
) -> None:
    page = copy_of_the_page(tmp_path)

    def fake_assess(source_id: str, *, live: bool, page_data: Path, cache: Path) -> dict:
        if source_id == "ghcnh":
            raise TimeoutError("The read operation timed out")
        return build.load_records(source_id)

    monkeypatch.setattr(build, "assess_source", fake_assess)
    monkeypatch.setattr(monitor, "STAGING", tmp_path / "staging")
    ask = lambda url: {"status": 200, "etag": '"other"'}  # noqa: E731  every file changed
    report = monitor.run(rerun=True, page_data=page, docs=tmp_path / "docs", ask=ask)
    by_source = {entry["source"]: entry for entry in report["reruns"]}
    assert list(by_source) == ["ghcnh", "nex-gddp-cmip6"]
    assert "TimeoutError" in by_source["ghcnh"]["failed"]
    assert "failed" not in by_source["nex-gddp-cmip6"]
    text = (tmp_path / "docs" / "monitoring.md").read_text()
    assert "## ghcnh: the re-run failed" in text and "--only ghcnh" in text


def test_only_reruns_the_named_source_and_a_staged_rerun_is_not_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_assessed: dict[str, str]
) -> None:
    page = copy_of_the_page(tmp_path)
    staging = tmp_path / "staging"
    calls = []

    def fake_assess(source_id: str, *, live: bool, page_data: Path, cache: Path) -> dict:
        calls.append(source_id)
        fresh = build.load_records(source_id) | {"run_at": "2999-01-01T00:00:00Z"}
        fresh = {k: v for k, v in fresh.items() if not k.startswith("profile")}  # a full run
        (page_data / "records").mkdir(parents=True, exist_ok=True)
        (page_data / "records" / f"{source_id}.json").write_text(json.dumps(fresh))
        return fresh

    monkeypatch.setattr(build, "assess_source", fake_assess)
    monkeypatch.setattr(monitor, "STAGING", staging)
    ask = lambda url: {"status": 404}  # noqa: E731
    run = lambda **more: monitor.run(  # noqa: E731
        rerun=True, page_data=page, docs=tmp_path / "docs", ask=ask, only=("jrc-flood",), **more
    )
    assert [entry["source"] for entry in run()["reruns"]] == ["jrc-flood"]
    again = run()
    assert calls == ["jrc-flood"] and again["reruns"][0]["reused"]
    run(again=True)
    assert calls == ["jrc-flood", "jrc-flood"]
    with pytest.raises(SystemExit, match="no assessed source named"):
        monitor.run(rerun=True, page_data=page, docs=tmp_path / "docs", ask=ask, only=("nope",))


def test_a_quick_rerun_says_so_and_cannot_be_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_assessed: dict[str, str]
) -> None:
    page = copy_of_the_page(tmp_path)
    staging = tmp_path / "staging"
    seen = {}

    def fake_assess(source_id: str, *, live: bool, page_data: Path, cache: Path,
                    profile: str = "full") -> dict:  # fmt: skip
        seen["profile"] = profile
        fresh = build.load_records(source_id) | {"profile": "quick", "profile_covers": "less"}
        fresh["checks"] = fresh["checks"][:-1]
        (page_data / "records").mkdir(parents=True, exist_ok=True)
        (page_data / "records" / f"{source_id}.json").write_text(json.dumps(fresh))
        return fresh

    monkeypatch.setattr(build, "assess_source", fake_assess)
    monkeypatch.setattr(monitor, "STAGING", staging)
    report = monitor.run(rerun=True, page_data=page, docs=tmp_path / "docs",
                         ask=lambda url: {"status": 404}, only=("jrc-flood",),
                         profile="quick")  # fmt: skip
    assert seen["profile"] == "quick" and report["reruns"][0]["profile"] == "quick"
    text = (tmp_path / "docs" / "monitoring.md").read_text()
    assert "Quick profile" in text and "validation-accept" not in text
    with pytest.raises(SystemExit, match="quick profile"):
        monitor.accept("jrc-flood")


def test_held_material_is_copied_into_staging_once(tmp_path: Path) -> None:
    held = tmp_path / "cache" / "jrc-flood" / "evidence" / "fema"
    held.mkdir(parents=True)
    (held / "a.json").write_text("held")
    staging = tmp_path / "staging"
    assert monitor.seed("jrc-flood", staging, tmp_path / "cache") == 1
    (staging / "jrc-flood" / "evidence" / "fema" / "a.json").write_text("fresher")
    assert monitor.seed("jrc-flood", staging, tmp_path / "cache") == 0
    assert (staging / "jrc-flood" / "evidence" / "fema" / "a.json").read_text() == "fresher"
    assert monitor.seed("ghcnh", staging, tmp_path / "cache") == 0


def test_framework_output_of_other_versions_is_removed_and_the_publisher_files_kept(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "nex-gddp-cmip6"
    (folder / "framework" / "installed").mkdir(parents=True)
    (folder / "framework" / "installed" / "answer.json").write_text("{}")
    (folder / "reference").mkdir()
    (folder / "reference" / "file.nc").write_text("publisher")
    (folder / "versions-served.json").write_text("[]")
    old, new = {"crc-sdk": "1"}, {"crc-sdk": "2"}
    assert monitor.fresh_for("nex-gddp-cmip6", tmp_path, old) == [
        "framework",
        "versions-served.json",
    ]
    (folder / "framework").mkdir()  # the run at the old versions wrote again, then stopped
    assert monitor.fresh_for("nex-gddp-cmip6", tmp_path, old) == []  # continued, not restarted
    assert monitor.fresh_for("nex-gddp-cmip6", tmp_path, new) == ["framework"]
    assert (folder / "reference" / "file.nc").read_text() == "publisher"
    assert set(monitor.FRAMEWORK_OUTPUT) == set(build.ASSESSMENTS)


def test_an_unlisted_release_leaves_the_assessment_current() -> None:
    """Yuri 2026-11-28: only releases listed in revalidate.toml make an assessment stale."""
    state = monitoring.source_state(RECORDS, SAME, {"crc-sdk": "0.12.0"})
    assert not state["stale"] and state["state"] == monitoring.EARLIER
    assert state["versions_changed"] == {"crc-sdk": {"assessed": "0.11.1", "installed": "0.12.0"}}
    assert monitoring.state_text(state) == "current; assessed on crc-sdk 0.11.1 (installed 0.12.0)"
    assert not monitoring.needs_attention([state], {"unclaimed_symbols": [], "new_options": []})
    other = monitoring.source_state(
        RECORDS, SAME, {"crc-sdk": "0.12.0"}, revalidate={"crc-sdk": ["0.13.0"]}
    )
    assert not other["stale"]
    listed = monitoring.source_state(
        RECORDS, SAME, {"crc-sdk": "0.12.0"}, revalidate={"crc-sdk": ["0.12.0"]}
    )
    assert listed["stale"] and listed["state"] == monitoring.STALE


def test_the_revalidate_file_loads() -> None:
    from data_source_check import monitor

    table = monitor.load_revalidate()
    assert set(table) <= {"crc-sdk", "crc-framework"}
    assert all(isinstance(v, list) for v in table.values())
