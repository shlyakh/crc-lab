# Event-loss tables in other frameworks: CLIMADA, Oasis LMF, OpenQuake

Research note, 2026-11-27 (F6, before `crc_event_loss` is built). It compares the design in
`docs/flood/event-loss-extension.md` with three open-source frameworks and with published
catastrophe-modelling practice. Source code was read at the versions below. The central claims
were checked against the code by the main session (marked ✓); the rest come from the research
agents' reading and are cited, but were not checked line by line.

| Framework | Version read | Licence |
|---|---|---|
| CLIMADA (`climada_python`, ETH Zürich) | 6.2.0, commit cc0b21516a15 (2026-11-06) | GPL-3.0 ✓ (conventions only, no code) |
| Oasis LMF (`OasisLMF` pytools, `ktools` docs) | OasisLMF commit 66d4d55e (2026-11-26); ktools 4a7506c7 (2026-09-28) | BSD-3-Clause ✓ |
| OpenQuake engine (GEM), event-based risk | 3.27.0, commit 80becc3f; LTS manual 3.23.5 | AGPL-3.0 |

Industry and actuarial sources: Homer & Li, CAS E-Forum, Spring 2017 ("most practical paper",
casact.org); SOA study note GI 301 (May 2025, catastrophe model output); Tasche, "Capital
allocation to business units and sub-portfolios: the Euler principle" (arXiv 0708.2542).

## 1. Side by side

| Concern | CLIMADA | Oasis LMF | OpenQuake | Our design |
|---|---|---|---|---|
| Timeline | Annual rate per event (`Hazard.frequency`); no years. Years only through Poisson sampling (`util/yearsets.py`) | Events mapped to periods (occurrence file); **optional period weights** (`periods.bin`, default 1/P) | Implicit rate 1/eff_time per event; eff_time = investigation_time × SES per path | `EventSet`: synthetic years with `YearWeights`, or annual rates |
| Event-loss table | `Impact.imp_mat`, sparse events × exposures, kept only with `save_mat=True`; HDF5 | ORD SELT/MELT/QELT: EventId, SummaryId, SampleId, Loss | `risk_by_event` (event × agg_id) | `EventLossTable`, event × component, Parquet |
| Year sum vs largest event | Sum only (`impact_per_year`, yearsets). `calc_freq_curve` is per event ✓ | AEP = sum, OEP = max, one pass ✓ (`lec/manager.py:175-191`) | `aep` sum, `oep` max, `ep` per event | `AGGREGATE`, `OCCURRENCE` |
| Return-period loss | Sort events, cumulative frequency, RP = 1/that ✓; log-log interpolation | RP = P/k unweighted; **1/cumulative weight** weighted ✓; linear interpolation between ranks; RP > P dropped | RP = eff_time/k ✓; log-RP interpolation; **NaN beyond eff_time** ✓ ("refuse the temptation to extrapolate") | CRC `Distribution.quantile` (lower quantile, no interpolation) |
| Tail mean | none | TCE (running mean of ranked losses), per OEP and AEP | none | CRC CVaR, boundary year taken in part |
| Average annual loss | `aai_agg` = Σ rate × loss; per exposure `eai_exp`, additive | ALT: period-weighted mean and std (N−1) | `aggrisk` per agg_id | CRC `Distribution.mean` |
| Attribution of tail figures | none (mean only, additive) | none (separate curves per summary id) | none (separate curves per tag) | Shares of VaR and CVaR (`RiskAttribution`) |
| Dependence | Only through shared events | Shared events, plus correlated damage sampling (`group_id`, ρ) | Shared events, plus `asset_correlation` 0 or 1 for damage sampling | Only through shared events; brackets for comparison |
| Full-dependence / independence brackets | none | none | none | `brackets` |
| Damage variability within an event | none (mean curve); `unsequa` varies the curve per run | sampled from damage bins | sampled with a coefficient of variation | none (left out, §4 of the note) |
| Intensity above the curve | clamped to the last value ✓ (`np.interp`) | hazard is pre-binned | **clipped** to the last level ✓ | **failure** (CRC refuses; BD-4) |
| Intensity below the curve / missing | clamped; missing = 0 | event without footprint skipped | below the first level: zero loss ✓ | `MissingIntensity.NO_LOSS` counted, or `ERROR` |
| Rate-based annual total | Poisson sampling, then every year rescaled to match the rate-based mean (`correction_fac`, on by default) ✓ | none | n/a | left out; occurrence exact for Poisson |

## 2. What this means for the design

**Confirmed: no change.**

1. *Sum in the event, then in the year, then rank.* All three do it this way, and
   OpenQuake's documentation gives the reason: losses at a return period do not add.
2. *Year weights* (open question 1 of the note). Oasis has a weighted route, which is a precedent.
   It gives the return period of the k-th largest loss as 1 over the cumulative weight. So
   `YearWeights` is not an oddity, and asking upstream for weights in #27's summary has an
   established model to point to.
3. *Two annual measures.* Year sum and largest event match AEP and OEP everywhere. I propose to
   keep the enum names and print AEP and OEP beside them in documentation and output, because
   these are the industry's names.
