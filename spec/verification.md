# Verification contract

Baseline: Product Master Document v2.0. Handoff version: 1.0.0. Product namespace: `aware-care`.

This handoff defines planned acceptance work. It does not establish that Aware Care runs on the Nano, that any model is connected, that the proposed paths are implemented, or that clinical/financial outcomes have been measured. All 40 requirement records are `planned`. Of the 40 primary tests and 82 scenarios, 16 and 35 are `PASSED` in the registry (the #25 evaluation of `v0.4.0-demo.1`) and the rest `NOT_EXECUTED`; later verdicts are recorded per release.

## Source and identity

`requirements.json` copies each canonical acceptance clause verbatim and records the exact source extraction SHA-256 and 1-based source line range. That hash identifies the extracted text, not a repository commit, normalized product lock or current device state. The merged pull requests and Git history record the approved repository baseline (the root specification lock was retired by ADR-019).

The primary test paths `tests/acceptance/test_R01.py` through `test_R40.py` come from the source. T-Rxx and their Sxx scenario suffixes are explicitly derived handoff aliases. Operation mappings reference only the 33 operation IDs (the 31 source operations, `getTelemetry` from ADR-017 and `getLogs` from #548) and are labeled derived associations; they do not introduce endpoints. R40 has no direct HTTP operation. M05 is invoked through other modules' operations and owns no independent listed HTTP endpoint.

Traceability is bidirectional and may be many-to-many. A screen can depend on several requirements, and a shared module/test can support several requirements. Registry completeness proves linkage, not behavioral correctness.

## Verification phases

| Phase | What it can establish | Required evidence |
|---|---|---|
| Handoff integrity | Valid registries, preserved IDs and canonical text, consistent planned links | Machine-readable check report and exact handoff hashes |
| Mock interaction | Responsive screens, synthetic navigation, validation, visible exception states | Current build's actual browser test report, screenshots as appropriate and scenario identity |
| Service and contract | Authorization, revision/state rules, typed answers, filters, jobs, cleanup and schemas | Implemented acceptance/contract tests with fixtures and observed reports |
| Connected local execution | Actual local model/data boundary, observed runtime, bounded failures and device performance | Nano/device inventory, model/runtime manifests, network capture, stage timings and full rehearsal reports |
| Clinical or outcome validation | Intended-use suitability, reviewed clinical content or real business outcomes | Appropriate expert review and separately approved pilot/validation protocol; a demo does not satisfy this phase |

Model-free deterministic tests should exercise contracts and state transitions before model integration. Model-dependent checks must later execute against the pinned local model and approved content. Report those result sets separately. A simulated delay, fixture response or hardcoded runtime card cannot substitute for local inference evidence.

## Required scenario coverage

The PMD's F01-F12 catalogue requires: routine completion; urgent entry; urgent facts during intake/record confirmation; unresolved critical context at slot 10; edit during generation; malformed/oversized/instruction-bearing records; impossible required provider criteria; offline cached directory; foreign/nested identifiers; reset/expiry during work; missing corpus/safety/model failures; and keyboard/mobile/zoom/refresh navigation.

The original mock package contains only 6 named presentation scenarios: `routine`, `selfcare`, `urgent`, `unsupported`, `nomatch`, `failure`. Their IDs remain stable. New runnable fixture assets must be authored and registered for uncovered behavior. The F catalogue is a source requirement, not a claim of existing fixture files or reviewed clinical content.

`acceptance.json` gives 2 or 3 actionable scenarios per requirement (82 in total). Its `source_fixture_ids` are catalogue references, `mock_scenario_ids` are links to earlier synthetic examples, and `fixture_refs` are intentionally empty until runnable connected-acceptance fixtures exist. Every scenario records a verification layer and review dependency. Execution evidence exists for the 35 `PASSED` scenarios; per-release verdicts are in `evidence/releases/<tag>/acceptance/`.

## Guardrails that must not drift

1. **No eleventh intake prompt.** Count issued slots, including invalidated prompts. Refetch/retry of the active prompt is idempotent; answer edits do not allocate a slot. A new clarification consumes a slot unless it directly edits the existing answer. At the cap, unresolved critical context constrains the result. Profile, document review and doctor filters remain outside this intake counter.
2. **No direct booking.** A11 supports a deliberate approved HTTPS contact or booking-site handoff with no case payload/referrer. The mock may display a labeled simulated contact dialog. There is no booking API, automatic reservation, automatic clinician transmission or extra appointment-confirmation screen. Direct booking belongs to future scope.
3. **No clinical inference from fixture navigation.** An urgent scenario selecting A15 tests routing, not clinical sensitivity. A short self-care scenario does not certify appropriate medical advice. Reviewed pathway rules, wording and fixture expectations are prerequisites for clinical assertions.
4. **No stale publication.** Jobs must recheck actor, state, input/reviewed revisions and deletion tombstone before commit. Edit, deletion or reset cannot resurrect a prior result. Direct URLs must enforce the same guards as button navigation.
5. **No cloud fallback for application inference.** Local model failure produces the documented limited/unavailable behavior. A coding assistant's separate development connection is not application inference evidence.
6. **No synthetic outcome claims.** Exports and completed scenarios are not appointments, avoided visits or insurance savings. Real outcomes remain Not measured until a suitable pilot supplies evidence.

## Mock-to-connected reconciliation

| Earlier mock behavior | Connected baseline requirement |
|---|---|
| In-tab memory, refresh clears state, simulated saved history | Server-owned cases/sessions, actual authentication and specified retention |
| Fixed question list and response aliases `single`/`multi` | Approved deterministic eligible-template selection and canonical `single_choice`/`multiple_choice`; include duration validation |
| Simulated records and review cards | Bounded local parsing/OCR, provenance, confirmation, stale-worker and purge tests |
| Scripted guidance with a 900 ms delay | Actual local model adapter, output validation, bounded repair, observed timings |
| Browser Print/Save PDF | Authorized current export jobs, expiring files and protected download responses |
| Fixed synthetic doctor data and simplified ranking | Labeled synthetic or attributable real records; all required eligibility/ranking/version rules |
| Public presenter demonstration controls | Separately authorized presenter operations and non-disclosing patient APIs |

These are deliberate phase differences, not permissions to remove the connected requirements. Preserve the mock as a labeled reference; record approved phase overrides and migration decisions in the root decision log.

## Evidence packet

Store immutable release evidence under `evidence/releases/<release_id>/`. Include:

- Requirement/scenario IDs and actual test report, including failed, blocked and not-run cases.
- Application commit/build and approved spec/contract/registry hashes.
- Fixture version; device, OS and runtime inventory; model/tokenizer/quantization/prompt settings; corpus and directory versions where relevant.
- Start/finish timestamps, measured stage timings, queue/errors/retrieval mode and reproduction steps.
- Network-boundary, ownership and deletion evidence; unresolved limitations and disabled/synthetic capabilities.

Keep all health-content fixtures synthetic for the customer demo. Logs and technical evidence must avoid symptoms, document names, prompts, generated health text or raw lookup queries unless a separately controlled fixture artifact is explicitly required by the test. General operational events are content-free.

## Presentation release gate

Before a connected customer presentation, the source requires every mandatory requirement verified, no blocking defect, all 24 routes working (25 since ADR-017 added W06 `/telemetry`), all reviewed urgent fixtures and ownership/data-boundary/deletion checks passing, and 10 consecutive full rehearsals on the actual device including failure recovery.

Report the measured target: next-question rendering within 5 seconds and final guidance within 20 seconds in at least 9 of 10 warm single-user rehearsals. Preserve slow/failed runs and record cold startup separately. These are product targets, not proven ZGX performance. Do not silently revise them to fit results.

The historical 30 mockup checks, source-text equality checks and successful installation of Node/uv/Python do not satisfy this gate. Current evidence remains empty until the relevant implementation has actually been exercised.
