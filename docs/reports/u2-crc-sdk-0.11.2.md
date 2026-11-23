# Move to crc-sdk 0.11.2

Date: 2026-11-23 · crc-sdk 0.11.1 to 0.11.2, crc-framework 0.6.0 unchanged · awaiting review

First move of the pin, and the first run of the procedure in `docs/upstream-updates.md`. The state
before it is `docs/baseline-crc-sdk-0.11.1.md` (tag `baseline-crc-sdk-0.11.1`).

## What the release changes

crc-sdk 0.11.2 was released on 2026-11-13 and contains our two pull requests and nothing else.
`git diff v0.11.1 v0.11.2` in the reference clone touches two source files:

- `crc_sdk/workflows/ibtracs.py`: the subset `active` is requested under NOAA's file name `ACTIVE` (#43).
- `crc_sdk/workflows/nex.py`: NetCDF attributes that arrive as bytes are decoded, so the one-character
  unit `K` is accepted (#42).

No documentation page under `docs/` changed. The name check (`just upstream-surface`) finds all 75
upstream names our code uses, 5 of them private, in 0.11.2.

## Re-runs

All four assessed sources were run again from the publishers' files against the installed 0.11.2 and
accepted onto the page. They remain unsigned drafts.

| Source | Before (0.11.1) | Now (0.11.2) | What moved |
| --- | --- | --- | --- |
| `ibtracs` | 71 checks: 70 confirmed, 1 differs | 78 checks: 78 confirmed | `address` from differs to confirmed; the `active` file is now read and compared (7 new checks; 82 rows, 14,268 values, 0 differ). 11 files, 323,443,902 values compared, 0 differ. NOAA had rewritten all ten earlier files on 2026-11-22 |
| `ghcnh` | 8 checks: 8 confirmed | 8 checks: 8 confirmed | Nothing. 1,000 station-years, 13,885,491 hourly reports, 0 values differ |
| `nex-gddp-cmip6` | 24 checks: 19 confirmed, 5 differ | 24 checks: 23 confirmed, 1 differs | The four `units` checks that differed are gone because the recipes now run; `txx` and `tnn` are compared cell by cell at the installed version: 8,632 cell values, 0 differ. 23,738 cell values in all. `versions-served` still differs (CRC-012-NEX) |
| `jrc-flood` | 44 checks: 40 confirmed, 4 differ | 44 checks: 40 confirmed, 4 differ | Nothing. 1,447,885,064 pixel values, 0 differ; 10,240,052 curves refitted, 2,959 differ. Texas fit 1,606 s |

Statement steps that changed outcome: IBTrACS `address` (differs to confirmed); NEX
`units-temperature` (differs to confirmed) and `statistic-temperature` (not checked to confirmed).

## Findings

| Finding | Before | Now | How it was checked |
| --- | --- | --- | --- |
| CRC-001-NEX | reported upstream | fixed in 0.11.2 | The NEX re-run: both temperature recipes return rows on NASA's files and every cell agrees with the recomputation |
| CRC-010-IBT | reported upstream | fixed in 0.11.2 | The IBTrACS re-run: NOAA answers 200 for the address crc-sdk builds for `active`, and the file's values agree |
| CRC-011-IBT | open | open, seen again | `provenance` checks of the re-run are unchanged |
| CRC-012-NEX | open | open, seen again | `versions-served` differs as before: NASA serves 2.0, crc-sdk accepts 1.0 to 1.2 |
| CRC-013-FWK, CRC-014-JRC, CRC-015-JRC | open | open, seen again | The same four `curves` checks differ with the same counts |
| The other 15 | open | open, not re-run | The code they cite is outside the two files the release changed; none has a probe that runs by command yet |

No new finding was opened.

## Changes in crc-lab

- Pin: `pyproject.toml`, `uv.lock`, `PINNED`, the prose in `README.md`, `AGENTS.md`, `../README.md`; reference
  clone `../upstream/crc-sdk` at `v0.11.2`. All done by `just upstream-bump crc-sdk 0.11.2`.
- The detour of the NEX assessment through `../forks/crc-sdk` is removed (`assessments/nex.py`,
  `build.py`). The temperature recipes carry the steps `units-temperature` and `statistic-temperature`.
- The IBTrACS reference reader requests `ACTIVE` for the subset `active`, and `active` is in the list of
  assessed subsets.
- Statement code references in `ibtracs.toml` and `nex-gddp-cmip6.toml` are moved to the lines of 0.11.2.
- `site/sources.json` names 0.11.2. The explorer layers under `site/data/sources/` were not rebuilt: they
  use the `NA` subset of IBTrACS and no NEX, which the release does not touch. Their manifests still say
  0.11.1, which is the version that built them.

## What the first run of the procedure showed, and what was changed

The live re-runs took five starts over about four hours. Causes and the changes made:

| What went wrong | Change |
| --- | --- |
| NOAA reset a connection, then timed out, among 1,000 GHCNh downloads; JRC timed out on one file. Each stopped the whole run | The GHCNh and JRC reference downloads retry (four tries, growing pause) |
| A failure in one source lost the report for the sources already done | The monitor writes its report after each source, records a failed source as failed and carries on |
| Every restart began again from the first source | A source already staged at the installed versions is not run again; `--only <id>` runs one source; `--again` forces |
| The JRC re-run asked FEMA and USGS again for outside evidence and stalled there for over an hour | Outside evidence and boundaries do not pass through crc-sdk; a re-run copies the files held, with their own retrieval dates |
| The Texas box takes 27 minutes whatever the release touched | `--profile quick` runs JRC flood on Houston, Austin, Fremont and the Rhine only (about two minutes of fitting). A quick re-run is labelled and cannot be accepted |
| Offline tests failed only because committed records named the old version | The monitor tests take the assessed versions from the records |
| No fast answer to "does our code still find what it imports" | `just upstream-surface` (`tools/crc_surface.py`, list in `docs/upstream-surface.md`) |
| A fixed finding showed no version in the generated reports | Reports print "fixed in <version>" |

`just release-check` chains the name check, the offline tests and the quick staged re-runs.

## Not done, and limits

- The IBTrACS and NEX reference downloads have no retry yet.
- Fifteen findings were not re-run on 0.11.2; they rest on the unchanged code. Probes that run by command
  exist only for some JRC findings (`tools/probes/jrc_flood_probes.py`).
- The quick profile reduces only JRC flood. IBTrACS still compares 323 million values and GHCNh 1,000
  station-years on every run.
- The monitor could not reach five GHCNh files with a HEAD request during this run (network errors on the
  day); they are listed in `site/validation/data/monitor.json` and do not make the source stale.
- The hail pipeline and the CRC Open explorer files were not rebuilt; the release does not touch what they call.
- The published NEX record still holds absolute paths of this machine (`crc_sdk_path`), as before.
- Browser check: `tools/smoke-validation.mjs` passes; `tools/smoke.mjs` (hail and explorer pages) was not run,
  since their data did not change.
- Nothing is pushed.
