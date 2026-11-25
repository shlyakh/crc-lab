# Verifying the data sources of Climate Risk Commons: what has been built

Written 2026-11-24. State described: crc-lab on crc-sdk 0.11.2 and crc-framework 0.6.0. The project moved to
crc-sdk 1.0.0 later the same day: the method and the parts described here are unchanged, the numbers in
section 5 and the register in section 6 are those of 0.11.2, and `docs/reports/u3-crc-1.0.0.md` gives the
records and findings on 1.0.0.

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

Package `src/data_source_check/`, about 10,600 lines of Python, with 395 offline tests in the repository.

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
| Page | `site/validation/` | The assessments, statements with their outcomes, checks, findings by address, links to maps | Reads the committed records |
| Map side | `src/crc_data_explorer/`, `site/validation/explore/` | The same sources on a map, with layers that show where a finding occurs | Each layer is tagged with its origin |

Three import rules hold the design together and are enforced by a test: `core/` imports no framework,
`reference/` does not import the framework under test, and the package imports nothing from the other
crc-lab projects.

## 4. How one assessment runs

IBTrACS, the simplest case, in order:

1. The inventory file states what crc-sdk says it does in twelve steps: which address it requests for
   each subset, that it saves the bytes unchanged and records a checksum, how it reads the header, how the
   two filters work, what the manifest holds.
2. The reference reader downloads NOAA's eleven files itself and reads them with Python's `csv` module.
3. The adapter asks crc-sdk for the same files and every row.
4. The assessment compares: the address crc-sdk builds against what NOAA serves; the bytes on both sides
   by checksum; every value in order; each filter against the same selection made independently.
5. Each check becomes a record: what was compared, the inputs with their checksums, the tolerance, the
   versions, the result, the outcome, and the statement steps it bears on.
6. The build turns the records into the page data and `docs/validation/sources/ibtracs.md`.

For gridded and fitted sources the same shape holds with more in it: NEX recomputes the annual value of
every grid cell from the whole NASA file; GHCNh recomputes 1,000 station-years from 13.9 million hourly
reports; JRC flood compares crc-sdk's crops with the publisher's tiles bit for bit and refits every curve.

## 5. What has been assessed

Twenty inventory entries: four assessed, two drafted by an agent and not published, fourteen not started.

| Source | Kind | Checks | Statement steps | Size of the comparison |
| --- | --- | --- | --- | --- |
| IBTrACS storm tracks | pass-through | 78 of 78 confirmed | 12: 11 confirmed, 1 not checked | 11 files, 323,443,902 values, 0 differ |
| GHCNh station observations | fitted curves | 8 of 8 confirmed | 14: all confirmed | 1,000 station-years from 13,885,491 hourly reports, 0 values differ |
| NEX-GDDP-CMIP6 projections | annual samples | 23 of 24 confirmed, 1 differs | 15: 14 confirmed, 1 differs | 23,738 cell values, 0 differ; the difference is NASA's version 2.0 files, which cannot be requested |
| JRC flood maps (GloFAS, EFAS) | fitted curves | 40 of 44 confirmed, 4 differ | 15: 11 confirmed, 4 differ | 1,447,885,064 pixel values, 0 differ; 10,240,052 curves refitted, 2,959 differ |

All four ran on 2026-11-23 against crc-sdk 0.11.2. All four are unsigned drafts: an assessment is a draft
until Yuri signs it. Drafted and unpublished: ERA5 and NOAA water levels. Thirty option values that
crc-sdk offers for the assessed sources were not exercised and are listed as such on the page.

What the JRC flood assessment established beyond pass or fail: the pixels that get no curve fall into two
groups, permanent water (equal or decreasing depths) and land with fewer than four depths; and against
FEMA's flood zones the GloFAS map floods 35.5%, 20.7% and 11.6% of the A zone in the three areas compared.

## 6. What was found

Twenty-two findings so far: 4 defects, 5 differences between documentation and code, 13 observations.
Fifteen were reproduced on data; seven rest on reading the code and say so.

