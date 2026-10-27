# Testing

| Check | Command | Proves |
|---|---|---|
| Traceability | `python3 scripts/check_traceability.py` | IDs, mappings and paths are consistent (no hash lock since ADR-019) |
| Contracts | `uv run --no-project --with jsonschema==4.25.1 python scripts/check_contracts.py` | Schemas and OpenAPI agree |
| Backend acceptance (mock and local) | `cd apps/api && uv run pytest -q` | Server behavior against the contracts, isolated data per test. The tests are in `tests/acceptance/test_Rxx.py` files named after the requirement they test: 32 files for 32 of the 40 requirements (none yet for R05, R07, R22, R23, R28, R30, R31 and R40). The `local` fixture runs local mode with the reviewed pathway and a scripted model (never ZRT): red flags, missing checklist, expired pathway, approved questions, the red-flag screen (a match routes urgent; a failure fails closed), local generation, its failures and the local summary |
| Web build | `cd apps/web && npm run build` | Typecheck and production build |
| Design contrast | `python3 scripts/check_contrast.py` | WCAG 2.2 AA for every colour pair the design uses (4.5:1 text, 3:1 UI and focus); run by `tests/tooling/test_check_contrast.py` (#98) |
| Browser UI (mock) | `cd apps/web && npm run test:ui` | `a11y.spec.ts` scans all 25 routes with axe-core 4.10.3 (WCAG 2.1 AA and best practice, 1440 and 360 px, any violation fails; #158); the suite runs under the gateway's Content-Security-Policy (#157). All 25 routes (including W06 Telemetry, whose `W06.spec.ts` checks the badges, cost estimates and calculator against a fixed local snapshot) at 1440 px, plus the tests tagged `@mobile` at 360 px (#509), on an isolated stack: one gateway 15174 for both roles (`/api` and `/presenter-api`, #487), API 18000. The cross-cutting `routes.layout.spec.ts` also checks the HP lockup, the local-AI signature and the site name as the tab title on all 25 routes (the deployment's device name, ADR-018), the official HP logo as the tab icon (#107), the signature's truthfulness (unknown, mock, local, degraded, unavailable), rendering with the bundled typeface while the internet is unreachable, and reduced motion (#98). Specs that intercept requests remove their interceptors after each test, so one in flight cannot fail the next test (#134). Every axe scan first calls `animationsSettled` (`tests/ui/support/journey.ts`, #604), so no entrance fade is measured half-way. Specs that move the page clock (`page.clock`) while the API runs on real time call `trackApi` before the page loads and `apiSettled` before each jump (`tests/ui/support/journey.ts`, #501): every authenticated response re-anchors the page to the server's clock (the session expiry and the guidance wait), so a response the page handles after a jump undoes it. Every journey runs under `guardNetwork`, the R34 check (ADR-014): only GET requests for static assets to allow-listed hosts may leave, with no body, identifier, `/api` path or analytics host. The gateway serves a production build with `vite preview` (built once, in the run's temporary directory), not the Vite dev server (#66). The run removes that temporary directory when it ends, pass or fail; set `AWARECARE_UI_KEEP_DATA=1` to keep it (#94) |
| Model qualification (Nano and Fury, operator) | `scripts/qualify_model.py` `identity` / `failures` / `run` / `context` / `judge` / `compare` / `gates` | ADR-002 gates for a ZRT-served model, through the app's own local path (`guidance/local.py`) and the existing adapter, on synthetic cases (`judge` measures the ADR-012 certainty reviewer on labeled statements; rerun results, first run). `gates` gives the ADR-002 verdict per stage, and is run after every ZRT, model or serving change (ZRT 0.43.0, all gates passed). Stage 6 samples the model processes' connections and listening sockets with `scripts/egress_watch.sh` (#151). On the ZGX Fury (#137), `gates --manifest` checks stage 0 against a candidate's manifest: Qwen3.8-Flash-Next-FP8 passed every gate and the Qwen3.6 control failed stage 2 (Fury results). Not run in CI; selects no model |
| Local journeys (Nano, operator) | `evidence/local-guidance/2026-10-15/run_local_journey.py` against an API started in local mode | The real API and served model end to end on synthetic cases; content-free report (results). Not run in CI |
| Deployed release (Fury or Nano, operator) | `cd apps/web && DEVICE=Fury\|Nano npm run test:device` | The specs in `tests/devices/` against a deployed release through the tunnel (the one address `127.0.0.1:18180` of patients and presenters, #487), at 1440 and 360 px, with the device's real model: the walk-through, the one-click flow timing, the usability walk, the #355–#357 measures (#367; see below) and the release smoke (`smoke`, one patient consultation and all three presenter Quick flows, each of which must show its result, run by `scripts/release/release.sh`). Not run in CI; `npm run typecheck:device` type-checks them in CI |
| Docs and Wiki tooling | `python3 -m unittest discover -s tests/tooling` and `python3 scripts/publish_wiki.py lint` | Wiki pages and links, and the tooling |

CI runs the workflow lint, traceability, contracts, backend, web build, browser (8 shards), package smoke, Wiki lint, tooling (with contrast) and dependency-audit checks on every pull request, in the merge queue and on `main` ([Release and Deployment](Release-and-Deployment)). The rows marked *operator* run on a device by hand and are not run in CI.

Locally the suite runs with two workers on the one isolated stack (`AWARECARE_UI_WORKERS` overrides); CI runs one worker per shard (#509).

Browser helpers wait for the server response that changes the page, rather than a fixed 5 s, so slow CI runners do not cause false failures (#16, #31). The waits are `POST /sessions` in `startSessionOnly`, `POST /cases` and the first `POST …/questions/next` in `enterConcern`, and each `POST …/questions/next` in `answerAll`. `enterConcern` also answers the A03 red-flag checklist with "None of these apply" (`noRedFlags`).

## All local checks in one command

`scripts/check_all.sh` runs the pre-PR checks (#368). By default (`--changed`, #509) it runs the web type-check, design contrast, contracts, the backend suite and only the browser specs related to the files changed against `origin/main` (`scripts/changed_ui_specs.py`: a screen's own spec and every spec that names the screen ID or its route, the specs of screens using a changed component, changed specs; the whole suite when shared files change: the API client, `Layout`, routing, state, styles, `playwright.config.ts`, `tests/ui/support/`). `--standard` runs web type-check, design contrast, tooling tests, traceability, contracts, Wiki lint, and the backend suite. Every check runs even after a failure; it ends with a summary table (result and seconds per check) and exits non-zero when any check failed.

| Option | Effect |
|---|---|
| `--changed` | The default (above); `--base REF` changes the base |
| `--standard` | Web type-check, contrast, tooling tests, traceability, contracts, Wiki lint and the backend (no browser suite) |
| `--fast` | `--standard` without the backend and browser suites |
| `--full` | `--standard` plus the whole browser suite; with `AWARECARE_PW_LOCK` set it waits for that lock (`flock`), so two worktrees never share the test ports |
| `--dry-run` | Prints the plan only |
| `--verbose` | Streams each check's output instead of the tail of a failing one |
| `--repo DIR` | The worktree to check (default: the one holding the script) |

It never installs dependencies: without `apps/web/node_modules` the web checks fail with a hint.

## AI regression set

`scripts/ai_regression/run.sh <nano|fury|both|here> [--only ID,ID]` runs about 60 synthetic cases (`scripts/ai_regression/cases.json`) once per device through the app API in local mode against the device's own model (#509): red-flag screen (carers, profile text, terse and other-language texts, negatives), concern check, guidance publishing (G08 in both context orders, #407's medicine phrasings through the real repair) and a few journeys. `here` (#537, what `./demo.sh check-model` runs) uses this machine against ZRT at `$AI_REGRESSION_ZRT_URL` (default `http://127.0.0.1:8080/v1`) and the served model `$AI_REGRESSION_MODEL`; reports go to `$AI_REGRESSION_OUT` (default `/tmp/ai-regression-<time>`). The table marks a device FAIL unless urgent recall is 100%, no medicine instruction is published, every expected publish is published and every health concern is accepted; false alarms are WARN. It is advisory (ADR-019): the run still exits 0, and a change to prompts, validation or repair runs it once per device before merge and puts the result in the PR. The full qualification set is only for major prompt rewrites. It holds the device's model lock (`scripts/dev/with_model_lock.sh`). It deploys nothing and changes no device setting.

## Acceptance evidence on exact release builds

Two acceptance figures exist, and they come from different sources:
- **Release evaluation:** the verdicts that `scripts/evaluate_acceptance.py` writes for each release (until #366 `evaluate.py` in the `v0.4.0-demo.1` evidence folder; that path still works) to `evidence/releases/<tag>/acceptance/evaluation.json` and its README. This is the per-release record. The table below gives both figures, each labeled with its source.
- **Acceptance registry:** the statuses in [`spec/acceptance.json`](<your-repo-url>/blob/main/spec/acceptance.json). They were recorded once, from the #25 evaluation of `v0.4.0-demo.1` ([CHG-DEV-ACC-003](<your-repo-url>/blob/main/spec/change-records-archive.md#chg-dev-acc-003)): 35 of 82 scenarios and 16 of 40 primary records `PASSED`, the rest `NOT_EXECUTED`. Since #55 ([CHG-DEV-ACC-004](<your-repo-url>/blob/main/spec/change-records-archive.md#chg-dev-acc-004)) verdicts are recorded per release, and the registry has not been changed. T-R15, T-R16, T-R17 and T-R25 therefore pass in the release evaluation but stay `NOT_EXECUTED` in the registry.

From `v0.5.4-demo.1` the evaluation uses the extended clause map of #55 (the 42 #25 scenarios plus the 16 ADR-003 clinician-dependent ones, connected to `general-adult-3`; scenarios and reasons). The latest evaluation in the repository is on `v0.15.1-demo.1` (evaluation): 45 of 58 scenarios and 20 primary records PASSED, as on every evaluated release since `v0.13.0-demo.1`. On `v0.10.0-demo.1` (commit `e4b9c85`; evaluation) it was 44 of 58 scenarios and 19 primary records: T-R37-S01 is missing only because #315 renamed its cited test, which passed; #319 restored the title, and PR #320's CI reports give 45 and 20 again. On `v0.9.0-demo.1` (commit `e32d2cd`) and `v0.8.3-demo.1` (commit `86272da`, where T-R15-S02 passed newly): 45 and 20. From `v0.5.4-demo.1` to `v0.8.2-demo.1` every evaluation gave 44 and 19; the #25 evaluation of `v0.4.0-demo.1` (commit `863f720`, mock mode) is where the series began. On the deployed `v0.5.5-demo.1` (commit `06e7158`) the extended map gave the same verdicts (v0.5.5 check); on `v0.5.4-demo.1` (commit `e5a12d4`, every report on its first run) it gave **44 of 58 scenarios and 19 primary records PASSED** (v0.5.4 check). The #25 set was re-run unchanged on `v0.5.0-demo.2`, `v0.5.1-demo.1`, `v0.5.2-demo.1` and `v0.5.3-demo.1` (commit `16bd7c3`, every report on its first run, v0.5.3 check; v0.5.2 commit `c613cce`, v0.5.2 check; v0.5.1 commit `5791db4`, regression check); on `v0.5.0-demo.2` (commit `e649b45`; regression check): the same 35 scenarios and 16 primary records passed, every report on its first run. On `v0.5.0-demo.1` one Nano browser run had a transient blank-page failure of a cited O01 test (details). Every cited test ran on that exact commit and passed in all five reports: CI x86_64 backend and browser, release arm64 backend, and Nano arm64 backend and browser. A scenario passes only when its given can be met and every then-clause is asserted.

| Measure | Count |
|---|---|
| Scenarios in `spec/acceptance.json` | 82 (40 primary records) |
| `PASSED` in `spec/acceptance.json` (registry, #25 evaluation of `v0.4.0-demo.1`) | 35 scenarios; 16 primary records: T-R01, R02, R03, R04, R08, R09, R11, R13, R19, R20, R27, R29, R32, R33, R35, R37 |
| Evaluated with the #55 clause map | 58 (the 42 #25 candidates plus 16 ADR-003 clinician-dependent ones) |
| `PASSED` on `v0.15.1-demo.1` (release evaluation; the same since `v0.13.0-demo.1`, and on `v0.9.0-demo.1` and `v0.8.3-demo.1`) | 45 scenarios; 20 primary records: T-R01, R02, R03, R04, R08, R09, R11, R13, R15, R16, R17, R19, R20, R25, R27, R29, R32, R33, R35, R37 |
| Not passed: saved mode (ADR-005) | T-R06-S02, T-R10-S01, T-R10-S02 (the guest equivalents are tested) |
| Not passed: M4 repair path and restricted worker | T-R18-S02, T-R26-S01, T-R26-S02 |
| Not passed: expiry warning (#42) and saved retention | T-R36-S01 |
| Not passed: clinical pathway and evidence | T-R14-S01 (no early-stop rule in `general-adult-4`), T-R24-S01; T-R21-S01, T-R22-S01, T-R22-S02 not applicable without a corpus (ADR-004) |
| Not passed: future pilot outcomes | T-R39-S02 (needs real participants) |
| Requirements `verified` | 0 (all `planned`) |

Earlier evaluations: `v0.1.0-demo.1` (#10, the clause review the evaluation starts from) and T-R03-S02 on the `v0.2.0-demo.1` application (#19).

Some tests use test-only synthetic data copied into a temporary fixture pack: a duration question, scripted lab, allergy and urgent record samples, and out-of-network and stale doctors. The bundled fixtures are unchanged.

The `mobile-360` project runs only the tests tagged `@mobile` (#509, `apps/web/playwright.config.ts`). The four tests in `routes.layout.spec.ts` that run once, on `desktop-1440`, are the two width sweeps (patient and presenter routes), which set 360/390/768/1440 px themselves, and the two network-boundary tests (the R34 guard, and the browser's refusal under the Content-Security-Policy, #157). The skipped tests per run are the three phone-only `@mobile` tests (#302, #330, #474) on `desktop-1440`.

## Device specs (#367)

`tests/devices/` holds the specs that ran from scratch copies until #367. They drive a deployed release through
`apps/web/playwright.devices.config.ts`, and the mock suite (`playwright.config.ts`, `tests/ui`) never picks them up.
- **Setting:** `DEVICE=Fury|Nano` (required).
- **Optional:**
  - `MODEL`: the telemetry page's model manifest id; default from `infra/`.
  - `OUT_DIR`: where results and screenshots go; default `apps/web/test-results/devices/<device>`.
  - `RELEASE`: the tag, shown in test titles only.
  - `ZRT_VERSION`: default from the device's model manifest.
- **The walk-through** (`walkthrough.spec.ts`) checks the release on the device: device name, headers, telemetry and
  slide, the presenter path (`/presenter-api`, reached from the home page's Presenter choice), urgent routing at creation, non-health refusal, a real consultation, the PDF. The summary preview must show the 9 sections #417 defines for a consultation without a doctor search (`SUMMARY_SECTIONS` in `support/device.ts`, checked against `spec/screens.json` by the tooling tests), and the PDF's headings must be the same titles in the same order (#493).
- **The one-click flows** (`quick-flows.spec.ts`) writes `quick-flows.json`: clicks and milliseconds per flow.
- **The usability walk** (`usability-walk.spec.ts`) writes `ux.json`: taps, distance below the first screen, keyboard
  presses and dead ends. It accepts both start labels.
- **The measures** (`measures.spec.ts`) writes `measures.json` with the #355–#357 measures.
- **Off-device requests:** every spec records each request that is not to `127.0.0.1`, and the walk-through and flow
  specs fail on any.
- **Full walk-through, one command:** `DEVICE=Fury RELEASE=<tag> OUT_DIR=<folder> npm run test:device -- walkthrough quick-flows`.

The older #322–#331 measure and the AI-calls tile probe were not moved. Their presenter steps ("Prepare quick demos")
were removed by #358, and the tile no longer lists parts.

## Reading results honestly

- A passing test run is **tested** behavior for that commit and mode. It does not move a requirement to `verified`; that needs release evidence bound to the exact commit (`evidence/README.md`).
- `NOT_EXECUTED` records in [`spec/acceptance.json`](<your-repo-url>/blob/main/spec/acceptance.json) are never counted as passed in the registry figures. A release evaluation may pass a scenario that the registry still records as `NOT_EXECUTED`; quote each figure with its source. A check that was not run is reported as not run.
- Mock results never stand in for local inference.

**Spec checks fail when they should (#301).** The contract check raises explicit errors (it works under `python -O`), `date-time` and `uri` formats are really checked, the contrast check compares unrounded ratios, and CI passes changed files NUL-separated after `--`.

**Cited tests must exist (#319).** `tests/tooling/test_cited_tests_exist.py` fails when a test cited by the #55 clause map or `spec/acceptance.json` is renamed or removed, so a scenario can never drop out of a release evaluation silently. Keep a cited test's title, or update both citations through a change record.

**Wait for a started session (#336).** A test helper that clicks "Start presenter session" must wait for the presenter controls before it navigates. Navigating sooner can abort the start request, and the next page then shows the gate again.

**One announcement per failed submit (#342).** Field messages on A01 and A03 are not alerts; the focused error summary is the announcement. Assert those messages by id, and assert the summary with `toBeFocused()` and an in-viewport check at 360×780.

**Focus after an action, and forced colours (QA 2026-10-22).** `tests/ui/qa-after-guidance.spec.ts` presses Enter on the focused control and asserts where focus lands with `toBeFocused()` (never the page body). Forced-colours checks use `page.emulateMedia({ forcedColors: "active" })` and compare computed outlines and backgrounds, because box-shadows and author colours are dropped in that mode. Deletion tests must reach History or Data settings through the header (the Menu button at 360 px), not `page.goto`, so the tab's memory survives as it would for a person.

**Not-found and error pages (#339).** `tests/ui/improve-wayfinding.spec.ts` checks the not-found page in each layout and the route error page (a screen that throws and a code chunk that fails to load), with axe. A test that needs a broken screen injects it in the test, never in the app.
