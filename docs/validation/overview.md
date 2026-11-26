# Verifying the data sources of Climate Risk Commons: what has been built

Written 2026-11-24, brought up to crc-sdk 1.0.0 on 2026-11-25. State described: crc-lab on crc-sdk 1.0.0
and crc-framework 1.0.0. The numbers of the previous version (0.11.2) are in
`docs/reports/u2-crc-sdk-0.11.2.md`, and its records are kept on the page as "previous version".

This document describes one of the three projects in crc-lab, the **source validation project**: what it
is for, the parts it is made of, what it has checked so far, what it found, and how it is kept current as
Climate Risk Commons (CRC) releases new versions. It assumes no knowledge of crc-lab. Numbers are taken
from the committed records and reports named beside them.

## 1. What it is for

crc-sdk, the Python layer of CRC, reaches about twenty outside data sources: storm tracks, station
observations, reanalysis, climate projections, flood maps. For each it downloads the publisher's files and
hands the user something derived from them: the same records reformatted, annual extremes, or fitted
return-period curves.

A user of those outputs is relying on two things that are rarely checked: that the framework delivers
what the publisher published, and that every change it makes on the way is one it states. This project
checks exactly that, source by source, and records the result in a form that can be re-run, compared across
versions and read by someone who was not there.

It was built for CRC first and is general by design: the framework-specific code is confined to one
folder of adapters.

## 2. The method in five sentences

1. **Three tiers.** Exploration asks what is there. Verification asks whether the framework delivers
   what the publisher published, changed only in the ways it states. Validation asks whether the values
   are fit for a stated use. Only the first two are built; verification can be settled, validation ends in a
   judgement.
2. **A transformation statement** per source: one line per step the framework takes (address, bytes,
   units, time axis, area, missing values, statistic, fit, labels), each with a reference to the code.
3. **An independent recomputation.** A reference reader that shares no code with the framework reads the
   publisher's files and recomputes the same result; the two are compared value by value within a stated
   tolerance.
4. **Outcomes are decided by the comparison, never by a language model.** Each check and each statement
   step ends as `confirmed`, `differs`, `not checked` or `not applicable`. A check that cannot fail proves
   nothing, so each comparison has a test that breaks a rule on purpose and must then differ.
5. **Findings are worded neutrally** (documented, observed, consequence), carry no grade, and stay
   visible after they are fixed.

The full method is `docs/validation/method.md` (version 0.2). Its structure follows the Federal Reserve's
SR 26-2 guidance on model risk; the check categories follow the Copernicus C3S quality assessments.

## 3. The parts

Package `src/data_source_check/`, about 13,100 lines of Python. 269 offline tests pass in the repository,
154 of them for this project; 8 test files of the other two projects wait for their port to crc-sdk 1.0.

