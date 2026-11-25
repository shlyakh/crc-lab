# Move to crc-sdk 1.0.0 and crc-framework 1.0.0

Date: 2026-11-24 · crc-sdk 0.11.2 to 1.0.0, crc-framework 0.6.0 to 1.0.0 · awaiting review

Second move of the pins, on the day of the release, on branch `crc-1.0`. The state before it is
`docs/reports/u2-crc-sdk-0.11.2.md`; what the two packages change is summarised in
`docs/crc-1.0-briefing.md`.

## What was moved and what was not

1.0 is a rewrite of the public interface of both packages, and the two pins move together. The move was
done for one project and not for the other two:

| Project | State on 1.0.0 |
| --- | --- |
| Source validation (`src/data_source_check/`) | Ported for the four assessed sources. The inventory, the register, the monitor and the page run on 1.0.0 |
| CRC data explorer (`src/crc_data_explorer/`) | Not ported. Its data under `site/data/` is the build made with 0.11.2, committed and labelled (`site/data/README.md`) |
| Texas hail risk (`src/crc_lab/`) | Not ported where it calls CRC (curves, impact adapter, cell geometry). Same frozen data |

`just upstream-surface` still reports 49 upstream names that no longer exist. All are in files that await
the port: the explorer and hail modules, `lab_common/horizons.py` and `texas.py`, the two unpublished
drafts (ERA5, NOAA water levels) and the kept 0.11 JRC adapter (`jrc_flood_011.py`). The tests of those
files are parked in `tests/conftest.py`, and every test run prints how many are parked: 8 test files and
3 tests. 269 tests pass, 3 are skipped.

## What a ported assessment now verifies

Each of the four statements was written again for what 1.0.0 does **by default**. Nothing is fitted by
default in 1.0, so the statements are shorter where 0.11 fitted (JRC flood, GHCNh) and the checks of the
fits are gone with them. Explicit fits are a later step. The 0.11.2 records are kept under
`site/validation/data/records/0.11.2/` and the page links to them as the previous version.

| Source | 0.11.2 | 1.0.0 | What is compared now |
| --- | --- | --- | --- |
| `ibtracs` | 78 of 78 confirmed | 32 of 32 confirmed | One file (`ALL`; the eleven subsets are gone), every agency: 233,822,080 values, 0 differ |
| `ghcnh` | 8 of 8 confirmed | 13 of 13 confirmed | Observations and the annual reduction: 1,000 station-years from 13,885,491 hourly reports, 0 values differ |
| `nex-gddp-cmip6` | 23 of 24 confirmed, 1 differs | 34 of 35 confirmed, 1 differs | 17,264 cell values, 0 differ; `versions-served` differs (the file version cannot be chosen) |
| `jrc-flood` | 40 of 44 confirmed, 4 differ | 38 of 39 confirmed, 1 not checked (four small areas) | Published depths at probabilities 1 - 1/T: 4,341,724 pixels, 440,723 delivered, 3,073,486 depths, 0 differ |

Two limits on the JRC flood record:

- It covers the four small areas of the quick profile (Houston, Austin, Fremont, Rhine), not the Texas
  box. The Texas run was started and had not ended after four hours (see CRC-022-JRC below).
- The JRC server did not answer on the evening of the release. crc-sdk was given local copies of the
  publisher's files, held from the 0.11.2 run, in place of the server: its decoding is verified, its
  downloads are not. The `transport` step is `not checked`, and four probes that need the server did not
  run (`docs/reports/v1-probes-1.0.0.md`).

## Findings

The register has 37 findings. Two statuses were added: `no longer applies` (the feature was removed) and
`superseded` (replaced by a finding entered at the new version).

