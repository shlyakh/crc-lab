# Data of the explorer and hail pages: frozen build

The files here were built with crc-sdk 0.11.2 and crc-framework 0.6.0 on 2026-11-24 (the versions are in
`manifest.json` and in each file's own header). They are the build that was public on that day, taken from
the pages workflow run of commit `a18dd3f`.

The repository is pinned to crc-sdk 1.0.0 since then. The explorer (`src/crc_data_explorer/`) and the hail
project (`src/crc_lab/`) are not yet ported to 1.0, so these files are committed and not rebuilt: `just data`,
`just storm-events`, `just curves` and `just sources` stop with a message. When the two projects are ported,
the files are generated again and the pages workflow gets its build steps back.

The validation project (`site/validation/`) is on crc-sdk 1.0.0 and is not part of this freeze.
