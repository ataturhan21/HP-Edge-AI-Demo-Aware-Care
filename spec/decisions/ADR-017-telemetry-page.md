# ADR-017: A public telemetry page (W06) with measured local-AI usage and estimated cost versus cloud LLM APIs

Status: **Accepted 2026-10-16** (issue #122), decided by the maintainer. Affected IDs:
- **New:** screen W06 `/telemetry` (route 25) and operation `getTelemetry` (operation 32), contract
  `TelemetrySnapshot`.
- **Mappings:** R34, R38, R39; M12.
- **Supporting files:** `infra/telemetry-pricing.json`, `infra/telemetry/power_sampler.py`,
  `apps/api/app/runtime/metering.py`.

Amends the stable boundaries "exactly 24 routes" and "all existing operation IDs" (CLAUDE.md, `check_traceability.py`,
`check_contracts.py`). Every earlier ID is unchanged.

## Context
The maintainer asked for "a perfect telemetry page for this app, especially showing the cost savings and other benefits
compared to a cloud llm api call", opened from a button in the web app. The plan's five recommendations were approved
on 2026-10-16: "i approve with your recommendations, complete all of them perfectly". The spec constrains such a page:
- **R39:** benefit views show "not measured" without real pilot outcomes, and synthetic runs are never counted as
  savings.
- **R34 / ADR-014:** no patient data leaves the device.
- **ADR-002:** no cloud model is ever called.

## Decision
1. **A new public page `/telemetry` (W06)**, linked from:
   - the main navigation of the public, patient and presenter layouts;
   - the footer of every page;
   - a "See live telemetry" call to action on the home page.
2. **Aggregates only.** `GET /api/v1/telemetry?period=24h|7d|release` is public and no-store. It returns:
   - model calls by task and outcome;
   - the token counts ZRT reports;
   - call and job timings;
   - GPU energy;
   - consultation outcomes from content-free events, with breakdowns below 5 withheld;
   - busy refusals;
   - privacy facts;
   - the reviewed price list.

   It holds no case, actor, text or exact time. The new `model_calls` table keeps the hour only and 90 days.
3. **Three bases on every figure:**
   - **Measured:** read on this device.
   - **Estimated:** computed from measurements and stated, editable assumptions, with the formula shown.
   - **Not measured.**

   Cloud cost is the measured tokens times reviewed list prices. No cloud call is made, so cloud latency is "Not
   measured". Healthcare outcomes stay "Not measured" (R39).
4. **Two cloud references**, from primary price pages on 2026-10-16:
   - **Like-for-like:** Qwen3.6-35B-A3B on Alibaba Cloud Model Studio, $0.248 / $1.485 per 1M tokens (Global).
   - **Frontier:** Claude Sonnet 5.5, $2 / $10 per 1M tokens.
5. **Default assumptions:**
   - **Device price:** HP Store US list price for the 4 TB ZGX Nano, $7,699. Retail prices seen the same day ranged
     from about $4,200 to $8,200.
   - **Lifetime:** 36 months.
   - **Electricity:** EIA's US commercial average for July 2026, $0.1453/kWh.
   - **Volume:** measured consultations per day, with labeled presets (50, 200, 2,000 per day).

   All are editable on the page, and none is saved or sent.
6. **Energy is measured, never estimated.** A host-side sampler reads `nvidia-smi power.draw` once a second into
   hourly files under the data directory. It is installed by each deployment and kept running by a user crontab line
   with `flock`. It only reads the GPU's reported power and changes no ZRT, driver, CUDA or GPU setting. Energy is
   integrated per call; a call without covering samples has no energy value. This is GPU power, not whole-system
   power, and the page says so.
7. **Reference images:** the registry requires mockups for every screen. W06's are screenshots of the implemented
   page (`spec/mockups/aware-care/`), labeled as such.

## Consequences
- **The honest result:** at demo volumes, the like-for-like hosted model is far cheaper per consultation than
  amortizing the device. Running the same open model locally is cheap per call, and its main benefits are sovereignty
  and availability. Against a frontier API the device can pay for itself only at high volume. The page shows this
  instead of hiding it.
- **Not claimed:** whole-system power, cloud latency, any healthcare saving.
- **Change record:** CHG-DEV-TEL-001 with a spec-lock refresh. R34, R38 and R39 stay `planned`.

## Amendment (2026-10-17, #127): a second frontier reference; whole-system power
- **Third cloud reference:** GPT-6 Astra (OpenAI), Standard tier, short context (up to 272K input tokens), $10 / $50 per
  1M tokens, confirmed on OpenAI's pricing page on 2026-10-17. Claude Sonnet 5.5 stays the default frontier reference
  in the calculator.
- **Whole-system power is not measurable in software on this Nano.** `nvidia-smi` reports GPU power only ("Module Power
  Readings" are N/A), and the only other sysfs power sensor is the ACPI fan meter. The page says so. The calculator
  takes an assumed non-GPU wattage (default 0 W, editable, for example a wall-socket meter reading minus GPU power)
  and applies it over the measured AI time per consultation (`ai_calls.duration_ms_total`). The result is labeled
  Estimated. A real wall-meter measurement would need external hardware.

## Amendment (2026-10-17, #129): share as a slide
W06 offers the figures and the calculator's current scenario as one 16:9 slide, as Download PNG (2×) and Download SVG.
- **Built on the device:** `W06Slide.ts` builds a self-contained SVG. The bundled HP logo is read from the app and
  embedded, and only Arial/Helvetica is used, so the file references nothing outside itself. The PNG is drawn on a
  canvas, and nothing is uploaded.
- **Content:** every figure keeps its basis label, estimates name their comparison and assumptions, and the
  footnote lists the price sources and retrieval dates and states that healthcare outcomes are not measured.

## Amendment (2026-10-19, #276, #271): outcome figures in complete UTC days; counts per running mode
QA found that the public, live page could be polled to watch one patient's outcome: `urgent_routes` (once at least 5)
and `guided` or the per-task counts ticked up when one person was routed. Maintainer decision of 2026-10-19: keep the
page public, and publish outcome breakdowns only in daily buckets.
- **The page stays public** (decision 1 and 2 above are unchanged).
- **Outcome figures count only complete UTC days before today:** consultations guided, urgent routes, repaired and
  fail-closed results, busy refusals, AI calls by task and errored AI calls, the guidance latency samples, and the
  metered consultations used for per-consultation figures. For the 24-hour period that is yesterday (UTC), for 7 days
  the 7 days before today, for "since this release" the release's start to the start of today. The snapshot names the
  window (`consultations.counted_from`, `consultations.counted_to`), and W06 says the outcome figures run to the end of
  yesterday (UTC).
- **Small-count suppression stays:** breakdowns below 5 are withheld, now per daily-bucket window.
- **Usage and cost totals are unchanged and live:** total AI calls, token counts, AI time, call durations, output
  speed and GPU energy, and so the cost estimates built on them.
- **Per running mode (#271):** events and jobs record the mode they ran in, and every telemetry query counts only the
  running mode's rows, so a data directory that served mock mode does not mix that activity into local figures. Rows
  written before the mode was recorded carry none and are not counted. The concern check (#154) is a task of its own
  (`by_task.concern_check`).
- **Consequence:** on the day of a demo the outcome figures do not move; the per-consultation defaults on W06 then fall
  back to the labeled values until a complete day has metered consultations. This is the price of the decision.
- **Change record:** CHG-DEV-API-001 with a spec-lock refresh. R34, R38 and R39 stay `planned`.

## Amendment (2026-10-20, #324, #325, #331): no tile mixes windows; live facts first; the counting start
Product review of v0.10.0-demo.1 on both devices. The outcome-window rule of the previous amendment is **unchanged**
(outcome figures count only complete UTC days before today); this amendment changes how W06 presents it.
- **No tile mixes windows (#324):** the "AI calls on the device" tile shows only the live total. AI calls by task and
  errored calls move to the Reliability section, with every other complete-day figure (guidance published and times,
  queue wait, repairs, fail-closed results, urgent routes, busy refusals), under a heading that names the days as
  absolute dates ("13–19 Oct 2026 (complete UTC days)", from `consultations.counted_from` / `counted_to`). W06 no longer
  says "the end of yesterday".
- **Counting start (#324):** the snapshot gains `consultations.counting_since`: the later of `counted_from` and the
  hour of the first event that records the running mode, when the data directory also holds events written before
  the mode was recorded (never counted, as before); otherwise equal to `counted_from`. It may be after `counted_to`
  (recording began today). W06 states it when it is later than the window start.
- **Live facts first (#325):** "At a glance" opens with a "Live on this device" group (patient data sent off the
  device, By design; AI calls, Measured; the estimated cloud cost of this work against measured GPU electricity,
  Estimated, with a link to the formulas; output speed, Measured; then tokens and GPU energy), followed by a
  "Consultation outcomes" group in complete UTC days. Outcome figures without samples say when today's consultations
  will appear (00:00 UTC on the next day) instead of a bare 0 or dash; the "covers 0 of the period's 0 consultations"
  sentence is not shown without consultations; the per-call row is named "Any AI call (mostly short safety screens)".
  The slide leads with the architecture's figure (cloud AI calls, By design) when no consultation is counted, and its
  footnote reserves the R39 sentence's lines first.
- **W03 (#331):** "Local processing at the healthcare edge" is a property of the architecture: W03 labels it By design
  with a link to W06's privacy section; the benefit hypotheses stay Not measured. W03's public actions go to W06 and
  W02; "Explore the demonstration" (O03) shows only on the presenter gateway.
- **Change record:** CHG-DEV-API-003 with a spec-lock refresh. R34, R38 and R39 stay `planned`.

## Amendment (2026-10-22, #398, #432, #437, #441): one window per figure; usage counted by the hour; mock mode
Comprehensive QA of v0.14.0-demo.1 (findings T-01, S-03, T-04, T-13). The outcome-window rule (amendment of
2026-10-19) and the presentation rules of 2026-10-20 are **unchanged**; this amendment closes three ways the page still
mixed windows or said more than it measured.
- **Per-consultation figures use one window (#398):** they divided the period's live usage (up to now) by the
  consultations of complete UTC days, so tokens, energy and AI time per consultation grew through the day and the
  calculator, the privacy sentence and the slide inherited the error. `metered` now carries its own usage: the AI calls,
  token counts, AI time and GPU energy of the same whole hours in which its consultations were guided (`metered.from`
  to `metered.to`: the complete UTC days of the outcome window, from the outcome counting start of #324 and the first
  whole metered hour of #124 on). Both tables are filtered alike (running mode, no release filter). W06 divides only
  these and names the window; the measured volume divides the counted consultations by the days actually counted; the
  cost note no longer compares a metered count with another window's consultations.
- **Usage counted by the hour (#432):** a concern routed to urgent help makes one AI call (the red-flag screen) and a
  routine one two (the screen and the concern check), so a live total showed one person's outcome to anyone polling the
  public page. Usage and cost totals (AI calls, tokens, AI time, call timings, output speed and GPU energy) now count
  complete hours only, up to the start of the current hour (`ai_calls.counted_from` / `counted_to`), the granularity
  events already keep (#275). The page says so and when the current hour appears. **Residual:** someone who knows
  that only one consultation happened in an hour can still read that hour's calls once it has ended, as with any
  aggregate; outcome figures stay in daily buckets with small counts withheld.
- **Mock mode (#437):** no model runs, so the snapshot gives no qualification network check in mock mode (as it names
  no model), and W01, W06 and the slide name scripted calls and guidance as scripted.
- **Percentiles (#441):** linear interpolation between closest ranks, the ADR-002 qualification's definition, so the
  median of an even number of values is the mean of the middle two.
- **Change record:** CHG-DEV-TEL-005 with a spec-lock refresh. R34, R38 and R39 stay `planned`.

## Amendment (2026-10-27, #638): the page shows the current day live
Owner decision of 2026-10-27. After a fresh install the outcome figures said "None in complete UTC days yet" all day,
so the page looked empty during a demo. The complete-UTC-day outcome window (amendment of 2026-10-19) and the
complete-hour usage window (#432, amendment of 2026-10-22) are **replaced**:
- **Every window runs up to now, including the current hour:** outcome figures (consultations guided, urgent routes,
  repaired and fail-closed results and their rules, busy refusals, AI calls by task and errored calls, guidance
  latency) and usage totals (AI calls, tokens, AI time, call timings, output speed and GPU energy) count the same whole
  hours, from the hour the period starts in up to the end of the current hour (event and call times keep the hour
  only, #275). Last 24 hours and Last 7 days are rolling windows ending now; Since this release runs from the release
  start to now. `consultations.counted_from` / `counted_to` and `ai_calls.counted_from` / `counted_to` name these hours
  (`counted_to` is the end of the current hour).
- **Unchanged:** the page stays public; breakdowns below 5 stay withheld; every query counts only the running mode
  (#271); the outcome counting start (#324); per-consultation figures divide usage and consultations of the same
  hours (#398), from the first whole metered hour (#124).
- **W06** describes live windows ("26 Oct 2026, 14:00 UTC to now"); it no longer speaks of complete UTC days or
  complete hours, or says when today's figures will appear. The measured volume per day needs at least one day
  counted; before that the calculator uses the labeled fallback.
- **Accepted consequence:** someone polling the public page can see one consultation's outcome as it happens (a guided
  consultation, or the one AI call fewer of an urgent route), the exposure amendments 3 and 5 closed. Only synthetic
  data is ever used (ADR-019), and small outcome breakdowns stay withheld.
