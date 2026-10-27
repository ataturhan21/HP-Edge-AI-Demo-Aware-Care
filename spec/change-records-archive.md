# Change records (archive)


Frozen on 2026-10-23. Until then every specification or tooling change had a `CHG-*` record under `spec/changes/`.
The lean delivery rules (ADR-019) retired them: the pull request and git history are the record now, and ADRs cover
real decisions. The records are kept here, unchanged except that their headings moved down one level. Search for a
record by its ID, for example `CHG-DEV-SEC-002`.

## CHG-BOOTSTRAP-001

Type: source conversion and repository handoff, not implementation release.
Baseline: original master 2.0. Handoff: 1.0.0.
Scope: preserve original IDs and clauses, add machine-readable contracts, decisions, fixtures, traceability, environment records and validation tools.
Evidence: see ../../evidence/handoff/VALIDATION_REPORT.md after package validation.
Runtime verification: not performed on the Nano by this handoff task.
Clinical approval: not provided. Clinical registries remain disabled.
Original documents: retained unmodified under ../source/ and ../mockups/original/.

## CHG-DEV-A11Y-001

Type: accessibility fixes and a new shared browser test (all screens; R34), not a release. Date: 2026-10-18. Issue:
#158.

### Scope
- **Banner landmark:** the demo notice (or the presenter toolbar), the navigation and the status strip form each
  shell's `<header>` (`components/Layout.tsx`).
- **Scrollable tables:** they use `ScrollTable` (`components/ui.tsx`), a focusable, named scroll region. This covers
  W03, W06, A13 and O02.
- **A12:** the summary's section headings are `h2` (styled as before).
- **New test:** `tests/ui/a11y.spec.ts`, registered under Layout.tsx and ui.tsx. axe-core 4.10.3 (pinned
  devDependency of apps/web) scans all 25 routes at 1440 and 360 px for WCAG 2.0/2.1 A/AA and best practice.

### Not changed
Every ID, route, operation and contract; requirement statuses (`planned`).

## CHG-DEV-ACC-001

Type: acceptance evidence reconciliation for an exact release build, not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #10.
Exact build: `9f5144177f22728652f0da4c105930ccc09ead75` (`v0.1.0-demo.1`), mock mode.

### Scope
- `evidence/releases/v0.1.0-demo.1/acceptance/`: the three exact-build test reports (CI x86_64 backend, release
  arm64 backend, CI browser), the per-clause coverage mapping of 42 candidate scenarios, an execution report in the
  `releases/template.json` shape bound to the current spec lock, and a README with the verdict table and the
  skipped-test analysis.
- `spec/acceptance.json`: T-R01-S01, T-R04-S01 and T-R33-S01 set to `PASSED`, with evidence references to that
  report. `execution_policy` text now states the per-scenario rule. All 40 primary T-Rxx records stay `NOT_EXECUTED`,
  because none has all of its scenarios fully asserted.

### Specification files changed
- `spec/acceptance.json` only. It is not part of `spec/lock.json`; `update_spec_lock.py --dry-run` produced an
  identical lock, so no lock refresh was needed. `scripts/check_traceability.py` passes.

### Not changed
Requirement statuses (`requirements.json` and `traceability.yaml`: all `planned`), screens, modules, contracts,
OpenAPI, product text, tests and application code.

## CHG-DEV-ACC-002

Type: acceptance evidence, not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #19.

### Scope
- `spec/acceptance.json`: T-R03-S02 set to `PASSED`, with an evidence reference to
  `evidence/releases/v0.2.0-demo.1/acceptance/t-r03-s02/acceptance-report.json`. T-R03 stays `NOT_EXECUTED`
  (T-R03-S01 is partial). No other status changes.
- `evidence/releases/v0.2.0-demo.1/acceptance/t-r03-s02/`: CI x86_64 and Nano arm64 reports for `53766cd`, the
  clause mapping, and the execution report. The application code is identical to `v0.2.0-demo.1`; only the operator
  tool, tests and docs differ.
- Wiki Testing page counts and the Issue Work Log entry for #19.

### Specification files changed
`spec/acceptance.json` only. It is outside `spec/lock.json`, so the lock is unchanged; `check_traceability.py` passes.

## CHG-DEV-ACC-003

Type: acceptance evidence for an exact release build, not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #25.
Exact build: `863f72072f1d966969da32550da1a9d7b2902b87` (`v0.4.0-demo.1`, draft prerelease), mock mode.

### Scope
- `evidence/releases/v0.4.0-demo.1/acceptance/`:
  - the five exact-build reports: CI x86_64 backend and browser, release linux/arm64 backend, Nano arm64 backend and
    browser;
  - the clause map of the 42 candidate scenarios, with its builder `build_clause_map.py`;
  - the evaluator `evaluate.py` and its output `evaluation.json`;
  - an execution report in the `releases/template.json` shape, bound to the current spec lock;
  - a README with the verdicts.
- `spec/acceptance.json`:
  - **35 scenarios** set to `PASSED`. The four already `PASSED` (T-R01-S01, T-R03-S02, T-R04-S01, T-R33-S01) keep
    their earlier evidence and gain this build's.
  - **16 primary records** set to `PASSED` (T-R01, R02, R03, R04, R08, R09, R11, R13, R19, R20, R27, R29, R32, R33,
    R35, R37), because all their scenarios passed on this build.
  - **Not passed**, so they stay `NOT_EXECUTED`: T-R06-S02, T-R10-S01, T-R10-S02 (saved mode, ADR-005), T-R18-S02
    and T-R26-S01 (out of scope, M4), T-R26-S02 (its given needs the M4 repair path or deadline), and T-R36-S01
    (2-minute warning #42; saved retention and logout, ADR-005).

### Rule applied
A scenario is `PASSED` only when its given can be met in this build, every then-clause is asserted, and every cited
test passed in every report of its kind: both backend architectures and both browser projects, on x86_64 and arm64.
A primary record is `PASSED` only when all its scenarios are.

### Specification files changed
`spec/acceptance.json` only. It is outside `spec/lock.json`, so the lock is unchanged; `check_traceability.py` passes.

### Not changed
- **Requirement statuses:** all still `planned`. No requirement is marked `verified`: that needs its own review, and
  this record only reports acceptance execution.
- **Everything else:** screens, modules, contracts, OpenAPI, product text, tests and application code.

## CHG-DEV-ACC-004

Type: acceptance authoring (tests and fixtures), not a release. Date: 2026-10-16. Baseline 2.0 unchanged.
Issue: #55 (refs #27, #79, #85, ADR-003, ADR-004).

### What changed
The 16 ADR-003 clinician-dependent scenarios are connected to the reviewed pathway `general-adult-3` and asserted in
local mode with a scripted model (the `local` fixture never contacts ZRT):
- **New tests:**
  - `test_R14.py` (+2), `test_R15.py` (+4), `test_R17.py` (+2) and `test_R25.py` (+2);
  - new files `test_R16.py` (3) and `test_R21.py` (2).
  - `conftest.py`: the scripted `LocalModel` can mark chosen statements unsafe in its certainty review.
- **Clause map:** `evidence/acceptance/55-clinician-scenarios/clause-map.json` is the #25 map (42 scenarios,
  unchanged) plus the 16, built by `build_clause_map.py`, with every then-clause checked verbatim against this file.
- **`spec/acceptance.json`:** `fixture_status` and `fixture_refs` for the 16 scenarios:
  - **`AUTHORED_CONNECTED_LOCAL_SCRIPTED_MODEL` (10):** the package and the asserting test files.
  - **`AUTHORED_GIVEN_NOT_MET_IN_DEMO` (2):**
    - T-R14-S01: the pathway has no early-stop rule;
    - T-R24-S01: no approved evidence snapshot.
  - **`NOT_APPLICABLE_TO_DEMO` (4):**
    - T-R21-S01, T-R22-S01 and T-R22-S02 need an approved corpus (ADR-004);
    - T-R39-S02 needs a real pilot.

### Not changed
- Every scenario `status` stays `NOT_EXECUTED`. Verdicts are recorded per release in `evidence/releases/<tag>/acceptance/`,
  as before.
- Requirements stay `planned`. The product, contracts, OpenAPI, routes and the lock hashes are unchanged.

### Known open clause
T-R15-S02 ("the matched rule IDs and input revision are recorded"): the IDs matched by the red-flag screen are not
recorded, only their level. This is a follow-up issue; the scenario stays NOT_PASSED.

## CHG-DEV-API-001