| Part | Where | What it does | Rule it keeps |
| --- | --- | --- | --- |
| Record format | `core/records.py` | The vocabulary: source kinds, tiers, outcomes, check categories, finding kinds and statuses. Refuses a record that would mislead (a `fixed` finding with no version, a `reported upstream` one with no address) | Never imports a framework |
| Comparison core | `core/compare.py` | Compares rows and values in order within a tolerance; builds check records with inputs, sample, tolerance and versions | Same |
| Inventory | `core/inventory.py`, `sources/crc_sdk/*.toml` | One file per source: publisher, purpose, options offered and options assessed, the transformation statement. Detects entry points and option values the inventory does not cover | Same |
| Reference readers | `reference/` (IBTrACS, GHCNh, NEX, JRC flood, ERA5, NOAA water levels) | Read the publisher's files independently: Python's `csv`, DuckDB on NOAA's Parquet, `h5py`, a TIFF and DEFLATE decoder written for the purpose. Every download is kept with its checksum and the publisher's headers, and retried on a dropped connection | Never imports the framework being checked |
| Adapters | `adapters/crc/` | The only code that calls crc-sdk: asks it for the same thing the reference reader computed, and lists what it offers | The one place to change when the framework changes |
| Assessments | `assessments/` | One module per source: chooses the sample, runs both sides, makes the checks, attaches each check to the statement steps it bears on | Offline tests on constructed publisher files, with deliberate faults |
| Findings register | `sources/crc_sdk/findings.toml` | Every issue met, numbered once (`CRC-014-JRC`), with kind, basis, status and the version it was found at | Nothing goes upstream before Yuri has reviewed the draft |
| Outside evidence | `evidence/`, `assessments/jrc_flood_evidence.py` | For JRC flood: FEMA flood zones, USGS gauge peaks, Harvey high-water marks beside the framework's depths | A comparison carries numbers and limits, never an outcome |
| Build and reports | `build.py`, `core/report.py` | Writes records as JSON; generates the inventory, one report per source, and the page data from them | Pages and reports are generated from records, never typed |
| Monitor | `monitor.py`, `core/monitoring.py` | Asks the publishers whether files changed; compares installed versions with those assessed; stages re-runs and reports what moved | Never publishes: a person accepts a re-run |
| Drafting | `draft.py`, skill `draft-source-assessment` | Lets an agent draft the assessment of a new source: brief, gate, preview | A draft never reaches the page by itself and decides no outcome |
| Reproductions | `tools/repro/` | One self-contained script per finding of 1.0.0, run with `uv run`; prints expected, observed and `REPRODUCED` or `NOT REPRODUCED`. Captured outputs beside them | No import from crc-lab: a maintainer can run one alone |
| Page | `site/validation/` | The assessments, statements with their outcomes, checks, findings by address, links to maps | Reads the committed records |
| Map side | `src/crc_data_explorer/`, `site/validation/explore/` | The same sources on a map, with layers that show where a finding occurs | Each layer is tagged with its origin |

Three import rules hold the design together and are enforced by a test: `core/` imports no framework,
`reference/` does not import the framework under test, and the package imports nothing from the other
crc-lab projects.

## 4. How one assessment runs

IBTrACS, the simplest case, in order:

1. The inventory file states what crc-sdk says it does in fifteen steps: which address it requests, that
   it keeps a checksummed copy of the bytes, how it reads the header and the units, which rows and columns
   it returns for an agency, what it records about the source.
2. The reference reader downloads NOAA's file of all storms itself and reads it with Python's `csv` module.
3. The adapter asks crc-sdk for every row of each of the ten agencies.
4. The assessment compares: the address crc-sdk records against the documented one; the bytes on both
   sides by checksum; every value in order, for every agency.
5. Each check becomes a record: what was compared, the inputs with their checksums, the tolerance, the
   versions, the result, the outcome, and the statement steps it bears on.
6. The build turns the records into the page data and `docs/validation/sources/ibtracs.md`.

For gridded sources the same shape holds with more in it: NEX recomputes the annual value of every grid
cell from the whole NASA file; GHCNh recomputes 1,000 station-years from 13.9 million hourly reports; JRC
flood decides from the publisher's tiles which pixels should be returned and compares every published
depth of every returned pixel.

From 1.0 crc-sdk fits nothing by default, and each statement describes that default. Fits a user asks for
explicitly are not assessed yet.

## 5. What has been assessed

Twenty inventory entries: four assessed, two drafted by an agent and not published, fourteen not started.

| Source | Kind | Checks | Statement steps | Size of the comparison |
| --- | --- | --- | --- | --- |
| IBTrACS storm tracks | pass-through | 32 of 32 confirmed | 15: 14 confirmed, 1 not checked | One file, ten agencies: 233,822,080 values, 0 differ |
| GHCNh station observations | annual samples | 13 of 13 confirmed | 14: all confirmed | 1,000 station-years from 13,885,491 hourly reports, 0 values differ |
| NEX-GDDP-CMIP6 projections | annual samples | 34 of 35 confirmed, 1 differs | 18: 17 confirmed, 1 differs | 17,264 cell values, 0 differ; the difference is the file version, which cannot be chosen |
| JRC flood maps (GloFAS, EFAS) | pass-through | 48 of 48 confirmed | 16: all confirmed | Five areas with a Texas box: 206,099,226 pixels, 11,510,034 returned, 75,534,400 depths, 0 differ |

