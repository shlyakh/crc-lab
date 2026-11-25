# Demo plan: Flood Loss & Trigger Lab

Draft, 2026-11-25. Author: Yuri Shlyakhter, with Claude. Companion to `docs/flood/requirements.md`
(version 3) and `docs/flood/plan.md` (version 2). It does not change either file: what it asks of them is
entered as proposals CH-5 to CH-10 in `docs/flood/changes.md`, to be assessed and decided under the usual
procedure. Until a proposal is accepted, the requirements and the plan stand as written.

This file says what is shown, to whom, on which date, and what the build must therefore finish first.

## 1. Two demos

| | Demo 1 | Demo 2 |
| --- | --- | --- |
| Date | Tuesday 2026-12-01 | Friday 2026-12-04 |
| Audience | The CRC maintainers, in their weekly meeting; resilience investment advisors as a possible follow-on | A parametric flood insurance company |
| Form | 15 minutes, presented live on a call, with the deployed page and one live re-run | A link, read cold with no presenter |
| Subject | Verification of a climate-risk result built on CRC 1.0.0, with a substation investment case as the result | Geospatial machine learning for parametric flood insurance |
| Must leave the audience with | "This is checked, I can see how far, and CRC carried it"; and a version they could show a resilience client | "This person can build and test a neural flood model and tie it to a payout" |

The rule of requirements §1 holds for both: no company is named as an audience in code, reports or pages.

## 2. Decisions taken on 2026-11-25

