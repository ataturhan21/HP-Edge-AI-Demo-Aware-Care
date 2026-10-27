# ADR-016: Presenter scenarios in local mode start a synthetic case for the live AI

Status: **Accepted 2026-10-16** (issue #113), decided by the maintainer. Affected IDs: O03, M12, `loadScenario` (no
contract change), R37, R39, R40; `fixtures/scenarios.json`; `infra/deploy/flow_check.py` (presenter check). Amends the
"scenarios stay mock-only" boundary of ADR-007 and of the local fixture-pack use (ADR-004 in the Architecture notes).

## Context
The Nano runs local mode. O03 offered six "Load scenario" buttons, but `loadScenario` refused every one with 404
("The requested resource is not available."), because synthetic scenarios were mock-only. The maintainer reported:
"no scenario in presenter mode works for me". The scenarios select scripted outcomes in mock mode, and the project
never converts local inference into a scripted result.

Given three options (live scenarios, an honest page only, or redeploying in mock mode), the maintainer chose **"Live
scenarios (Recommended)"** on 2026-10-16.

## Decision
1. **In local mode, a scenario only starts a synthetic case.** `fixtures/scenarios.json` gives each scenario a
   `local_mode` block: a realistic synthetic concern and the red-flag checklist answer. `loadScenario` resets as
   before, creates the demo patient session, and creates the case through the same gate as a patient-created case. It
   stores the checklist answer as the case's confirmed context. Loading never asks the model.
2. **Everything after loading runs live:** the reviewed questions, the red-flag screen of the person's words and the
   local model's guidance, with the same validation, single repair and fail-closed handling as any case. Results vary
   like a real consultation.
3. **Per scenario:**
   - **routine, selfcare, nomatch:** the full live journey. `nomatch` shows the recovery path when the presenter
     picks the strict "Demo Exclusive Plan" filter in A09, as in mock mode.
   - **urgent:** the checklist answer ticks RF01 (approved list), so the case is `urgent` with 0 questions.
   - **unsupported:** the presenter's scope choice makes the case `limited` (`unsupported_scope`) with no model call,
     as in mock mode. A16 then explains that the concern is outside the demo scope.
   - **failure:** not available in local mode (404). Forcing a generation failure would fake the local AI. O03 shows
     it disabled, with that reason.
4. **O03 in local mode** explains what the scenarios do ("Live scenarios on the HP ZGX Nano") and tags each card.
5. **Deploy check:** a release declares the API capability `local-scenarios`. For such a release in local mode, the
   presenter check runs the same handoff as in mock mode (load, continue on the patient gateway, reset) and asserts
   that `failure` is refused. Older releases, such as a rollback target, are still checked for refusing every load.

## Consequences
- **The scenario outcome is not scripted.** For example, "Explore self-care guidance" gets whatever level the reviewed
  pathway and the model reach for its answers, not a scripted self-care result. The mock-mode tags ("Shorter intake")
  are not shown in local mode.
- **No contract, route or requirement change.** The fixture pack stays `synthetic` with
  `clinical_execution_enabled: false`. It supplies only synthetic input text, and the clinical behaviour is the
  reviewed pathway's.
- **ADR-006** (proposal) is unaffected. Its catalogue of six scenario IDs stands.

## Amendment 1 (2026-10-20): one-click handoff and quick demos prepared live ahead of time (#315, #316)
Status: **Accepted 2026-10-20**, from the maintainer's request of that day: "it is hard to present, for example you need
to open a new tab, go to history etc. make using presenter scenarios much easier and faster. also for some audience, we
should be able to demo these scenarios only under 10 seconds so arrange presenter scenarios accordingly and
perfectly". Measured before the change: local guidance takes about 19 s on the ZGX Nano and 2.3 s on the ZGX Fury;
every other step takes milliseconds. Contract change: CHG-DEV-API-002 (additive).