All four ran on 2026-11-24 and 25 against crc-sdk 1.0.0. All four are unsigned drafts: an assessment is a
draft until Yuri signs it. Drafted and unpublished, and still on the 0.11 interface: ERA5 and NOAA water
levels. Thirty-nine option values that crc-sdk offers for the assessed sources were not exercised and are
listed as such on the page.

No value differs in any of the four sources. What the runs established beyond that is in the findings:
which rows are returned, what is recorded about a source, defaults, messages and run time. The comparison
of the JRC maps with FEMA's flood zones, USGS gauges and Harvey high-water marks was made on crc-sdk 0.11
and has not been repeated on 1.0.0.

## 6. What was found

Thirty-eight findings so far: 5 defects, 9 differences between documentation and code, 24 observations.
Thirty were reproduced on data; eight rest on reading the code and say so.

| Status | Count | Which |
| --- | --- | --- |
| Fixed upstream | 6 | Two through our pull requests #42 and #43, released in crc-sdk 0.11.2: CRC-001-NEX (temperature recipes failed on real files) and CRC-010-IBT (a subset was requested under a name NOAA does not serve). Four by the 1.0.0 rewrite, each shown by a run: provenance of JRC output (CRC-003), a licence field for IBTrACS (CRC-011), the JRC licence (CRC-018), identifiers that depended on the box (CRC-020) |
| Superseded | 4 | The behaviour changed in 1.0.0 and a new finding describes what it does now (CRC-012 by 031, CRC-013 by 026, CRC-014 by 023, CRC-016 by 024) |
| No longer applies | 1 | CRC-015-JRC: the fitted curve it described is no longer made by default |
| Open | 27 | Sixteen were entered at 1.0.0 (CRC-023 to CRC-038). Among them: with the default coverage one incomplete day leaves a GHCNh station-year without a value (CRC-035); 20 of 34 NEX models are refused for their calendar (CRC-032); 4 to 12% of flooded JRC pixels are left out and counted with dry pixels (CRC-023); a connection the publisher drops ends a read (CRC-038). Eleven are older; ten of them have not been run on 1.0.0 |

Each finding of 1.0.0 has a script under `tools/repro/` that shows it by command, and five have a fix
prepared on a branch. None has been sent yet.

A finding moves `open` to `reported upstream` to `fixed`, or to `by design`, `superseded` or `no longer
applies`, and each step has a condition: a draft reviewed by Yuri before anything is sent, an address once it is sent, the fixing version
once a re-run shows the fix. The full list with evidence is `docs/validation/inventory.md`.

## 7. Keeping it current

An assessment is a statement about particular files and a particular version. Two things can make it
stale, and each has a mechanism.

**The publisher changes a file.** `just validation-monitor` asks each publisher, with HEAD requests only,
about the 1,016 files the assessments read and compares ETag and Last-Modified with what was recorded. A
weekly GitHub workflow runs it and never commits. A file the source's TOML declares rewritten in place
(`[monitoring]`, IBTrACS only) is reported as a new copy, with the SHA-256 of the copy assessed, and does
not fail the run; the rules are in `method.md` §9.

**The framework changes.** The pins live in one place and move with a tool:

| Command | What it does |
| --- | --- |
| `just upstream-check` | Lists releases of crc-sdk and crc-framework newer than the pins, with their notes |
| `just upstream-bump <package> <version>` | Moves a pin everywhere it is written, the reference clone, the lock file and the changelog. Refuses to skip a release, to move a pin that would not resolve, or to touch a changed file. `--with` moves two packages that require each other; `--pre` allows a pre-release |
| `just upstream-surface` | Looks up the 78 upstream names our code uses in the installed version and prints the ones that are gone |
| `just release-check` | The first look in minutes: the name check, the offline tests, quick staged re-runs |
| `just validation-monitor-rerun` | Re-runs stale sources into a staging folder and reports what moved: outcomes changed, checks added or no longer run. A failed source is reported and the others continue; a repeat skips what is already staged; output written by another framework version is discarded first |
| `just validation-accept <id>` | A person publishes a staged re-run after reading the report |

The quick profile (`--profile quick`) runs JRC flood on four small areas in minutes; the full run includes
a Texas box that crc-sdk 1.0.0 reads in two and a half hours. A quick re-run is labelled and cannot be
accepted.

