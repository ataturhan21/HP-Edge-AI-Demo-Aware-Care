# Strict object and wire contracts

These 76 JSON Schema 2020-12 files are a machine-readable translation of product master 2.0, with explicitly labeled handoff wire refinements. They are not code or evidence of clinical validation. See `../api/README.md` for the distinction between baseline requirements and newly formalized transport choices.

All standalone `$ref` values resolve to sibling schemas. `registry.json` enumerates the files; `../api/openapi.json` embeds equivalent copies for tooling. Objects are closed (`additionalProperties: false`). Request DTOs do not allow client-supplied roles, actor IDs, urgency decisions, case states, issued-slot counts or latest-guidance pointers.

## Contract families

| Family | Main contracts |
|---|---|
| Identity | Session, CreateSessionRequest, CreateSessionResponse |
| Profile | Profile, ProfileItem, Allergies, ProfileWrite |
| Cases | Case, CaseWrite, CaseEdit, ConfirmedContextWrite, CaseReadResponse, CaseList |
| Intake | Question, QuestionConstraints, Choice, Answer, AnswerWrite, NextQuestionResponse |
| Records | Document, DocumentPublic, Fact, FactReview, RecordList |
| Work | Job, DeletionAccepted |
| Clinical output | UrgencyDecision, Guidance, Claim, Action |
| Grounding | Evidence, CaseSources, Pathway, PathwayRule, Reviewer |
| Providers | Provider, ProviderCriteria, ProviderMatch, ProviderSearchResult, ProviderCard |
| Export | Export, ExportRequest |
| Privacy | Settings, SettingsWrite, SettingsResponse, DeleteAllRequest |
| Operations | RuntimeSnapshot, TimingSummary, Event, ControlsResponse, Readiness, LogsSnapshot |
| Governance | SpecLock, registry.json |

## Validation layers

1. Validate JSON shape, types, enums, string bounds and unknown fields.
2. Validate ownership and foreign-key references using server records.
3. Validate revision/state and one-use token/idempotency semantics in a transaction.
4. Apply reviewed scope, urgency and evidence support rules.
5. Recheck current revision and deletion tombstone when background work commits.
6. Validate rendering and logging projections so internal keys, model text and health content do not leak.

Only layer 1 is provided by these files. For actual inference, a syntactically valid `Guidance` must still pass every clinical and provenance check. No claim, action or pathway is approved by matching a schema.

UUID formats require a format-aware validator, not only ordinary JSON Schema structure validation. Generated UUID values must be server-controlled for real requests. `date-time` is UTC in storage/transport; schema validators alone may accept other offsets, so normalize and reject invalid/ambiguous timestamps in application code.

`SpecLock` is the master-defined minimal lock shape; the repository lock (`spec/lock.json`) was retired by ADR-019. If a package lock contains additive file inventories or approval state, it is governed by the package lock's own format; do not force extra fields into this closed baseline schema without documenting that extension.
