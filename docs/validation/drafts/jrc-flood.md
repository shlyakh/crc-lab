# Drafting note: JRC flood hazard maps, GloFAS and EFAS (`jrc-flood`)

Drafted by an agent on 2026-11-17 to Yuri's plan of the same day (Stage 1 of V8). Not reviewed.
Numbers are copied from the draft records `data/cache/validation/drafts/records/jrc-flood.json`
(run of 2026-11-17T09:47Z, crc-sdk 0.11.1, crc-framework 0.6.0) unless another file is named.

## What was compared

| Item | Number |
| --- | --- |
| Areas, GloFAS 2.1.2 | Texas box (resolution 7), Houston and Austin (9), Fremont, California (10) |
| Area, EFAS 3.1.1 | Rhine box of crc-docs' `flood_risk_by_province` notebook (7) |
| Requests outside the coverage | EFAS for the Texas box and for the Fremont box |
| Publisher files in the reference copy | 35 GloFAS depth tiles (5 tiles, 7 return periods) and 9 EFAS rasters, about 3.3 GB, each with its SHA-256 |
| Pixel values of crc-sdk's crops compared bit for bit | 1,447,885,064; differ: 0 |
| Curves refitted by the reference | 10,240,052 |
| Pixels fitted by the reference and not by crc-sdk | 2,957 (Texas 2,821, Houston 82, Fremont 5, Rhine 49, Austin 0) |
| Pixels fitted by crc-sdk and not by the reference | 0 |
| Curve parameters differing by more than 1e-6 m | 2 of 19,702,276 in the Texas box (largest 1.1e-6 m); 0 elsewhere |
| Checks | 44: 40 confirmed, 4 differ (`curves` in Texas, Houston, Fremont, Rhine) |
| Statement steps | 15: 11 confirmed, 4 differ (`nodata`, `knots`, `fit`, `fit-failure`) |

A second run from the caches (`build jrc-flood --draft` without `--live`) gave the same records
apart from `run_at`.

The four steps that differ are the four the `curves` check bears on. The cause sits in one of them,
`fit`: the pixels in question have depths at enough return periods, are not constant and do not
decrease; crc-framework's optimizer does not converge on them (finding CRC-013-FWK). The record
format books one check against all its steps, as noted for ERA5.

### How the two sides meet

