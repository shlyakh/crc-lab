# Concerns for the demos of 1 and 4 December

Written 2026-11-25, after F2, at Yuri's request. Companion to `docs/flood/demo-plan.md`. It lists what
could make a demo show something other than what the plan expects, the evidence so far, when each concern
is settled, and what could be shown instead. Nothing here changes the plan; a change would go through
`docs/flood/changes.md`.

## 1. The main concern: the substations may not be in danger from rain

Demo 1 opens with "Should the lead substation be raised by 0.9 m?". The evidence so far says the modelled
answer may be that rain barely reaches it.

**Evidence, from the city's own stormwater maps on the project grid (F2):**

| Scenario | Flooded cells inside any substation outline | Nearest flooding to a Farragut outline | Nearest to the other outlines |
| --- | ---: | --- | --- |
| Limited, 1.77 in/hr | 0 | 3 m | 141 m or more |
| Moderate, 2.13 in/hr | 0 | 3 m | 25 m (unnamed Williamsburg yard), others 141 m or more |
| Moderate, 2050 sea level | 0 | 3 m | 66 m or more |
| Extreme, 3.66 in/hr, 2080 sea level | 0 | 3 m | 66 m or more |

- The four named Con Edison substations are one complex at Vinegar Hill, on a slope that falls to the
  East River (ground from 9.5 m down to 3.2 m at Farragut). Rain runs off towards the river.
- Farragut's real exposure is the river. Coastal surge is out of this study's scope.
- **What this evidence cannot say.** The city masked large non-residential lots out of its maps, so
  "nothing inside the outline" may be the mask and not a dry yard. The maps are also classes, not
  depths. Only our own model can say what stands in the yards.

**When it is settled.** F3's replay of Ida on the real terrain, Thursday or Friday. The plan's rule: if no
substation site is wet in any catalogue storm, stop and report.

**What "not in danger" would look like in numbers.** Depth at every substation under about 0.1 m in both
replays and in most catalogue storms; expected annual damage a small fraction of a percent of value; a
benefit-cost ratio far below 1 at any replacement value in the placeholder range.

## 2. What could be shown instead

The subject of Demo 1 is verification (DP2); the flood study is the worked example. So the question is
which worked example gives the audience a result worth checking.

| Option | What minutes 0 to 4 show | For | Against | Extra work |
| --- | --- | --- | --- | --- |
| **A. Keep the substation, report the honest "no"** | "Against rain alone, raising Farragut does not pay; here is the range of values over which that holds, and here is what the study does not cover (the river)" | True to the data; a negative result that survives checking is a strong verification story; no change of plan | A resilience advisor is shown a case with no investment in it; the event-loss extension has little to add up; "out of scope" carries the interesting risk | None |
| **B. Lead with buildings near deep flooding** | Loss for the blocks where the city maps and our model agree water stands, with and without a measure (raising or protecting openings below grade) | There is real exposure: on the Moderate map 123 buildings stand within a cell of deep flooding, 48 of them with space below grade; on the Extreme map 677 and 270. Values are the inventory's, not placeholders. The portfolio is what the event-loss extension is for | The case is a portfolio, not one asset: harder to tell in four minutes. Building damage curves (FR3) and the basement variant must be ready in F6. 5,416 buildings have no value | Curve work in F6 already planned; the lead-asset card is redrawn for a block |
| **C. Both: buildings carry the loss, the substation is the single-asset card** | The portfolio's loss curve for buildings; then one substation card that shows the method on a single asset, with its small or zero loss stated | Keeps the live re-run (one asset, one raise height) and the component prototype; the loss figures are not empty | Two stories in fifteen minutes; needs a firm running order | The reduced page carries two cards |
| D. Add river surge so the substation is exposed | | The exposure that matters for Farragut | A new hazard, new sources, new validation: not possible by Tuesday, and a scope change | Not recommended |
| E. Move the study area | | | F1 to F3 again | Not possible by Tuesday |

**Recommendation.** Decide by rule on Friday, at the review of F3's replays, not on Sunday night:

- If a substation is wet to 0.3 m or more in the Ida replay or in the Moderate-map run: keep the plan.
- If not: option C, with buildings as the lead result. It keeps every exhibit of the plan alive (E1 as a
  block card beside a substation card, E2 on the buildings' own values, E7 with something to add up,
  E8 and E9 on the substation as method) and it stays honest about the substation.

The 0.3 m is a proposed threshold **[P]**: the lower of FM1's two raise heights, below which neither
measure has anything to do.

