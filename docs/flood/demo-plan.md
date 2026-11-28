# Demo plan: Flood Loss & Trigger Lab

Version 2, 2026-11-25 (the draft of the same day is on branch `flood/demo-plan`). Author: Yuri
Shlyakhter, with Claude. Companion to `docs/flood/requirements.md` (version 6) and `docs/flood/plan.md`
(version 3). What it asks of them was entered as proposals CH-8 to CH-13 in `docs/flood/changes.md`
(numbered CH-5 to CH-10 in the draft, which collided with changes accepted at the F1 and F2 stops),
assessed against the build as it stood after F2, and accepted by Yuri on 2026-11-25. The requirements
carry them in their section 15 and the plan in its section "Until 4 December". Section 11 here is the
review that went with the acceptance. What could make a demo show something other than planned, and what to
show instead if the substations turn out not to be in danger, is in `docs/flood/demo-concerns.md`; the
passages a person has to read are in `docs/flood/reading-list.md`.

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
| DP4 | The storm catalogue runs in full (150 storms) unattended over the weekend, starting when the calibrated constant loss rate (the drainage allowance) is frozen. Monday's figures use the runs finished by then, at least 60 (updated 2026-11-27, Yuri: Demo 1 uses all 150 runs with rain on the whole square, CH-26, not the 60-run copy tagged `flood-f4-demo1-60runs`); every run's full grid of maximum inundation depth and storm descriptors are kept as training data for Demo 2 |
| DP5 | Validation (F5) is reduced for Monday to the surveyed marks and the sensors. "Who saw the flood" moves after Demo 1 |
| DP6 | A thin prototype of composable assets: one substation as three components. Built after F7 passes, time-boxed to 5 hours. A proposal note is written whether or not the prototype is built |
| DP7 | Replacement values stay placeholder ranges (FD4). The benefit-cost result is shown with a break-even view, so the conclusion can be read without trusting the placeholder. Valuation formulas are not worked on now |
| DP8 | Interaction in Demo 1 is precomputed toggles on the page plus one live re-run. Skills and shared notebooks come later |
| DP9 | Findings about CRC: the meeting shows the gaps as what was built to close them, and one finding on screen. The second round of reviewed issues is raised with Yuri on or after Monday 2026-11-30, as he first asked, each sent on his word (answer of 2026-11-25; the draft said Friday 27 November); the extensions possibly before the meeting. Nothing goes out before Yuri has reviewed it (the repository's standing rule) |
| DP10 | Demo 2's centrepiece is the solver emulator (F9), with the trigger panel for 2023-09-29 and label fusion around it |
| DP11 | Yuri reviews once a day and answers questions as they arise, from his phone through Claude Code's Remote Control when away. A stage whose checks pass may proceed to the next without waiting; a failing check, a differing fact or a number that would have to be invented still stops everything (plan, "A stage", step 5). Each stage still runs in a session of its own, on its own branch, and ends with its report; Yuri starts the session. The next stage's branch is made from the finished stage's branch; merges into `main` (D14) are still made on his go, at the daily review (answer of 2026-11-25) |
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
| E2 | Break-even chart: benefit-cost ratio against replacement value, with the placeholder range shaded and the break-even value marked, at 7% and at 3.1% labelled "not a FEMA rate" (requirements §14) | F7 (FM7) | Required |
| E3 | Source table: one row per source, one cell per fact, "facts confirmed" and "values recomputed by an independent reader" named apart | Test gallery, F0 and F2 | Required; exists since F2 (32 sources, four with values recomputed) |
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
| F4 Storm catalogue | All 150 storms, rain on the whole square (CH-26; Yuri, 2026-11-27) | Full 150 run unattended from the calibration freeze; outputs kept whole (CH-8) |
| F5 Validation | Marks and sensors only | "Who saw the flood" after Demo 1 (CH-9) |
| F6 Curves, event-loss extension, risk | Yes | None; figures state how many storms they rest on |
| F7 Measures, outage cost, benefit-cost | Yes | Break-even view added, about 2 hours (CH-10) |
| Component prototype | If F7 has passed by Sunday evening | New, 5 hours, time-boxed (CH-11) |
| F8 Triggers and basis risk | No | Deferred to Demo 2; the 2023-09-29 panel may be pulled forward if the chain finishes early (CH-12) |
| F11 The page | Reduced | Lead-substation card, loss curves, break-even chart, flow diagram, test gallery, live re-run path; no storm player (CH-13) |

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
| Wed 25 Nov | F1 and F2 built, reviewed and merged (done) | Remote Control and phone notifications set up |
| Thu 26 Nov | F3 build and first replay; beside it the parts of F4 that do not wait for the calibration: RainyDay's environment, the rainfall record, the transposition domain | Daily review, short; questions by phone; the FEMA and Williams passages (§11) |
| Fri 27 Nov | F3 calibration frozen; catalogue starts; F5 (marks and sensors) | Review of the calibration |
| Sat 28 Nov | F6 | Review of the interface and design note of `crc_event_loss` |
| Sun 29 Nov | F6 passes; F7; component prototype if F7 has passed | Review; lead finding chosen (E5); fallback decision (§6) |
| Mon 30 Nov | Reduced page; live re-run path; recorded walk-through | Rehearsal against the clock, twice; extensions sent ahead if ready; the second round of CRC issues raised (DP9) |
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
   before F11 (D14). **Answered 2026-11-25: public is fine.** The test gallery has been in the published
   folder since F0.
2. The length of the slot on Tuesday is taken as 15 minutes; confirm with the meeting's host.
3. Component value shares and per-component curves have no source found. They carry the placeholder tag
   **[P]** on every figure of E8.
4. Whether the extensions are sent ahead of the meeting depends on Saturday's and Sunday's reviews.

## 11. Review against the build, 2026-11-25

Made by the coordinating model after F2 was merged, at Yuri's request, before the proposals were
accepted. The draft was written before F1 and F2 finished; this is what they change.

**Ahead of the draft's schedule.** F1 and F2 are merged a day early. The Limited Flood map is read, so
F3 calibrates on two maps. The source table (E3) exists.

**What the build has found that the demo must reckon with.**

1. **The substation case is one complex, and it may come out nearly dry.** The four named Con Edison
   substations are adjoining blocks at Vinegar Hill; with the unnamed Williamsburg yard that is five
   assets at two places. In the city's own maps no flooded cell lies inside any substation outline in
   any of the four scenarios. Mapped flooding comes within 3 m of one Farragut outline in all four, and
   within 25 m of the unnamed yard on the Moderate map; every other outline is 66 m or more away. The
   city masked large non-residential lots out of its maps, so "nothing inside" is not evidence that the
   yards stay dry. The first Ida replay in F3 is the test. The draft's rule stands: if no site is wet in
   any catalogue storm, stop and report, and buildings become the lead asset. Farragut (345 kV, ground
   at 3.2 m on the bulkhead, the lowest of the complex) is the likely lead.
2. **The honest answer to "should it be raised by 0.9 m" may be no, for rain.** Farragut's larger
   exposure is the river, and coastal surge is out of scope. A demo about verification is not weakened
   by a result that says the measure does not pay against rain alone, provided minute 0 to 4 says so
   plainly. Worth deciding the wording before the rehearsal, not during it.
3. **The benefit-cost ratio rests on three placeholders, not one**: replacement value (a range of about
   forty to one), measure cost (FM3) and project life (FM4). The break-even view answers the first.
   The other two are swept or sourced: see the passages below.
4. **Outage cost has no customer count.** No public figure for customers served exists and none was
   invented (FD7). Monday's case shows outage in customer-hours per customer served, or leaves it out;
   it cannot show dollars.
5. **F4 has a build of its own before any storm runs.** The draft starts the catalogue on Friday at the
   calibration freeze, but RainyDay needs its own environment (no release exists; its repository pins
   Python 3.8), the rainfall record (the largest download of the project) and a transposition domain.
   These do not depend on the calibration and start on Thursday beside F3.
6. **Solver time is an extrapolation.** 425 s a run comes from toy terrain; real terrain with the Navy
   Yard pits may force a smaller time step. F3's first real run is the measurement, and "at least 60
   storms by Monday" should be re-read against it on Friday.
7. **Kept grids fit the budget.** A whole peak-depth grid is 640,000 cells; 150 of them are under 0.4 GB
   uncompressed, inside the 3 GB set aside for solver runs.
8. **E5 has candidates already.** A blind review caught building values understated by $7.2 billion in
   F1 (one inventory record kept where the publisher divides a building over several). In F2 the
   second reader's clock rule shows 824 FloodNet events on a different day in New York than in GMT,
   Ida's among them; and the publisher's depth profile disagrees with its own peak column in 52
   events. All three are reviewed and in the reports.
9. **Demo 2 is the tight one.** The emulator (F9, 10 hours in the plan) is built, trained and scored in
   two days on a catalogue that must be complete by Tuesday night, with F8's panel and a page beside
   it. The draft's own rule ("not sent without item 2") is the right guard. Its Python environment and
   data loader can be built on Monday or Tuesday against the runs finished by then.
10. **The live re-run is realistic.** One asset goes through CRC's point route, not the 600,000-cell
    raster read (96 s); under a minute is plausible and is measured in F7.

**Yuri's answers on 2026-11-25.** A new session per stage, proceeding without a wait when checks pass
(DP11); merges into `main` stay on his go. The second round of CRC issues stays on Monday 30 November (DP9). He reads the FEMA and Williams
passages himself, from the instructions below. The page being public is fine.

**Passages for a person to read** (the sites refuse automated access; each value is entered with its
address and the sentence read, and replaces a placeholder):

| What | Where | What to bring back | Needed by |
| --- | --- | --- | --- |
| Project useful life for elevation, and for floodproofing or flood barriers | FEMA, Benefit-Cost Analysis page (`fema.gov/grants/tools/benefit-cost-analysis`); in the BCA Reference Guide or the current toolkit's guidance, the table of "project useful life" by mitigation type | The years for each of the two, the document's title and date, the page or table number, the sentence or table row as written | F7, Sunday 29 Nov |
| Current BCA Toolkit version | The same page | The version number and its release date as the page states them | F7 |
| Hazus functional depth for substations | Hazus Inventory Technical Manual 4.2 SP3 (`fema.gov/sites/default/files/documents/fema_hazus-inventory-technical-manual-4.2.3.pdf`), Table 10-12 or the table of flood functionality thresholds for electric power facilities | The depth at which a substation stops functioning, for low- and high-voltage, with the table number and the row as written; whether the table is 10-12 | F7 (outage threshold, FM5) |
| Williams et al. 2025 substation damage at 3 m | Journal of Flood Risk Management, doi:10.1111/jfr3.70045 | The damage ratios at 3 m for substation, distribution substation and grid exit point (the requirements say 0.52–0.76, 0.51–0.77, 0.49–0.70), with the table or figure number | F6, Saturday 28 Nov |

If a passage is not read in time, the value stays a labelled placeholder and the break-even view carries
it; nothing is stated as FEMA's that was not read.