| Status | Count | Which |
| --- | --- | --- |
| Fixed upstream | 2 | CRC-001-NEX (temperature recipes failed on real files) and CRC-010-IBT (the `active` subset was requested under a name NOAA does not serve). Both were sent as pull requests #42 and #43, merged, and released in crc-sdk 0.11.2; the re-run on 0.11.2 confirmed both |
| Open | 20 | Not yet sent. Ten concern JRC flood, among them: a flooded pixel that gets no curve and no message (CRC-014); a fitted curve metres away from the published depth (CRC-015); a licence stated as CC BY 4.0 where the publisher's README names the Open Database License (CRC-018); 27 minutes and 5.8 GB of memory for the Texas box (CRC-022) |

A finding moves `open` to `reported upstream` to `fixed`, or to `by design`, and each step has a
condition: a draft reviewed by Yuri before anything is sent, an address once it is sent, the fixing version
once a re-run shows the fix. The full list with evidence is `docs/validation/inventory.md`.

## 7. Keeping it current

An assessment is a statement about particular files and a particular version. Two things can make it
stale, and each has a mechanism.

**The publisher changes a file.** `just validation-monitor` asks each publisher, with HEAD requests only,
about the 1,027 files the assessments read and compares ETag and Last-Modified with what was recorded. A
weekly GitHub workflow runs it and never commits.

**The framework changes.** The pins live in one place and move with a tool:

| Command | What it does |
| --- | --- |
| `just upstream-check` | Lists releases of crc-sdk and crc-framework newer than the pins, with their notes |
| `just upstream-bump <package> <version>` | Moves a pin everywhere it is written, the reference clone, the lock file and the changelog. Refuses to skip a release, to move a pin that would not resolve, or to touch a changed file. `--with` moves two packages that require each other; `--pre` allows a pre-release |
| `just upstream-surface` | Looks up the 75 upstream names our code uses in the installed version and prints the ones that are gone |
| `just release-check` | The first look in minutes: the name check, the offline tests, quick staged re-runs |
| `just validation-monitor-rerun` | Re-runs stale sources into a staging folder and reports what moved: outcomes changed, checks added or no longer run. A failed source is reported and the others continue; a repeat skips what is already staged; output written by another framework version is discarded first |
| `just validation-accept <id>` | A person publishes a staged re-run after reading the report |

The quick profile (`--profile quick`) runs JRC flood on four small areas in under three minutes in place
of 27; a quick re-run is labelled and cannot be accepted.

This procedure was used once, on 2026-11-23, to move from crc-sdk 0.11.1 to 0.11.2: the IBTrACS address
check went from differs to confirmed, the NEX temperature recipes were checked on the installed version
for the first time, and GHCNh and JRC flood did not move. The account is
`docs/reports/u2-crc-sdk-0.11.2.md`; the procedure is `docs/upstream-updates.md`.

## 8. Looking at a version before moving to it

crc-sdk 1.0 and crc-framework 1.0 are rewrites of the public interface: 73 of the 75 upstream names our
code uses do not exist in 1.0.0a1. Moving to them is a port of every adapter, and crc-lab stays on 0.11.2
until that is done.

To see what 1.0 does to the open findings without moving, `just v1-probes <sdk version> <framework
version>` runs eleven small probes in an environment of their own, each ending in a verdict (`not
reproduced on 1.0`, `still reproduces`, `changed`, `new behaviour`, `could not run`). The generated report
is `docs/reports/v1-probes-<version>.md`; what the two migration guides say is summarised in
`docs/crc-1.0-briefing.md`.

## 9. Limits

- Verification only. No source has a validation tier; that waits for criteria.
- Four sources of twenty, and for each a stated sample: one model and member for NEX, forty stations for
  GHCNh, five areas for JRC flood. A `confirmed` outcome holds for those files, options and versions.
- Every assessment is an unsigned draft, and the method document itself has not been reviewed.
- Seven findings rest on code reading. Most findings have no probe that re-checks them by command.
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
| 5 | `http://127.0.0.1:8000/validation/#finding-CRC-014-JRC` | An open finding in neutral wording: documented, observed, consequence, evidence |
| 6 | `http://127.0.0.1:8000/validation/explore/#tab=crc&layer=jrc_review_glofas_tx_no_curve_share` | The same finding on the map: where in Texas flooded pixels get no curve |
| 7 | `http://127.0.0.1:8000/validation/explore/#tab=crc&layer=jrc_evidence_glofas_austin_fema` | Outside evidence: the GloFAS map beside FEMA's flood zones in Austin |
| 8 | `docs/validation/monitoring.md`, then `docs/reports/v1-probes-<version>.md` | How it stays current, and what the probes say about 1.0 |
