# Limited Flood map: export through ESRI's File Geodatabase API

The city's Limited Flood map (1.77 in/hr, current sea levels; NYC Open Data `9i7c-xyvv`) is stored in
ESRI's compressed geodatabase format, which GDAL's open driver cannot read
(`docs/flood/reports/F0-derisk.md`, section 5). This folder reads it through ESRI's own library.

**State on 2026-11-25: built, not yet run.** The program compiles against the library. Running it was
refused by the session's permission system, so no export exists and nothing about the Limited map's
content is known. A person runs the command below, or allows it.

## Run

```sh
cd ~/work/crc/crc-lab
uv run python tools/flood/limited_flood_map/export.py
```

It builds `dump_gdb.cpp`, runs it on the uncompressed Moderate map and compares the result with GDAL's
open driver (row count, codes, area per code and symmetric difference within 1e-6), and only if that
agrees writes `data/cache/flood/nyc-stormwater-flood-maps/converted/limited-current.gpkg` (layer
`limited_current`, field `Flooding_Category`, EPSG:2263) with `limited-current.json` beside it.
`--proof-only` stops after the comparison.

## The library

ESRI File Geodatabase API 1.5.5, macOS arm64:
<https://raw.githubusercontent.com/Esri/file-geodatabase-api/master/FileGDB_API_1.5.5/FileGDB_API_MacOS-ARM64-clang.zip>,
46,479,910 bytes, sha256 `8bea40a60c0427b4988eee28e4220fc2b3c4243c81245b77a4286dbbac18c33d` as fetched
on 2026-11-25 (ESRI publishes no checksum). Unpack it to
`data/cache/flood/f2/esri-filegdb/FileGDB_API_MacOS-ARM64-clang/`. It is never committed.

Terms read before use: the repository's `License.txt` and the archive's `license/` folder give the
Apache License 2.0; `license/userestrictions.txt` covers ESRI's sample code only (free use and
redistribution with its notice). No passage asks for an ArcGIS licence or limits what is done with data
read through the library. ESRI's 1.4 notes list "Add support for Compressed Data File. (Read Only)".
One bundled part (`libfgdbunixrtl`) is LGPL 2.1. The texts are kept in `data/cache/flood/f2/esri-terms/`.
