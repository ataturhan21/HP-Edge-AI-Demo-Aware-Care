# Synthetic fixture pack

These files seed the API's mock adapter (`apps/api/app/core/fixtures.py`). They are **not API request/response examples**, not a real provider directory, and not enabled clinical pathways. Validate transformed records against `spec/contracts/` before using a local backend. The original compact browser fixture remains in `spec/mockups/original/spec/fixtures.json` for exact provenance.

## Files

| File | Contents |
| --- | --- |
| `scenarios.json` | Original routine, selfcare, urgent, unsupported, nomatch and failure aliases; expected screen paths, counts, recovery and typed example answers |
| `questions.json` | Original Q01-Q10 template identity, text and options plus handoff-authored deterministic option keys |
| `profiles.json` | Jordan Taylor and an unconfirmed sample document fact; no real PDF or OCR result is claimed |
| `providers.json` | Original p01-p03 aliases, fictional doctors/plans and distances, no contact URLs or claimed availability |
| `provider-filter-cases.json` | Authored deterministic matcher expectations; all execution statuses are not_run |
| `id-map.json` | Optional UUIDv5 mapping from original aliases to future seed records |
| `records/` | Synthetic sample record PDFs and `manifest.json` with their scripted facts (ADR-009); regenerate with `scripts/make_sample_records.py` |

## Identity conversion

Legacy browser `caseId` values such as `demo-001` and provider aliases `p01` through `p03` are not valid local API UUIDs. The seed loader may use `id-map.json` to create deterministic records in a resettable synthetic dataset. Newly created sessions and cases still need independent IDs and actor ownership. A fixture alias is never an authorization credential. Q01-Q10 remain `template_id`; each issued Question and Answer has its own per-case identifier.

Keep seed configuration, display labels and wire payloads separate. Sample answers currently use human-readable `display_value`; map choice labels to the issued Question choices and set the typed answer value. A skipped/unknown response has explicit status and no inferred value. Do not send display strings directly to strict API schemas.

## Mode boundaries

The mock adapter selects a scripted scenario and never assesses free text. `selfcare` stops after four questions solely to exercise early stopping. The urgent scenario exercises interruption using an explicit fixture trigger. Neither behavior defines a clinical rule. All files except `id-map.json` declare `clinical_execution_enabled: false`; they cannot enable or substitute for a reviewed package in local-inference mode.

All provider facts are true only inside the fictional seed. Even a value marked confirmed_in_fixture is not verified in the real world. Every card must say Fictional doctor. Contact is an explicit A11 simulation modal with no external call, link or appointment creation. A12 remains a preparation summary.

Master F01-F12 requirements and their tests remain separate from these six UI scenarios. A related_master_fixture_ids entry is a traceability pointer, not evidence that a clinical, ownership, retention or hardware test passed.

## Matching expectations

The master defines the local matcher: eligibility before ranking; in-person radius; verified telehealth jurisdiction; unknown required plan/language fails; optional preference order then freshness then applicable distance then stable ID. These files add synthetic TX jurisdiction labels only to make the future target seed testable. The compact historic browser reference simplifies some rules and is not the final matcher implementation.

Run explicit checks for empty results, unknown plan, no plan preference, language, telehealth jurisdiction, reset and filter relaxation. Never relax a hard filter without the user's explicit action. `provider-filter-cases.json` is an expectation catalogue, not a passing test report.
