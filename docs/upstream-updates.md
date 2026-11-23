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

## After the bump: what a person or an agent still does

1. Read the release notes and `git -C ../upstream/crc-sdk diff v<old> v<new> --stat`. Note which sources,
   workflows and providers the release touches.
2. `just test` and `just lint`. Tests that stub private names of crc-sdk
   (`crc_sdk.workflows.ibtracs.urlopen`, `crc_sdk.workflows.nex._open_backend`,
   `crc_sdk.providers.ghcnh.fsspec`) are the likeliest to break on a rename.
3. `just validation-monitor-rerun`. The monitor sees that the installed version differs from the version
   each assessment recorded and re-runs the stale ones into a staging folder.
4. Read `docs/validation/monitoring.md`: which checks changed outcome, and why.
5. `just validation-accept <id>` for each source whose re-run has been read. Accepting is a person's step.
6. Findings (next section).
7. Review `site/sources.json`, which is written by hand and names the version it describes.
8. `just validation`, `just sources`, `just data`, `just site`, and the two browser smoke tests.
9. Fill in the last column of the new `CHANGELOG-upstream.md` row: the effect on crc-lab.
10. A short report in `docs/reports/u<n>-<package>-<version>.md`: what the release changed, what changed in
    our records, which findings moved.

### What to re-run

Every assessed source is re-run on every move, including the statewide Texas run of `jrc-flood` (about
27 minutes, 5.8 GB of cache). A record then always states the version it actually ran on. The alternative,
restamping records of sources a release did not touch, was considered and not taken: it would make the
version on a record a claim rather than a fact.

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