This procedure has been used twice. On 2026-11-23, from crc-sdk 0.11.1 to 0.11.2: the IBTrACS address check
went from differs to confirmed and the NEX temperature recipes were checked for the first time
(`docs/reports/u2-crc-sdk-0.11.2.md`). On 2026-11-24, from 0.11.2 to 1.0.0, below. The procedure is
`docs/upstream-updates.md`.

## 8. The move to 1.0.0

crc-sdk 1.0 and crc-framework 1.0 are rewrites of the public interface: 73 of the 75 upstream names our
code used did not exist any more, and the two pins had to move together. For this project the move was a
port, done on the day of the release and the day after (`docs/reports/u3-crc-1.0.0.md`):

- Before the release, `just v1-probes <sdk version> <framework version>` ran eleven probes of the open
  findings against the pre-releases in an environment of their own (`docs/reports/v1-probes-<version>.md`).
- The four adapters, assessments and statements were written again for the default behaviour of 1.0.
  The reference readers, which do not depend on crc-sdk, were kept and extended.
- The 0.11.2 records stay on the page as the previous version, so a reader can see what moved.
- Each finding was closed, superseded or kept by a run on 1.0.0, never by reading the release notes.
- The other two projects of crc-lab (the map explorer and the hail study) are not ported yet; their data
  is a labelled build made with 0.11.2. The name check reports 49 names missing, all in files that are
  not ported: those two projects and the two unpublished drafts.

## 9. Limits

- Verification only. No source has a validation tier; that waits for criteria.
- What crc-sdk 1.0 does by default only. Fits and reductions a user asks for explicitly are not assessed.
- Four sources of twenty, and for each a stated sample: one model and member for NEX, forty stations for
  GHCNh, five areas for JRC flood. A `confirmed` outcome holds for those files, options and versions.
- Every assessment is an unsigned draft, and the method document itself has not been reviewed.
- Eight findings rest on code reading. The sixteen findings of 1.0.0 can be re-checked by command; most
  older ones cannot, and ten of those have not been run on 1.0.0.
- The statements cite upstream code by file and line; a release that moves code means moving references,
  and a rewrite means writing statements again.
- The JRC flood record holds no publisher file addresses, so the monitor can flag it only through a
  version change.
- Outside-evidence comparisons (FEMA, USGS) carry no outcome by design: they inform a reader and settle
  nothing.

## 10. A five-minute tour

Serve the site locally with `just serve` and open the addresses below in order; each is one stop. On the
published site, replace `http://127.0.0.1:8000` with `https://shlyakh.github.io/crc-lab`.

| Stop | Address | What to say |
| --- | --- | --- |
| 1 | `http://127.0.0.1:8000/validation/` | The top of the page: which framework and versions, how many sources, how many assessed, how many findings |
| 2 | `http://127.0.0.1:8000/validation/#inventory-section` | Twenty sources by kind and tier; most are not assessed yet, and the page says so |
| 3 | `http://127.0.0.1:8000/validation/#assessment-ibtracs` | IBTrACS: the summary, then the statement with an outcome on every step, then the checks with their numbers |
| 4 | `http://127.0.0.1:8000/validation/#finding-CRC-010-IBT` | A finding that went the whole way: found, sent as a pull request, fixed in 0.11.2 |
| 5 | `http://127.0.0.1:8000/validation/#finding-CRC-023-JRC` | An open finding in neutral wording: documented, observed, consequence, evidence |
| 6 | `http://127.0.0.1:8000/validation/explore/#tab=crc&layer=jrc_review_glofas_tx_no_curve_share` | The finding it replaced (CRC-014), on the map: where in Texas flooded pixels got no curve. The map side still shows the build made with crc-sdk 0.11.2 |
| 7 | `http://127.0.0.1:8000/validation/explore/#tab=crc&layer=jrc_evidence_glofas_austin_fema` | Outside evidence: the GloFAS map beside FEMA's flood zones in Austin |
| 8 | `docs/validation/monitoring.md`, then `docs/reports/v1-probes-<version>.md` | How it stays current, and what the probes said about 1.0 before the move |
