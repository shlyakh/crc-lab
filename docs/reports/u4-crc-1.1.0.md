# Move to crc-sdk 1.1.0 and crc-framework 1.1.0

Date: 2026-11-26 · crc-sdk 1.0.0 to 1.1.0, crc-framework 1.0.0 to 1.1.0 · awaiting review

Third move of the pins, on branch `crc/1.1.0`, the day the releases came out. The state before it is
`docs/reports/u3-crc-1.0.0.md`. Not pushed, nothing sent upstream.

## Four steps, one release at a time

crc-sdk 1.1.0 requires crc-framework 1.1, so the order was set by the requirements and the release dates.
Each step is one commit with its own changelog row:

| Step | Move | What the release does for crc-lab |
| --- | --- | --- |
| 1 | crc-sdk 1.0.0 to 1.0.1 | Our pull requests #53 to #56: GHCNh attributed to NOAA NCEI only, NEX licence read from `cmip6_license`, a `source_year_unavailable` warning for a NEX year with no file, an `area_outside_coverage` warning for a JRC box outside the product |
| 2 | crc-framework 1.0.0 to 1.0.1 | Speed only: laws built and queried natively, no interface or format change |
| 3 | crc-framework 1.0.1 to 1.1.0 | Built-in impact models only (calibration facts for seven, fire weather needs the wildland-urban interface, hot days retired). crc-lab binds none of them |
| 4 | crc-sdk 1.0.1 to 1.1.0 | Answers to our issues #57 to #59 (pull requests #62 to #64): NEX read on 365- and 360-day calendars, GHCNh `daily_coverage`, every flooded JRC pixel returned. Also many speed changes, DuckDB 2.x allowed (the lock keeps 1.5.6), `Dataset.from_raster` names a decreasing pixel in its error |

`just upstream-bump` was run for each step. It moves the reference clones under `../upstream/` and edits
`../README.md`; both are outside this worktree and were not to be touched, so the tool ran with its
workspace pointed at a scratch copy (clones made from the local ones, tags fetched from GitHub). The
workspace README therefore still names v1.0.0 for both clones, and the reference clones still sit at
v1.0.0: moving them is Yuri's step. 13 tests of `tests/test_upstream_tool.py` copy that README and fail
until it names the pins; with the scratch copy all 48 pass.

## What touches what we use

| Area | Change | Effect here |
| --- | --- | --- |
| IBTrACS | Downloads overlap with `Runtime(workers)`; none of our three IBTrACS findings addressed | Statement unchanged |
| GHCNh | NCEI-only attribution (1.0.1); `daily_coverage` added, default still all 24 hours (1.1.0) | Provenance statement names NCEI only; `daily_coverage` is a new parameter, not yet assessed |
| NEX | `cmip6_license` read (1.0.1); `source_year_unavailable` (1.0.1); native 365/360-day calendars (1.1.0) | Licence, year-without-file and calendar statements and checks ported |
| JRC flood | `area_outside_coverage` (1.0.1); a return period a flooded pixel lacks is read as 0 m, only decreasing pixels are skipped, dry pixels are a note and no longer requested or skipped (1.1.0) | Area, selection, skipped-count, knots and coverage statements and checks ported; the reference reader applies the new rule |
| Flood lab | `Dataset.from_raster`: the skipped-pixel message splits dry and one-value pixels, a decreasing pixel's error names it; Arrow curves decoded by column; `QuantileCurve`, `Dataset.from_quantiles`, `Impact`, `Distribution` unchanged in interface | F4 CRC routes re-run, below |
| Hail project, explorer | Not ported (frozen 0.11.2 data); nothing in the notes reaches them before their port | Not rebuilt |

`just upstream-surface`: 106 names checked, the same 49 missing as on 1.0.0, all in the files that await the
1.0 port. `docs/upstream-surface.md` is regenerated (it predated the flood lab).

## What was run

| What | Result |
| --- | --- |
| `uv run pytest -q` after each step | 1.0.1: 559 passed, 4 skipped; framework 1.0.1 and 1.1.0: the same; crc-sdk 1.1.0: 559 passed, 4 skipped, after porting the three tests that failed on the new behaviour (JRC flood twice, NEX calendar). Plain `uv run pytest -q`, with the real workspace README: 546 passed, 13 failed, all in `tests/test_upstream_tool.py` for the reason above |
| `just lint` | clean |
| `just validation`, `just site-validation`, `just site-flood`, `just site-hail`, `just site-explorer` | complete |
| `just validation-monitor` (HEAD requests only) | the four sources stale for the framework version; no publisher file changed |
| Repro scripts against the new versions (copies with the pins replaced, outputs in `tools/repro/out/*.1.0.1.txt`, `*.1.1.0.txt`) | 023, 024, 025, 026, 027, 030, 035, 036, 037, no-retry |
| F4 check, CRC part | Below |

