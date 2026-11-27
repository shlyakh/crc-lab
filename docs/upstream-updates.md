# Following CRC releases

How crc-lab moves from one release of `crc-sdk` or `crc-framework` to the next. Agreed 2026-11-23.

## Rules

- crc-lab runs on released versions only, installed from PyPI and pinned exactly. It never installs from
  upstream `main` or from a fork.
- One release at a time. If two releases are waiting, move to the older one first, finish the checklist,
  commit, then move again. Each commit then shows what one release changed in our results.
- A move is one commit: pin, lock file, changelog row, re-run records, findings, report.
- Nothing is pushed, and nothing is sent upstream, without Yuri's word.

## Seeing that a release is out

```sh
just upstream-check
```

Prints the pinned and latest versions of both packages, the release notes of anything newer, and whether
the reference clones under `../upstream/` sit at the pinned tags. It only reads. The weekly
`validation-monitor` workflow runs the same check and puts the result in its summary.

## Moving the pin

```sh
just upstream-bump crc-sdk 0.11.2 --dry-run   # shows every change, makes none
just upstream-bump crc-sdk 0.11.2
```

The bump does the mechanical part and stops:

| What | Where |
| --- | --- |
| Reference clone to the new tag | `../upstream/crc-sdk` or `../upstream/crc-framework-rs` |
| Dependency pin | `pyproject.toml`, then `uv lock` and `uv sync` |
| Pin guard | `PINNED` in `src/lab_common/__init__.py` (checked by `tests/test_pins.py`) |
| Prose that names the pin | `README.md`, `AGENTS.md`, `../README.md` |
| Changelog row from the release notes | `CHANGELOG-upstream.md` |

It refuses to run if the target is not a release, if a release would be skipped, or if a file it edits has
changed since it was written. It does not touch reports, generated files, findings or tests.

Two cases need a flag:

- **Releases that require each other.** crc-sdk 1.x requires crc-framework 1.x and crc-sdk 0.11 requires
  crc-framework below 0.7, so neither pin can move alone. The tool reads the requirements from PyPI,
  refuses a move that would not resolve, and names the joint command:
  `just upstream-bump crc-sdk <version> --with crc-framework=<version>`. This is the one exception to
  "one release at a time".
- **Pre-releases** are ignored and refused unless `--pre` is given (`just upstream-check --pre`,
  `just upstream-bump ... --pre`). The changelog row then says "(pre-release)".

Tags are found by version, not by spelling: crc-framework tags `v1.0.0-alpha.2` for 1.0.0a2.

A major release is a port, not a pin move followed by a re-run. For 1.0 see `docs/crc-1.0-briefing.md`.

## First look, in minutes

```sh
just release-check
```

Runs three things in order and stops at nothing but the first:

1. `just upstream-surface`: every crc-sdk and crc-framework name our code imports, reads or stubs
   (listed in `docs/upstream-surface.md`, private names marked) is looked up in the installed version.
   A name that is gone is printed with each file and line that uses it. Method calls further down a
   chain cannot be found this way; the tool says how many it left unchecked.
2. The offline tests.
3. Quick staged re-runs (`just validation-monitor-rerun --profile quick`): every source against the new
   version, with JRC flood on its four small areas only (about two minutes of fitting in place of 27).
   The result is in `docs/validation/monitoring.md`. A quick re-run is labelled and cannot be accepted.

This answers "what did the release break or change" before any long run. For a major release expect
step 1 or 2 to fail first; fix the adapters under `src/data_source_check/adapters/crc/` and repeat.

## After the bump: what a person or an agent still does

1. Read the release notes and `git -C ../upstream/crc-sdk diff v<old> v<new> --stat`. Note which sources,
   workflows and providers the release touches.