| # | Decision |
| --- | --- |
| DP1 | Demo 1 is for the CRC maintainers first. The ask is that they take this to resilience advisors together with Yuri or introduce him; the supporting ask is review of the extensions for upstream |
| DP2 | What Demo 1 is about is verification: how well a climate-risk system can be checked. The flood study is the worked example |
| DP3 | By Monday night the build finishes one complete, checked chain to the investment case. Triggers and basis risk (F8) are deferred and come back only if time allows |
| DP4 | The storm catalogue runs in full (150 storms) unattended over the weekend, starting when the drainage calibration is frozen. Monday's figures use the runs finished by then, at least 60; every run's full peak-depth grid and storm descriptors are kept as training data for Demo 2 |
| DP5 | Validation (F5) is reduced for Monday to the surveyed marks and the sensors. "Who saw the flood" moves after Demo 1 |
| DP6 | A thin prototype of composable assets: one substation as three components. Built after F7 passes, time-boxed to 5 hours. A proposal note is written whether or not the prototype is built |
| DP7 | Replacement values stay placeholder ranges (FD4). The benefit-cost result is shown with a break-even view, so the conclusion can be read without trusting the placeholder. Valuation formulas are not worked on now |
| DP8 | Interaction in Demo 1 is precomputed toggles on the page plus one live re-run. Skills and shared notebooks come later |
| DP9 | Findings about CRC: the meeting shows the gaps as what was built to close them, and one finding on screen. The reviewed issues go to the maintainers by Friday 2026-11-27; the extensions possibly before the meeting. Nothing goes out before Yuri has reviewed it (the repository's standing rule) |
| DP10 | Demo 2's centrepiece is the solver emulator (F9), with the trigger panel for 2023-09-29 and label fusion around it |
| DP11 | Yuri reviews once a day and answers questions as they arise, from his phone through Claude Code's Remote Control when away. A stage whose checks pass may proceed to the next without waiting; a failing check, a differing fact or a number that would have to be invented still stops everything (plan, "A stage", step 5) |
| DP12 | Demo 1 runs 15 minutes and opens with the question, not the method |
| DP13 | The thing to protect is the investment case for one substation (F7). On Sunday night Yuri decides whether to switch to the fallback of §6 |

## 3. Demo 1: running order

Fifteen minutes. Each item names the exhibit it needs; §4 lists the exhibits.

| Minutes | Item | Exhibit | What is said |
| --- | --- | --- | --- |
| 0–4 | **The question and the answer.** Should the lead substation be raised by 0.9 m? | E1, E2 | Loss with and without the measure; the range of replacement values at which it pays |
| 4–9 | **How do you know.** | E3, E4, E5 | The source table and its two levels of check; one stage card with its pass rule; one case where an independent recomputation caught something |
| 9–12 | **What CRC did and what was added.** | E6, E7, E8 | The chain with CRC's steps marked; the event-loss extension; the component prototype or its note. If time is short, the live re-run replaces part of this |
| 12–13 | **Live re-run.** A raise height named by the audience | E9 | One command; the card and its check update |
| 13–15 | **Asks and what comes next.** | none | DP1's two asks; Demo 2 on 4 December; skills and notebooks later |

If the slot shrinks, drop the live re-run first, then E8.

## 4. Exhibits Demo 1 needs

| ID | Exhibit | Comes from | State on Monday night |
| --- | --- | --- | --- |
| E1 | Lead-substation card: depth frequency, damage-curve envelope, loss by return period, before and after the measure | F6, F7, reduced F11 | Required |
| E2 | Break-even chart: benefit-cost ratio against replacement value, with the placeholder range shaded and the break-even value marked, at 7% and 3.1% | F7 (FM7, proposed) | Required |
| E3 | Source table: one row per source, one cell per fact, "facts confirmed" and "values recomputed by an independent reader" named apart | Test gallery, F0 and F2 | Required; exists in part |
| E4 | One stage card with figure, numbers, threshold and badge. Use the calibration card (F3) or the marks comparison (F5) | Test gallery | Required |
| E5 | One finding, before and after, in neutral wording | F2, F5 or F6, whichever yields the clearest reviewed case | Required; chosen by Yuri at the Sunday review |
| E6 | The flow diagram of requirements §3 with the steps CRC performs marked and the steps the lab adds marked | Requirements, redrawn for the page | Required |
| E7 | `crc_event_loss`: its design note, its interface, and the portfolio loss curve it produces | F6 (FR9 to FR12) | Required unless the §6 fallback is taken |
| E8 | Component prototype: three components, one measure applied to one of them, and the recombination test | FA1 to FA5, proposed | Optional; the note alone if not built |
| E9 | Live re-run path for one substation and one raise height | FP10, proposed | Optional; a recorded run stands in |
| E10 | A three-minute recorded walk-through of the page | `tools/record-demo.mjs` pattern | Required, recorded Monday |

**Choosing the lead substation.** After F1 and the first replay: the substation site, not rail, with the
greatest modelled depth in the Ida replay among those near mapped flooding. Recorded with the numbers that
chose it. If no site is wet in any catalogue storm, stop and report: the investment case would have
nothing to show, and the study area's buildings become the lead asset.

## 5. What the build finishes by Monday night

Hours are the plan's estimates; changes against plan version 2 are in the last column.

| Stage | By Monday | Change proposed |
| --- | --- | --- |
| F1 Terrain and assets | Yes | None |
| F2 Sources with second readers | Yes | None |
| F3 Solver, calibration, two replays | Yes | None |
| F4 Storm catalogue | Running; at least 60 storms finished | Full 150 run unattended from the calibration freeze; outputs kept whole (CH-5) |
| F5 Validation | Marks and sensors only | "Who saw the flood" after Demo 1 (CH-6) |
| F6 Curves, event-loss extension, risk | Yes | None; figures state how many storms they rest on |
| F7 Measures, outage cost, benefit-cost | Yes | Break-even view added, about 2 hours (CH-7) |
| Component prototype | If F7 has passed by Sunday evening | New, 5 hours, time-boxed (CH-8) |
| F8 Triggers and basis risk | No | Deferred to Demo 2; the 2023-09-29 panel may be pulled forward if the chain finishes early (CH-9) |
| F11 The page | Reduced | Lead-substation card, loss curves, break-even chart, flow diagram, test gallery, live re-run path; no storm player (CH-10) |

Rules for the weekend runs (plan, "Who does what", step 7): background commands under `caffeinate -i`,
resumable, one record per run. If the solver slows the stages being built, it runs overnight only. Every
figure built on a partial catalogue prints the number of storms it used and is rebuilt when the catalogue
completes.

## 6. Fallback, decided Sunday night

Checked at the Sunday review, in this order.

| If this has not passed | Then | Demo 1 loses |
| --- | --- | --- |
| F6 | Loss for the lead substation from the six design storms through CRC's own curves, labelled as the comparison method; go straight to F7 | E7 as a working exhibit, and dependence between assets |
| F7 | Nothing else is started until it passes; the page is the gallery and report figures | Polish only |
| Component prototype | The note stands alone | E8 as a working exhibit |
| Live re-run | The recorded run (E10) | Nothing essential |

The catalogue keeps running in every case; Demo 2 needs it.

## 7. Schedule

| Day | Build | Yuri |
| --- | --- | --- |
| Wed 25 Nov | F1; F2 beside it | Remote Control and phone notifications set up |
| Thu 26 Nov | F1 and F2 finish; F3 build | Daily review, short; questions by phone |
| Fri 27 Nov | F3 calibration frozen; catalogue starts; F5 (marks and sensors) | Review of the calibration; reviewed issues sent to the CRC maintainers (DP9) |
| Sat 28 Nov | F6 | Review of the interface and design note of `crc_event_loss` |
| Sun 29 Nov | F6 passes; F7; component prototype if F7 has passed | Review; lead finding chosen (E5); fallback decision (§6) |
| Mon 30 Nov | Reduced page; live re-run path; recorded walk-through | Rehearsal against the clock, twice; extensions sent ahead if ready |
| Tue 1 Dec | none | Demo 1 |
| Wed 2 – Thu 3 Dec | F9 emulator on the full catalogue; F8 trigger panel and label fusion; Demo 2 page | Daily review |
| Fri 4 Dec | Smoke test, captions, limits | Demo 2 link sent |

## 8. Demo 2: what the link must contain

Read cold, so the page carries its own explanation: each section has one figure and two sentences.

1. **The storm.** Modelled depth for 2023-09-29 against the sensors, and for Ida against the surveyed
   marks, with the errors printed.
2. **The emulator.** Solver, emulator and difference for held-out storms; scores on held-out storms and on
   a held-out block; a calibration plot; hardware and training time (FE1 to FE6). The statement that it is
   trained and tested in one neighbourhood and is not claimed to transfer.
3. **Pricing a trigger.** The indices of FT1 over thousands of emulated years: how often each would pay,
   with intervals; the same from the solver runs alone, to show what the emulator changes.
4. **One real storm.** Would each index have paid on 2023-09-29 (FT4)? The pilot described only as its
   sponsors and the press reported it.
5. **Noisy labels.** Label fusion and precision-recall scoring (FT5 to FT8) if F8 goes smoothly; otherwise
   the design and what it would need, stated as not built.
6. **How it was checked.** A link to the test gallery.

Not sent without item 2. A version lacking the emulator shows flood modelling to specialists in flood
modelling and none of what the link is for.

## 9. After both demos

In this order unless Yuri says otherwise: the rest of F5 and F8; F10 engine agreement; a
question-in-one-sentence skill on the pattern of crc-docs' five skills; a shared notebook; valuation
formulas for replacement value; composable assets as a full extension beside `crc_event_loss`.

## 10. Open items

1. The flood page's address is public once deployed, even though the landing page does not link to it
   before F11 (D14). Yuri has not objected; confirm before Monday's deploy.
2. The length of the slot on Tuesday is taken as 15 minutes; confirm with the meeting's host.
3. Component value shares and per-component curves have no source found. They carry the placeholder tag
   **[P]** on every figure of E8.
4. Whether the extensions are sent ahead of the meeting depends on Saturday's and Sunday's reviews.