## F4: the CRC routes on 1.1.0

There is no option to run only the CRC routes, so `flood_lab.checks.f4_catalogue` ran in full with
`--records`, `--figures` and `--work` in a scratch folder and a copy of the cached per-run arrays (13 min;
the copy's keys did not match this checkout, so all 162 runs were extracted again into the copy, reading
`data/cache/flood/f4/runs` only). Compared with `site/flood/tests/records/f4.json` of branch `flood/f4-150`
(all 150 runs, crc-sdk 1.0.0):

- All nine checks have identical outcomes and values: grid route read back equal (`Dataset.from_raster`),
  point route read back equal (`Dataset.from_quantiles`) and CH-23 pass with 0 differences, as before; the
  rainfall check fails as it did.
- Every number and table is identical apart from timings, `runs_extracted_this_time` (162 against 90) and
  the versions. The eight depth rasters have the same SHA-256 as before.
- One text differs: the grid route's skipped message now reads "260024 without a valid value and 0 with
  one" (same count, 260,024 of 640,000). The release identifier of that read differs only because the
  rasters were written under another path.

No committed record or figure was written.

## Findings

| Finding | Before | Now | How it was shown |
| --- | --- | --- | --- |
| CRC-024-JRC | reported upstream | fixed in 1.0.1 | Repro against the JRC server; offline assessment requires the warning |
| CRC-037-GHC | reported upstream | fixed in 1.0.1 | Repro against NOAA's bucket. The generic licence text and the missing dataset version, also in this finding, are unchanged |
| CRC-033-NEX | reported upstream | fixed in 1.0.1 | Offline assessment on constructed files only (NASA read not run) |
| CRC-034-NEX | reported upstream | fixed in 1.0.1 | Offline assessment on constructed files only |
| CRC-032-NEX | reported upstream | fixed in 1.1.0 | Offline assessment on constructed files only |
| CRC-023-JRC | reported upstream | fixed in 1.1.0 | Repro on the Fremont GloFAS tile: 9,828 of 10,603 flooded pixels returned, the 459 with one depth among them; 775 decreasing pixels left out with their own warning; 76,398 dry pixels in a note |
| CRC-025-OWN | reported upstream | unchanged, partly addressed | Repro: one decreasing pixel still fails the read; the error now names it |
| CRC-035-GHC | reported upstream | unchanged, partly addressed | Repro: 2 of 20 station-years with a value by default, 20 of 20 at 0.9. The knob is added and the default documented |
| CRC-026, 027, 030, 036, 038 | open | open, seen again | Repro scripts on the new versions |
| CRC-028, 029, 031, 022 and the older open ones | open | open, not re-run | Downloads too large for the disk (IBTrACS 333 MB, NEX about 250 MB a year, Texas JRC 5.5 GB) |

Each status change carries a `note` in `findings.toml` saying what was run. Where only the offline
assessment shows a fix, the note says so.

## Not done, and why

- **Staged re-runs** (`just release-check` step 3, `just validation-monitor-rerun`): the staging cache was
  emptied the same day, so even the quick profile would download the publishers' files again (well over
  the 300 MB allowed with 6.5 GB free). The published records still state crc-sdk 1.0.0 and the page says
  so; no source was accepted.
- **CRC-022-JRC** (Texas box, 5.5 GB) and the NEX and IBTrACS repro scripts (028, 029, 031, 032, 033, 034).
- The pins inside `tools/repro/*.py` stay at 1.0.0: `docs/upstream-updates.md` does not ask for a change,
  and the scripts are the evidence of the issues as filed. They were run against the new versions from
  copies with the pins replaced, and each output is kept next to the 1.0.0 one.
- The 16 flood records under `site/flood/tests/records/` state crc-sdk 1.0.0 and crc-framework 1.0.0. None
  was regenerated.

## For Yuri

- Move `../upstream/crc-sdk` and `../upstream/crc-framework-rs` to v1.1.0 and update `../README.md`.
- Whether to regenerate the flood records on 1.1.0 (all 16 name 1.0.0), and the full staged re-runs once
  there is disk.
- CRC-025-OWN and CRC-035-GHC: upstream changed the message and added a setting but kept the behaviour;
  `by design` or kept open.
- CRC-037-GHC is closed on its main point; the licence text and the dataset version could become a
  finding of their own.