Type: API behavior, contract and test change (M03, M05, M06, M08, M09, M10, M11, M12; W06, A10, A11, A13), not a
release. Date: 2026-10-19. Issues: #261 to #276 and the server half of #305
(QA 2026-10-19). Decision: ADR-017 (amended, #276).

### Scope
- **Contract `TelemetrySnapshot`:** `consultations` gains the required `counted_from` and `counted_to` (the complete
  UTC days the outcome figures cover, #276); `ai_calls.by_task` gains `concern_check` (#271). Embedded copy in
  `spec/api/openapi.json`, contract cases in `tests/handoff/contract-cases.json` and `apps/web/src/api/schema.ts`
  regenerated (`npm run gen:api`).
- **OpenAPI descriptions:** `listCases.limit` documents its default 20 and `cursor` its keyset meaning (#266);
  `getProvider.search_id` documents 409 for a search that is not current and 404 for a provider not in it (#267).
  Both parameters already existed; no parameter, status code or operation was added.
- **Behavior now matching the contract or the state table:**
  - non-finite numbers (NaN, Infinity) and wrong-typed context values are 422 field errors; nothing is stored (#261,
    #262); a concern of only whitespace or invisible format characters is empty (422, #305);
  - interrupted jobs are settled at startup and a failed job submit rolls back (#263);
  - `editCase` corrects a case limited only for the missing warning-sign checklist (#264);
  - the PDF summary uses WinAnsiEncoding (#265);
  - `listCases` pages with `limit` and a keyset `next_cursor`; A13 offers "Show older consultations" (#266);
  - `getProvider` requires `search_id`; the web client sends it (#267);
  - guidance counts only intake answers (#268);
  - ScenarioLoaded reports the effective expiry, urgent guidance offers no doctor matching, never-generated guidance
    and sources are 404, a non-numeric Content-Length is 400 `MALFORMED_REQUEST` (#269);
  - provider search matches city and language case-insensitively and refuses unknown specialties (#270);
  - telemetry counts per running mode and knows the concern check (#271); outcome figures in complete UTC days (#276);
  - record bytes are written inside the committing transaction, orphan files are swept, uploads run off the event
    loop (#272);
  - `editCase` checks revision and state before any model call (#273);
  - SQLite `secure_delete` and a WAL checkpoint after every purge (#274);
  - events carry no urgency level and only the hour (#275).
- **Storage:** `events` and `jobs` gain a nullable `mode` column, added in place on start.
- **Tests:** `tests/acceptance` (R03, R04, R09, R10, R14, R15, R17, R24, R25, R26, R27, R29, R32, R34, R35, R36, R37,
  R38) and `tests/ui` (A11, A13, W06). Existing assertions changed where the issues changed the expected behavior:
  never-generated guidance is 404 (was 409), urgent events carry `RED_FLAG_DESCRIBED` (was the level), telemetry
  outcome checks move the activity to yesterday first, and getProvider calls pass `search_id`.

### Not changed
Every ID, route, operation and screen; reviewed clinical text; local-mode failure behavior (no fallback); requirement
and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-API-002

Type: API contract (additive), behavior, screen-contract, fixture, deploy and test change (M12; O03, A10; `loadScenario`,
`getJob`), not a release. Date: 2026-10-20. Issues: #315 and #316 (maintainer
request of 2026-10-20). Decision: ADR-016 amendment 1.

### Scope
- **Contract `LoadScenarioRequest`:** `reset` changes from `const true` to a boolean (`true` keeps the earlier
  behaviour; `false` adds the case to the presenter's live demo patient). New optional `prepare`: `start` (default,
  the earlier behaviour) or `result` (a quick demo prepared ahead of time).
- **Contract `ScenarioLoaded`:** new required `state` (the case state when the load returned), `next_path` (the
  patient-site path to open, `^/app/…`) and `prepare_job_id` (uuid or null).
- **Contract `Job`:** `kind` gains `scenario_prepare` and `result_type` gains `prepare_receipt` (the presenter-owned
  preparation job; `case_id` null; status and a content-free error code only).
- Embedded copies in `spec/api/openapi.json` (and the `loadScenario` description), contract cases in
  `tests/handoff/contract-cases.json` (7 new: 3 valid, 4 invalid) and `apps/web/src/api/schema.ts` regenerated
  (`npm run gen:api`). No operation, route, status code or parameter was added.
- **Behavior (M12, `apps/api/app/modules/operations/scenarios.py`):** reset=false joins the presenter's demo actor
  only while one of its sessions is still valid (an expired actor is never revived); prepare=result runs the reviewed
  questions with the fixture's synthetic answers, the review confirmation, guidance and, for a doctor result, the
  provider search through the patient services as the demo patient, in a presenter-owned job on its own workers
  (`JobRunner.submit_prepare`); a reset cancels a running preparation; a restart fails it with `INTERRUPTED`. Local mode
  keeps validation, the single repair and fail-closed handling; nothing is substituted on failure.
- **Fixture `fixtures/scenarios.json`:** `local_mode.quick` for `routine`, `selfcare` and `nomatch` (synthetic answers
  by template ID, the result screen, the doctor-search preset). The pack stays `synthetic` with
  `clinical_execution_enabled: false`. No reviewed clinical text changed.
- **Screen contract O03 (`spec/screens.json`, `spec/screens.yaml`):** content, primary action, three state variants
  (`quick_preparing`, `quick_ready`, `quick_not_ready`), two validation rules and the action contracts (Prepare quick
  demos, Show → A07/A10/A15/A16, Load scenario → A05/A15/A16, Reset). Route, ID and requirements unchanged.
- **Web:** O03 redesign (quick demos, full journeys, reset; named patient tab with link fallback); A10 runs a named
  search preset (`?preset=default|strict-plan`) when opened from a quick demo, since search results live in the tab's
  memory only and no read operation for a stored search exists; `PATIENT_ORIGIN` from the device script.
- **Deploy:** the presenter gateway's device script gains `patientOrigin` (`AWARECARE_PATIENT_ORIGIN`, set by
  `nano_deploy.py` from `network.browser_origin`, which must now be a plain http(s) origin); the API image declares the
  capability `quick-demos`; `flow_check.py` adds a model-free quick-demo check for such releases and checks older ones
  as before. Workflows unchanged; deployments stay manually triggered.
- **Docs:** ADR-016 amendment 1; `spec/engineering/08-delivery-and-nano-runbook.md` (presenter check).
- **Tests:** `tests/acceptance/test_R37.py` (16 new), `tests/ui/O03.spec.ts` (6 new, 1 changed),
  `tests/ui/intuitive2.spec.ts` (#234 intro text), `tests/tooling/test_flow_check_presenter.py` (4 new),
  `tests/tooling/test_second_device.py` (1 new, 1 extended).

### Not changed
Every ID, route, operation and screen; reviewed clinical text and order; local-mode failure behavior (no fallback, no
scripted substitute); presenter authorization (ADR-005 option A); requirement and acceptance statuses (`planned`,
`NOT_EXECUTED`).

## CHG-DEV-API-003

Type: API contract (additive), behavior, screen-contract and test change (M12; W06, W03; `getTelemetry`), not a
release. Date: 2026-10-20. Issues: #324, #325 and #331 (product review of
v0.10.0-demo.1, 2026-10-20). Decision: ADR-017 amendment of 2026-10-20.

### Scope
- **Contract `TelemetrySnapshot`:** `consultations` gains the required `counting_since` (date-time): the later of
  `counted_from` and the hour of the first event that records the running mode, when the data directory also holds
  events written before the mode was recorded; otherwise equal to `counted_from`; may be after `counted_to` (#324).
  Embedded copy in `spec/api/openapi.json`, the three TelemetrySnapshot contract cases in
  `tests/handoff/contract-cases.json` and `apps/web/src/api/schema.ts` regenerated (`npm run gen:api`). No operation,
  route, parameter or status code was added.
- **Behavior (M12, `apps/api/app/modules/operations/telemetry.py`):** computes `counting_since` from the content-free
  `events` table (hours only). The outcome window (complete UTC days before today), small-count suppression and
  per-mode counting are unchanged; rows without a mode are still never counted.
- **Screen contract W03 (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** primary action "See what is measured on this
  device" (W06); action contracts W06, W02, the local-processing chip (W06 privacy section) and "Explore the
  demonstration (presenter gateway only)" (O03); two validation rules (#331). Route, ID, requirements unchanged.
- **Screen contract W06:** one validation rule (no tile mixes windows; absolute complete-day windows; the counting
  start; honest empty states; #324, #325). Route, ID, requirements and actions unchanged.
- **Web:** `W06.tsx` (live group first, outcome group with absolute dates and empty states, breakdown and complete-day
  figures in Reliability, counting-start note, renamed per-call row, `/telemetry#privacy` lands on the privacy
  section, legend, build line and section links follow the figures); `W06Slide.ts` (By design badge; the footnote
  reserves the R39 sentence's lines); `W03.tsx` (By design chip linking to W06, public actions, presenter action only
  on the presenter gateway); `PresenterGate.tsx` exports its gateway check; `styles.css` (group titles, chip link).
- **Tests:** `tests/acceptance/test_R38.py` (3 new), `tests/ui/improve-telemetry.spec.ts` (8 new, both viewports),
  `tests/ui/W06.spec.ts` (1 changed: the task breakdown moved to Reliability; the window is stated as complete UTC
  days instead of "to the end of yesterday").
- **Docs:** ADR-017 amendment of 2026-10-20.

### Not changed
Every ID, route, operation and screen; the outcome-window rule (ADR-017 amendment of 2026-10-19); the price list and
assumptions (`infra/telemetry-pricing.json`, `infra/fury/telemetry-pricing.json`); reviewed clinical text, models and
prompts; the privacy boundary; requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-API-004

Type: API contract (additive), behavior, screen-contract and test change (M10, M03, M09; A12, A07; `getCase`,
`createExport`), not a release. Date: 2026-10-21. Issue: #356. Decision:
maintainer, 2026-10-21, on the v0.12.0 usability proposals: "yes", the visit summary includes the suggested level of
care and the doctors.

### Scope
- **Contract `CaseReadResponse`:** gains the optional `found_doctors` object (`search_id`, `data_mode` = `synthetic`,
  `doctors`: 1-3 items of `provider_id`, `name`, `specialties`, `practice`, `distance_miles`, `confirmed_matches`;
  closed objects). Present only when the case is `guided` with current non-urgent guidance and a current doctor
  search at the case's revision found at least one eligible doctor; otherwise absent. Embedded copy in
  `spec/api/openapi.json`, three contract cases in `tests/handoff/contract-cases.json` (one valid, two invalid: four
  doctors, an unlisted field) and `apps/web/src/api/schema.ts` regenerated (`npm run gen:api`). No operation, route,
  parameter or status code was added; existing fields are unchanged.
- **Behavior (M09, `apps/api/app/modules/providers/service.py`, `found_doctors`):** reads the stored current search
  (`provider_searches`, `current=1`, same `input_revision`) and returns at most its first three eligible (ranked)
  matches with the fixture's name, specialty and practice and the match's fictional distance and confirmed facts,
  exactly what A10 shows. Disclosed (ineligible) candidates are never listed. A clinical edit already retires the
  search (`cases/repository.py`), so a new revision has no doctors until the patient searches again.
- **Behavior (M03, `apps/api/app/modules/cases/service.py`):** `getCase` adds `found_doctors` when it exists.
- **Behavior (M10, `apps/api/app/modules/exports/service.py`):** the PDF adds "Suggested level of care" (heading
  "(AI-generated, check with a clinician)" in local mode, "(synthetic scripted outcome)" in mock mode) with the
  published guidance's level in A07's words (`LEVEL_LABELS` = A07 `URGENCY`), only when the guidance has a level; and
  "Doctors you found (fictional doctors from a synthetic directory)" with a fictional-doctors notice, one line per
  doctor (name · specialty · practice · fictional distance) and its confirmed facts, only when `found_doctors` exists.
  The doctors are taken in the same transaction that checks the revision and the guidance. Text is still WinAnsi
  (cp1252; "·" is in WinAnsi, dashes are mapped as before); both fonts keep `/Encoding /WinAnsiEncoding`.
- **Screen contract A12 (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** content names the two
  sections; one validation rule (#356). Route, ID, requirements, actions and states unchanged.
- **Web:** `A12.tsx` shows "Suggested level of care" (level text with its icon, labelled "AI-generated on this
  device" or "Scripted synthetic outcome") and "Doctors you found" (labelled "Fictional doctors", in A10's order,
  with confirmed facts), each as a named region and only when it exists; `A07.tsx` exports its level words and icons
  so both screens use the same; `styles.css` (neutral level badge on the summary; the doctors list).
- **Tests:** `tests/acceptance/test_R32.py` (5 new), `tests/ui/improve-summary.spec.ts` (2 new, both viewports),
  `tests/ui/colour.spec.ts` (1 changed: the summary's section titles include "Suggested level of care", five
  distinct icon tiles).

### Not changed
Every ID, route, operation and screen; the export expiry (15 minutes) and invalidation rules (a clinical edit revokes
an export; a new doctor search does not change the case revision, so an export made before it stays valid and a new
one includes the new doctors); reviewed clinical text, guidance wording, models and prompts; the privacy boundary
(no new request leaves the device; the fictional directory data was already served by `searchProviders` and
`getProvider`; nothing is kept in browser storage); requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-API-005

Type: API contract (additive), behavior, screen-contract and test change (M04; A05; `nextQuestion`), not a release.
Date: 2026-10-21. Issue: #357. Decision: maintainer decision of 2026-10-21 on the
v0.12.0 usability proposals: "yes" to a previous-question step.

### Finding (before the change)
The question order does not depend on answers. `next_question` (apps/api/app/modules/intake/service.py) issues the
first template of a fixed order that has not been issued yet: the scenario's fixture order in mock mode, and the
reviewed pathway's R12 order (urgency priority, then stable template ID) in local mode. Answers decide nothing about
which question comes next. `saveAnswer` already accepted a change to any issued, not invalidated question during intake
(revision-checked, one current answer per question, no slot allocated, the mock urgent signal honored during intake,
and in local mode every current answer read by the reviewed red-flag screen before guidance). So a changed earlier answer
leaves every later issued question and answer valid; nothing has to be discarded or re-issued. What was missing was a
way for A05 to obtain the earlier issued questions and their stored typed answers: the case read carries only display
values, and the issued question objects were kept only in browser memory.

### Scope
- **Contract `NextQuestionResponse` (kind `question`):** gains the optional `earlier_questions` array (at most 9) of
  `{question: Question, answer: Answer}`: the case's issued questions with a slot below the current one that are not
  invalidated, with their current answers, in slot order. Embedded copy in `spec/api/openapi.json`,
  `spec/contracts/NextQuestionResponse.schema.json` and `apps/web/src/api/schema.ts` (`npm run gen:api`). No operation,
  route, parameter or status code was added; existing fields are unchanged.
- **Behavior (M04, `intake/service.py`):** the list is read fresh on every question response, idempotent replays
  included, and is never written to the idempotency record, so no answer value is copied into another table. Slot
  issuance, the 10-slot cap, revision and idempotency checks, `saveAnswer`, urgent screening and the question order are
  unchanged.
- **Screen contract A05 (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** action contract "Previous
  question (change an earlier answer)" (A05, A15) and one validation rule. From question 2 on, "Previous question"
  shows the previous issued question with its saved answer filled in (same input; a skipped answer shows nothing chosen;
  an unknown answer shows the question's "Not sure" choice where it has one); it can be repeated back to question 1, and
  "Back to question n" returns without saving. Submit answer, Not sure and Skip keep their meaning: an unchanged answer
  returns to the current question without a request; a changed one is saved with `saveAnswer` at the current revision
  and the page returns to the current question with the choice made there and not yet sent. Before saving, the page says
  "Changing it keeps your later answers and the questions that follow." (no later answer is dropped, see the finding).
  The synthetic urgent signal (mock mode) on an earlier question routes to urgent help as on the current one. The
  heading of the shown question takes focus on every switch; the exact line "Question n of up to 10" names the shown
  question's slot.
- **Web:** `A05.tsx` (earlier questions, saved-answer prefill, unchanged check, kept draft, remembered issued questions
  for A06), `styles.css`.
- **Tests:** `tests/acceptance/test_R11.py` (7 new: earlier questions and answers, fresh replay without storing them,
  a change keeps later questions and answers, the cap with changes at every step, the urgent signal on a changed
  answer, stale revision 409, local-mode red-flag screen reads the changed answer); `tests/ui/improve-previous.spec.ts`
  (6 tests, both viewports). Registered in `spec/traceability.yaml` (R11, R15).

### Not changed
Every ID and route (25), operation and module; the question order, wording, options, red flags and levels of the
reviewed pathway and the mock fixtures; models and prompts; the privacy boundary (the answers go only to the case owner,
as in the case read); requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-API-006

Type: API contract (additive), behavior, screen-contract, web, deploy and test change (M12; O03; `loadScenario`), not a
release. Date: 2026-10-21. Issue: #358 (maintainer request of 2026-10-21).
Decision: ADR-016 amendment 2.

### Scope
- **Contract `LoadScenarioRequest`:** new optional `urgency_input`: `checklist` (default, the earlier behaviour: the
  scenario's own red-flag checklist answer) or `written` (the case gets only the scenario's written concern, with the
  checklist answered "none of these apply"). Embedded copy in `spec/api/openapi.json` (and the `loadScenario`
  description), `spec/contracts/LoadScenarioRequest.schema.json`, two contract cases in
  `tests/handoff/contract-cases.json` (1 valid, 1 invalid) and `apps/web/src/api/schema.ts` regenerated
  (`npm run gen:api`). No operation, route, status code, parameter or response field was added; the existing 503 now
  also carries `RED_FLAG_SCREEN_UNAVAILABLE` for this request.
- **Behavior (M12, `apps/api/app/modules/operations/scenarios.py`, `routes.py`):** with `urgency_input=written` in
  local mode the load runs createCase's red-flag screen of the concern (#153; `red_flag_screen` on the device's model,
  through the runtime adapter, outside any transaction, after a replay was ruled out). A match creates the case urgent
  with the level, rule IDs and revision recorded as createCase does, and the content-free `urgent_interrupt` event with
  `RED_FLAG_DESCRIBED`; no match creates an ordinary case at its questions; a screen that cannot run fails closed with
  503 `RED_FLAG_SCREEN_UNAVAILABLE` and creates nothing. Mock mode keeps the scripted outcome. Idempotency hashes of
  requests without `urgency_input` are unchanged.
- **Screen contract O03 (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** content, primary action, state
  variants (`flow_running`, `flow_shown`, `flow_failed` replace the three `quick_*` variants), two validation rules and
  the action contracts (Run on the device and Show again → A07/A15; Load scenario; Reset). The secondary view
  `/presenter/scenarios/more` is part of O03: no new screen ID, the 25 screen routes are unchanged.
- **Web:** O03 shows three one-click flows and one line of device status; one click opens the patient tab inside the
  click (a fresh one shows a one-line waiting note), loads the flow with `reset=false` and `prepare=result` (guidance
  flows) or `urgency_input=written` (warning sign), shows progress with the device name and the elapsed seconds
  (announced politely, seconds not announced), then moves the patient tab to the finished screen and offers "Show
  again". Failures are named, with "Nothing was substituted". Prepared quick demos, "Prepare quick demos", "How these
  demos work", their session storage and "Reset for next audience" are removed; full journeys and Reset demo moved to
  More scenarios. The presenter navigation lists Scenarios first, then Runtime, Controls, Telemetry and More scenarios.
  Styles reuse the existing tokens (no new colour).
- **Deploy:** the API image declares the capability `quick-flows`; `infra/deploy/flow_check.py` (via `nano_deploy.py`)
  then also checks, without a model call or a new case, that `urgency_input` is understood (an unknown scenario is
  refused 404, not 422). Older releases are checked as before. Workflows unchanged.
- **Docs:** ADR-016 amendment 2; `spec/engineering/08-delivery-and-nano-runbook.md` (presenter check).
- **Tests:** `tests/ui/improve-quick-flows.spec.ts` (8 new, both widths), `tests/acceptance/test_R37.py` (7 new),
  `tests/tooling/test_flow_check_presenter.py` (3 new); `tests/ui/O03.spec.ts` updated for the moved controls (the
  cited titles kept; the prepared-quick-demo tests removed with the feature), and navigation updates in
  `A07`, `colour`, `qa`, `intuitive2`, `improve-telemetry-dates` and `routes.layout` specs.

### Not changed
Every screen ID and its route, every operation, the reviewed clinical content, questions, red-flag list, prompts and
models; the privacy boundary (nothing leaves the device; the presenter reads only its load response and the prepare
job's content-free status); local-mode failure behavior (no fallback, no scripted substitute); presenter authorization
(ADR-005 option A); requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-API-007

Type: API contract (additive), behavior, screen-contract, web, device-record and test change (M12, M01; O01, O03, W06;
`getRuntime`, `resetDemo`, `loadScenario`, `createSession` cookie), not a release. Date: 2026-10-22. Issues:
#396, #422, #423, #424, #425, #426, #427, #428, #429, #430, #443, #460, #461,
#462, #470 (comprehensive QA of 2026-10-22, v0.14.0-demo.1, presenter group).

### Scope
- **Reset scope (#396, M12 `scenarios.py`, M01 `access/presenter.py`, `service.py`, `routes.py`, `core/db.py`):**
  presenter sessions started in one browser form a lineage, tied together by a new HttpOnly, SameSite=Strict
  presenter-gateway cookie `awarecare_presenter_lineage` (path `/api`, 7 days; only its hash is stored, in the new
  table `presenter_lineages`, without a foreign key so an ended session's actor still counts). `resetDemo` (and
  `loadScenario` with `reset=true`) removes every demo actor of the lineage and cancels its running quick-demo jobs, so a
  demo made under an ended earlier presenter session is removed too. Patient guest data and another presenter
  browser's demos are never touched (the `resetDemo` contract's "never delete another presenter run" holds). The reset
  that blocks a new demo (409 `RESET_PENDING`, 503 `RESET_FAILED`) is the lineage's last one; `reset=false` joins the
  lineage's live demo patient. No operation, route, status code or request field was added.
- **Contract `RuntimeSnapshot` (additive, required fields):** `observed_at` (when this response checked readiness and the
  queue), `device_inventory_observed_on`, `runtime_version` and `runtime_qualified_on` (local mode: the model manifest's
  runtime record and its last passed qualification; null in mock mode), `timings_latest_at`, and `demo`
  (`reset_status` none/running/succeeded/failed, `reset_finished_at`, `live_case_ids`: the lineage's demo cases whose
  demo patient still has a live session; IDs only). `TimingSummary` is unchanged; in mock mode `inference_ms` is null
  (no model runs) and the summary counts only the running mode's jobs. Embedded copies in `spec/api/openapi.json` (and
  the `getRuntime`/`resetDemo` descriptions), `spec/contracts/RuntimeSnapshot.schema.json`, `TimingSummary` description,
  and `apps/web/src/api/schema.ts` regenerated (`npm run gen:api`).
- **Device record (#429):** `infra/device-inventory.json` is a new read-only observation of the Nano
  (`nano-observed-2026-10-22`, evidence `evidence/operations/2026-10-22-nano-inventory/observation.txt`): ZRT 0.43.0,
  snap revision x4, serving the selected model; the 2026-10-13 snapshot predated the ZRT upgrade, the model and the
  app. Device, driver, ZRT, model and service configuration are unchanged. A backend test keeps each device's inventory
  in step with its model manifest's runtime record (Nano and Fury).
- **Screen contracts (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** O01 one validation rule
  (provenance and observation times; scripted mock timings); O03 four validation rules (lineage reset; server truth
  for the blocked state and for Show again; runs that survive leaving or reloading; truthful status text and accessible
  names); W06 one rule (opened from the presenter tools it renders in the presenter shell at `/presenter/telemetry`,
  the same screen: no new screen ID, the 25 screen routes are unchanged).
- **Web:** O03's one-click runs live in `apps/web/src/components/presenterRuns.ts` (sessionStorage per tab: flow,
  times, the load's idempotency key, case and job IDs, the patient-site path; no patient content). Leaving the page never
  stops a run; a reload of any presenter page replays the load with the same idempotency key and follows its prepare job
  (#423). Load scenario waits while a flow runs (#424). The blocked banner and disabled controls follow the server's
  `demo.reset_status` on both views, after a reload and in every tab (#425); an ended presenter session shows the
  presenter gate on Run, Load and Reset, never a reset failure or a raw code, and presenter job polls no longer trigger
  the patient expiry redirect (#422, #460). Show again checks `demo.live_case_ids` first; an ended or reset demo says
  "Expired: run it again", and a reset in another presenter tab moves this tab's patient tab to the start page (#426).
  The Loaded banner says only what happened (#430); the running button's accessible name starts with "Running…"
  (#443); durations read "under 0.1 s"/"0.4 s", one pair of parentheses, Run buttons aligned by a CSS subgrid (#462).
  O01 shows the observation time, the inventory date, the serving runtime and its qualification date, and labels mock
  timings scripted without an Inference row (#428, #429). On the presenter gateway the brand link and the footer and
  navigation Telemetry links stay in the presenter tools; patient pages there say they belong to the patient site and
  link to it; the public navigation offers "Presenter tools" (#427, #470). The presenter gate explains a refused
  `localhost` address and links the 127.0.0.1 one (#461). Every write's error banner on both gateways turns
  `ORIGIN_REJECTED` into the configured address, the two-port tunnel and the `--origin`/`--presenter-origin`
  (`network.browser_origin`/`network.presenter_origin`) settings (#461 extension).
- **Deploy (#461):** the patient gateway's `/aware-care-device.js` also carries `patientOrigin` (its configured
  `browser_origin`), and the presenter's also `presenterOrigin`; `nano_deploy.py` passes `AWARECARE_PATIENT_ORIGIN` to
  every web container and `AWARECARE_PRESENTER_ORIGIN` with the presenter gateway, and refuses a `presenter_origin` that
  is not a plain http(s) origin (as it already did for `browser_origin`). The web image defaults both to empty; older
  images ignore them. Workflows unchanged.
- **Tests:** `tests/acceptance/test_R37.py` (9 new), `tests/ui/O03.spec.ts` (15 new, both widths; two existing bodies
  updated with their cited titles kept), `tests/ui/O01.spec.ts` (2 new), `tests/tooling/test_second_device.py` (1 new),
  updated expectations in `improve-quick-flows.spec.ts` and `colour.spec.ts` (#259: three timing rows in mock mode).

### Not changed
Every screen ID and its 25 routes, every operation ID, the reviewed clinical content, prompts and models; presenter
authorization (ADR-005 option A: the gateway assertion still decides the role; the lineage cookie authorizes nothing by
itself); the privacy boundary (the presenter reads only its load responses, its jobs and content-free demo IDs);
local-mode failure behavior; requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-API-008

Type: deployment, gateway, cookie-scope, screen-contract, web and test change (M01, M12; W01, W03, O01-O03; R01, R03,
R37; ADR-005 amendment), not a release. Date: 2026-10-22. Issue: #487.

### Request
"different ports for patients and presenters are so confusing, just create one home page perfectly. you will have 2
options on that main page either patient or presenter" (maintainer).

### Scope
- **Gateway (one port, one origin; ADR-005 amendment):** the separate presenter listener on 8181
  (`infra/deploy/presenter.conf.template`) is removed. `infra/deploy/web.conf.template` is the one gateway for both
  roles on 8180 (forwarded as 18180, origin `http://127.0.0.1:18180`):
  - `/api/` strips any `X-AwareCare-Presenter` header, as the patient gateway did;
  - `/presenter-api/` (`infra/deploy/presenter-api.conf.template`) signs a fresh assertion with
    `infra/deploy/presenter.js` exactly as the presenter gateway did, proxies to the API's `/api/` and adds
    `X-AwareCare-Gateway: presenter` to these responses only;
  - without presenter access, `/presenter-api/` answers `403 PRESENTER_REQUIRED` itself
    (`infra/deploy/presenter-api-disabled.conf`) and never reaches the API.

  `25-aware-care-presenter.sh` always renders one of the two into the server block. It enables the signing path only
  when `AWARECARE_PRESENTER_ENABLED=1`, the key is readable and `AWARECARE_WEB_BIND` is loopback. The root `/` is the
  app's home page; the presenter port's redirect to O03 (#326) is gone. The device script names the one address
  (`origin`, from `AWARECARE_ORIGIN`). `patientOrigin`, `presenterOrigin` and `AWARECARE_PRESENTER_ORIGIN` are removed.
- **API:** the trust rules are unchanged: key file, trusted loopback peer, 60 s freshness, single-use nonce for session
  creation, the per-request presenter check and the separate cookies. One change: every cookie is scoped to `/` instead
  of `/api` (`COOKIE_PATH` in `app/core/security.py`). The browser then sends it to both prefixes, as it sent it to
  both ports before. The cookies are the pre-session nonce, the patient and presenter sessions, the presenter lineage,
  and the removal of a session cookie. The allowed origins are the one origin.
- **Deploy tool (`infra/deploy/nano_deploy.py`):**
  - It opens no presenter port. The API container gets one allowed origin. The web container gets
    `AWARECARE_WEB_BIND` (from `network.bind_host` or the new `--bind-host`, default `127.0.0.1`), `AWARECARE_ORIGIN`
    and `AWARECARE_PRESENTER_ENABLED`.
  - **Loopback guard:** it refuses a presenter key together with a non-loopback bind, first in the preflight, before
    any pull or container change. Presenter access must not reach a network without ADR-005's still-open TLS / mTLS
    control.
  - Older settings stay readable: `network.presenter_port`, `network.presenter_origin` and
    `network.presenter_tunnel_example`, and the hidden `--presenter-port` and `--presenter-origin`, are accepted and
    ignored. They are logged and named in the evidence (`presenter.ignored_legacy_settings`).
  - Evidence `presenter` records `path`, `origin` and `bind` instead of a port. Releases from before the path report
    `NOT_SUPPORTED_BY_RELEASE`.
  - `demo-zgx-nano.json` and `demo-zgx-fury.json` drop the presenter port, origin and tunnel and add
    `presenter.path`. `infra/device-inventory.json` lists 8180 as the one gateway.
- **Deploy checks (`infra/deploy/flow_check.py`):** `presenter_check(base_url, origin, mode, …)` drives both roles
  through one address: `/presenter-api/v1` must identify itself; `/api/v1` must not; a forged header on `/api/v1`
  gives an ordinary guest session and `403 PRESENTER_REQUIRED`; the O03 handoff continues on `/api/v1`; the device
  script names the configured `origin`. New `--presenter` runs this model-free check from the command line.
- **Release scripts:**
  - `scripts/release/host_checks.sh` checks the one gateway: headers, gzip on both API paths, the root, the presenter
    path's hint, and that 8181 is closed.
  - `scripts/release/deployed_checks.sh` adds the presenter check through 18180 (`presenter-check.json`).
  - `scripts/release/dispatch_deploy.sh` prints the presenter path.
  - `deploy-nano.yml` and `deploy-fury.yml` name the presenter path in their summaries.
  - The CI package smoke test deploys without `--presenter-port` and `--presenter-origin`.
- **Web:**
  - **W01 (`/`):** two large choices, Patient (`ConsultationLink`: Start a new consultation or Continue consultation,
    A01) and Presenter (Open the presenter tools, O03, quick flows first). The page keeps the demo notice, urgent help,
    HP branding, the on-device story and the three steps. Each card has one named link. Its surface follows the link for
    a pointer. Both widths are covered, and the new colour pairs are in `scripts/check_contrast.py`.
  - **`apps/web/src/api/client.ts`:**
    - The role of a request follows its page: `/presenter/...` pages use `/presenter-api/v1`, every other page
      `/api/v1`. The page is read at every request, so reloads, deep links and in-app navigation agree.
    - The presenter operations (`getRuntime`, `getControls`, `loadScenario`, `resetDemo`) and the presenter gate's
      `createSession` always name the presenter role. So do a running quick flow's job polls (`pollJob` `role`), which
      may outlive their page.
    - The CSRF token and "session known" are kept per role. The expiry warning and its cross-tab channel follow the
      patient session only.
  - **Removed:** `servedByPresenterGateway`, the `X-AwareCare-Gateway` store, `PATIENT_ORIGIN`/`patientOriginFrom`,
    `presenterAddressFrom`, the two-port tunnel and the "This is the presenter address" notice (`PatientSiteNotice`).
  - O03 and `presenterRuns.ts` open the patient tab at `/app/...` on the same address.
  - The presenter gate asks `/presenter-api` whether presenter access is offered. Without it the gate says that
    presenter access is not enabled and links the home page.
  - The presenter toolbar links "Home: patient or presenter".
  - `OriginHelp` names the one configured address and the one tunnel. W03 drops "Explore the demonstration". The
    not-found page offers Presenter scenarios in the presenter layout only.
- **Dev and test stacks:** `apps/web/vite.config.ts` proxies `/api` (header stripped) and, with
  `AWARECARE_PRESENTER_KEY_FILE`, `/presenter-api` (signed, rewritten to `/api`). Without a key, `/presenter-api`
  answers like the disabled gateway. `apps/web/playwright.config.ts` runs one production build on 15174 with the
  throwaway key; 15175 is gone. The device specs (`tests/devices/`) use 18180 for both roles and enter the presenter
  tools through the home page.
- **Screen contracts (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):**
  - W01: content, primary action, one validation rule and the action "Open the presenter tools" to O03.
  - W03: the presenter-only action is removed and its rule reworded.
  - O03: the patient-tab rule names the same address.

  No screen ID or route is added: 25 routes.
- **Documents:** ADR-005 amendment ("from a port to a path", the equivalence argument and the loopback guard),
  `open-decisions.md`, runbook `08-delivery-and-nano-runbook.md` (sections 2, 5, 10, 10c), `07-nano-zrt-operations.md`,
  README, `apps/web/README.md`, `tests/ui/README.md`, Wiki (Architecture, Troubleshooting, Product Overview, Release
  and Deployment, Testing, Local Development).

### Not changed
- Every screen ID, the 25 routes, every operation ID, request and response schema and status code.
- Presenter authorization: the assertion format, key, freshness, nonce, trusted peers, the per-request check and the
  separate cookies.
- The reviewed clinical content, prompts and models; local-mode failure behavior; TLS, drivers, CUDA, ZRT, system
  Python and host services.
- Requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).
- Cited test titles are kept. The bodies of `O01.spec.ts` "the patient site shows presenter tools as unauthorized and
  offers no presenter session" (now a device without presenter access) and the "stays unauthorized" tests (now: no
  presenter data without a presenter session) follow the one address.

## CHG-DEV-APP-001

Type: development application scaffold (mock mode), not a release.
Date: 2026-10-13. Baseline 2.0 unchanged. Decisions: `../decisions/ADR-007-dev-mock-build.md`.

### Scope
- `apps/api`: FastAPI app `app.main:app` (127.0.0.1:8000, prefix `/api/v1`) with all 31 baseline operation IDs,
  SQLite store, session/Origin/CSRF/consent guards, idempotency, revisions, intake slot accounting, mock
  guidance jobs via the runtime adapter interface, factual provider matcher, PDF export, deletion/retention.
  Mock and ZRT providers live beside the unchanged `app/runtime/adapter.py` interface.
- `apps/web`: React/TypeScript/Vite app (127.0.0.1:5173, `/api` proxied with prefix preserved) with the 24
  canonical screens and `src/routes.tsx`; API types generated from `spec/api/openapi.json`.
- `tests/acceptance`: executed backend acceptance tests for R01, R02, R08, R11, R15, R24, R26, R29, R32, R35, R37.

### Specification files changed
- `spec/traceability.yaml`: registered every new runtime file under `shared_files`; existing planned module
  `routes.py`/`schemas.py` entries that now exist were marked `implemented` with their executed tests.
  Requirement statuses remain `planned`; no requirement, screen, operation or contract identity changed.
- `spec/lock.json`: `traceability_sha256` refreshed for this change only. Product, contract and screen hashes unchanged.
- Added `spec/decisions/ADR-007-dev-mock-build.md` and this record.

### Not changed
`spec/product.md`, `requirements.json`, `screens.json`, `openapi.json`, contracts, acceptance statuses
(still `NOT_EXECUTED` in `spec/acceptance.json`), fixtures, infra records, ZRT, drivers, existing services.

### Evidence
`evidence/dev/CHG-DEV-APP-001-run.md` records the commands actually run and their results. There is no Git
commit for this working tree, so no result qualifies as release evidence.

## CHG-DEV-APP-002

Type: Milestone 1 completion for the development application (mock mode). Not a release.
Date: 2026-10-13. Baseline 2.0 unchanged. Decisions: `../decisions/ADR-008-m1-patient-branches.md`.

### Scope
- M05 `apps/api/app/modules/safety/service.py`: explicit mock urgent fixture trigger (`is_urgent_fixture_trigger`) and
  R14 information limits (`apply_information_limits`, reason code `LIMITED_INFORMATION`).
- M04 `apps/api/app/modules/intake/service.py`: urgency recheck on `saveAnswer`. The urgent interrupt invalidates the
  prompt, keeps its slot, bumps the revision and sets state `urgent`.
- M08 `apps/api/app/modules/guidance/service.py`: applies the information limits before publish.
- Web: A05 adds the mock label and "Simulate urgent answer". A07 adds the limited-information banner. A07, A12 and
  A15 add reset/another-case actions (`components/ResetActions.tsx`). A01 adds the pre-session nonce retry
  (direct-load bug) and the reset confirmation. A05 routes "review" through `nextQuestion` (ADR-008 #7).
  `api/client.ts` recovers the CSRF token after a reload (ADR-008 #8). `vite.config.ts` gains env-only port/target overrides.
- Tests: `tests/acceptance/test_R14.py` (new), `test_R15.py` (patient-path urgent cases), `test_R35.py` (fixed a
  race in the test's own wait loop). New browser tests `tests/ui/{A01,A05,A06,A07,A10,A11,A12,A15}.spec.ts` with
  `tests/ui/support/journey.ts`, run by `apps/web/playwright.config.ts` (`npm run test:ui`).
- Dev dependencies (apps/web only): `@playwright/test`, `@types/node`. The Playwright Chromium build lives in the
  user cache `~/.cache/ms-playwright`; no system packages were installed.

### Specification files changed
- `spec/traceability.yaml`: registered the new runtime/test files; updated statuses of now-existing planned paths.
  Requirement statuses remain `planned`.
- `spec/lock.json`: `traceability_sha256` only, via `scripts/update_spec_lock.py --change-id CHG-DEV-APP-002`.
- Added ADR-008 and this record.

### Not changed
`spec/product.md`, `requirements.json`, `screens.json`, `openapi.json`, contracts, `acceptance.json` statuses,
fixtures, infra, ZRT, drivers, the running dev services (8000/5173) and their data.

### Evidence
`evidence/dev/CHG-DEV-APP-002-run.md`. No commit identifies this working tree yet, so it is not release evidence.

## CHG-DEV-APP-003

Type: Milestone 2 (full patient experience) for the development application, mock mode. Not a release.
Date: 2026-10-13. Baseline 2.0 unchanged. Decisions: `../decisions/ADR-009-m2-records-and-context.md`.

### Scope
- M06 records: `apps/api/app/modules/records/{service,routes,schemas}.py` cover validated upload, opaque storage,
  the extraction job (bundled synthetic sample only, in mock mode), the review list and confirm/correct/reject.
  `core/db.py` adds the `documents` and `fact_reviews` tables. `core/fixtures.py` loads byte-keyed record samples.
- M03: `cases/repository.py` returns confirmed-only facts. `cases/service.py` validates profile context and now
  scopes context edits to profile facts (answer-erasure defect).
- M04: `intake/schemas.py` uses strict scalars (bool-coercion defect).
- M11: `privacy/service.py` purges record bytes on deletion and retention sweep.
- Fixtures: new `fixtures/records/` (synthetic sample, unreadable sample, manifest) and the generator
  `scripts/make_sample_records.py`. Existing fixture files are unchanged.
- Web: A04 rebuilt (sample upload, document status, fact review). A06 labels confirmed record facts. A14 handles
  end-session failure and the delete label. `components/ui.tsx` adds the page-level `EmptyState`, used by the
  whole-page empty states in A04-A08 and A10-A12. `api/client.ts` adds multipart upload and `reviewFact`.
  `vite.config.ts` adds `fs.allow` for `fixtures/records`. `styles.css` adds empty-state h1 sizing.
- Tests: new `tests/acceptance/test_R03,R04,R06,R09,R10,R13,R18,R19,R20,R27,R33,R36.py` with `records_helpers.py`,
  and record purge cases in `test_R35.py`. New browser specs `tests/ui/W01-W05, A02, A03, A04, A08, A09, A13, A14,
  A16.spec.ts` and `routes.layout.spec.ts`. All 21 public/patient screens now have a primary spec.

### Specification files changed
- `spec/traceability.yaml`: registered new helpers and shared tests; records files moved to `implemented` with
  their tests. Requirement statuses remain `planned`.
- `spec/lock.json`: `traceability_sha256` only, via `scripts/update_spec_lock.py --change-id CHG-DEV-APP-003`.
- Added ADR-009 and this record.

### Not changed
`spec/product.md`, `requirements.json`, `screens.json`, `openapi.json`, contracts, `acceptance.json` statuses,
existing fixture files, infra, ZRT, drivers, the running dev services and their data.

### Evidence
`evidence/dev/CHG-DEV-APP-003-run.md`. Uncommitted working tree; not release evidence.

## CHG-DEV-APP-004

Type: application change (M01, M11), not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #42 (ADR-013).

### Scope
- **API:**
  - `apps/api/app/core/security.py`, `apps/api/app/main.py` and `apps/api/app/modules/access/routes.py`: every
    response to an authenticated request (except 401) carries `X-Session-Expires-At`, the session's expiry after the
    request; `createSession` carries it too.
  - `apps/api/app/modules/privacy/routes.py`: `deleteSession` reports none, because the session has ended.
- **Web:**
  - `apps/web/src/api/client.ts`: keeps the latest expiry and the server clock offset; `probeSession` reads it after
    a page load.
  - `apps/web/src/components/SessionExpiryWarning.tsx` (new, in the patient shell `Layout.tsx`): the warning 2
    minutes before the end; "Stay signed in" (one read, never past 8 hours); the 8-hour limit message; Dismiss; and
    "Your session has ended".
  - `styles.css`.
- **Spec:**
  - `spec/api/README.md`: a declared wire refinement row.
  - `spec/decisions/ADR-013-session-expiry-signal.md`.
  - `spec/traceability.yaml`: the component and `tests/ui/SessionExpiry.spec.ts` under R36.
  - `spec/lock.json`: refreshed with `update_spec_lock.py --change-id CHG-DEV-APP-004`.
- **Tests:**
  - `tests/acceptance/test_R36.py`: three tests (the sliding expiry, never past the absolute limit, no header without
    a live session);
  - `tests/ui/SessionExpiry.spec.ts`: five tests with a controlled page clock.

### Not changed
- **The contract:** `spec/api/openapi.json`, the 31 operations and the contracts. The header is transport, like
  `X-CSRF-Token`.
- **The session limits:** 30 minutes idle and 8 hours absolute.
- **Saved-account retention**, which stays blocked by ADR-005.

## CHG-DEV-APP-005

Type: application, API contract (relaxed field rule), screen-contract and test change (M01-M05, M08, M11; A02-A07,
W04-W06), not a release. Date: 2026-10-22. Baseline 2.0 unchanged. Issues (comprehensive QA of 2026-10-22, journey
group): #392, #388, #408, #409, #410, #411, #449, #412, #413, #415, #450, #451,
#452, #453, #399, #404. #414 is not part of this change (see "Not changed").

### Scope
- **Contracts `CaseWrite` and `Case` (#392, R15):** `concern` loses `minLength: 1` (still at most 4000 characters) and
  gains a description: required unless the `red_flags` checklist answer ticks a reviewed warning sign; the case then goes
  to urgent help at once and a concern that was not written is stored empty. Embedded copies in `spec/api/openapi.json`;
  `apps/web/src/api/schema.ts` regenerated (`npm run gen:api`, no type change). No operation, route, parameter or status
  code changed. R07's canonical acceptance (a valid 1-4000 character concern creates revision 1) is unchanged.
- **API behavior:**
  - `cases/service.py` `createCase` (#392): with a ticked reviewed sign a blank concern is stored as `""` and the case is
    urgent at the reviewed level, with no model call; without one the concern stays required (422 `concern`/`empty`).
  - `cases/service.py` `meaningful` (#452): besides whitespace, Cc and Cf, the default-ignorable code points (for example
    U+00AD, U+034F, U+115F/U+1160, U+3164, U+FFA0, variation selectors) and the Braille blank U+2800 alone are empty.
  - `cases/service.py` `editCase` (#411): a concern saved unchanged with no context change is a no-op: no revision, no
    state change, the review and derived results stay.
  - `cases/repository.py` `facts` (#449): answers are listed in question (slot) order; other facts keep their places.
- **Screen contracts (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** validation rules on A02 (#410,
  #451), A03 (#392, #408, #412, #452), A04 (#413, #450), A05 (#404), A06 (#388, #411, #449), A07 (#415, #453) and W04,
  W05, W06 (#399); the A03 rule "Require one concern" now has the urgent-sign exception.
- **ADR-013 amendment (#399, #409):** the session warning also on the public pages; tabs share the latest expiry
  (same-origin `BroadcastChannel`, two times only, memory only); "Your session has ended" only after a quiet read
  returns 401.
- **Web:** `A02.tsx` (unsaved-entries blocker and `beforeunload`, digits-only age), `A03.tsx` (session check before the
  form, urgent sign without a concern, wider blank set and the server's `empty` as a field error, no-profile notice),
  `A04.tsx` (local-mode notice without upload buttons, upload only with `upload_record`, Continue to the current step),
  `A05.tsx` (`aria-invalid`/`aria-describedby` on the answer, text label names the question), `A06.tsx` (editor
  pre-filled from the answer fact, unchanged saves send nothing, after a concern edit the case is asked for its next
  step), `A07.tsx` (no "Back to review" on the preparing and failed views; the wait counts from the job's
  `created_at` or the case's change into generating), `A13.tsx` (an empty concern reads "No concern written"),
  `A16.tsx` ("Start a new consultation" to `/app/new`, like the header link), `Layout.tsx` (the warning in
  `PublicLayout`), `SessionExpiryWarning.tsx`, `api/client.ts` (`pollJob` read callback; cross-tab expiry).
- **Tests:** `tests/acceptance/test_R15.py` (2), `test_R04.py` (1), `test_R09.py` (2); `tests/ui/A02.spec.ts` (2),
  `A03.spec.ts` (4), `A04.spec.ts` (2), `A05.spec.ts` (1), `A06.spec.ts` (3), `A07.spec.ts` (2), `SessionExpiry.spec.ts`
  (#399, #409; the "ended" test now has the server confirm the end; "public pages show no session warning" became
  "... without a session"), `qa.spec.ts` (#278 leaves A07 through the navigation). Both viewports.
- `spec/lock.json`: refreshed with `update_spec_lock.py --change-id CHG-DEV-APP-005`.

### Not changed
- Every ID and route (25), operation (32) and module; the session limits; the reviewed pathway (questions, options,
  order, red flags, levels, messages) and the mock fixtures; models and prompts; ZRT, drivers and device configuration.
- **#414 (question explanations):** the "why" reasons of Q01/Q04 and the "this example" wording of Q04/Q10 live in the
  reviewed package `content/pathways/general-adult-4/questions.json` (verbatim from the ADR-003 review, enforced by
  `tests/acceptance/test_R12.py`, and mirrored in `fixtures/questions.json`). Changing them needs a new package version
  with a clinical review record (`content/pathways/README.md`), which cannot be created without the reviewer; left for a
  clinical decision.
- Requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-CI-001

Type: delivery workflow (CI, manual arm64 release, manual ZGX Nano deployment), not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #3.
Decisions: `../decisions/ADR-010-delivery-workflow.md`. Runbook: `../engineering/08-delivery-and-nano-runbook.md`.
Affected IDs: R34, R37, R38, R40; M12. No screen, route, operation, schema or application code changes.

### Scope
- `.github/pull_request_template.md`: issue link, requirement/contract IDs, change summary, actual validation
  evidence, deployment considerations.
- `.github/workflows/ci.yml` (PRs to and pushes on `main`): actionlint/shellcheck; traceability (full and
  changed files); contracts; backend acceptance (mock); generated API types; web typecheck and build; browser UI
  (mock); package smoke test of both images through `nano_deploy.py`; and the CI gate.
- `.github/workflows/release.yml` (manual): verifies the commit and its CI result, re-runs the gates on arm64,
  pushes `linux/arm64` images to GHCR, then creates an annotated tag carrying the manifest and a draft prerelease
  with `release-manifest.json`, `package-digests.txt` and the JUnit report.
- `.github/workflows/deploy-nano.yml` (manual, at a release tag): explicit `mock`/`local` mode, environment
  `demo-zgx-nano`, serialized, digest-pinned pull, readiness and flow checks, deployment evidence, automatic and
  documented manual rollback.
- `infra/deploy/`: `demo-zgx-nano.json` (deployment configuration), `api.Dockerfile`, `web.Dockerfile`,
  `nginx.conf`, `web.conf.template`, `build_images.sh`, `nano_deploy.py`, `flow_check.py`, `release_manifest.py`.
  Plus `.dockerignore` (allowlist build context).
- `spec/engineering/08-delivery-and-nano-runbook.md`, `spec/decisions/ADR-010-delivery-workflow.md`, this record,
  and a README section.

### Specification files changed
- `spec/traceability.yaml`: the 13 new workflow and `infra/deploy` files are registered under `shared_files`
  (R34/R37/R38/R40 as applicable, per product.md "Machine checks and review"), status `implemented`, with no
  direct acceptance tests. Their executed checks are the CI package smoke job and the runs in the evidence file.
  Requirement statuses remain `planned`.
- `spec/lock.json`: `traceability_sha256` only, via `scripts/update_spec_lock.py --change-id CHG-DEV-CI-001`.

### Not changed
`spec/product.md`, `requirements.json`, `screens.json`, `openapi.json`, contracts, `acceptance.json` statuses
(still `NOT_EXECUTED`), application code under `apps/`, fixtures, `infra/deployment.yaml` and the other infra
records, ZRT, drivers, CUDA, the Docker daemon configuration, the running development servers and their data,
repository and organization settings, environments, variables and runners.

### Evidence
`evidence/dev/CHG-DEV-CI-001-run.md`. This is a development run record, not release evidence. No release was
created and no deployment to `demo-zgx-nano` was triggered.

## CHG-DEV-CI-002

Type: delivery and process tooling (CI and local merge helpers), not a release.
Date: 2026-10-21. Baseline 2.0 unchanged. Issues: #365, #369, #370.
Decisions: `../decisions/ADR-010-delivery-workflow.md` (CI), `../decisions/ADR-011-wiki-before-closure.md` (Wiki).
Affected IDs: R34, R40; M12. No screen, route, operation, schema, contract or application code changes.

### Scope
- `.github/workflows/ci.yml` (#365): the browser UI job runs as 4 parallel matrix jobs (Playwright `--shard=i/4`
  over both projects, one worker each, unchanged retries and timeouts, each on its own runner so the isolated
  stack's fixed ports stay valid). Each shard uploads a blob report; the new `ui-report` job ("Browser UI tests
  (mock)") merges them with `playwright merge-reports` into the one JSON report under the unchanged artifact name
  `browser-ui-report` (`ui-report.json`), refuses a missing shard and fails unless every shard passed.
- `.github/workflows/ci.yml` (#369): new "Dependency audit" job: `npm audit --omit=dev` on `apps/web`
  (high or critical fail) and `pip-audit` (pinned by `PIP_AUDIT_VERSION`) on the requirements exported from
  `apps/api/uv.lock` with hashes (any known vulnerability fails; pip-audit has no severity). A failed lookup fails.
- The CI gate requires every job, now including `ui-report` and `audit`. Same runner expression, same pinned
  actions, `contents: read` everywhere, no secrets, no new triggers. Release and deploy workflows are unchanged.
- `scripts/dependency_audit.py` and `.audit-ignore.json` (#369): the audit decision and the dated ignore list
  (`id`, `ecosystem`, `package`, `reason`, `expires`); an expired or malformed entry fails. The list is empty.
- `apps/api/uv.lock` (#369): certifi 2026.7.22 to 2026.10.19 for PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2
  (critical; compromised emSign intermediate CAs), found by the first audit. Lockfile only; no code change.
- `.gitattributes` and `scripts/merge_wiki_log.py` (#370): the paragraph-union merge driver `wiki-union` for
  `docs/wiki/Issue-Work-Log*.md` (including future monthly archive pages) and `docs/wiki/Product-Overview.md`.
  Git's built-in `merge=union` is not used because it cuts entries apart. Local merges and rebases only, after
  `python3 scripts/merge_wiki_log.py --install`; without it git merges as before.
- `scripts/refresh_spec_lock.sh` (#370): after a rebase, regenerates `spec/lock.json` with
  `update_spec_lock.py --change-id` for each change record the branch adds, then runs `check_traceability.py`.
- Tests: `tests/tooling/test_workflows.py` (job structure, gate, merge step), `test_dependency_audit.py`,
  `test_merge_tools.py`. Docs: README (CI table, lock refresh, merge driver setup) and runbook section 1.

### Specification files changed
- `spec/traceability.yaml`: `scripts/dependency_audit.py` (R34, R40), `scripts/merge_wiki_log.py` (R40) and
  `scripts/refresh_spec_lock.sh` (R40) are registered under `shared_files`, status `implemented`, with their tooling
  tests; the `ci.yml` note names this record. Requirement statuses are unchanged.
- `spec/lock.json`: `traceability_sha256` only, via `scripts/update_spec_lock.py --change-id CHG-DEV-CI-002`.

### Not changed
`spec/product.md`, `requirements.json`, `screens.json`, `openapi.json`, contracts, `acceptance.json` statuses,
application code, `apps/web/playwright.config.ts`, the release evaluation, `release.yml`, `deploy-*.yml`,
`wiki-completion.yml`, repository settings, rulesets (the required check stays "CI gate"), variables and runners.

### Evidence
Local runs only (development record, not release evidence): the sharded suite and the merged report against the
release evaluation, both audits, and the merge-tool tests and replay. The CI wall time is measured on the first
push to `main` after merge.

## CHG-DEV-DEC-001

Type: decision preparation, documentation only. Not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #11. Next task: #14.

### Scope
- `spec/decisions/ADR-005-presenter-access-proposal.md` and `ADR-006-presenter-identity-and-scenarios-proposal.md`:
  proposals, status Proposed.
- `spec/decisions/ADR-002-model-qualification-protocol.md`: qualification stages and gates; no model selected.
- `spec/decisions/ADR-003-clinical-review-packet.md` and `ADR-004-corpus-review-packet.md`: what each owner must approve.
- `spec/decisions/open-decisions.md`: status table appended; the original table is unchanged.
- Wiki Product Overview and Issue Work Log.

### Specification files changed
Decision records only. No requirement, screen, operation, schema, acceptance or traceability change, so the lock is
unchanged.

## CHG-DEV-DEC-002

Type: decision record, documentation only. Not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #14 (first acceptance
criterion). Decision: ADR-005 option A (SSH-gated presenter gateway) accepted for milestone 3.

### Scope
- `spec/decisions/ADR-005-presenter-access-proposal.md`: status Accepted (option A) and a Decision section listing
  the decider, accepted consequences and the follow-ups that remain open. The filename is kept so existing links
  stay valid.
- `spec/decisions/open-decisions.md`: ADR-005 row and closing sentence.
- Wiki Product Overview decision table.

### Specification files changed
Decision records only. No requirement, screen, operation, schema, acceptance or traceability change; lock unchanged.

### Not changed
Application code, deployment, ADR-006 (still proposed), and every other open decision.

## CHG-DEV-DEV2-001

Type: new runtime and delivery file registration, configuration and test change (second device; R24–R27, R34, R37,
R38, R40), not a release. Date: 2026-10-18. Issue: #141. Decision: ADR-018.

### Scope
- **New files**, registered in `spec/traceability.yaml`:
  - `.github/workflows/deploy-fury.yml` and `infra/deploy/demo-zgx-fury.json`: the `demo-zgx-fury` target;
  - `infra/fury/model-manifest.json`, `device-inventory.json` and `telemetry-pricing.json`: the Fury's model,
    inventory and prices;
  - `infra/fury/zrt/serve-model.sh` and `aware-care-zrt-model.service`: operator assets, not part of any image;
  - `apps/web/public/aware-care-device.js`: the default device, the Nano.
- **Changed:**
  - **API:** `AWARECARE_TELEMETRY_PRICING` setting (`apps/api/app/config.py`); the API image copies `infra/fury/`.
  - **Gateway and deploy:** both templates answer `/aware-care-device.js` from `AWARECARE_DEVICE_*`; `nano_deploy.py`
    passes the configured device and API files.
  - **Web:** `index.html` loads the device script. Brand, O03, W06 and the W06 slide name the deployment's device.
  - **CI:** lints the Fury configuration and serve script.
- **Tests:**
  - `tests/tooling/test_second_device.py` (new, 7);
  - `tests/acceptance/test_R24.py` (+1) and `test_R38.py` (+1);
  - `tests/ui/routes.layout.spec.ts` (+2).

### Not changed
Every ID, route, operation and contract; requirement statuses (`planned`). The Nano's model manifest, inventory, prices
and deployment.

## CHG-DEV-DOC-001

Type: documentation and registry correction, not a release.
Date: 2026-10-19. Baseline 2.0 unchanged. Issues: #293, and the documentation
parts of #290 and #291.
Affected IDs: none changed. Registry notes touch shared files mapped to R01–R40 and screens A05, A08, A10, A11.

### Why
QA (2026-10-19) found documentation and registry statements that no longer matched the code or the evidence: the
enabled pathway (`general-adult-4`, not `general-adult-3`), test counts, two acceptance figures quoted without their
source, ADR status lines, the configuration contract, and `spec/traceability.yaml` entries for files that do not exist.

### Specification files changed
- `spec/traceability.yaml` (`shared_files` only; no requirement entry, status, test or code path changed):
  - removed five `planned` entries for files that were never created, because their controls live in
    `apps/web/src/components/ui.tsx`: `Button.tsx`, `StatusBanner.tsx`, `ConfirmDialog.tsx`, `EmptyState.tsx`,
    `LoadingState.tsx`. The `ui.tsx` note now names them. Its requirement and test mapping is unchanged;
  - added notes to the remaining `planned` entries that point to files that do not exist (`StepProgress.tsx`,
    `TextField.tsx`, `ChoiceGroup.tsx`, `SourceLink.tsx`, `ProviderCard.tsx`, seven module `schemas.py` and
    `safety/routes.py`), saying where the behaviour lives instead. They stay `planned` convention paths, which the
    default traceability check allows (missing planned paths went from 26 to 21).
- `spec/lock.json`: `traceability_sha256` refreshed for the change above with
  `python3 scripts/update_spec_lock.py --change-id CHG-DEV-DOC-001`.
- `spec/decisions/ADR-001-current-target.md`: an amendment section (25 routes and 32 operations since ADR-017, ZRT
  0.43.0, models under ADR-002 and ADR-018, `general-adult-4` without an early-stop rule). The 2026-10-13 text is kept.
- `spec/decisions/ADR-005-…` and `ADR-006-…`: status amendments citing what is implemented. ADR-006 stays proposed.
- `spec/api/README.md` (32 operations), `spec/implementation-plan.md` and `spec/verification.md` (25 routes since
  ADR-017), as annotations of the baseline counts.

### Other files
README.md, HANDOFF_README.md, apps/api/README.md, tests/acceptance/README.md, content/corpus/README.md and the note in
content/corpus/manifest.json, infra/.env.example (every variable the API reads), the Wiki pages Product Overview,
Testing, Architecture and Troubleshooting, and the tooling test `tests/tooling/test_docs_consistency.py`.

### Not changed
`spec/acceptance.json` and every acceptance status, requirement statuses (all `planned`), `spec/requirements.json`,
`spec/modules.json`, screens, OpenAPI, contracts, product text, clinical content and application code.

The requirement mappings of the five removed planned component entries are merged into the `apps/web/src/components/ui.tsx` entry, which exports those controls, so no requirement loses a traced file.

## CHG-DEV-EXP-001

Type: behavior, screen-contract and test change (M10, M08, M07; A12, A08, A07; `createExport`, `downloadExport`,
`generateGuidance` in mock mode), not a release. Date: 2026-10-22. Baseline 2.0 unchanged. Issues:
#395, #416, #417, #455, #456 and #459 (comprehensive QA of 2026-10-22,
v0.14.0-demo.1, findings P-02, P-03, P-04, P-11, P-12 and P-16). Related: CHG-DEV-API-004 (#356), CHG-DEV-UI-003
(#215), #265, #347, ADR-015.

### Scope
- **Behavior (M10, `apps/api/app/modules/exports/service.py`):**
  - #395: a fact is printed under its question when it is an answer (`answer:*`) and otherwise under its kind, in
    A06's words (`CONTEXT_LABELS` gains `record:medications`, `record:allergies`, `record:lab_result`). A record
    fact's `original_text` is the record's extracted source text, kept unchanged when the person corrects the value,
    so it is never a label: a corrected fact reads "Medications (from a record you confirmed): Ibuprofen 200 mg as
    needed", not "No medications listed in sample record: Ibuprofen 200 mg as needed". A test result keeps its printed
    unit and reference range, or says they were not readable, as A06 shows it (R19).
  - #459: the generation time is in the product's date style (#347), labelled UTC: "Generated 22 Oct 2026, 03:13
    UTC.", no longer a raw ISO timestamp with microseconds.
  - #417: two headings take the A12 preview's titles ("Main concern (as you described it)", "Questions for a
    clinician"), so every PDF heading is a preview title with the PDF's label in parentheses.
  - #456: in mock mode the explanations heading reads "Possible explanations (scripted illustrative text, not from an
    AI model or reviewed sources; not a diagnosis)" and Sources "No approved evidence sources are loaded; the possible
    explanation is scripted illustrative text for this synthetic demo, not from an AI model." Local wording unchanged.
- **Behavior (M10, `apps/api/app/modules/exports/pdf.py`):**
  - #416: lines are wrapped by their drawn width in the font they use (the standard Helvetica and Helvetica-Bold
    advance widths of the WinAnsi characters), not by 92 characters; headings wrap too; a word wider than a line is
    split at the margin. Every line ends at x <= 556 pt of the 612 pt page (56 pt margins); nothing is cut off. Each
    line is placed with its own text matrix, so a wrapped list item continues under its text.
  - #455: text is NFC-normalised before it is encoded, so a decomposed accent prints as its WinAnsi letter ("café");
    signs WinAnsi lacks are written out ("≥" ">=", "≤" "<=", "≠" "!=", "≈" "~", arrows "->", "<-", "℃" "°C", Greek mu
    "µ", thin spaces as spaces). Characters WinAnsi has are unchanged; anything still unshowable prints as "?" with the
    existing notice. Both fonts keep `/Encoding /WinAnsiEncoding` (#265).
- **Behavior (M08, `apps/api/app/modules/guidance/service.py`, mock path only):** #456: the mock result's limit is
  `SCRIPTED_EXPLANATION_LIMIT` ("The possible explanation is scripted illustrative text for this synthetic demo, not
  from an AI model or reviewed sources ...") instead of `GENERAL_KNOWLEDGE_LIMIT`, so A07 "Limits of this result", the
  A12 preview and the PDF no longer call the scripted sentence general medical knowledge. The claim keeps the
  contract's `general_knowledge` status (the only status for an unsourced clinical claim). Local results unchanged.
- **Web:** `A12.tsx` (#417) shows every section the PDF prints, in its order and under the same titles: "Unresolved or
  unknown details" (renamed; "None recorded" when empty), "Suggested next step(s)" (labelled like the level),
  "Possible explanations" (only shown ones, labelled scripted in mock and general medical knowledge in local mode),
  "When to seek help sooner" and "Sources" (the PDF's sentence); #395 the fact label rule above. `A08.tsx` (#456) reads
  the guidance's model manifest with the sources and, in mock mode, labels the explanation "Scripted illustrative
  text — no AI model, no reviewed source" and says so in its banner; local wording unchanged.
- **Screen contracts (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** A12 content and one validation
  rule (#417, #395, #456); A08 one validation rule and its product line (#456). IDs, routes, actions and states
  unchanged.
- **Tests:** `tests/acceptance/test_R32.py` (10 new; `test_pdf_contains_facts_gaps_sources_timestamp_and_ai_labels_only`
  now expects the date style and the mock wording), `tests/acceptance/test_R21.py` (1 new),
  `tests/ui/summary-review.spec.ts` (3 new, both widths; registered under R32), `tests/ui/A08.spec.ts` (1 new; the
  general-knowledge test now shows a local result), `tests/ui/A07.spec.ts` (mock limit wording) and
  `tests/ui/colour.spec.ts` (the summary's section titles and icon tiles).

### Not changed
Every ID, route, operation, contract and schema (no API change: A12 already reads the guidance, A08 reads it with
`getGuidance`); the #356 level-of-care and doctors sections; the export expiry (15 minutes) and invalidation rules;
reviewed clinical content, red flags, questions, the pathway, prompts and models; local-mode wording and behaviour
(no scripted result in local mode); the privacy boundary (nothing leaves the device; nothing is kept in browser
storage); the bundled sample-record fixtures; requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-GUID-001

Type: a concern check at case creation (M03), development application. Not a release by itself. Date: 2026-10-18.
Baseline 2.0 unchanged. Issue: #154. Decision: ADR-015 amendment 2.

### Scope
- **Concern check:** `apps/api/app/modules/cases/concern_check.py` (new; task `concern_check`, prompt
  `concern-check-1`) and `apps/api/app/modules/cases/service.py`.
  - In local mode, a concern with no health matter is refused at `createCase` and `editCase` (422, field `concern`,
    code `not_health_concern`).
  - It runs after the red-flag screen of the concern and only when no red flag is ticked or written. A failure lets
    the case proceed.
  - The content-free events are `concern_not_health` and `concern_check_deferred`.
- **Web:** `apps/web/src/screens/A03.tsx` shows the refusal inline.
- **Tests:** `tests/acceptance/test_R16.py` (5 new); `test_R15.py` and `conftest.py` (the scripted concern check);
  `tests/ui/A03.spec.ts` (1 new test, on desktop and mobile).
- **Traceability:** `spec/traceability.yaml` registers `concern_check.py` under R16, with `A03.spec.ts`.
- **Evidence:**
  - `evidence/clinical-review/2026-10-18-concern-check/`;
  - `evidence/model-qualification/2026-10-18-guidance-local-4/`: the re-qualification attempts of the deferred
    prompt.
- **Lock:** `spec/lock.json` refreshed with `update_spec_lock.py --change-id CHG-DEV-GUID-001`.

### Not changed
- **Guidance:** the guidance prompt (`guidance-local-3`), the validator, the qualification harness and the model
  manifests.
- **Interfaces:** OpenAPI and contracts. `FieldError.code` is free text, and a 422 `VALIDATION_FAILED` already exists
  for the concern. Routes and screens.
- **Telemetry:** concern checks count as `other` in `ai_calls.by_task`, whose keys are fixed by the contract.

## CHG-DEV-M3-001

Type: milestone 3, first slice: presenter access (ADR-005 option A) and O01. Not a release by itself.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #14.
Affected IDs: R03, R34, R37, R38; O01 (O02 and O03 become reachable for presenters with unchanged behavior);
M01, M12; createSession, getRuntime (getControls, loadScenario, resetDemo gated the same way). No new route,
operation, schema or requirement.

### Scope
- API (M01):
  - `modules/access/presenter.py` verifies gateway assertions.
  - `access/service.py` creates presenter sessions from valid single-use assertions and refuses invalid ones.
  - `core/security.py` `require_presenter` needs the role and a fresh assertion on every request.
  - `config.py` adds `AWARECARE_PRESENTER_KEY_FILE` (startup fails if it is set but unreadable or too short).
  - `core/db.py` adds the `presenter_nonces` table (created idempotently on startup).
- Gateway (web image):
  - `infra/deploy/presenter.js` (njs signer) and `presenter.conf.template` (loopback presenter listener).
  - `25-aware-care-presenter.sh` enables the listener only with a port and a readable key.
  - `nginx.conf` loads njs; the patient template strips the header.
  - `web.Dockerfile` and `.dockerignore` include the new files.
- Deployment:
  - `nano_deploy.py`: `presenter-key` command; read-only key mounts; web container runs as the deploying user.
  - The API gets `AWARECARE_APP_COMMIT` and both origins.
  - Presenter port preflight; a presenter check after the flow check; release-aware for rollback targets.
  - `flow_check.py` adds `presenter_check`.
  - `demo-zgx-nano.json` adds presenter port, origin and key settings.
  - The `ci.yml` package smoke test creates a throwaway key; the `deploy-nano.yml` summary gains a presenter row.
- Web:
  - `PresenterGate.tsx` offers a presenter session only on the presenter gateway.
  - `api/client.ts` adds `quietUnauthorized` for presenter reads; O01–O03 pass `reload`.
  - `vite.config.ts` and `playwright.config.ts` add a development/test presenter gateway (15175).
- Tests:
  - Seven new cases in `tests/acceptance/test_R03.py`.
  - The `presenter` fixture now uses the real createSession path.
  - New `tests/ui/O01.spec.ts`; `tests/ui/support/journey.ts` allows the test presenter port.
- Docs: ADR-005 implementation notes, runbook section 10, README limitation, and the Wiki Architecture, Local
  Development, Release and Deployment and Troubleshooting pages.

### Specification files changed
- `spec/traceability.yaml`:
  - `modules/access/presenter.py` and the three gateway files registered;
  - `PresenterGate.tsx` set to implemented with `tests/ui/O01.spec.ts`.

  Requirement statuses unchanged.
- `spec/lock.json`: `traceability_sha256` only, via `update_spec_lock.py --change-id CHG-DEV-M3-001`.

### Not changed
Product baseline, OpenAPI, contracts, screens registry, acceptance statuses (T-R03-S02 is re-evaluated only after
an exact release build is deployed), saved accounts, TLS, disk encryption, ADR-006.

## CHG-DEV-M3-002

Type: release and deployment evidence for M3.1, plus an operator status fix. Not a release by itself.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #14 (follow-up to CHG-DEV-M3-001).

### Scope
- `evidence/releases/v0.2.0-demo.1/`:
  - the release → deployment → Wiki record;
  - the deployment evidence (a workflow run);
  - the exact-build test reports for `0901cbd`;
  - the T-R03-S02 re-evaluation (partial; no status change; gaps in #19).
- `infra/deploy/nano_deploy.py`: `status` reports the presenter gateway from the running web container. It no longer
  reports from key presence alone, which said "enabled" while a pre-gateway release was running.
- Wiki: Release and Deployment, Product Overview, Issue Work Log entry for #14.

### Specification files changed
None. `spec/acceptance.json` is unchanged (T-R03-S02 stays `NOT_EXECUTED`); traceability and lock are unchanged.

## CHG-DEV-M3-003

Type: milestone 3 completion (O02, O03, separate presenter cookie, scenario load and reset). Not a release by itself.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #24.
Affected IDs: R03, R35, R36, R37, R38, R39; O02, O03; M01, M11, M12; createSession, deleteSession, getJob,
getControls, loadScenario, resetDemo. No new route, operation, schema or requirement.

### Scope
- API:
  - `core/security.py`: gateway-based session resolution with separate `awarecare_presenter` and
    `awarecare_session` cookies.
  - `access/routes.py`, `privacy/routes.py`: set and clear the cookie matching the role.
  - `operations/scenarios.py` and `routes.py`: `loadScenario` returns the demo session token and sets the patient
    cookie; the token is rotated on an idempotent replay.
- Web:
  - `O02.tsx`: Unverified, Not checked and None recorded states; outbound event list.
  - `O03.tsx`: Load scenario for the six fixtures, Reset demo with job polling, and the blocking reset-failure
    state with Retry reset.
  - `api/client.ts`: `loadScenario`, `resetDemo`.
- Deployment:
  - `api.Dockerfile` declares `io.aware-care.capabilities=scenario-handoff`.
  - `flow_check.presenter_check` loads a scenario, continues it on the patient gateway, then resets and confirms
    revocation, when the running API declares the capability.
  - `nano_deploy.py` reads the capability from the running container.
- Tests:
  - Backend: cookie coexistence (`test_R03`); six-scenario load, reset observability, and failed-reset blocking
    with repair (`test_R37`); reset cancels an in-flight guidance write (`test_R35`); content-free events after
    presenter actions (`test_R36`).
  - Browser: presenter paths in `O02.spec.ts` and `O03.spec.ts` (load and continue in the same browser, reset,
    failed-reset block); the presenter route width sweep in `routes.layout.spec.ts` (all 24 routes).
- Docs: ADR-005 implementation notes, runbook section 10, README milestone table and limitations, and the Wiki
  Architecture, Product Overview, Release and Deployment and Testing pages.

### Specification files changed
None. No new registered files (the tests and screens were already mapped), so traceability and the lock are
unchanged. Requirement and acceptance statuses are unchanged until exact-build evidence after release.

## CHG-DEV-M3-004

Type: milestone 3 release and deployment evidence. Not a release by itself.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #24 (follow-up to CHG-DEV-M3-003).

### Scope
- `evidence/releases/v0.3.0-demo.1/`:
  - the release → deployment → Wiki record;
  - the deployment evidence (a workflow run, presenter check with the scenario handoff);
  - the exact-build test reports for `388889b`;
  - the milestone 3 exit-criteria table.
- Wiki: Release and Deployment, Product Overview, and the Issue Work Log entry for #24.

### Specification files changed
None. Acceptance, traceability and lock are unchanged.

## CHG-DEV-M4-001

Type: development tooling and decision record, not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #45 (refs #26).

### Scope
- `scripts/qualify_model.py`: the ADR-002 qualification harness. It is registered in `spec/traceability.yaml`
  `shared_files` with R24–R27, R37 and R38.
  - It drives the existing `ZrtRuntimeAdapter` unchanged, with synthetic cases from the fixtures.
  - Subcommands: `identity`, `failures`, `run`, `context` and `compare`.
- `spec/decisions/ADR-002-model-qualification-protocol.md`: the 2026-10-15 run, its decision (no model selected) and
  the owner's open items.
- `infra/model-manifest.json`:
  - adds the observed engine (vLLM 0.30.0), endpoint verification and a `qualification` record;
  - `status` stays `unconfigured`, and every `model.*` field stays null.
- `evidence/model-qualification/2026-10-15/`: the results.

### Specification files changed
`spec/traceability.yaml` (one `shared_files` entry). `spec/lock.json` is refreshed for the traceability hash only,
with `scripts/update_spec_lock.py --change-id CHG-DEV-M4-001`.

### Not changed
- **Product spec:** requirements, screens, modules, contracts, OpenAPI and product text.
- **Code:** the application code, including the adapter.
- **Device:** ZRT setup and its managed dependencies, drivers and CUDA.
- **Local mode:** stays unavailable (ADR-003, ADR-004).

## CHG-DEV-M4-002

Type: application change (M08), not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #51 (refs #26, ADR-002,
ADR-012).

### Scope
- `apps/api/app/modules/guidance/local.py` (new): the local generation path for the qualified model.
  - **Prompt:** `guidance-local-1`, verbatim the qualified `qual-guidance-2` text; its SHA-256 is recorded in
    `infra/model-manifest.json`.
  - **Draft schema:** `GuidanceDraft`, derived from the spec's `Action` and `Claim`.
  - **Rules:** the service rules, with one repair on the same snapshot, the ADR-012 certainty review and a 60 s
    deadline covering all of it.
  - **Mapping:** into the published `Guidance`. Case-fact claims are `supported` only with confirmed fact
    references; clinical claims stay `suppressed` without an approved corpus.
- `apps/api/app/modules/guidance/guidance_draft.schema.json` (new): the draft schema shipped with the app (the API image has no `spec/`). It is generated from `spec/api/openapi.json` by `local.derive_draft_schema`, and `test_R24.py::test_shipped_draft_schema_matches_the_spec` fails on any drift.
- `apps/api/pyproject.toml` and `uv.lock`: `jsonschema==4.25.1` moves from the dev group to the runtime dependencies, at the same pin and version, so the image can validate drafts. No new package; 30 resolved, as before.
- `spec/traceability.yaml`: `local.py` and the schema file added to the code of R24, R25, R26 and R27. The note for
  `scripts/qualify_model.py` is updated: the harness now drives this app path, so there is one source for the
  prompt, schema and rules.
- `spec/lock.json`: traceability hash refreshed with `update_spec_lock.py --change-id CHG-DEV-M4-002`.
- Tests: local-path cases in `tests/acceptance/test_R24.py`, `test_R25.py` and `test_R26.py`.

### Not changed
- **API:** `generateGuidance` keeps refusing local mode (503). The path needs a reviewed urgency decision (ADR-003)
  and approved evidence (ADR-004), so it is reached only by tests and the Nano harness.
- **Mock mode:** the mock adapter, mock candidate shape and mock behavior are unchanged.
- **Spec:** contracts, OpenAPI, screens and product text are unchanged.

## CHG-DEV-M4-003

Type: application change (M03, M04, M05, M08, M12), not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #27 (ADR-003 accepted; refs
ADR-002, ADR-004, ADR-012, #51).

### Scope
- **Reviewed pathway package** `content/pathways/general-adult-1/` (new), enabled in `content/pathways/registry.json`:
  - `pathway.json` conforms to `spec/contracts/Pathway.schema.json`. It holds RF01–RF16 as urgent rules, Q01–Q10 as
    eligible questions and the 10-slot stop rule, plus the review metadata: role MD, approved 2026-10-15, expiring
    2027-10-15, and record `ADR-003-review-2026-10-15`.
  - `questions.json` holds Q01–Q10, verbatim from `fixtures/questions.json`.
  - `red-flags.json` holds RF01–RF16 and the two urgent messages, verbatim from
    `evidence/clinical-review/2026-10-15/review.json`.
- `apps/api/app/modules/safety/pathway.py` (new, M05): loads the enabled package and checks the structure it relies on.
  A malformed package fails startup. A package that is expired, disabled or not approved loads but is not active.
- `apps/api/app/modules/safety/service.py` (M05):
  - the `red_flags` checklist answer (ticked RF IDs, or an empty list for "none apply") is validated;
  - any ticked item routes to urgent, in both modes;
  - in local mode, a missing active pathway or a missing checklist answer limits the case (R17);
  - `urgency_decision` gives the policy (a) starting level, `self_care_candidate`, reduced by the R14 information
    limits.
- `apps/api/app/modules/cases/service.py` (M03): the checklist is applied on `createCase` and `editCase` (R15). An
  edit that does not answer the checklist keeps the earlier answer.
- `apps/api/app/modules/intake/service.py` (M04): local mode issues the package's approved templates in R12 order,
  recorded with `pathway_version` `general-adult-1`.
- `apps/api/app/modules/guidance/service.py` (M08): `generateGuidance` serves local mode while the pathway is active.
  It runs the qualified local path (`local.py`, `guidance-local-1`, ADR-012 review) with the pathway's decision. A
  failure leaves the case limited with a retry; there is no mock or cloud fallback. `local.py`: docstring only.
- `apps/api/app/modules/operations/service.py` (M12):
  - **Local readiness:** `ready` with an active pathway and a served model; `degraded` when ZRT does not serve the
    model; `unavailable` without an active pathway or a model ID.
  - **Runtime facts:** they report the model manifest ID and the fictional directory version, and the pathway control
    states the active package.
- `apps/api/app/main.py`, `config.py`, `core/context.py`, `core/fixtures.py`:
  - both modes load the fixture pack, but local mode uses only its fictional provider directory (ADR-004);
  - `pathways_dir` is a new setting.
- `apps/api/app/modules/exports/service.py`: the summary wording is now true for local results, and the checklist
  answer is labeled.
- **Web:**
  - `apps/web/src/components/RedFlags.tsx` (new): the checklist and its data, verbatim from the package; a test checks
    for drift.
  - A03: the checklist must be answered, and the banner is true in both modes.
  - A15: shows the reviewed message for the ticked level, without naming the sign.
  - A06 and A12: show the checklist answer in plain words.
  - A07: a notice that local guidance is AI-generated and can make mistakes.
- **Deployment:**
  - `infra/deploy/api.Dockerfile` copies `content/pathways`.
  - `infra/deploy/flow_check.py` answers the checklist ("none apply").
  - The runbook's local-mode text is updated (`spec/engineering/08-delivery-and-nano-runbook.md`).
- **Traceability:** `pathway.py` is added to the code of R12, R15, R16 and R17, and `RedFlags.tsx` to R15. The lock is
  refreshed with `update_spec_lock.py --change-id CHG-DEV-M4-003`.
- **Tests:**
  - new `tests/acceptance/test_R12.py` and `test_R17.py`;
  - red-flag tests in `test_R15.py`, local journey tests in `test_R24.py`, local failure tests in `test_R26.py`;
  - a `local` fixture in `conftest.py`, with a scripted model and no ZRT;
  - UI: checklist tests in `A03.spec.ts` and `A06.spec.ts`, with journeys answering the checklist.

### Not changed
- **Spec:** contracts, OpenAPI, the 24 routes, screens, requirement text and operation IDs. The checklist uses the
  existing `confirmed_context` of `CaseWrite` and `CaseEdit`.
- **Mock mode:** scenarios, the mock adapter and its labeled outcomes. The only addition is that a ticked red flag
  routes to urgent.
- **Evidence:** no corpus is approved. Clinical claims stay suppressed, and retrieval stays unavailable.
- **Requirement statuses:** all stay `planned`. The 16 clinician-dependent scenarios stay `NOT_EXECUTED` until they
  run against an exact release.

## CHG-DEV-M4-004

Type: clinical content and application change (M05, M08), not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #73 (ADR-003 amendment;
refs #63).

### Decision implemented
The clinical reviewer (role MD) answered the #63 monitoring finding on 2026-10-15: **"3 with 1a, RF17 and RF18 as
proposed."** The finding was that borderline cases first answering `undetermined` are unstable; B08 was never urgent
in 5 repeats. After the 50-case re-run, the reviewer added **"RF19 as recommended."**

### Scope
- `content/pathways/general-adult-2/` (new, enabled), contract `Pathway`:
  - `red-flags.json`: RF17 "Coughing up blood" and RF18 "Skin redness that is spreading, with fever", both
    `urgent_clinician`; RF19 (emergency) "New numbness around the groin, buttocks or inner thighs, or back pain with
    new difficulty starting to urinate or loss of bladder or bowel control". RF01–RF16 and both messages are
    unchanged.
  - `policy.json` (new): `undetermined_floor: routine_clinician`.
  - `pathway.json`: the three new urgent rules, scope lines and the amendment review record.
  - `questions.json`: unchanged.
- `general-adult-1` is kept, disabled, for history. `content/pathways/registry.json` enables `general-adult-2`.
- `apps/api/app/modules/safety/pathway.py`: reads the optional `policy` file; an invalid floor fails startup.
- `apps/api/app/modules/safety/service.py`: the decision carries the floor when the pathway has one.
- `apps/api/app/modules/guidance/local.py`:
  - **The floor:** with a floor, an `undetermined` draft for a non-urgent decision is accepted and published at the
    floor, with reason code `MODEL_UNCERTAIN_CLINICIAN_FLOOR` (`published_level`). It is never repaired toward
    self-care.
  - **Self-care while unsure** is rejected with one repair (`self_care_when_undetermined`).
  - **Without a floor** (the qualification harness and `general-adult-1`), the previous rule applies.
  - **The qualified prompt `guidance-local-1` is unchanged:** same text and SHA-256.
- `apps/web/src/components/RedFlags.tsx`: the checklist data regenerated from the v2 package (drift test).
- **Tests:**
  - `test_R12.py`, `test_R15.py`, `test_R17.py` and `test_R24.py` read the enabled package. They check RF17 and RF18
    against the amendment record (RF19 included), and add three floor tests.
  - `test_R26.py`'s failure case is now self-care advice while unsure.
  - The UI tests count 19 red flags and add RF17/RF18 and RF19 tests.
- **Evidence:** `evidence/clinical-review/2026-10-15-amendment/`: the decision, the generator, the 50-case run, the
  borderline repeats, and the reviewer's grades of the changed answers.

### Not changed
- Contracts, OpenAPI, routes, the qualified prompt, the model and the questions.
- The never-lower rule for decided levels.
- Policy (a) for clear cases.
- The traceability mappings: no new runtime file.

## CHG-DEV-M4-005

Type: application and tooling change (M08, M12), not a release.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #75 (ADR-002 runtime
re-qualification on ZRT 0.43.0).

### Scope
- `apps/api/app/modules/guidance/local.py`:
  - `schema_problems`: a schema repair now lists the failing fields by path. Invalid fact or evidence IDs get "use
    only ids listed in confirmed_facts (or evidence), or an empty list". Only paths and schema messages are included,
    no case text.
  - `snapshot`: a case with no confirmed facts gets a `no_facts` line. App cases always carry the checklist answer,
    so their snapshot is unchanged.
  - The qualified prompt `guidance-local-1` is unchanged (same SHA-256).
- `scripts/qualify_model.py gates` (new subcommand): the pass/fail verdict of every ADR-002 stage from one
  qualification's result files. A missing stage is NOT_RUN, and the overall result is PASSED only when all stages
  pass.
- `infra/model-manifest.json`: runtime ZRT 0.43.0 (snap x4, vLLM 0.30.0), `serving.interface`, and
  `qualification.runtime_requalifications`.
- `spec/decisions/ADR-002-model-qualification-protocol.md`: the "Runtime re-qualifications" section.
- `spec/engineering/07-nano-zrt-operations.md` §8: the procedure for ZRT updates.
- **Tests** (`tests/acceptance/test_R26.py`):
  - the repair names invalid IDs;
  - the gate check applies the gates unrelaxed;
  - only a case without facts gets the no-facts line;
  - every local app case reaches the model with at least one fact.
- **Evidence:** `evidence/model-qualification/2026-10-15-zrt-0.43.0/` (the failing first check), `…-requal/` (attempt
  1) and `…-requal2/` (attempt 2, all gates passed).

### Not changed
The model, its revision and serving settings; the prompt; the ADR-002 gates; the contracts; the clinical pathway.

## CHG-DEV-M4-006

Type: clinical content and application change (M05, M08, A07, A15), not a release.
Date: 2026-10-16. Baseline 2.0 unchanged. Issue: #79 (ADR-003 amendment 2;
refs #73, #78).

### Decision implemented
Finding #79: on the deployed v0.5.2-demo.1, B06-like and B08-like presentations got self-care advice in 2 of 3 runs
each when the person described the red flag in their own words but did not tick it. The clinical reviewer (role MD)
chose the default proposal on 2026-10-16: a red-flag screen of the person's own words, reviewed after release
(`evidence/clinical-review/2026-10-16-amendment-2/decision.json`, ADR-003 "Amendment 2").

### Scope
- `content/pathways/general-adult-3/` (new, enabled), contract `Pathway`:
  - `questions.json` and `red-flags.json`: the same questions, RF01–RF19 and messages as `general-adult-2`.
  - `policy.json`: the same clinician floor, plus `red_flag_screen: true`.
  - `pathway.json`: a scope line for the screen and the amendment 2 review record.
- `general-adult-2` is kept, disabled, for history. `content/pathways/registry.json` enables `general-adult-3`.
- `apps/api/app/modules/safety/screen.py` (new, R15 and R17):
  - **Task:** `red_flag_screen`, prompt `red-flag-screen-1`, schema `RedFlagScreen`.
  - **Input:** the approved red-flag IDs and wording, and the person's words (the concern and every answered
    question).
  - **Accepted output:** only `{"present": [distinct approved IDs]}`. The level is the highest matched level.
- `apps/api/app/modules/safety/pathway.py`: reads `red_flag_screen` from the policy. A non-boolean value fails
  startup.
- `apps/api/app/modules/guidance/service.py`, local path:
  - **When the pathway has the screen,** it runs before any guidance call, within the same 60 s deadline.
  - **On a match:** the case becomes `urgent`, and the job fails with `RED_FLAG_DESCRIBED_EMERGENCY` or
    `RED_FLAG_DESCRIBED_URGENT_CLINICIAN`. Event `urgent_interrupt` (generateGuidance) is recorded. No guidance is
    generated.
  - **On an unavailable or invalid screen** (`RED_FLAG_SCREEN_UNAVAILABLE`, `RED_FLAG_SCREEN_INVALID`): limited with
    retry, so it fails closed.
- `apps/web/src/screens/A07.tsx`: on an urgent case, passes the described level from the job's error code to A15.
- `apps/web/src/screens/A15.tsx`: shows the approved message for that level, once the case reads as urgent.
- `scripts/monitoring.py`: the monthly report counts `red_flag_described` by level.
- **Tests:**
  - `test_R15.py`: 8 screen tests (snapshot, match by level, invalid and unavailable fail closed, retry, a package
    without the screen, accept and level rules, an invalid setting fails startup).
  - `test_R12.py`, `test_R17.py`, `test_R24.py`: read the enabled package (`general-adult-3`).
  - `A15.spec.ts`: A07 to A15 with each level, and no level when none was given.
  - `test_monitoring.py`: the new count.
  - The CI image check asserts `general-adult-3` and the screen.
- **Traceability:** `screen.py` is registered under R15 and R17.

### Not changed
- Contracts, OpenAPI and routes. The job's `error_code` is a free string in `Job`, and the new codes fit its bounds.
- The qualified prompt `guidance-local-1`, the model, the questions, the red flags and messages, the floor and
  policy (a).
- Mock mode, which has no screen.

## CHG-DEV-M4-007

Type: requirement wording change, contract change, prompt change and test change (R22, R24; A07, A08; M07, M08), not
a release. Date: 2026-10-16. Baseline 2.0 unchanged. Issue: #105.
Decision: ADR-015.

### Decision implemented
The product owner, 2026-10-16: "you don't need evidence corpus  show explanations every time, it should never come
blank". Possible explanations come from the model's general medical knowledge and are labeled as such.

### Scope
- **R22's canonical clause,** in `spec/product.md`, `spec/requirements.json` and `spec/acceptance.json`:
  - **was:** "Given an unknown source ID, stale source or unsupported claim, suppress the affected claim and disclose
    the limit; never fabricate a URL."
  - **is now:** "Given an unknown source ID, stale source or unsupported claim, suppress the affected claim or show it
    only as labeled general medical knowledge without a citation, and disclose the limit; never fabricate a source,
    citation or URL."
- **T-R22-S01's first then-clause:**
  - **was:** "Each affected clinical claim is suppressed and the limit disclosed."
  - **is now:** "Each affected clinical claim is suppressed, or shown only as labeled general medical knowledge without
    its citation, and the limit is disclosed."
- **Other spec text:** `product.md` (A08 required exception, the Claim data model, the prompt rule) and `screens.json`
  with its `screens.yaml` mirror (A08 required exception and validation rule).
- **Contract:** `Claim.validation_status` gains `general_knowledge`, allowed only for `kind: clinical` with an empty
  `evidence_ids` list (`spec/contracts/Claim.schema.json`, `spec/api/openapi.json`; `apps/web/src/api/schema.ts`
  regenerated).
- **Local generation:** prompt `guidance-local-2` (rules 5, 7, 9); validation code `no_possible_explanation` with its
  repair hint replaces `clinical_claim_without_evidence`; unsourced clinical claims map to `general_knowledge`. The
  manifest records the new prompt hash; the prompt is **not re-qualified** (owner's choice, ADR-015).
- **Mock mode:** one scripted, labeled explanation with status `general_knowledge`.
- **Presentation:** the uncertainty sentence, the A08 badge and banner, the A07 empty-state fallback, the PDF section
  "Possible explanations" and its Sources line, and the O02 corpus control text.
- **Tests:** R21, R24 and R32 assertions updated; new tests for the never-blank rule (repair once, then fail closed),
  the contract rule, the PDF section and the A07/A08 UI.

### Not changed
- R21's clause, retrieval (`unavailable`) and ADR-004's no-corpus decision.
- R21, R22 and R24 stay `planned`. No route or endpoint change.
- The model, revision, runtime, draft schema and certainty review (ADR-002, ADR-012).

## CHG-DEV-M4-008

Type: clinical content change (M05; A03, A15; the red-flag screen), not a release. Date: 2026-10-19. Baseline 2.0
unchanged. Issue: #194 (ADR-003 amendment 4).

### Decision implemented
The clinical reviewer (role MD) approved RF20, "Took too much of a medicine, or swallowed something poisonous", at
the emergency level, on 2026-10-19 (`evidence/clinical-review/2026-10-19-amendment-4/decision.json`, ADR-003
"Amendment 4").

### Scope
- **Package:** `content/pathways/general-adult-4/` (new). It is `general-adult-3` plus RF20 in `red-flags.json` and in
  `pathway.json` (an urgent rule, the scope line and the reviewer entry). The review date is 2026-10-19; the expiry
  stays 2027-10-15.
- **Registry:** `general-adult-4` is enabled; `general-adult-3` is kept for history.
- **Web:** `apps/web/src/components/RedFlags.tsx`, the verbatim checklist with RF20, checked by the R15 parity test.
- **Tests:** R12 (the package matches the approved chain: the review, amendment, amendment 2 and amendment 4; only RF20
  added), R12, R24 and R37 (the pathway version), CI's package check (20 red flags).
- **Records:** ADR-003 amendment 4; the decision record and its pre-release measurement.

### Not changed
- RF01–RF19, both messages, Q01–Q10, the clinician floor and policy (a).
- The red-flag screen prompt, the guidance prompt, the models and the API contract.

## CHG-DEV-OPS-001

Type: operations stabilization of the deployed mock baseline, not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #9.
Affected IDs: R34, R37, R38, R40; M12. No requirement, screen, route, operation, schema or application code change.

### Scope
- `scripts/issue_completion.py`: `project-access` diagnostic reporting credential type, owner, classic scopes and
  expiry (never the value), a Project read, an item read and an idempotent Status write. Tests in `tests/tooling`.
- `.github/workflows/wiki-completion.yml`: manual `operation` input (`complete` | `project-access`).
- `evidence/releases/v0.1.0-demo.1/`: the release → deployment → Wiki record, both deployment evidence files, and the
  controlled recovery exercise.
- Runbook sections 8 (credential diagnosis) and 9 (recovery exercise); Wiki Release and Deployment, Troubleshooting
  and the Issue Work Log.

### Specification files changed
None. No new runtime file needs registration, so `spec/traceability.yaml` and `spec/lock.json` are unchanged.

### Operational actions (not repository changes)
- Throwaway probe branch `probe/project-access` ran the diagnostic in Actions with the real secret, then was deleted.
- Device backup under `~/.local/share/aware-care-demo-backups/`; local-mode candidate deployment a workflow run
  (failed, rolled back automatically). No ZRT, driver, Docker or service configuration changed.

## CHG-DEV-OPS-002

Type: operator tooling (M12), not a release and not an application change.
Date: 2026-10-15. Baseline 2.0 unchanged. Issue: #63 (ADR-003 item 7).

### Scope
- `scripts/monitoring.py` (new): the ADR-003 monthly monitoring.
  - **`collect`:** saves per-day counts from the content-free `events` table (database opened read-only, no other
    table read) for every completed UTC day still inside the API's 30-day retention. Saved days are never
    overwritten, and the store lives outside Git.
  - **`report`:** builds a month from the saved days, states its coverage, and labels the counts as operational usage
    of a synthetic demo, not outcome evidence (R39).
  - **`review-sample`, `review-worksheet`, `review-score`:** the seeded monthly synthetic sample through the app's
    local path with the active pathway, the grading page, and the satisfaction rate. A borderline "wrong" raises the
    re-review flag.
- `scripts/monitoring_worksheet.html` (new): the grading page template.
- `tests/tooling/test_monitoring.py` (new).
- `spec/traceability.yaml`: `scripts/monitoring.py` registered under R36, R38 and R39.
- `spec/lock.json`: traceability hash refreshed with `update_spec_lock.py --change-id CHG-DEV-OPS-002`.
- `spec/engineering/08-delivery-and-nano-runbook.md`: section 10a with the monthly procedure.
- `evidence/monitoring/2026-10/`: the October baseline (the ADR-003 review, 50/50) and the first observation.

### Not changed
- **Application code, contracts, OpenAPI, screens and the event schema.** The events already were content-free
  (R38).
- **The 30-day event retention (R36).**
- **No patient-facing feedback control.** It would need a new API operation and a product decision.

## CHG-DEV-OPS-003

Type: operator tooling and device operations (M12), not a release and not an application change.
Date: 2026-10-18. Baseline 2.0 unchanged. Issue: #170 (recovery exercise).

### Scope
- `infra/deploy/nano_deploy.py`:
  - a redeploy of the deployment that already runs keeps `state/previous.json`, the rollback target;
  - state files are written 0600;
  - each successful deployment copies `boot_check.py` to `<data root>/ops/` and reports whether the `@reboot` line is
    installed (`boot_check` in the evidence).
- `infra/deploy/boot_check.py` (new): the post-boot recovery check, content-free and private.
- `infra/nano/zrt/serve-model.sh` and `aware-care-zrt-model.service` (new): the Nano's model at boot, with the
  manifest's qualified command, as the Fury's (#142).
- `tests/tooling/test_recovery.py` (new); `.github/workflows/ci.yml` lints the new script and compiles the new module.
- `spec/traceability.yaml`: the three new files registered under R37 (and R38 for the boot check).
- `spec/lock.json`: traceability hash refreshed with `update_spec_lock.py --change-id CHG-DEV-OPS-003`.
- `spec/engineering/07-nano-zrt-operations.md` §10 and `08-delivery-and-nano-runbook.md` §6 and §9a.
- `evidence/operations/2026-10-18-recovery-exercise/`.

### Not changed
- **Application code, contracts, OpenAPI and screens.**
- **The served models and their commands.** ZRT, CUDA, drivers, system services, sudoers and the network
  configuration.
- **A real reboot was not performed.** It needs root, which neither device account has.

## CHG-DEV-OPS-004

Type: device operations (serving environment), not an application change. Date: 2026-10-18.
Baseline 2.0 unchanged. Issue: #175.

### Scope
- `infra/nano/zrt/serve-model.sh` and `infra/fury/zrt/serve-model.sh`: export `VLLM_NO_USAGE_STATS=1`,
  `VLLM_DO_NOT_TRACK=1`, `DO_NOT_TRACK=1` and `HF_HUB_OFFLINE=1` for the model process.
- `infra/model-manifest.json` and `infra/fury/model-manifest.json`: `serving.environment` records them.
- `tests/tooling/test_recovery.py` and `test_second_device.py` pin them.
- `spec/engineering/07-nano-zrt-operations.md` §11; Wiki page Troubleshooting.
- `evidence/operations/2026-10-18-vllm-usage-stats/`.
- `spec/lock.json`: refreshed with `update_spec_lock.py --change-id CHG-DEV-OPS-004`.

### Not changed
- ZRT, vLLM, CUDA and drivers.
- The application.
- The served models, their commands and their qualified settings. The environment change is re-qualified with #154
  on both devices.

## CHG-DEV-OPS-005

Type: release and device-test tooling, not an application change. Date: 2026-10-21.
Baseline 2.0 unchanged. Issues: #366, #367.

### Scope
- `scripts/release/`: the release toolkit, moved into the repository from the per-release scratch copies and made
  version-free (version, device, model and rollback target are arguments):
  - `dispatch_release.sh`: release.yml after a successful push CI run;
  - `nano_suites.sh`: the suites on the Nano in a clean worktree;
  - `backup.sh`: the pre-deployment backup;
  - `dispatch_deploy.sh`: a deployment through the deploy workflows, with the environment approval as practised
    since #170;
  - `host_checks.sh`: the read-only host checks;
  - `deployed_checks.sh` and `probes/`: the probes;
  - `assemble_evidence.py` and `towebp.mjs`: the evidence folder.
- `scripts/evaluate_acceptance.py`: the clause-map evaluator, moved from
  `evidence/releases/v0.4.0-demo.1/acceptance/evaluate.py`. That path is now a shim that runs the new file, so the
  older release READMEs still reproduce. The output is byte-identical (checked on the v0.13.0-demo.1 reports).
- `tests/devices/` with `apps/web/playwright.devices.config.ts`, `npm run test:device` and `npm run
  typecheck:device`. The specs are the deployed walk-through, the one-click flow timing, the usability walk and the
  #355–#357 measures. The mock suite (`playwright.config.ts`, `tests/ui`) does not run them.
- `tests/tooling/test_release_toolkit.py`.
- CI: shellcheck and py_compile of the new scripts, and a typecheck of the device specs.
- `spec/traceability.yaml`: the new files as shared files.
- Wiki pages Release and Deployment (Release runbook) and Testing (Device specs).
- `spec/lock.json`: refreshed with `update_spec_lock.py --change-id CHG-DEV-OPS-005`.

### Not changed
- The application, its contracts, screens and routes.
- The deploy workflows and their approval rules.
- ZRT, drivers, CUDA, system Python and services. The scripts are read-only on the devices and deploy only
  through the workflows.
- Requirement statuses and acceptance records. The evaluator records verdicts per release, as before.

## CHG-DEV-PRIV-001

Type: requirement wording change and test change (R34), not a release. Date: 2026-10-16. Baseline 2.0 unchanged.
Issue: #97. Decision: ADR-014.

### Decision implemented
The product owner, 2026-10-16: "requests can leave the device. only requirement is that llm will run locally on zgx
and no patient data will leave zgx".

### Scope
- **R34's canonical clause,** in `spec/product.md`, `spec/requirements.json` and `spec/acceptance.json`:
  - **was:** "Given normal use and failure paths, network inspection shows no raw health content, cloud inference,
    remote fonts or third-party analytics."
  - **is now:** "Given normal use and failure paths, network inspection shows no patient content or API payload
    leaving the device, no cloud inference, and no third-party analytics or session replay."
- **T-R34-S01's second then-clause:**
  - **was:** "No cloud model inference, remote fonts or third-party analytics are observed."
  - **is now:** "No cloud model inference, third-party analytics or session replay is observed; any off-device
    request is a static-asset GET to an allowed host and carries no patient content."
- **`tests/ui/support/journey.ts`:** `guardNetwork` enforces ADR-014, with an allow-list (`ALLOWED_ASSET_HOSTS`,
  empty) and named reasons. `routes.layout.spec.ts` adds a test that the guard flags each kind of violation and that
  the page declares no-referrer.
- **`apps/web/index.html`:** `<meta name="referrer" content="no-referrer">`.

### Not changed
- R34 stays `planned`.
- No contract, route or API change.
- ADR-002 (local inference only).

## CHG-DEV-QUAL-001

Type: qualification protocol amendment and the Nano's serving setting (M08, ADR-002). Not an application change.
Date: 2026-10-19. Baseline 2.0 unchanged. Issue: #178.

### Scope
- **Decision:** `spec/decisions/ADR-002-model-qualification-protocol.md`: "Amendment (2026-10-19)".
- **Nano serving:** `infra/nano/zrt/serve-model.sh` and `infra/model-manifest.json` (`serving.command`), with
  Inductor combo-kernel benchmarking off.
- **Harness:** `scripts/qualify_model.py` gets `--corpus real-concerns` (the default) and `fixture-placeholders` (the
  old corpus). The corpus is recorded in the run summary.
- **Records:** `runtime_requalifications` entries in both model manifests. The Nano's says FAILED (stage 4) and the
  Fury's PASSED.
- **Evidence:** `evidence/model-qualification/2026-10-19-nano-deterministic/`; Wiki pages Troubleshooting and
  Release and Deployment.
- **Lock:** `spec/lock.json` refreshed with `update_spec_lock.py --change-id CHG-DEV-QUAL-001`.

### Not changed
- **Gates:** the gate thresholds.
- **Models and prompts:** the models, ZRT, the prompts (`guidance-local-3` on both devices) and the validator.
- **The Fury's serving.**

## CHG-DEV-QUAL-002

Type: model-input encoding of the local guidance path (M08) and its ADR-002 re-qualification. Date: 2026-10-19.
Baseline 2.0 unchanged. Issue: #199. Related: #192, #209.

### Scope
- **Code:** `apps/api/app/modules/guidance/local.py`:
  - `ENCODING_VERSION = "short-ids-1"`;
  - `aliases`, `model_schema` and `restore_ids`;
  - the snapshot uses `F`/`E` aliases, and the draft's aliases are restored before validation.
- **Tests:** `tests/acceptance/test_R24.py` (the alias snapshot; restored ids; an unknown alias rejected and named in the
  repair; malformed drafts left to the validator).
- **Decision:** `spec/decisions/ADR-002-model-qualification-protocol.md`, "Re-qualification with short id aliases
  (2026-10-19, #199)".
- **Records:** `runtime_requalifications` entries (PASSED) and `generation.encoding` in both model manifests.
- **Evidence:** `evidence/model-qualification/2026-10-19-short-ids/`.
- **Lock:** `spec/lock.json` refreshed with `update_spec_lock.py --change-id CHG-DEV-QUAL-002`.

### Not changed
- **Prompt:** the guidance instructions and their hash (`guidance-local-3`).
- **Checks:** the draft schema the service validates, the rules, the certainty review and the published `Guidance`.
- **Other tasks:** the red-flag screen, the concern check and the certainty-review prompts.
- **Protocol:** the models, ZRT, serving, the qualification corpus and every gate threshold.

## CHG-DEV-QUAL-003

Type: guidance prompt change (M08) with its ADR-002 re-qualification. Date: 2026-10-19. Baseline 2.0 unchanged.
Issue: #179. Related: #154, #178, #199.

### Scope
- **Code:** `apps/api/app/modules/guidance/local.py`:
  - `PROMPT_VERSION = "guidance-local-4"`, with rule 10 added to the instructions;
  - `THIRD_PERSON_RE` and the `third_person` code with its repair hint.
- **Harness:** `scripts/qualify_model.py` scores third-person wording.
- **Tests:** `tests/acceptance/test_R24.py` (rule 10 only, rules 1–9 unchanged; third-person statements repaired, the
  person's questions not checked).
- **Records:** both model manifests (`generation.prompt_version`, `prompt_sha256` `91cd723e…`, `prompt_source`, and a
  PASSED `runtime_requalifications` entry); ADR-015 amendment 3; an ADR-002 note.
- **Evidence:** `evidence/model-qualification/2026-10-19-guidance-local-4/`.
- **Lock:** refreshed with `update_spec_lock.py --change-id CHG-DEV-QUAL-003`.

### Not changed
- Rules 1–9, the certainty review and the general-knowledge labels.
- The models, serving, the encoding, the corpus and every gate.

## CHG-DEV-QUAL-004

Type: concern-check prompt change (M03) with its ADR-002 re-qualification. Date: 2026-10-21. Baseline 2.0 unchanged.
Issue: #314. Related: #154, #178.

### Scope
- **Code:** `apps/api/app/modules/cases/concern_check.py`: `PROMPT_VERSION = "concern-check-2"` and the stricter
  instructions (sha256 `e885b6ec…`).
- **Tests:** `tests/acceptance/test_R16.py`:
  - the prompt version the scripted model receives;
  - the shipped version and hash match the qualification record, both devices' gate files and both model manifests,
    and each re-qualification PASSED;
  - the measurement set meets the issue (≥ 40 non-health, ≥ 60 health, every B/C review concern);
  - the rules that protect real concerns are kept.
- **Records:**
  - both model manifests carry `generation.concern_check` (version, hash, PASSED qualification, previous prompt);
  - ADR-015 amendment 4 and an ADR-002 note.
- **Evidence:** `evidence/model-qualification/2026-10-21-concern-check-2/`, with the set, the held-out set, the
  runner, the gate script, the baselines, the drafts and both devices' runs.
- **Lock:** refreshed with `update_spec_lock.py --change-id CHG-DEV-QUAL-004`.

### Not changed
- **Check behaviour:** the task, the `ConcernCheck` answer, the verdict handling, the refusal and the failure path.
- **Model work:** the red-flag screen and urgent routing at creation, the guidance prompt, the certainty review.
- **Devices:** the models, serving, ZRT and the device configuration. `runtime_requalifications` stays the guidance
  record that telemetry reports.
- **Interfaces:** OpenAPI, contracts, routes and screens.

## CHG-DEV-QUAL-005

Type: red-flag screen prompt change (M05) and concern-check prompt change (M03), each with its ADR-002
re-qualification on both devices. Date: 2026-10-22. Baseline 2.0 unchanged.
Issues (QA of `v0.14.0-demo.1`): #389 (C-02), #390 (C-03), #406 (C-05).
Decisions: ADR-003 amendment 6, ADR-015 amendment 5, ADR-002 note of 2026-10-22.

### Scope
- **Red-flag screen (#389, R15, R17):** `apps/api/app/modules/safety/screen.py`: `PROMPT_VERSION = "red-flag-screen-2"`
  (sha256 `598398e1…`).
  - An acute sign happening now, or just now, in someone the person cares for or is with counts when the words ask
    for help for them, as the person's own does.
  - Another person's past illness, long-standing condition, family history, a sign that is only background to the
    writer's own concern, and a question about what to do next time do not count.
  - Examples added: "threw up something like coffee grounds" or "吐血" is vomiting blood, "I bring up every sip of
    water" is being unable to keep fluids down, "kms" is a thought of suicide.
  - Everything else of `red-flag-screen-1` stays, including "When you are unsure ..., count it".
- **Terse false alarms (#390): not fixed.** Every draft that narrowed "when unsure, count it" for terse or
  other-language concerns lost at least one labelled emergency on the Nano (drafts 3–5, 9, 10, 15), so none shipped.
  `red-flag-screen-2` lowers these false alarms only slightly (the C-03 sets: Nano 54 → 50, Fury 37 → 32).
- **Concern check (#406, R16):** `apps/api/app/modules/cases/concern_check.py`: `PROMPT_VERSION = "concern-check-3"`
  (sha256 `198623b5…`). Medical abbreviations ("ED", "IBS") and emoji that show a symptom, a sore body part or feeling
  unwell ("🤒") count as health matters; emoji with no health meaning do not. Everything else of `concern-check-2`
  stays.
- **Tests:** `tests/acceptance/test_R15.py` (shipped screen version and hash equal the record, both gate files and both
  manifests; carers' emergencies urgent on both devices and not before; other people's past or background signs stay
  out; the kept rules; the set carries every labelled urgent set) and `tests/acceptance/test_R16.py` (the same for
  `concern-check-3`; "ED" and "🤒" accepted on both devices and refused before; `concern-check-2`'s record kept).
- **Records:** both model manifests carry `generation.red_flag_screen` (new) and the updated
  `generation.concern_check`; ADR-003 amendment 6, ADR-015 amendment 5 and an ADR-002 note.
- **Evidence:** `evidence/model-qualification/2026-10-22-red-flag-screen-2/` and
  `evidence/model-qualification/2026-10-22-concern-check-3/`: sets, held-out sets, runners, gate scripts, baselines,
  drafts and both devices' runs.
- **Lock:** refreshed with `update_spec_lock.py --change-id CHG-DEV-QUAL-005`.

### Not changed
- **Clinical content:** RF01–RF20, their wording and levels, both messages, Q01–Q10, the pathway `general-adult-4`.
- **Behaviour around the prompts:** the screen's input (`person_words`, #387), its answer schema, its failure paths
  (defer at creation, fail closed before guidance), the concern check's answer, refusal and failure path.
- **Devices:** models, serving, ZRT, services and device configuration. The guidance prompt and the certainty review.
- **Interfaces:** OpenAPI, contracts, routes and screens.

## CHG-DEV-SAFE-001

Type: clinical-safety behaviour (M03, M05) and one API field, development application. Not a release by itself.
Date: 2026-10-18. Baseline 2.0 unchanged. Issue: #153. Decision: ADR-003
amendment 3.

### Scope
- **Screening:** `safety/screen.py`, `cases/service.py`. In local mode the red-flag screen reads the concern when a
  case is created, and when its concern is edited:
  - a match routes the case to urgent help before any question;
  - a failure defers to the screen before guidance, which still fails closed.
- **Level on the case:** `core/db.py`, `cases/repository.py`, `guidance/service.py`, `operations/scenarios.py`. The new
  nullable `cases.urgent_level` column is added in place on older databases. It records the reviewed level of the
  red flag that routed the case, on every urgent route.
- **Setting:** `config.py`, `AWARECARE_CONCERN_SCREEN_TIMEOUT_SECONDS` (default 20).
- **API:** `spec/api/openapi.json` and `spec/contracts/Case.schema.json`. `Case.urgent_level` is added: `emergency`,
  `urgent_clinician` or `null`, and required. `apps/web/src/api/schema.ts` is regenerated.
- **Web:**
  - A03 and A06 go straight to A15 with the level when the response is urgent;
  - A07 and A15 read the level from the case.
- **Tests:** `tests/acceptance/test_R15.py` (7 new; existing screen tests script the answer after creation),
  `test_R17.py`, `test_R38.py` and `conftest.py`; `tests/ui/A15.spec.ts` (3 new tests, each on desktop and mobile).
- **Lock:** `spec/lock.json` refreshed with `update_spec_lock.py --change-id CHG-DEV-SAFE-001`.

### Not changed
- **Prompts and qualification:** the red-flag screen prompt and the guidance prompt. No re-qualification is needed:
  the same screen gets a subset of its usual input.
- **Approved content:** the approved red flags and messages.
- **Mock mode:** typed text is still never evaluated there.
- **Routes, operation IDs and screens.**

## CHG-DEV-SAFE-002

Type: clinical-safety behaviour of the red-flag screen (M05) and of guidance post-processing (M08), and context write
validation (M03), development application. Not a release by itself. Date: 2026-10-22. Baseline 2.0 unchanged.
Issues (QA of `v0.14.0-demo.1`): #387 (C-01), #391 (C-04), #407 (C-06), #448
(C-07), #393 (J-10), #433 (S-04). Decisions: ADR-003 amendment 5, ADR-012 amendment 2.

### Scope
- **Profile text in the red-flag screen (#387, R15, R17):** `safety/screen.py`, `cases/service.py`.
  - The person's words now include the free text typed into the profile: relevant history, current medications and
    reported allergies, each labelled with its field (`profile_words`).
  - The screen reads them with the concern when a case is created, when an edit changes the concern or that text, and
    before guidance with every answer.
  - A profile edit that leaves the text unchanged is not screened again. The concern check runs only for a changed
    concern, as before.
- **Level consistency (#391, R24):** `guidance/local.py` (`clinician_next_step`, `published_level`) and
  `guidance/service.py`.
  - A self-care draft whose own next steps send the person to a clinician is published at `routine_clinician`. That
    covers an imperative to see, book, arrange, contact, consult, ask or talk to a clinician, an appointment or
    medical advice, and a step or rationale saying the concern needs a professional assessment.
  - Reason code `CLINICIAN_NEXT_STEP_RAISED_LEVEL`; content-free event `guidance_level_raised`.
  - Conditional safety-netting, preparation for an existing visit and a pharmacist do not count. It never lowers a
    level, and the mock path is unchanged.
- **Medication tripwire (#407, R25):** `guidance/service.py`, `guidance/local.py`.
  - `MEDICATION_CHANGE_PATTERNS` send dosing and change phrasings to the certainty reviewer.
  - `medication_instruction` is a deterministic validator rule (code `medication_change`, repaired once): a clause
    that itself instructs stopping or changing a medicine, or gives a dose.
- **Allergy limits (#448, R04):** `guidance/local.py` (`allergy_limits`), `guidance/service.py`. Unless allergies were
  reported, the model's limits that mention allergies are dropped. With the status unknown, "Allergies were not
  recorded." is listed instead. A07, A12 and the PDF read the same list.
- **Located repair (#393, R24):** `guidance/local.py`. For `third_person` and `medication_change`, the single repair
  names the statement's place (`actions[2].rationale`), never its text. The validator rule is unchanged.
- **Reserved context kinds (#433, R04, R14):** `cases/service.py`, `guidance/service.py`.
  - `createCase` and `editCase` refuse `confirmed_context` kinds `answer:`, `fixture:` and `record:` with 422
    `VALIDATION_FAILED`, field `confirmed_context.kind`, code `reserved`. `spec/api/README.md` notes it.
  - `intake_answers` counts only answers that have their question as source.
- **Tests:**
  - `tests/acceptance/test_R15.py`: 5 new; `conftest.py`: the scripted screen may depend on its words.
  - `test_R24.py`: #391, #393 and #448, with the phrase lists for both directions.
  - `test_R25.py`: #407, its phrasings and its negatives; `test_R04.py`: 3 new for #433.
- **Records:** ADR-003 amendment 5, ADR-012 amendment 2, the Wiki pages Architecture, Product Overview and
  Troubleshooting, and the Issue Work Log.

### Measured on the Nano (local path of this branch, synthetic input)
Evidence: `evidence/clinical-review/2026-10-22-qa-clinical-safety/`.
- **#387:** the QA's overdose in "Current medications" and suicide attempt in "Relevant history" (API and A02 form
  shapes) were routed to urgent help when the case was created, 3 of 3 (RF20, RF11). The creation-time screen found
  5 of 5 written profile emergencies in every one of 3 runs. It raised no false alarm on 12 ordinary history,
  medication and allergy texts.
- **#393:** the dry-skin case failed 3 of 3 before (`third_person` in both attempts). After the change it passed
  3 of 3 by the app path, each after one repair.
- **#391:** the QA's heartburn (G02), low mood (G04) and medication question (G08) results published `routine_clinician`.
  Over the 50 clinical-review cases, 49 published, as before. The one fallback, C20, fails the same way without this
  change. The rule raised 7 self-care results, each with a clinician next step or rationale.
- **#407:** the reviewer judged 4 of the 5 new phrasings unsafe, 3 of 3 runs each. It cleared the published
  "Stop any new medication immediately if ..." 3 of 3, so the validator rule above rejects it. In G08 the rule caught
  it and the repair removed it.
- **#448:** G04 and G09 list "Allergies were not recorded." where the QA saw "The specific nature of your allergies is
  unknown."

### Not changed
- **Prompts and qualification:** the guidance prompt, the red-flag screen prompt and the reviewer prompt are
  unchanged; so are the models and ZRT.
- **Approved content:** the approved red flags, messages, questions and levels.
- **Mock mode:** typed text is still never evaluated there.
- **Routes, operation IDs, screens and wire schemas:** unchanged, so `spec/lock.json` does not change.

## CHG-DEV-SEC-001

Type: new operator-script registration and qualification-harness change (ADR-002 stage 6; R34, R37), not a release.
Date: 2026-10-18. Issue: #151. Decisions: ADR-002, ADR-014, ADR-018.

### Scope
- **New file:** `scripts/egress_watch.sh`, registered in `spec/traceability.yaml`. It samples the model processes'
  connections **and listening sockets** every second.
- **Changed:**
  - `scripts/qualify_model.py gates` parses the sampler's fields and fails stage 6 on a non-loopback connection or
    listener. It reports `listeners_checked` for older logs that lack the field.
  - `infra/fury/zrt/serve-model.sh` pins `VLLM_HOST_IP=127.0.0.1`.
  - `infra/fury/model-manifest.json` records the serving environment and the re-qualification.
- **Tests:** `tests/acceptance/test_R26.py` (+1).

### Not changed
Every ID, route, operation, contract and gate threshold; requirement statuses (`planned`).

## CHG-DEV-SEC-002

Type: API behavior, contract-description, spec-text, web and test change (M01, M03, M06, M10, M11, M12; R01-R03, R18,
R34-R38), not a release. Date: 2026-10-22. Issues (comprehensive QA of 2026-10-22, API security group):
#397, #431, #434, #435, #440, #463, #464, #465, #466, #471.

### Scope
- **Admission of the concern screens (#397, M03/M12):** the red-flag screen and concern check that `createCase`,
  `editCase` and a written-urgency `loadScenario` run inside the request now pass the central admission
  (`JobRunner.screening`, a sibling lane of the generation admission): one screening on the runtime, three waiting
  (the configured active and queued limits), at most one per session, and 429 `QUEUE_FULL` with `Retry-After` in the
  Error schema beyond that (counted as `admission_refused`, like generation). A duplicate `createCase` with the same
  Idempotency-Key waits for the first and replays it (one model call). A refused request changes nothing.
- **Per-session bounds (#397):** at most 100 open consultations per session (409 `CASE_LIMIT`), 10 summaries per
  15 minutes (429 `EXPORT_LIMIT` with `Retry-After`), 30 records per session (413 `RECORD_LIMIT`; 3 per case as
  before). A03 shows the refusal message (no change needed); A12 now shows the reason of a 429 in its failure banner.
- **Body limit by exact route (#431):** the 30 MiB allowance is matched by method and whole route (`POST
  /cases/{case_id}/records`); every other request is capped at 256 KiB whatever its last path segment. The checks run
  in one ASGI layer (`BodyPolicy`) before any body is read: malformed `Content-Length` 400, oversized 413, an upload
  without a valid session 401, chunked bodies read only up to the limit.
- **Session rotation (#434, M01):** `createSession` with a valid session of the same role continues the actor under a
  new session (new ID, token and CSRF token, `Set-Cookie`) and revokes the old one, instead of returning the existing
  session. Contract change: the `createSession` description in `spec/api/openapi.json` (and the regenerated
  `apps/web/src/api/schema.ts`); no field, status or operation changed. T-R01-S01/S02 still hold (no second actor; the
  existing actor stays the owner).
- **Concurrent duplicate scenario loads (#435, M12):** `loadScenario` runs serialized per Idempotency-Key
  (`idempotency.serialized`), so duplicates return the original 201 body instead of 500 or 409 `RESET_PENDING`.
- **Strict request types (#463):** `adult_eligible` and the provider search booleans are StrictBool; every
  `expected_revision`/`profile_revision` is a strict integer; `facts_confirmed`/`user_reviewed` accept only `true`; a
  duration amount is a JSON number. Coercible values get 422. Query and multipart form fields are unchanged.
- **Error shape (#464):** body-decode failures, unknown paths and wrong methods answer in the Error schema
  (`MALFORMED_REQUEST`, `NOT_FOUND`, `METHOD_NOT_ALLOWED` with `Allow`); `HEAD` on a `GET` resource is answered like
  `GET` without a body.
- **Response headers (#465):** every API response carries `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and `Cache-Control: no-store`, errors included.
- **Image validation (#466, M06):** a PNG needs an intact first IHDR (non-zero size, valid depth and colour type), an
  IDAT, a final IEND and correct CRCs; a JPEG needs non-zero frame dimensions. Malformed images get 422
  `RECORD_MALFORMED` before a byte is stored and use no record slot.
- **Retention (#440, #471, M11):** job rows lose their actor, case and result IDs and keep only the hour when the
  owner's session ends (logout, expiry, presenter reset of a demo patient; the sweep also unlinks rows of actors that no
  longer exist); finished job rows are deleted after 30 days; AI usage counts older than 90 days are deleted by every
  sweep. W04's Retention card names job records and the 5-minute cleanup.
- **Spec text:** `spec/product.md` (session creation issues a new token; job records and AI usage counts in Default
  retention), `spec/api/README.md` (guest session retry, body limits, strict types, headers, HEAD, per-session bounds,
  error table), `spec/engineering/03`, `04`, `05`, `07`.
- **Tests:** `tests/acceptance/test_R01.py` (2 new; the two cited reuse tests keep their titles and now assert the
  rotation), `test_R02.py` (3 new, 12 cases), `test_R18.py` (2 new, 12 cases; the over-40-megapixel case now has a
  valid CRC), `records_helpers.py` (a valid `PNG_1PX`, PNG builders), `test_R34.py` (7 new), `test_R36.py` (6 new),
  `test_R37.py` (1 new, 3 cases), `test_R38.py` (7 new); `tests/ui/W04.spec.ts` (1 new), `tests/ui/qa.spec.ts`
  (3 new), both widths.

### Not changed
Every screen ID and route, every operation ID, status code set and schema field; the reviewed clinical content,
red-flag list, questions, prompts and models; local-mode failure behavior (no fallback; a screen that cannot run
defers or fails closed exactly as before); the nginx gateway templates (the API sets the headers); requirement and
acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-TEL-001

Type: new screen, new operation and contract, requirement mapping change and test change (W06; getTelemetry; R34,
R38, R39; M12), not a release. Date: 2026-10-16. Baseline 2.0 otherwise unchanged. Issue:
#122. Decision: ADR-017.

### Scope
- **Screens:** W06 `/telemetry` (Telemetry, M12) added to `spec/screens.json` and its `.yaml` mirror (25 screens) and
  to `spec/product.md`. Reference images in `spec/mockups/aware-care/`.
- **API:** `GET /telemetry` (`getTelemetry`, M12, public, `period=24h|7d|release`) in `spec/api/openapi.json` and
  `spec/api/operations.json` (32 operations). New contract `TelemetrySnapshot` with three contract cases.
- **Mappings:**
  - **R38 and R39:** gain W06 and `getTelemetry`, plus new acceptance scenarios T-R38-S03 and T-R39-S02
    (NOT_EXECUTED in the registry);
  - **R34:** gains W06;
  - **M12:** owns `getTelemetry` and W06.
- **Traceability:** new runtime files registered.
- **Checkers:** `check_traceability.py` (25 screens, 32 operations, route W06) and `check_contracts.py` (the added
  operation; public like `getReadiness`). CLAUDE.md: W01–W06, 25 routes.

### Not changed
- Every earlier requirement, screen, route, module, operation and contract.
- All requirement statuses stay `planned`.

## CHG-DEV-TEL-002

Type: contract change and test change (`TelemetrySnapshot`; R38, R39; W06), not a release. Date: 2026-10-16. Issue:
#124. Decision: ADR-017 (unchanged).

### Scope
- **Contract:** `TelemetrySnapshot` gains the required object `metered` with `since` and `guided`: the window in which
  model calls are metered (from the first start of a telemetry release) and the consultations guided in it. Updated
  in `spec/contracts/TelemetrySnapshot.schema.json` and `spec/api/openapi.json`, with the contract cases.
- **Why:** the deployed `v0.6.0-demo.1` divided metered tokens and energy by every consultation in the period,
  including those from releases before metering, so per-consultation figures were too low by about 16 times.
- **W06:** per-consultation defaults use `metered.guided`. The page says when metering began after the period start.

### Not changed
Every ID, route and operation; ADR-017's decision; requirement statuses (`planned`).

## CHG-DEV-TEL-003

Type: contract change and test change (`TelemetrySnapshot`; R38, R39; W06), not a release. Date: 2026-10-17. Issue:
#127. Decision: ADR-017 (amended).

### Scope
- **Contract:** `TelemetrySnapshot.ai_calls` gains `duration_ms_total` (total model time). The pricing assumptions
  gain `other_system_power_w`.
- **Price list `2026-10-17`:** adds GPT-6 Astra (OpenAI, Standard tier, short context, $10 / $50 per 1M tokens, from
  https://developers.openai.com/api/docs/pricing, retrieved 2026-10-17) as a second frontier reference, and the
  other-system-power assumption (0 W).
- **W06:** a third cost bar; a calculator field that applies an assumed non-GPU wattage over the measured AI time per
  consultation; the statement that whole-system power is not measured on this device.

### Not changed
Every ID, route and operation; requirement statuses (`planned`).

## CHG-DEV-TEL-004

Type: new runtime file registration and test change (W06; R34, R38, R39), not a release. Date: 2026-10-17. Issue:
#129. Decision: ADR-017 (amended).

### Scope
- **New file:** `apps/web/src/screens/W06Slide.ts`, registered in `spec/traceability.yaml`. It builds the telemetry
  figures and the calculator's current scenario as one self-contained 16:9 slide (SVG, with the HP logo embedded),
  and draws it to PNG on a canvas. It is offered on W06 as Download PNG and Download SVG, with a preview.
- **Tests:** `tests/ui/W06.spec.ts` (+1): the PNG signature and 3200×1800 size, the SVG content and no external
  references, the network guard.

### Not changed
Every ID, route, operation and contract; requirement statuses (`planned`).

## CHG-DEV-TEL-005

Type: API contract (additive), behavior, screen-contract and test change (M12; W06, W03, W01; `getTelemetry`), not a
release. Date: 2026-10-22. Issues: #398, #432, #436, #437, #438, #439, #441,
#442, #446, #447, #467, #468, #469, #472, #473, #476, #477 and #405 (comprehensive QA of v0.14.0-demo.1, 2026-10-22).
Decision: ADR-017 amendment of 2026-10-22.

### Scope
- **Contract `TelemetrySnapshot`:**
  - `metered` gains the required `from`, `to`, `ai_calls`, `with_token_counts`, `prompt_tokens`, `completion_tokens`,
    `duration_ms_total`, `calls_with_energy` and `wh_total`. These are the usage of the same whole hours in which
    `metered.guided` counts its consultations (#398).
  - `ai_calls` gains the required `counted_from` and `counted_to`: the whole hours the usage totals count (#432).
  - The embedded copy in `spec/api/openapi.json`, the three TelemetrySnapshot contract cases in
    `tests/handoff/contract-cases.json` and `apps/web/src/api/schema.ts` (`npm run gen:api`) were updated.
  - No operation, route, parameter or status code was added.
- **Behavior (M12, `apps/api/app/modules/operations/telemetry.py`):**
  - Per-consultation usage comes from one window (#398).
  - Usage totals count complete hours only (#432).
  - Percentiles interpolate linearly between closest ranks (#441).
  - Mock mode gives no qualification network check (#437).
  - The outcome window, small-count suppression and per-mode counting are unchanged.
- **Screen contract W06 (`spec/screens.json`, `spec/screens.yaml`):** the window rule now says live figures count
  complete hours and that a window starting within a day names its hour (#432, #467). Three rules were added: one
  window per per-consultation figure (#398, #468, #477); mock mode (#437); calculator entries and the update control
  (#438, #439, #446). Route, ID, requirements and actions are unchanged.
- **Web:**
  - `W06.tsx`:
    - Defaults come from `metered` and name their window and basis; the volume is measured over the days counted.
    - The live figures say "complete hours".
    - The slide and the outcome tile name the span actually counted (#436, #467).
    - Mock-mode wording (#437).
    - Number fields keep the viewer's entry, reject invalid ones visibly and name their unit (#438, #439, #442).
    - Presets carry `aria-pressed` (#405).
    - An "Update every minute" control (#446).
    - One legend item per series, and the device line is dashed (#447).
    - Reliability and What we don't claim are in the section menu (#469).
    - Sources use one date and money style (#472) and stack at 360 px (#476).
  - `W06Slide.ts`: the mock-mode title, the cost panel's basis and a three-line scenario note (#437, #477).
  - `W01.tsx`: the mock-mode hero (#437).
  - `W03.tsx`: the local-processing row is labeled By design; the columns are Benefit and Status (#473).
  - `styles.css`: the legend, the dashed series and the update control.
- **Tests:**
  - `tests/acceptance/test_R38.py`: 5 new tests; 5 changed because usage totals now count complete hours.
  - `tests/ui/improve-telemetry.spec.ts`: 16 new tests, both viewports.
  - `tests/ui/W01.spec.ts`: 1 new test.
  - Changed tests: `tests/ui/W06.spec.ts` (3: the metered window, the slide's scenario title, no cross-window count),
    `tests/ui/improve-telemetry-dates.spec.ts` (the menu lists 9 sections; price-list dates are no longer exempt) and
    `tests/ui/improve-patient.spec.ts` (the W03 table's name and Status column).
- **Docs:** ADR-017 amendment of 2026-10-22; Wiki Architecture (telemetry) and the Issue Work Log.

### Not changed
- Every ID, route, operation and screen.
- The outcome-window rule (ADR-017 amendment of 2026-10-19).
- The price lists (`infra/telemetry-pricing.json`, `infra/fury/telemetry-pricing.json`); their ISO dates are formatted
  for display only.
- Reviewed clinical text, models and prompts, and the privacy boundary.
- Requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-TEST-001

Type: test coverage for T-R03-S02 (presenter refusal). Not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #19.
Affected IDs: R03 (T-R03-S02); O01–O03 screens (tests only). No application, contract or requirement change.

### Scope
- `tests/acceptance/test_R03.py`: `createSession` bodies carrying `actor_id`, `session_id`, `role`, `kind` or an
  unknown mode are rejected with `422`, and no actor or session is created.
- `tests/ui/O01.spec.ts`: with an active guest session, direct navigation to O01 stays unauthorized.
- `tests/ui/O02.spec.ts` (new): the same for O02.
- `tests/ui/O03.spec.ts` (new): the same for O03. With storage and cookie flags set to "presenter" and a forged
  assertion, every presenter operation (runtime, controls, scenario load, reset) called from the page returns
  `403 PRESENTER_REQUIRED`, and the UI still offers no presenter session.

### Specification files changed
- `spec/traceability.yaml`: `tests/ui/O02.spec.ts` and `tests/ui/O03.spec.ts` added to R03's tests. They already
  existed as planned test paths of R22, R23, R34, R37–R40.
- `spec/lock.json`: `traceability_sha256` only, via `update_spec_lock.py --change-id CHG-DEV-TEST-001`.

## CHG-DEV-TOOL-001

Type: delivery process tooling, not a release. Date: 2026-10-21. Baseline 2.0 unchanged.
Issues: #368 and #371. Decisions: ADR-010, ADR-011. Affected IDs: R40.

### Scope
- `scripts/check_all.sh` (#368): every local pre-PR check in CI order (web type-check, contrast, tooling tests,
  traceability, contracts, Wiki lint, backend), with a summary table and a non-zero exit on any failure; `--fast`
  skips backend and browser, `--full` adds the browser suite under the optional `AWARECARE_PW_LOCK` lock, `--pre-pr`
  lints `#PRNUM` as a number without changing the work log, `--dry-run` prints the plan. Never installs dependencies.
- `scripts/dev/` (#371), brought into the repository from the maintainer's process and generalised (repository from
  `$AWARECARE_REPO` or `gh repo view`, worktree `--repo DIR`, Project `--project` / `$AWARECARE_PROJECT` / 77):
  - `ship.sh`: preconditions (branch `<type>/<N>-<topic>`, clean tree, `Refs #N`, no closing keyword), checks, push
    without force, PR create or reuse, `#PRNUM` fill and commit, merge after green, then tick code boxes;
  - `merge_when_green.sh`: merge commit at the checked head SHA only when every check run succeeded;
  - `devtools.py`: box rules (device-measurement and deployment boxes stay open), `#PRNUM` fill, pre-PR lint, the
    keep-both-sides conflict resolver;
  - `project_fields.py`: Project field values from a file; Release options added with existing option ids kept.
- `tests/tooling/test_dev_tooling.py`: box rule, PR-number fill, union resolver, check_all arguments, ship dry run,
  merge_when_green against a stand-in `gh`, Project option merge, and no scratchpad path, home path or token in the
  scripts.
- CI lints the new shell scripts (`bash -n`, `shellcheck`) and compiles the Python ones.
- Documentation: CLAUDE.md, the PR template, the Testing Wiki page (one section), a new Contributing Wiki page
  (managed page, sidebar and Home).

### Specification files changed
`spec/traceability.yaml` registers the five new scripts as shared files (R40, `implemented`, tested by
`tests/tooling/test_dev_tooling.py`); `spec/lock.json` refreshed for this record.

### Not changed
Product baseline, requirements, screens, OpenAPI, contracts, acceptance statuses, application code, deploy workflows.

## CHG-DEV-UI-001

Type: presentation and interaction change (web), not a release. Date: 2026-10-16. Baseline 2.0 unchanged.
Issue: #98. Related: ADR-014 (#97).

### What changed
A premium, HP-branded redesign of `apps/web`, with a truthful local-AI signature on every route.
- **Design system** (`src/styles.css`): tokens, components and screens.
  - **Colours:** HP blue `#024AD8`, taken from the official logo, is the primary action colour. The spec palette is
    otherwise kept, with status roles derived from it.
  - **Type:** a bundled typeface, Inter (OFL, `@fontsource-variable/inter` 5.3.0, pinned), with a system fallback.
  - **Structure:** a type scale, the spacing scale, elevations, and motion that is honoured only without reduced
    motion.
- **`src/components/Brand.tsx` (new):**
  - the HP lockup, using the official logo (`src/assets/brand/HP_logo_2025.svg`, supplied by the product owner);
  - the local-AI signature in the header strip and the footer of every layout. It claims a running model only when a
    server response proved local mode and readiness is `ready`. It says mock in mock mode, and degraded or
    unavailable when readiness does.
- **`src/components/Icon.tsx` (new):** an inline stroke icon set, always next to text.
- **`src/state/AppState.tsx`:** in-memory runtime mode, learned from responses, and readiness, from GET
  `/health/ready` on load and every minute. Neither is health data, and neither is persisted.
- **Screens:**
  - W01: the on-device story;
  - A07: a leading level card with a labelled level badge, and an even result grid;
  - O01: status tiles.
  - All others take the new system through shared classes. The texts, roles and behaviour of every screen are
    unchanged.
- **`spec/product.md`:** the token table's primary colour and typeface notes.
- **`spec/traceability.yaml`:** `Brand.tsx` and `Icon.tsx` registered (R01, R15, R34).
- **Checks:**
  - `scripts/check_contrast.py`: WCAG 2.2 AA for every design pair, enforced by
    `tests/tooling/test_check_contrast.py`;
  - `tests/ui/routes.layout.spec.ts`: the lockup and signature on all 24 routes; signature truthfulness (unknown,
    mock, local, degraded, unavailable); rendering with the bundled typeface while the internet is unreachable; and
    reduced motion.

### Not changed
- The 24 routes, the screen IDs, all API calls and operations, and behaviour.
- The reviewed clinical text: red flags, the A15 messages, questions and guidance.
- Truthfulness labels.
- No endpoint is added, and no request leaves the device (the `guardNetwork` allow-list stays empty).

## CHG-DEV-UI-002

Type: presentation and interaction change (web), not a release. Date: 2026-10-19. Baseline 2.0 unchanged.
Issues: #182 to #191. Related: CHG-DEV-UI-001 (#98).

### What changed
Ten usability and accessibility improvements to `apps/web`, one issue each:
- **#182, a phone menu everywhere:** the patient and presenter layouts use the same Menu button as the public
  layout, so their navigation is no longer cut off at 360 px.
- **#183, a step indicator (`src/components/JourneySteps.tsx`, new):** every consultation screen shows where the
  person is among eight steps, as an ordered list with `aria-current="step"`. On phones it is a compact
  "Step n of 8" line with a bar.
- **#184, red flags:** the "none of these" option is set apart by an "or" divider. Ticking a sign announces that
  Continue leads to urgent help.
- **#185, one "Not sure":** when a question offers "Not sure" as a choice, the separate button is hidden. Choosing it
  still records the answer as unknown, so it counts as a gap (R13, R14) exactly as before.
- **#186, guidance progress:** while guidance is generated, A07 shows the elapsed seconds and what is happening, a
  note after 30 s, and a screen-reader status every 10 s.
- **#187, next steps first:** A07's next steps (Find care, Summary, Sources) sit directly under the level card, once.
- **#188, history:** A13 shows each case's concern, start time and time left, and names the resume action by the
  case's state.
- **#189, a short demo notice on phones:** one line with its essentials ("Demo · fictional people only · not medical advice"). The full notice, which
  also asks not to enter real health information, stays on wider screens and, visually hidden, for screen readers on
  phones.
- **#190, disabled-button hints:** A06 and A12 say why Generate or Create is disabled, linked by
  `aria-describedby`.
- **#191, W06:** an "On this page" section list that moves focus to the chosen heading.

`spec/traceability.yaml`: `JourneySteps.tsx` registered (R01, R11, R14); `tests/ui/ux.spec.ts` added to `Layout.tsx`.

### Not changed
- The routes, the screen IDs, API calls, operations, the stored data, and the intake and guidance behaviour.
- The reviewed clinical text: red flags, questions, guidance, and the urgent-help messages.
- Truthfulness labels.

## CHG-DEV-UI-003

Type: presentation and wording change (web), plus the display range of scale answers and plain punctuation in the
PDF. Not a release. Date: 2026-10-19. Baseline 2.0 unchanged. Issues: #212 to
#221. Related: CHG-DEV-UI-002.

### What changed
Ten changes that make the app easier to use, one issue each, from a screen-by-screen audit at 1440 and 360:
- **#212, A01:** guest is stated, not offered as a one-option choice. Consent is headed in plain words, with its
  version in small print. The session request is unchanged.
- **#213, A02:** the disabled "Save to profile" says why (`aria-describedby`).
- **#214, A03:** a link moves focus to "None of these apply" without ticking it. The reviewed wording and order are
  unchanged.
- **#215, M04:** a scale answer's fact carries its range in `units` ("on a 0–10 scale"), so A06, A12 and the PDF show
  "4 on a 0–10 scale". The local model reads only the value, so its input is unchanged. The PDF writer now prints
  typographic dashes, quotes and ellipses plainly instead of as "?".
- **#216, A09:** each criterion is tagged Filter, Ordering or Optional, matching the provider search. The request is
  unchanged.
- **#217, A10 and A11:** each doctor fact appears once; only the rest of the explanation is shown with the lists.
- **#218, A14:** each delete action says what it removes and what happens next.
- **#219, A16:** a line under "Use reviewed alternative guidance" says it opens Help. The label is the screen
  contract's primary action and stays.
- **#220, `src/components/ResumeSession.tsx` (new), W01 and A01:** an open guest session is offered "Continue your
  consultation", using the existing quiet session probe. No new endpoint.
- **#221:** plain wording on A04, A10, A11 and A14. The directory version stays visible in small print.

`spec/traceability.yaml`: `ResumeSession.tsx` registered (R01, R02).

### Not changed
- The routes, screen IDs, primary actions, API operations and schemas.
- The reviewed clinical text (red flags, questions, guidance) and its order.
- The model inputs, and truthfulness labels.

## CHG-DEV-UI-004

Type: presentation change (web): a wider colour palette. Not a release. Date: 2026-10-19. Baseline 2.0 unchanged.
Issues: #239 to #248. Related: CHG-DEV-UI-001 (design system), CHG-DEV-UI-003.

### Why
The design system used HP blue for nearly everything, with teal and the warm accent hardly visible. Screens looked
uniform: every card, status and step had the same blue-grey treatment. `spec/product.md` asks for "purposeful
color" and the blue, teal and warm accent palette.

### What changed
`spec/product.md`, the Color row of the visual design table: the extended palette and the rule that colour marks one
meaning per screen, always beside a text label, number or icon.

One issue per change:
- **#239, tokens:** violet, sky, amber, rose, green, coral and slate (solid, tint, ink), a solid teal, the 0–10 scale
  ramp (`--scale-0` to `--scale-10`), and a brand gradient line. 106 pairs are checked in `scripts/check_contrast.py`
  (text 4.5:1, UI 3:1, and large text 3:1 for the bold 19 px numeral of a selected scale value). All pass.
- **#240, frame:** a 3 px gradient line (blue, teal, violet, coral) under the header and above the footer, and soft
  radial washes behind the home hero.
- **#241, W01:** the three steps are blue, teal and violet, each with an icon tile and its number.
- **#242, journey steps:** done steps are teal with a check, the current step is blue with a ring, and the phone
  progress bar is a gradient.
- **#243, A07:** the level of care has its own colour as a band, a wash and the badge outline: self-care green,
  routine blue, urgent clinician amber, emergency red, undetermined slate. The level stays named in text.
- **#244, A07:** the four guidance cards have violet, teal, amber and slate accents with an icon tile.
- **#245, A05:** scale values run cool to warm. The numerals stay, the selected value fills with its colour, and the
  anchor labels take the ends' colours. The question card has a sky band; a ticked choice is tinted.
- **#246, A13 and A04:** statuses are chips with an icon and their words. Fact badges are green (confirmed), amber
  (unconfirmed) and slate (rejected).
- **#247, A10 and A11:** doctor cards take a hue per rank on the edge and the rank badge. Confirmed facts carry a green
  check and unknown facts an amber question mark, under the existing Confirmed and Unknown headings. Marks are
  decorative (empty alternative text).
- **#248, W06 and O03:** telemetry tiles cycle through five hues; presenter scenario cards take a hue per kind (the
  urgent scenario red).

Hover lift on cards only under `prefers-reduced-motion: no-preference`.

### Not changed
- The routes, screen IDs, primary actions, text, API operations and schemas.
- The reviewed clinical text, its order, the model inputs, and the truthfulness labels.
- Colour is never the only signal: each hue sits beside the text, number or icon it accompanied before.

### Evidence
- `tests/ui/colour.spec.ts` (new): computed colours per change at 1440 and 360. The steps, guidance cards, scale
  values, doctor ranks, telemetry tiles and scenarios are distinct; the labels, numbers and icons remain.
- `scripts/check_contrast.py` and `tests/tooling/test_check_contrast.py`: 106/106 pairs pass, and every checked literal
  is one the stylesheet uses.
- The full browser suite (including axe on all 25 routes), backend and tooling suites, run on the mock stack.
- Not verified for release; not deployed.

## CHG-DEV-UI-005

Type: presentation change (web): the second colour pass. Not a release. Date: 2026-10-19. Baseline 2.0 unchanged.
Issues: #250 to #259. Related: CHG-DEV-UI-004 (first colour pass).

### Why
The first pass (#239–#248) coloured the core journey. The public pages (W02–W05), consent (A01), the warning-sign
checklist (A03), the summary (A12), data settings (A14), urgent help (A15) and the presenter runtime (O01) were still
white and grey, and primary buttons were a flat blue block.

### What changed
`spec/product.md`, the Color row: primary actions use an HP blue gradient (#024AD8 to #2D3FCF). The rest of the pass
uses the palette CHG-DEV-UI-004 recorded.

One issue per change:
- **#250:** the eyebrow dash is a short blue, teal and violet gradient bar.
- **#251:** primary buttons are a blue gradient with a soft blue shadow. Secondary, danger and urgent buttons are
  unchanged. New token `--brand-deep`; white text passes on both ends.
- **#252, W02:** the steps are blue, teal and violet with icon tiles, matching W01. The example question's choices
  are sky chips (still a list).
- **#253, W03:** each stakeholder has a coloured icon tile. "Not measured" cells are slate chips, so a hypothesis
  never reads as a result.
- **#254, W04 and W05:** privacy cards with teal, sky, amber and violet accents and icons. FAQ items have a violet
  chevron that turns when open and a tinted open state (native `details`/`summary`, unchanged text).
- **#255, A01:** the consent panel is violet with a shield until the terms are accepted, then green with a check.
- **#256, A03:** a ticked warning sign turns rose; a ticked "None of these apply" turns green. The reviewed wording
  and order are unchanged; the concern card has a sky band.
- **#257, A12:** summary sections have icon tiles (sky, teal, amber, violet). Unknown or unanswered values are soft
  slate tags, not underlined, so they are never mistaken for links. The PDF is unchanged.
- **#258, A14 and A15:** retention sky and delete rose; "What to do" red and "Start a different case" slate, each with
  an icon. The urgent instruction and actions are unchanged.
- **#259, O01:** the device, runtime and status tiles are blue, violet and a state colour (green ready, amber
  degraded, red unavailable), with the state still in words. Each timing has a bar proportional to the total.

New icons in `src/components/Icon.tsx`: download, sliders, trash, users, stethoscope, building, wallet, chevron, help
and file. Like the rest of the set, they are decorative and hidden from assistive technology.

### Not changed
- The routes, screen IDs, primary actions, text, API operations and schemas.
- The reviewed clinical text, its order, the model inputs, the truthfulness labels and the PDF.
- Colour is never the only signal.

### Evidence
- `tests/ui/colour.spec.ts`: ten new tests (#250–#259) at 1440 and 360; 34 colour tests pass.
- `scripts/check_contrast.py`: 123/123 pairs pass (17 new). `tests/tooling`: OK.
- The full browser suite (with axe on all 25 routes), backend and tooling suites on the mock stack.
- Not verified for release; not deployed.

## CHG-DEV-UI-006

Type: screen-contract, behavior and test change (M01, M03, M05; W01, W02, W05, A01, A13, A15, A16 and every layout),
not a release. Date: 2026-10-21. Issues: #339, #340 and #345 (usability walk of
v0.11.0-demo.1 on the ZGX Nano and the ZGX Fury, 2026-10-21). Decision: ADR-013 amendment of 2026-10-21 (label only).

### Scope
- **#339, not-found and error pages (`apps/web/src/components/NotFound.tsx`, `routes.tsx`, `main.tsx`):** each layout
  (public, patient app, presenter) gets a fallback for unknown addresses under it (`*`, `/app/*`, `/presenter/*`) and
  a route-level error page; both render inside that layout (header, "Emergency? Call 911", footer) with ways on: the
  open consultation ("Continue consultation") or "Start a new consultation", home, Help, and on the presenter gateway
  the presenter scenarios (O03). The error page offers Reload, names no error and shows no developer text, stack trace
  or result in place of the failed page. A failure of a layout itself falls back to a plain page with Reload, home,
  Help and the 911 line. These are not screens: the 25 screen IDs and routes (`SCREEN_ROUTES`, `spec/screens.json`)
  are unchanged. The gateways already serve `index.html` for unknown paths (`infra/deploy/web.conf.template` and
  `presenter.conf.template`, `try_files $uri /index.html`); they are unchanged.
- **#340, one resume target (`apps/web/src/components/resume.tsx`):** the current screen of the open guest session's
  most recently changed consultation, from the session's own case list (operation `listCases`, read with the quiet
  401 handling as `api.listCasesQuietly`), mapped with A13's rule (`caseNextStep`, moved out of `A13.tsx`); with a
  session and no consultation, A03. Used by Help (W05), the home and A01 banner (`ResumeSession.tsx`), the public
  header and the home hero (and W02). No new operation, nothing in browser storage; without a session nothing changes
  and no error shows.
- **#345, one name:** "Start a new consultation" for every action that starts one (public header and W01/W02 without
  a session, app navigation, A07/A12 reset card, A13 empty state, A15, A16, the case-unavailable state, the session-
  ended warning); "Continue consultation" for resuming. Surrounding text follows (reset card heading and line, A15
  restart card's last sentence, A01 session-ended and reset banners).
- **Screen contracts (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** W01, W02 and W05 primary actions
  and action contracts (start and continue, with their targets); A15 and A16 restart action labels; the public
  website navigation row. IDs, routes, modules and requirements unchanged.
- **Traceability:** `components/resume.tsx` and `components/NotFound.tsx` registered as shared files;
  `tests/ui/improve-wayfinding.spec.ts` added to `Layout.tsx` and `ResumeSession.tsx`.
- **Tests:** `tests/ui/improve-wayfinding.spec.ts` (10 new, both viewports). Assertions changed for the new labels
  (titles unchanged): `A12.spec.ts`, `A15.spec.ts`, `A16.spec.ts`, `W01.spec.ts`, `SessionExpiry.spec.ts`,
  `colour.spec.ts` (two), `intuitive2.spec.ts` (two), `ux.spec.ts`, and `intuitive.spec.ts` (#220: the banner now
  opens the open question instead of History).

### Not changed
Every ID, route, operation and screen; the API; reviewed clinical text (urgent and limits messages, red flags,
guidance), models and prompts; the privacy boundary; local mode failing closed; requirement and acceptance statuses
(`planned`, `NOT_EXECUTED`).

## CHG-DEV-UI-007

Type: screen-contract and presentation change (web; A05, A10, A11, the shared step indicator), not a release.
Date: 2026-10-21. Issues: #341, #343 and #348 (usability walk of
v0.11.0-demo.1 on the ZGX Nano and the ZGX Fury, 2026-10-21).

### Scope
- **#341, screen contracts A10 and A11 (`spec/screens.json`, `spec/screens.yaml`, `spec/product.md`):** both gain the
  action contracts "Continue to visit summary" (A12) and "Back to guidance" (A07) and one validation rule each. A11's
  primary action is now "Continue to visit summary"; "Open contact or booking site" (the simulation dialog, "Preview
  contact handoff") stays on the page as a secondary action, and "Back to matches" stays. A10's primary action
  ("Inspect doctor", per card) is unchanged; the no-match recovery (explicit filter change, "Keep my requirements",
  "Change preferences yourself") is unchanged and the two ways on are added below it.
- **#343, step indicator (`apps/web/src/components/JourneySteps.tsx`):** once a screen's own case read shows current
  guidance (A07 showing guidance, A10 with a search, A11 with a card, A12 with its preview; A05, A06 and a failed or
  stale A07 clear it), Guidance (A07), Find care (A09, the destination of A07's "Find appropriate care") and Summary
  (A12) are links, except the current step. Profile, Concern, Records, Questions and Review stay text. On phones the
  links form a compact row under "Step n of 8"; the screen-reader step list there names them as text, so no hidden
  element takes focus. The observation is kept in React memory of the patient shell only; no request is added and
  nothing is persisted. The current step keeps `aria-current="step"`; done steps keep "(done)".
- **#348, screen contract A05:** one validation rule. At phone width the question page shows one indicator,
  "Step 4 of 8 · Question n of up to 10", with one bar (the question bar); the journey's phone line and bar give way
  while a question is shown. Wider screens keep the step list, the question line and its bar. The element with the
  exact text "Question n of up to 10" is unchanged at both widths.
- **Web:** `A05.tsx`, `A06.tsx`, `A07.tsx`, `A10.tsx` (shared `WaysOn`), `A11.tsx`, `A12.tsx`, `JourneySteps.tsx`,
  `ui.tsx` (`PageHead` eyebrow accepts elements), `styles.css`.
- **Tests:** `tests/ui/improve-flow.spec.ts` (7 tests, both viewports). Registered in `spec/traceability.yaml`.

### Not changed
Every ID and route (25), operation, schema and module; A11 contact remains a simulation with no booking API; reviewed
clinical text, models and prompts; the privacy boundary; requirement and acceptance statuses (`planned`,
`NOT_EXECUTED`).

## CHG-DEV-UI-008

Type: presentation and behavior change (web: A01, A02, A03), plus test changes. Not a release. Date: 2026-10-21.
Baseline 2.0 unchanged. Issues: #342 and #344 (usability walk of v0.11.0-demo.1
on the ZGX Nano and the ZGX Fury, 2026-10-21).

### Scope
- **#342, `src/components/ErrorSummary.tsx` (new), A03 and A01:** a failed submit shows an error summary at the top of
  the form ("Check these before you continue"), listing each open problem as a link that moves focus to its field
  (A03: the concern, the first warning sign; A01: the "Yes, I am 18 or older" choice, the terms checkbox), and moves
  focus to the summary on every failed attempt (WCAG 3.3.1, 2.4.3). The server's not-a-health-concern refusal on A03
  uses the same summary. Each item closes as soon as its problem is fixed; the summary goes when none is left. The
  summary is a named group, not a live region, and the field messages stay next to their fields without
  `role="alert"`, so the problems are announced once, through the focus. `RedFlags.tsx` gains an id on the first
  sign and an `announce` option for its message; the reviewed package (wording, order, levels) is unchanged. A01's
  age group and terms checkbox are tied to its message (`aria-describedby`, `aria-invalid`).
- **#344, A02:** "Skip — continue without a profile" near the top (after the notices, above the fields) hands A03
  exactly the session context of "Use for this session" with every field blank and allergies unknown; no request is
  added. When something was entered, it asks first ("Keep my details" or "Continue without a profile"). The bottom
  button stays.
- **`spec/traceability.yaml`:** `ErrorSummary.tsx` registered (R02, R07).
- **`scripts/check_contrast.py`:** three pairs for the summary (heading and links on the error tint, its mark, its
  focus ring).
- **Tests:** `tests/ui/improve-forms.spec.ts` (8 new, both viewports); `tests/ui/A01.spec.ts` (1 changed) and
  `tests/ui/A03.spec.ts` (3 changed): the field messages are asserted by id and text instead of `role="alert"`.

### Not changed
Every ID, route, operation, schema and screen contract (`spec/screens.json` already records A02's "Use profile or
skip" action and its "skipping does not invent negative facts" rule; A01's and A03's validation rules are unchanged);
the validation itself; the reviewed red-flag list and the consent terms; models and prompts; the privacy boundary;
requirement and acceptance statuses (`planned`, `NOT_EXECUTED`).

## CHG-DEV-UI-010

Type: presentation change of reviewed clinical content (web: A03), plus test changes. Not a release. Date:
2026-10-21. Baseline 2.0 unchanged. Issue: #355. Decision: maintainer decision of
2026-10-21 on the v0.12.0 usability proposals ("absolutely, add it to the top and group signs").

### Clinical-content note
The red-flag checklist shows the reviewed package `content/pathways/general-adult-4/red-flags.json` (ADR-003 and its
amendments). This change alters only where its items appear on A03: no sign is added, removed, merged or reworded; every
sign keeps its ID (RF01-RF20) and level; the prompt, the "None of these apply" label and the urgent messages are
unchanged; the server still re-checks every ID and decides the urgent routing. The reviewed-package block in
`RedFlags.tsx` is byte-for-byte unchanged (`tests/acceptance/test_R15.py` unchanged and passing). The group headings
are navigation aids written for this screen, not reviewed clinical content; they make no clinical claim and are not
sent to the server or the model.

### Scope
- **`apps/web/src/components/RedFlags.tsx`:** "None of these apply" is the first control of the warning-sign question,
  right after the question and its hint, and remains the one exclusive choice (ticking a sign clears it and choosing
  it clears the signs, as before). It carries the id `red-flags-first`, so the #342 error summary link ("Answer whether
  any warning signs apply to you") moves focus to it. The #214 skip link to the bottom choice is removed (no longer
  needed). The "or" divider (#184) now follows it. The hint begins "Read the signs below.".
- **Grouping:** `RED_FLAG_GROUPS` (one place, by sign ID, next to the reviewed-package block) puts the 20 signs under
  six short body-system headings; each group is a named group (`role="group"` labelled by an `h2`) inside the one
  question fieldset and legend. All signs stay visible (no collapsing); within a group the reviewed order is kept.
  - Heart, breathing and circulation: RF01, RF03, RF07, RF15
  - Brain and nerves: RF02, RF04, RF05, RF06, RF19
  - Bleeding and belly pain: RF08, RF09, RF10, RF17
  - Infection and fever: RF12, RF16, RF18
  - Mental health and poisoning: RF11, RF20
  - Injury and pregnancy: RF13, RF14
- **`apps/web/src/styles.css`:** group spacing and heading style; the unused skip-link rule is removed.
- **`spec/traceability.yaml`:** `tests/ui/improve-redflags.spec.ts` added to R15's tests.
- **Tests:** `tests/ui/improve-redflags.spec.ts` (6 new, both viewports: group guard against the reviewed package,
  position, groups and wording, exclusivity, error-summary focus and keyboard, axe); `tests/ui/intuitive.spec.ts`
  (#214 test rewritten: the choice is reached by one Tab, no link) and `tests/ui/routes.layout.spec.ts` (keyboard
  journey: Tab from the concern lands on the choice; the signs follow before Continue).

### Not changed
Every ID, route, operation, schema and screen contract (`spec/screens.json` does not describe the checklist layout);
the reviewed red-flag package (wording, levels, IDs, prompt, messages); urgent routing and the pathway; the
`red_flags` context sent to the server; models and prompts; the privacy boundary; requirement and acceptance statuses
(`planned`, `NOT_EXECUTED`).

## CHG-DEV-UI-011

Type: behavior and presentation change (web: A01, A04, A06, A09-A15, W05, O01/O03 sign-in and busy buttons, shared
header, controls and styles; API: provider matching for a telehealth-only search), plus test changes. Not a release.
Date: 2026-10-22. Baseline 2.0 unchanged. Issues: #394, #400, #401, #402, #403,
#418, #419, #420, #421, #444, #454, #457, #458, #474 and #475 (comprehensive QA of v0.14.0-demo.1, 2026-10-22,
after-guidance group).

### Scope
- **#394, #419, `src/components/MatchingCase.tsx` (new), A09, A10, A11:** the doctor pages read the case
  (`getCase`) before they show anything, as A07, A08 and A12 do. A case that cannot be shown (deleted, ended with its
  session, another session's, unknown) shows "This consultation is not available"; a case without current reviewed
  non-urgent guidance shows "No current guidance" (or, for an urgent case or urgent guidance, "Doctor matching is not
  available") with a link to its current step (A13's `caseNextStep`). A search held in the tab's memory is shown only
  while it is the case's current search: made at the case's current revision and the search the case read names for
  the summary (`found_doctors.search_id`, present only when the search found an eligible doctor); searches run on the
  page itself count as current.
- **#394, A13, A14, `src/state/AppState.tsx`, `JourneySteps.tsx`:** once the server accepts a deletion (one case or
  all), the tab forgets what it held for the deleted cases (doctor search and criteria, issued questions, the
  Guidance/Find care/Summary step links). `forgetCases` and `useForgetJourneyCase` are new.
- **#421, A10:** without a search on the page (after a reload, in another tab) the copy says the latest search is
  kept on this device for the consultation and its doctors appear in the visit summary (or, when no doctor was found,
  asks for a search); "Set preferences" and the #341 ways on ("Continue to visit summary", "Back to guidance") follow.
  The untrue "Search results are not kept after a reload" is gone.
- **#418, A12, `src/api/client.ts`:** the download link is followed by the page (`downloadExport`, the existing
  `downloadExport` operation read as a Blob and saved under the server's file name); a refusal shows the matching
  state in the app: 404 "This summary is no longer available" (and the page re-reads the case, so a deleted case shows
  "not available"), 409 "Your case changed" (then "Review required" when the guidance is no longer current),
  `EXPORT_EXPIRED` "The download link expired", 401 the session-ended start page, any other failure an error with the
  link kept. The link keeps its `href`.
- **#402, #420, focus, `src/components/ui.tsx` `useFocusReturn` and `Button`:** a control disabled while its action
  runs gets keyboard focus back when the action ends (or, if it is gone or stays disabled, a given fallback or the page
  heading); focus another element took meanwhile is kept. Used by `Button` (its own focus only), A04 (Confirm,
  Correct, Reject, Try unreadable file; fallback: the fact's next usable button), PresenterGate (Start presenter
  session) and O03 (Load scenario, Reset demo: one line). A04's correction editor and A06's concern editor take focus
  when they open and return it to Correct / Edit concern when they close. A10: after "Keep my requirements" focus moves
  to "You kept your requirements…"; after an accepted filter change to the new results line (or the no-match heading),
  and the outcome is announced in a status region. A12: Create PDF is `aria-disabled` while the PDF is made (it keeps
  focus) and focus moves to "Download summary (PDF)" when it is ready; a refused download or an expiring link moves
  focus to Create. Presenter sign-in moves focus to the page heading.
- **#403, `EmptyState` page variant:** its h1 takes focus when it appears (like `PageHead`), so in-app navigation to
  "This consultation is not available", "No current guidance", "This step is complete", "Review required" and the
  other page-level states is announced. A section-level state may name its heading (`headingId`) for focus.
- **#444, A10:** each "Inspect doctor" link's name includes its doctor ("Inspect doctor: Dr. Maya Chen"); the visible
  words come first (WCAG 2.5.3).
- **#454, `apps/api/app/modules/providers/service.py`, A09:** a telehealth-only search uses no in-person distance:
  no `distance_miles`, no distance in the rank key and no distance fact, whatever the radius (A10, A12 and the PDF show
  none). A09 tags the distance "Not used" ("not used for telehealth visits") while Telehealth is chosen. In-person and
  "Either" searches are unchanged.
- **#457, A15:** "Routine guidance and doctor matching are not available for this consultation" and "This urgent case
  cannot continue…" appear only when the case read shows the case is urgent; an owned case that is not urgent keeps
  the general urgent help and gets "Back to your consultation" (its current step). Urgent cases are unchanged.
- **#458, A13:** the delete confirmation names the consultation: its concern as in its row, when it started and its
  status.
- **#474, `Layout.tsx`:** the phone menu closes on any navigation (links outside the menu, Back/Forward) and on
  Escape, which returns focus to Menu.
- **#475, W05:** "My consultations" only while a guest session is open (the resume check, #340).
- **#400, #401, `styles.css`:** in forced-colours mode a focused text field, text area or select shows a 3 px
  `Highlight` outline (the box-shadow ring is dropped by forced colours), and the chosen scale value and the selected
  telemetry period or preset are drawn in `Highlight`/`HighlightText`.
- **`spec/screens.json` (and its mirror `screens.yaml`):** validation rules added to A09-A15 and W05 for the above;
  A15 gains the action "Back to your consultation" (A05, A06, A07, A16). **`spec/product.md`:** the Accessibility row
  states forced-colours visibility and focus after an action. **`spec/traceability.yaml`:** `MatchingCase.tsx`
  registered (R28-R31, R35); `tests/ui/qa-after-guidance.spec.ts` added to R29, R33, R35 and the shared header,
  controls and journey files.
- **Tests:** `tests/ui/qa-after-guidance.spec.ts` (new, both viewports; the menu test at 360 px only);
  `tests/acceptance/test_R29.py` (#454, 2 new); `tests/ui/colour.spec.ts` (#250/#251: the plain secondary button is
  checked on A01, since /help shows "My consultations" only with a session).

### Not changed
Every ID, route, operation and schema (the download uses the existing `downloadExport`; `distance_miles` was already
nullable); the reviewed clinical content (red flags, questions, pathway, urgent messages) and urgent routing; the
server's guards (it still checks every request); models and prompts; the privacy boundary (nothing new is stored or
sent; the PDF bytes stay in the tab until the browser saves them); requirement and acceptance statuses (`planned`,
`NOT_EXECUTED`).

## CHG-DEV-WIKI-001

Type: delivery process (Wiki before issue closure), not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issue: #5.
Decisions: `../decisions/ADR-011-wiki-before-closure.md` (amends ADR-010 #1). Affected IDs: R40.
No requirement, screen, route, operation, schema or application code changes.

### Scope
- `docs/wiki/`: reviewed Wiki source (Home, Product Overview, Architecture, Local Development, Testing, Release and
  Deployment, Troubleshooting, Issue Work Log, sidebar, footer). `docs/wiki-publication.json` lists managed pages,
  the import record and the Project target.
- `scripts/issue_completion.py`: check, publish, verify, complete, sync-project, sweep, guard, import, lint.
- `.github/workflows/wiki-completion.yml`: trusted publication and completion after merge, hourly retry, closure guard.
- `.github/workflows/ci.yml`: new `docs` job (lint and tooling tests) in the CI gate.
- `.github/pull_request_template.md`: `Refs #N`, acceptance-criteria status, documentation impact.
- `.claude/rules/github-work-tracking.md`: unconditional completion rule for Claude sessions.
- `tests/tooling/test_issue_completion.py`, ADR-011, this record, ADR-010 #1 and README updates.

### Specification files changed
- `spec/traceability.yaml`: `scripts/issue_completion.py`, `.github/workflows/wiki-completion.yml` and
  `docs/wiki-publication.json` registered under `shared_files` (R40, `implemented`, tested by
  `tests/tooling/test_issue_completion.py`). Requirement statuses remain `planned`.
- `spec/lock.json`: `traceability_sha256` only, via `scripts/update_spec_lock.py --change-id CHG-DEV-WIKI-001`.
- `spec/decisions/ADR-010-delivery-workflow.md` #1: `Closes #` replaced by `Refs #`.

### Not changed
`spec/product.md`, `requirements.json`, `screens.json`, `openapi.json`, contracts, `acceptance.json` statuses,
application code, infra, the project board workflows, repository settings other than the new `ready-for-completion` label.

### Evidence
Tooling tests and checks are recorded in the Issue Work Log entry for #5 and in the PR. No Wiki publication happened:
the Wiki repository is not initialized.

## CHG-DEV-WIKI-002

Type: delivery process amendment, not a release.
Date: 2026-10-14. Baseline 2.0 unchanged. Issues: #5 and #3.
Decision: ADR-011 #6, amended on the maintainer's choice ("option 2"). Affected IDs: R40; delivery records R34, R37, R38.

### Scope
- `scripts/issue_completion.py`:
  - A PR merged without an approving review counts as accepted only when an admin or maintainer merged it and an
    admin or maintainer applied `ready-for-completion`. A "changes requested" review blocks.
  - The completion comment states the acceptance basis for each PR.
  - Paginated API calls no longer need `gh --slurp`, which `gh` 2.45 lacks.
- `tests/tooling/test_issue_completion.py`: four maintainer-acceptance cases (27 tests).
- ADR-011 #6, `.claude/rules/github-work-tracking.md` rule 4.
- Wiki source: the Issue Work Log entries for #3 and #5, plus Release and Deployment and Product Overview for the
  first mock deployment. Runbook §3 state.

### Specification files changed
None registered: no new files, so `spec/traceability.yaml` and `spec/lock.json` are unchanged.

### Not changed
Product baseline, requirements, screens, OpenAPI, contracts, acceptance statuses, application code, workflows.
