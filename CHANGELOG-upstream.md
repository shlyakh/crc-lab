# Upstream changes watched (requirement N8)

| Date | Package | Version | What changed | Effect on crc-lab |
| --- | --- | --- | --- | --- |
| 2026-11-23 | crc-sdk | 0.11.2 (released 2026-11-13) | Our two fixes and nothing else: [#43](https://github.com/RiskThinking/crc-sdk/pull/43) IBTrACS subset `active` requests NOAA's file `ACTIVE`; [#42](https://github.com/RiskThinking/crc-sdk/pull/42) NEX temperature recipes accept the one-character unit `K`. Changes `crc_sdk/workflows/ibtracs.py` and `nex.py` only | Pin moved. All four assessments re-run and accepted: IBTrACS 78 of 78 checks confirmed (`active` now assessed), NEX 23 of 24 (temperature now checked: 8,632 cell values, 0 differ), GHCNh and JRC flood unchanged. CRC-010-IBT and CRC-001-NEX fixed in 0.11.2. The detour through the fork is removed. Report: `docs/reports/u2-crc-sdk-0.11.2.md` |
| 2026-11-12 | crc-sdk | pull request [#43](https://github.com/RiskThinking/crc-sdk/pull/43), merged 2026-11-13 | Ours: IBTrACS subset `active` requests NOAA's file name `ACTIVE` (finding CRC-010-IBT) | Released in 0.11.2, see above |
| 2026-11-12 | crc-sdk | pull request [#42](https://github.com/RiskThinking/crc-sdk/pull/42), merged 2026-11-13 | Ours: NEX-GDDP-CMIP6 temperature recipes accept the one-character unit `K` (finding CRC-001-NEX); mentions NASA's v2.0 files (CRC-012-NEX) | Released in 0.11.2, see above |
| 2026-11-04 | crc-framework | 0.6.0 | Type-7 interpolated empirical law ("expectations can shift slightly"); out_of_domain error policy; GIL released; skew-normal CDF aligned with SciPy | Baseline pin. Re-run conformance tests on any later release |
| 2026-11-04 | crc-sdk | 0.11.1 | Python >=3.11 | Baseline pin |
| 2026-10-26 | crc-framework | 0.5.0 | Impact function schema v1.0.0 | Impact definitions target this schema |