- The reference downloads every publisher file whole and keeps its checksum; crc-sdk reads windows
  of the same files over the network (GDAL through DuckDB) into its cache. Shared: the publisher's
  bytes and zlib. Not shared: transport, TIFF parsing (a reader written in
  `reference/jrc_flood.py` with `struct` and `zlib`; tested against rasterio on constructed files
  and on a block cut from a real tile), window arithmetic, the fit (closed-form least squares
  against crc-framework's optimizer), the cells (h3-py `grid_disk` plus shapely overlap against
  crc-sdk's `h3shape_to_cells_experimental`), the identifiers.
- crc-sdk's crops are read back with the reference's own reader, not with rasterio.
- The reference uses numpy; unlike the ERA5 reference it is not free of it.

## Findings entered (at Yuri's request; `docs/validation/method.md` §7, exception)

All in `src/data_source_check/sources/crc_sdk/findings.toml`. How to reproduce, study and fix each
is in `local/upstream-review.md` and in the stage report.

| Id | Kind | Basis | One line |
| --- | --- | --- | --- |
| CRC-003-JRC | doc-code difference | reproduced (was code reading) | Output files carry no licence, attribution, retrieval time or checksum; shown on five outputs |
| CRC-013-FWK | defect | reproduced | The quantile fit does not converge on flat-then-rising depths; crc-sdk drops the pixel silently |
| CRC-014-JRC | observation | reproduced | 11.6 to 25.8% of flooded pixels get no curve and no message |
| CRC-015-JRC | observation | reproduced | The curve can be positive where the map is dry, negative where wet, metres from the published depth |
| CRC-016-JRC | observation | reproduced with a cache; stream mode read | The out-of-coverage error does not name the coverage |
| CRC-017-JRC | observation | reproduced; reuse without asking again is read | The release is one README line; no publisher checksum |
| CRC-018-JRC | doc-code difference | reproduced | crc-sdk says CC BY 4.0; JRC's README says Open Database License v1.0, its copyright.txt CC BY 4.0 |
| CRC-019-JRC | observation | reproduced for GloFAS | JRC's spurious-depth and permanent-water masks are not read |
| CRC-020-JRC | observation | reproduced | With a cache, a pixel's `source_id` depends on the box asked for |
| CRC-021-JRC | defect | reproduced | A cache made under a relative path fails offline from another working folder |
| CRC-022-JRC | observation | reproduced (one run) | Texas box: 1,604 s, 5,804 MB, written only at the end |

Candidates of the plan that the data did not bear out: duplicated rows at tile seams (none in
10,703,386 rows); return periods in the code differing from the publisher's directory (equal).
Horizon 0 with pathway `historical` is documented for time-invariant data and was not entered.

## Steps and rules confirmed on constructed files only, or not run

- A stream run (no cache), a subset of return periods, other policies, `for_assets`: not run.
- `manifest`: that a later run does not ask the publisher again is read in the code.
- `coverage`: the stream-mode error is read in the code.
- `cells` and `source-id`: a seeded sample of 2,000 pixels per area, not every pixel.
- `values`: 20,000 pixels per area (all 7,864 in Fremont), at the published return periods and at
  25 and 250 years.
- Two tiles meeting at a seam, a box that only touches a tile, a pixel with a non-finite value:
  constructed files only (the Texas box does cross real seams).
- The EFAS spurious-depth mask and both permanent-water layers were not read.

## What I was unsure of

- **The tolerance.** 1e-6 m absolute was fixed before the final run. Two parameters in the Texas
  box exceed it by a tenth. An iterative optimizer's error grows with the size of the numbers
  (depths there reach 108 m); a relative tolerance may be the better rule. I did not change it
  after seeing the result.
- **Whether the non-converging pixels belong under `fit` or `fit-failure`.** The statement's
  `fit-failure` step lists equal and decreasing depths as the causes of a failed fit; the optimizer
  giving up is a third cause the statement did not have. I left the statement as written so that
  the check differs, and entered the finding.
- **What a constant 1 m is.** Every pixel with equal depths at all its return periods has exactly
  1 m (698,317 in the Texas box). The README's categorized map has a class "<1 m"; whether the
  depth files use 1 m as a floor is not stated there. Not established.
- **Process memory.** The peak recorded for the smaller areas is that of the whole process, which
  had already read the Texas tiles; only the Texas figure is crc-sdk's own. An earlier separate run
  of Houston peaked at 656 MB (session log, not in the records).
- **Findings as public text.** They are on the page once `just validation` runs; the method's rule
  was that a draft adds none. The exception is written into `method.md` §7 for your review.

## What the sample leaves out

Other regions of GloFAS (5 of 271 tiles were read), boxes across the 180 degree meridian,
EFAS outside the Rhine box, resolutions other than 7, 9 and 10, the low-level API
(`canonicalize_jrc_flood`), `HazardDataset.jrc`, and everything downstream of the file
(`for_assets`, evaluation with warnings on extrapolation).

## Bytes and caches

- Reference copy: `data/cache/validation/jrc-flood/original/` (3.3 GB), one `.json` beside each file
  with address, SHA-256, size, retrieval time and the publisher's Last-Modified.
- crc-sdk's stored answers: `data/cache/validation/jrc-flood/framework/` (887 MB): per area its
  cache, `hazard.parquet` and `run.json`.
- Probes: `data/cache/validation/jrc-flood/probes/probes.json`, written by
  `tools/probes/jrc_flood_probes.py`.
- Live runs made on 2026-11-17: trial runs per area while the assessment was written (superseded),
  one statewide run that failed because the script came from standard input, one complete run whose
  reference pass stopped on a network timeout after crc-sdk's Texas run had finished, and the final
  run, which reused that Texas answer and ran the other areas again from empty caches.