4. *Dependence only through shared events.* This is CLIMADA's model, and the base of the other
   two. Oasis and OpenQuake add correlation only to damage sampling within an event, which we
   leave out.
5. *Attribution.* None of the three allocates a tail figure to components. The literature
   standard is the Euler allocation: a component's share of CVaR is its mean loss in the tail
   years (Tasche). The note's CVaR shares are exactly that, and the VaR shares are the components
   in the VaR year. The note should name Euler and cite Tasche.
6. *No damage sampling* matches CLIMADA. It is left out, as stated.

**New in our design: no precedent found.** The brackets (full dependence and independence of the
same marginals) appear in none of the three, nor in any open-source package the agents found
(catagg, gemact). They are our own diagnostic and should be presented as such. This also supports
CH-28: there is no established "the event loss lies between the brackets" test to follow.

**Differences that needed a decision.** All six accepted as recommended (Yuri, 2026-11-27); built in `crc_event_loss`.

| # | Question | Others | Options | My recommendation |
|---|---|---|---|---|
| P-1 | Return-period loss: step or interpolated? | Oasis interpolates linearly between ranks; OpenQuake interpolates in log return period; CLIMADA log-log | (a) CRC's lower quantile only; (b) also an interpolated figure | (a). The rule "every figure is CRC's" holds, and the note states the convention. With 150 weighted years an interpolated 1-in-100 would differ only between neighbouring years. Reported, not hidden |
| P-2 | Beyond the catalogue | Oasis drops return periods beyond P; OpenQuake gives NaN beyond eff_time | Refuse a level whose tail mass is smaller than the smallest year's mass, or allow it | Refuse, with a diagnostic, as OpenQuake does. With stratified weights this sets the largest return period that can be reported |
| P-3 | Intensity above the curve's last point | CLIMADA and OpenQuake clip to the last value; nobody fails | (a) failure (now: CRC refuses, BD-4, C-6); (b) a stated `CLAMP` policy | Keep failure as the default, since it is the strict choice. Add `FailurePolicy`-style reporting with counts, and consider an explicit clamp as a sensitivity. This sits oddly with the others; your call |
| P-4 | Annual-rate route, year sums | CLIMADA samples Poisson years and rescales every year silently | Leave out (now); or sample with a seed and report any correction | Leave out. If added later, report the correction factor and never apply it silently |
| P-5 | Column names in the table | ORD (Oasis): EventId, SummaryId, SampleId, Loss; PeriodNo, PeriodWeight | own names; or ORD names in an export | Keep our names inside the package. Add an ORD-style export of the year and event tables (SPLT/SELT) later, so that results can be read by Oasis tools |
| P-6 | Cross-check | — | Run Oasis's weighted EPT code on the same year-loss table as an independent check of AEP, OEP and TVaR | Yes, as a test outside the package (BSD-3, so it can be a test dependency). Built: `tests/event_loss/test_oasis_crosscheck.py`, `just event-loss-crosscheck` (oasislmf 2.5.10). It found two more differences: the boundary rank (question 7 of the design note) and Oasis's unweighted TVaR (question 8) |

## 3. Sources

Code, read at the commits above (scratchpad clones, not kept in this repository):

- CLIMADA: `climada/engine/impact.py` (`calc_freq_curve` 767-805, `impact_per_year` 395-434),
  `climada/engine/impact_calc.py` (604-656), `climada/util/yearsets.py` (`impact_yearset`,
  `correction_fac`), `climada/entity/impact_funcs/base.py:113-130` (`calc_mdr`, `np.interp`).
- Oasis LMF: `oasislmf/pytools/lec/manager.py:175-191` (sum and max per period),
  `oasislmf/pytools/lec/aggreports/write_tables.py` (`get_loss` 9-41, `write_ept_weighted`
  488-640), `oasislmf/pytools/common/input_files.py:637-673` (`read_periods`),
  `oasislmf/pytools/aal/manager.py` (weighted AAL); ktools `docs/md/ORDOutputComponents.md`.
- OpenQuake: `openquake/risklib/scientific.py` (`fix_losses` 1519, `losses_by_period` 1547,
  clipping 280-291, `MultiEventRNG` 826-875), `openquake/calculators/post_risk.py`
  (`get_loss_builder` 166-190, `compute_aggrisk` 327-408); manual
  docs.openquake.org/oq-engine/LTS/manual/user-guide/outputs/event-based-risk-outputs.html.
- Homer, D. and Li, M. (2017), CAS E-Forum Spring 2017,
  casact.org/sites/default/files/2021-02/2017_most-practical-paper_homer-li.pdf.
- SOA GI 301 study note (2025), soa.org/globalassets/assets/files/edu/2025/fall/study-note/2025-11-gi-301-study-note-catastrophe-output.pdf.
- Tasche, D. (2007), arXiv:0708.2542.

Not verified: the Poisson OEP formula 1 − exp(−Σ rates) was not found printed in the sources read
(SOA gives the Bernoulli form 1 − Π(1 − p)); no public vendor rule for ties or the boundary year
was found.