2. `just release-check`, as above, then `just lint`.
3. `just validation-monitor-rerun`: the full re-run into the staging folder. It can be left to run:
   - the report is written after each source, a source that fails is reported as failed and the others
     still run;
   - a source already staged at the installed versions is not run again, so the command can simply be
     repeated after a failure; `--only <id>` runs one source, `--again` forces a repeat;
   - outside evidence and boundaries (FEMA, USGS) do not pass through crc-sdk and are copied from the
     cache held, not asked for again;
   - what the framework itself wrote into the staging cache at other versions is removed first, so a
     re-run never compares an old version's output under the new version's name; the publisher's files
     fetched by the reference readers are kept, and all four reference downloads retry on a dropped
     connection.
4. Read `docs/validation/monitoring.md`: which checks changed outcome, and why.
5. `just validation-accept <id>` for each source whose re-run has been read. Accepting is a person's step.
6. Findings (next section).
7. Review `site/sources.json`, which is written by hand and names the version it describes.
8. `just validation`, `just sources`, `just data`, `just site`, and the two browser smoke tests.
9. Fill in the last column of the new `CHANGELOG-upstream.md` row: the effect on crc-lab.
10. A short report in `docs/reports/u<n>-<package>-<version>.md`: what the release changed, what changed in
    our records, which findings moved.

### What to re-run

Every assessed source is re-run in full before its records are accepted, including the statewide Texas
run of `jrc-flood` (about 27 minutes, 5.8 GB of memory). A record then always states the version it
actually ran on. The alternative, restamping records of sources a release did not touch, was considered
and not taken: it would make the version on a record a claim rather than a fact. The quick profile is for
the first look only.

The hail project (`crc_lab`) and the explorer layers are rebuilt only when the release notes or the diff
touch what they call; step 1 decides this, and the report says which was chosen.

## Findings across versions

Findings live in `src/data_source_check/sources/crc_sdk/findings.toml`. Each carries the version it was
found at (`framework_version`) and a `status`:

| Status | Meaning | Who sets it |
| --- | --- | --- |
| `open` | Found by us, not sent upstream | whoever enters the finding |
| `reported upstream` | An issue or pull request exists; `upstream_ref` holds its address | set after Yuri approves the draft in `local/upstream-review.md` and it is sent |
| `fixed` | A release contains the fix; `fixed_in` holds that version (required by `core/records.py`) | set on the move to that release, after the re-run shows the fix |
| `by design` | Upstream answered that the behaviour is intended | set with Yuri, with the answer in `upstream_ref` |

The statuses and the `fixed_in` rule are defined in `src/data_source_check/core/records.py`
(`FINDING_STATUS`); the page shows "fixed in <version>" and keeps a fixed finding visible.

On each move, every finding that is not `fixed` or `by design` is checked again against the new version:

- A reported finding whose fix is in the release: confirm with the re-run that the behaviour is gone, set
  `status = "fixed"` and `fixed_in`. Remove any detour our code took around it.
- A finding that still reproduces: leave it as it is. `framework_version` keeps the version where it was
  first found; the report of the move lists the findings seen again and how each was checked (re-run,
  probe, or code reading of the diff).
- A finding that no longer reproduces although no fix was announced: do not close it. List it in the
  report for Yuri with what was run and what was seen.
- Anything new met during the re-runs is entered as a new finding with the next free number.

## History

| Date | Move | Report |
| --- | --- | --- |
| 2026-11-10 | Baseline: crc-sdk 0.11.1, crc-framework 0.6.0 | `docs/reports/0-setup.md`, `docs/baseline-crc-sdk-0.11.1.md` |
| 2026-11-23 | crc-sdk 0.11.1 to 0.11.2 | `docs/reports/u2-crc-sdk-0.11.2.md` |
| 2026-11-24 | crc-sdk 0.11.2 to 1.0.0 and crc-framework 0.6.0 to 1.0.0 (validation project ported; explorer and hail frozen) | `docs/reports/u3-crc-1.0.0.md` |
| 2026-11-26 | crc-sdk 1.0.0 to 1.0.1 to 1.1.0 and crc-framework 1.0.0 to 1.0.1 to 1.1.0, four commits (no staged re-run: downloads) | `docs/reports/u4-crc-1.1.0.md` |