1. **Handoff (#315).** `ScenarioLoaded` names the case `state` and the patient-site `next_path`. O03 opens or reuses one
   named patient tab there (opened inside the click, so pop-up blockers allow it) and always offers an "Open on patient
   site" link. The patient address comes from the presenter gateway's `/aware-care-device.js` (`patientOrigin`, the
   deployment's `network.browser_origin`); without it, the same host with the port one lower. No trip through History.
2. **Reset is optional.** `LoadScenarioRequest.reset` is a boolean. `true` keeps the earlier behaviour. `false` adds
   the case to the presenter's live demo patient (a new session for the same demo actor), so prepared demos coexist and
   appear together in History; without a live demo patient a new one is created. A pending or failed reset still
   blocks. O03 full journeys load with `reset=false`, so loading no longer removes prepared quick demos; Reset removes
   every demo case of the presenter, as before.
3. **Quick demos are prepared live ahead of time (#316).** `prepare="result"` makes the server, as the demo patient
   actor and through the same services, checks and audit as a patient, answer the reviewed questions with the
   scenario's synthetic answers (`local_mode.quick` in the fixture pack), confirm the review and start guidance: in
   local mode the live local model with unchanged validation, single repair and fail-closed handling; in mock mode the
   scripted fixture outcome. A doctor result then runs the provider search (the strict "Demo Exclusive Plan" for
   `nomatch`). `urgent` and `unsupported` are at their result after the gate, with no model call. The work runs in a
   presenter-owned `scenario_prepare` job, so the presenter follows a content-free status and error code and never
   reads the patient's content. A failure leaves the case recoverable exactly as for a patient, and O03 says "Not
   ready" with "Prepare again"; nothing is substituted. O03 prepares the quick demos one after another, so the
   generation queue never refuses one; a busy refusal is still shown.
4. **What the result is.** A prepared result is the device model's output for synthetic answers, generated before the
   audience sees it, and O03 says so ("generated HH:MM on the device"). The guidance page says it was generated on the
   device. In local mode nothing calls it scripted; in mock mode the mock labels stay. The model decides the level of
   care, so a quick demo's result can differ from its card's title, and O03 says that too.
5. **Deploy check.** A release declares the API capability `quick-demos`. For such a release the presenter check also
   asserts, without a model call, that a load names its screen, that `reset=false` keeps the earlier case, that the
   urgent quick demo is ready at once and that the presenter gateway's device script names the patient site. Older
   releases are checked exactly as before.

Consequences: the fixture pack stays `synthetic` with `clinical_execution_enabled: false`; the quick answers are
synthetic input only and the clinical behaviour stays the reviewed pathway's. No route, screen, requirement or reviewed
clinical text changes. Prepared demos live in the demo patient's session: its 30-minute idle limit and 8-hour absolute
limit apply, and O03 forgets which demos it prepared when the presenter page is reloaded (Prepare again starts a fresh
set).

## Amendment 2 (2026-10-21): three one-click flows run live at the click (#358)
Status: **Accepted 2026-10-21**, from the maintainer's request of that day: "quick demos are still too hard to use. 1-
make scenarios first tab 2- just put 3 quick flows, nothing else 3- every input should come ready in quick flows, you
will just click 1 button, it will do ai inference 4- simplify usage for quick flows even better and make its design
perfect". Contract change: CHG-DEV-API-006 (additive). It replaces, on the Scenarios page, the quick demos prepared
ahead of time (amendment 1, items 3 and 4); the server machinery of amendment 1 stays and is what the flows use.

1. **Scenarios first.** The presenter navigation lists Scenarios first (then Runtime, Controls, Telemetry and More
   scenarios); the presenter address still opens it.
2. **Three flows, nothing else.** `/presenter/scenarios` shows one line of device status and three flows, each with a
   title, one line and one button ("Run on <device>"): **Guidance from the local AI** (`routine`), **Self-care guidance**
   (`selfcare`) and **Urgent warning sign** (`urgent`). Nothing is prepared ahead.
3. **One click runs the flow live.** The click opens or reuses the named patient tab (inside the click, so no pop-up
   blocker stops it; a fresh tab shows a one-line waiting note) and loads the scenario with every input ready: the
   synthetic concern, the demo patient's consent, the checklist answer and the synthetic answers. The guidance flows use
   `reset=false, prepare="result"` (amendment 1, item 3: the reviewed questions with the fixture's synthetic answers,
   then guidance on the device's model with unchanged validation, single repair and fail-closed handling). The card
   shows progress with the device name and the elapsed seconds, then the patient tab moves to the finished screen and
   the card says "Shown in the patient tab" with a "Show again" link. When the device's own red-flag screen routes a
   guidance case to urgent help, that real result is shown and named as such.
4. **The warning sign is the AI's.** `LoadScenarioRequest.urgency_input="written"` gives the case only the written
   concern, with the checklist answered "none of these apply", as a patient who writes an emergency in their own words.
   The concern then takes createCase's red-flag screen (ADR-003 amendment 3, #153; task `red_flag_screen`) on the
   device's model before the case exists: a match routes the case to urgent help at creation, with the level and rule
   IDs recorded as for a patient. No match leaves an ordinary case at its questions, and O03 says the AI did not flag
   it. A screen that cannot run fails the load closed (503 `RED_FLAG_SCREEN_UNAVAILABLE`) and creates nothing; unlike a
   patient's createCase, which defers to the screen before guidance, the presenter flow has nothing to show without
   the screen. Mock mode keeps the scenario's scripted urgent outcome and says so.
5. **Failures.** Any failure says so on the card in plain words with "Nothing was substituted"; a fresh patient tab
   closes again. Mock mode is labelled as scripted, local mode never.
6. **More scenarios.** The full journeys and the reset are the secondary view `/presenter/scenarios/more` of O03 (no
   new screen ID). Reset there also returns the patient tab to the start page, so the separate "Reset for next
   audience" is no longer needed.
7. **Deploy check.** A release declares the API capability `quick-flows` as well; the presenter check of amendment 1
   stays model-free and additionally asserts that the `urgency_input` field is accepted by validation without running
   a flow (a request the server refuses before any model call).

Consequences: no route of the 25, screen ID, operation, requirement, reviewed clinical text, prompt or model changes.
A flow's result is a fresh case under the presenter's live demo patient, so History lists every run until Reset.
