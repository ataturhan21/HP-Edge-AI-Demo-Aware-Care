# Implementation plan and acceptance gates

Work in vertical slices. The order below is an engineering work plan, not a rewrite of requirement priority.

| Milestone | Scope | Exit evidence |
|---|---|---|
| 0 Baseline | Read sources, inspect existing repository, verify contracts (`scripts/check_contracts.py`), inventory device and ZRT | Handoff checks pass; no fabricated environment claims |
| 1 Mock patient flow | W01-W05, A01-A03, A05-A07, A09-A12; access/case/intake/guidance/provider/export owners | One complete synthetic flow plus urgent/limited branches; server guards tested |
| 2 Full patient experience | A04/A08/A13-A16, patient screen variants, records, history/settings | All 21 public/patient routes complete (22 since ADR-017 added W06); ownership, revision and retention cases pass |
| 3 Presenter and privacy | O01-O03, runtime mode, evidence, events, reset | All 24 routes complete (25 since ADR-017); truthful states, no patient content in logs, deletion cancels late writes |
| 4 ZRT integration | Pin model, implement adapter, generic transport/schema tests, reviewed-content gating | Actual non-clinical local request and error tests; no false clinical readiness |
| 5 Connected demo release | Approved content packages, all R01-R40 acceptance, all 24 UI tests (25 since ADR-017), F01-F12 and 10 rehearsals | Exact-release evidence; clinical and technical blockers resolved |

## Do not conflate levels
A browser-only prototype may reproduce the mockup without backend controls; label it a prototype. The local application must implement server-owned sessions, revision checks, real export generation, authorization and retention. A mock model does not remove these application obligations. UI parity does not prove clinical behavior or hardware acceleration.

## Every task
Record IDs, intended paths, relevant contracts, acceptance examples, and unresolved decisions. Inspect existing implementation. Make the smallest complete change. Run the affected checks. Update traceability and evidence. Add no parallel module or route when the existing owner can be extended.

## Initial repository tooling
Use Node 24 and Python 3.12 already observed. Resolve actual frontend/backend package versions on the Nano and commit package-lock.json and uv.lock after installation succeeds. Do not install app packages into ZRT, update GPU drivers as scaffolding, or invent a lockfile without dependency resolution.