| Finding | Before | Now | How it was checked |
| --- | --- | --- | --- |
| CRC-003-JRC, CRC-018-JRC, CRC-020-JRC | open | fixed in 1.0.0 | The JRC run: licence, attribution, retrieval time and checksum are in the output; the licence is the publisher's; identifiers do not depend on the box |
| CRC-011-IBT | open | fixed in 1.0.0 | The IBTrACS run: the resource identity carries a licence |
| CRC-015-JRC | open | no longer applies | No curve is fitted by default; published depths are returned unchanged |
| CRC-012-NEX | open | superseded by CRC-031-NEX | Version 2.0 is now read, but the version cannot be chosen |
| CRC-013-FWK | open | superseded by CRC-026-FWK | The fit case was run again; which number format converges has swapped |
| CRC-014-JRC | open | superseded by CRC-023-JRC | Pixels are skipped by a different rule and are now counted, with dry pixels in the same count |
| CRC-016-JRC | open | superseded by CRC-024-JRC | Outside coverage there is no error any more: an empty result reported as complete |
| CRC-022-JRC | open | open, worse on first sight | The Texas read had not ended after four hours at about 22,000 pixels a second, against 27 minutes for the whole run on 0.11; memory stayed near 110 MB against 5.8 GB. Not yet entered as numbers |
| CRC-017, 019, 021 (JRC); CRC-002, 004 to 009 | open | open, not re-run | No run on 1.0.0 yet |

Entered at 1.0.0, all open, none sent upstream:

| Finding | What was observed |
| --- | --- |
| CRC-023-JRC | Flooded pixels with one depth or a decreasing depth are left out (4 to 12% of flooded pixels in four areas); the one count reported also holds every dry pixel |
| CRC-024-JRC | A box outside a product's coverage returns no rows, no diagnostic, complete and valid |
| CRC-025-OWN | `Dataset.from_raster` fails the whole read on one decreasing pixel and does not name it |
| CRC-026-FWK | Whether a Gumbel quantile fit converges depends on 32-bit against decimal values of the same depths |
| CRC-027-FWK | The checksum recorded for a file read by window is of crc-sdk's cut-out |
| CRC-028-IBT | An agency's wind and pressure are placed at the combined position |
| CRC-029-IBT | Every point is returned for every agency; 60 to 99% of rows carry no value |
| CRC-030-IBT | Documentation says an explicit agency; the constructor has a default |
| CRC-031-NEX | The file version cannot be chosen |
| CRC-032-NEX | Models on a calendar that is not Gregorian are refused; shown for one model in our record |
| CRC-033-NEX | No licence is recorded; the model licence in the file is not read |
| CRC-034-NEX | A year without a file gives rows with no value and no message |
| CRC-035-GHC | With the default completeness rule 0 of 592 station-years of forty Texas airports carry a value; 339 at a 0.9 fraction |
| CRC-036-GHC | One unusable report stops the read of every selected station (constructed files) |
| CRC-037-GHC | Attribution names CO-OPS; generic licence text; no dataset version |

## Changes in crc-lab

- Pins: `pyproject.toml` (the `geometry` extra is gone), `uv.lock`, `PINNED`, prose; reference clones at
  `v1.0.0`; `../upstream/crc-docs` at `5f61ee7`.
- `adapters/crc/enumerate.py` reads the providers exported by `crc_sdk`; all twenty source files are
  updated; OS-Climate is marked removed in 1.0.0.
- Four adapters, four assessments and four statements written again; the 0.11 JRC modules are kept as
  `*_011` for the later explicit-fit work.
- crc-sdk is fed offline in tests through one patch per source: its download function (IBTrACS, GHCNh), a
  local server (NEX), the JRC layout table. The last is private to crc-sdk.
- `tools/probes/v1/` marks a publisher that does not answer as `could not run`, not as a verdict.
- The pages workflow no longer builds the explorer and hail data; `just data`, `storm-events`, `curves` and
  `sources` stop with a message until the port.
- `site/sources.json` still describes the explorer of 0.11.2, which is what the explorer page shows.

## What the day showed about the procedure

| What happened | Consequence |
| --- | --- |
| The plan allowed four hours; the work took about six | Publisher connection resets (NOAA, NASA) and the JRC outage |
| The JRC server was down all evening | The local-copy route (`publisher_at`) was added so the decoding could still be verified |
| The Texas box takes hours on 1.0.0 | The full JRC re-run no longer fits the rule "every source is re-run in full before acceptance" within a working day; the rule or the box needs a decision |
| Three sources were ported in parallel in separate worktrees | Worked; the worktrees were made from `main` and had to be moved to the branch first |

## Open

- Texas JRC run: outcome, then the full record or a decision on the box.
- JRC network probes and CRC-021 when the JRC server answers.
- The older open findings on 1.0.0.
- Port of the explorer and the hail project; explicit fits; ERA5 and NOAA water levels; CRC Open (readable
  on 1.0.0: `CRCOpen().inspect()` lists 875 series in one release).
