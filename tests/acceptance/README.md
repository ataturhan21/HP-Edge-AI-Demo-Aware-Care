# Acceptance implementation contract

At handoff (2026-10-13) this directory held only this implementation plan. It now holds the backend acceptance suite: 32 `test_Rxx.py` files, for 32 of the 40 requirements (no file yet for R05, R07, R22, R23, R28, R30, R31 or R40), plus `conftest.py` and `records_helpers.py`. On the `v0.8.3-demo.1` commit it ran 333 tests (evidence); `cd apps/api && uv run pytest --collect-only -q` counts the current ones. The rules below still apply. A generated empty test, unconditional `pass`, skipped test or successful import must never be used as evidence that a product requirement works.

## Authoritative inputs

- `spec/requirements.json` preserves the exact R01-R40 titles and normative acceptance clauses from Product Master Document v2.0, including their original source line locations and extraction hash.
- `spec/acceptance.json` contains 40 test records and 82 authored Given/When/Then scenarios. At handoff all were `NOT_EXECUTED`. It now records 16 records and 35 scenarios `PASSED` from the #25 evaluation of `v0.4.0-demo.1` (CHG-DEV-ACC-003); the rest stay `NOT_EXECUTED`. Later per-release verdicts are in `evidence/releases/<tag>/acceptance/`, not in this registry.
- `spec/modules.json` preserves M01-M12 ownership and the existing API operation identities owned by each module.
- `spec/verification.md` explains phases, evidence and release gates.

R01-R40 and `tests/acceptance/test_Rxx.py` are canonical source identities. `T-R01` through `T-R40` are handoff registry aliases derived from those requirements; the source document does not contain those T-prefixed identifiers. Scenario IDs such as `T-R11-S01` are handoff identifiers, not new product requirements. Preserve all source IDs.

## Implement real tests

For each Rxx, create `tests/acceptance/test_Rxx.py` only when it contains meaningful assertions against implemented behavior. Mark the relevant requirement IDs in the test using the repository's adopted annotation mechanism. Register shared helpers and cross-cutting coverage rather than copying domain rules into each screen.

Each test should establish the fixture's preconditions, call the real service/API/worker boundary appropriate to the assertion, and inspect observable output and side effects. Negative cases must verify both the rejected operation and the absence of forbidden writes, disclosure, network calls or late publication. Isolate tests and restore their data so ordering does not affect results. Use a controllable clock for retention; use synchronized workers for revision/deletion races.

Implement the scenarios and canonical clause, not just the happy path. Add further tests when the full module or object contract exposes another failure mode. If an authored scenario appears to conflict with a normative clause, preserve the clause, record the conflict and obtain an approved source change before altering required behavior.

The primary file does not need to contain every layer of testing. It may call shared fixtures or reference an independently executed UI, network or device test. The resulting evidence must still prove the requirement and identify all relevant artifacts. Corresponding screen tests belong at `tests/ui/<screen-ID>.spec.ts`.

## Fixture identity and medical scope

`source_fixture_ids` F01-F12 refer to the PMD's scenario catalogue; they are not claims that fixture files exist. `fixture_refs` remain empty until actual runnable fixture assets are authored and registered. `mock_scenario_ids` preserve the original mockup IDs: `routine`, `selfcare`, `urgent`, `unsupported`, `nomatch` and `failure`.

The original browser fixtures are synthetic interaction examples. They are not an approved clinical pathway pack, an adaptive-question engine, a real directory or proof that the backend works. A duration-answer test and many service/worker failures require additional fixtures. Clinical interpretation assertions require an enabled, clinician-reviewed pathway and corresponding reviewed fixture pack; do not label draft content approved.

## Record execution honestly

After implementation, run the relevant tests against an identified build and retain the actual report. Evidence must include requirement and scenario IDs, commit/build, source/contract hashes, fixture versions, environment, timestamp, results, failures and limitations. Device/model-dependent checks also require observed device, runtime, model and corpus manifests.

Keep historic mockup reports separate. The previous 30 browser flow checks were checks of the earlier mockup artifact. They are not a pass for this repository, its backend, the Nano or a local model. Installed development tools are environment evidence, not application acceptance evidence.

Do not change a record to verified on the strength of generated code, static registry validation or an AI statement. Product release requires implemented paths and successful applicable execution evidence. A handoff integrity check may pass while every product requirement remains planned.