**What can be done now so that either answer works.** Build the lead-asset card, the break-even view and
the single-asset re-run for any asset type, not for substations only. F6 loads building curves (FR3) as
well as substation curves in any case. Neither costs extra time if decided before F6 starts.

## 3. Other concerns

| # | Concern | Evidence | Settled when | If it goes wrong |
| --- | --- | --- | --- | --- |
| 1 | **The benefit-cost ratio rests on three placeholders**: replacement value (a range of about forty to one), measure cost, project life | F1 found no public replacement value; FEMA's useful-life table has not been read | Project life: when read (`docs/flood/reading-list.md`). The others stay placeholders | The break-even view (FM7) shows the conclusion across the ranges. With buildings as lead (option B or C) the value is the inventory's and one placeholder goes away |
| 2 | **Outage cost has no customer count** | No public figure for customers served by these substations; none invented | Not before Tuesday | Outage is shown in customer-hours per customer served, or left out and named as a limit |
| 3 | **Solver time is an extrapolation** | 425 s a storm comes from toy terrain under emulation; real terrain and the three Navy Yard pits may force smaller time steps | F3's first real run | At twice the time, 150 storms take 35 hours and still finish over the weekend; at four times, Monday rests on the 60-storm minimum, and Demo 2's catalogue completes on Tuesday or Wednesday |
| 4 | **The catalogue needs its own setup before any storm runs** | RainyDay has no release and pins Python 3.8; the rainfall record is the project's largest download (10 GB budget) | Thursday, beside F3 | The catalogue starts late; fewer storms on Monday |
| 5 | **Validation is thin in this area** | 11 surveyed marks for Ida and no sensor that recorded it; 5 sensors for 29 September 2023. In 52 FloodNet events the publisher's depth profile disagrees with its own peak column | F5 | The demo says how many points each error figure rests on. The published research model reached 0.20 m only after calibration on 8 marks, 0.40 m before |
| 6 | **Calibration is against the city's maps, which are a model too** | The maps come from the city's own hydraulic model, mask large lots, and publish no storm duration | F3 | The report says the constant loss rate (the drainage allowance) is fitted to another model's output, with the one-hour storm as an assumption and its sensitivity shown |
| 7 | **Demo 2's emulator is built in two days** | F9 is 10 hours in the plan, on a catalogue that must be complete first | Tuesday night (catalogue), Thursday (scores) | The plan's own rule: the link is not sent without the emulator. Its environment and loader can be built on Monday against the runs finished by then |
| 8 | **An emulator trained on one 4 km square** | By design (FE) | F9 | Stated on the page: trained and tested in one neighbourhood, not claimed to transfer. A reader in parametric insurance will ask; the held-out block is the answer available |
| 9 | **Unattended work can stall on a refused action** | In F2 the permission system refused an agent launch and refused running a compiled program; both needed Yuri | Each stage | Long runs are plain commands under `caffeinate -i`, started while Yuri is reachable. A stage that needs a refused action stops and says so; it is not worked around |
| 10 | **One laptop** | The solver, the builds and the reviews share 8 cores and 28 GiB of free disk | Throughout | The solver runs overnight if it slows a stage; the disk rule of F0 applies below 10 GiB free |
| 11 | **A change of coordinating model** | The plan gives the coordinating model the CRC calls, calibration, risk arithmetic and verdicts. If stages are coordinated by Opus 5.5 in place of Fable 5.2, the plan's safeguard is the same: a blind review of each stage's diff by an agent that is not told what to expect | Each stage | Keep the blind review for every stage; it found the costly errors of F1 and F2. Consider one Fable session for the decisions hardest to undo: the calibration freeze (F3) and the event-loss interface (F6) |
| 12 | **Findings shown to the CRC maintainers** | Nothing goes out before Yuri's review; the second round of issues is for Monday 30 November | Monday | The meeting shows one reviewed finding on screen and names the rest as "sent" or "in review" |
| 13 | **Placeholder on placeholder in the component prototype** | Value shares and per-component curves have no source | When built | Every figure carries the tag; the prototype is offered as a way of expressing an asset, not as a result |

## 4. Decisions this asks of Yuri

1. The rule of section 2 for Friday: the 0.3 m threshold, and option C if it is not met.
2. Whether the lead-asset card and break-even view are built for any asset type from the start
   (recommended).
3. The wording for minutes 0 to 4 if the substation's answer is "no for rain".
4. Which sessions, if any, stay with Fable 5.2 (concern 11).
