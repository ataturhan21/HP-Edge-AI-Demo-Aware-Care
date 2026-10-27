# API contract handoff

Product baseline: **2.0**. Handoff package: **1.0.0**. Status at handoff: **specified, not implemented or clinically approved**. Since then the operations are implemented in `apps/api` (not clinically approved, no requirement verified).

`openapi.json` contains exactly **33 operation IDs**: the 31 baseline operations plus `getTelemetry`, added by [ADR-017](../decisions/ADR-017-telemetry-page.md), and the presenter-only `getLogs` (#548, the Logs view on O01). It embeds the same schemas stored in `../contracts/`. `operations.json` is the machine-readable inventory. Requirement associations are derived from the canonical `../requirements.json` `api_operation_ids` lists: `operations.json` requirements and OpenAPI `x-requirement-ids` must equal their inverse. Associations include direct behavior and supporting cross-cutting controls such as consent and ownership. Each endpoint still has exactly one owning module; associations do not create multiple owners. R40 is a verification/governance requirement with no direct HTTP operation. `check_contracts.py` checks this mapping in both directions. `/api/v1` is the common prefix. The 31 baseline operations are preserved from the master, and ADR-017's read-only `getTelemetry` and the presenter-only `getLogs` (#548) are the only additions, with no booking, EHR, email, free-chat, login-password, arbitrary web-search, or model-management endpoint added.

## Authority and regeneration

The master gives field names, constraints, endpoint identities and behavioral rules but does not fully specify every nested wire shape. This handoff translates those into strict JSON Schema 2020-12 and OpenAPI 3.1. Fields and constraints from the master remain normative. Added wire details below are **explicit draft design choices**. They must be reconciled with existing code before being frozen as the implementation API; do not call them a previously approved API. Record any change in the repository decision log (the spec lock was retired by ADR-019).

Once implementation exists, implement Pydantic models against this contract and compare exported FastAPI OpenAPI structurally. The backend export becomes the TypeScript client generation input only after that conformance check. Do not silently overwrite this contract with an arbitrary backend export or maintain handwritten duplicate DTOs.

Standalone schema refs are sibling filenames. OpenAPI uses internal `#/components/schemas/...` refs and is therefore self-contained. `contracts/registry.json` indexes all schema files. Every data object rejects unknown fields. Null values are explicit and do not mean a negative finding. The schema does not replace authorization, clinical evaluation, evidence support checks or DB constraints.

## Declared wire refinements

| Detail | Handoff choice | Rationale / decision status |
|---|---|---|
| Cookie/header names | `awarecare_session`, `X-CSRF-Token`, `X-Request-ID` | Draft transport names; same-origin app API |
| Session expiry signal | `X-Session-Expires-At` (ISO 8601 UTC) on every response of an authenticated request except 401 and the session-ending `deleteSession`; `createSession` reports it too | The session's current expiry after the request: the earlier of 30 minutes idle and 8 hours absolute (R36). Lets the browser warn 2 minutes ahead; the server stays authoritative. Added like `X-CSRF-Token`, by the transport layer, not per operation ([ADR-013](../decisions/ADR-013-session-expiry-signal.md), #42) |
| Session response | Original 3 body fields, token in response header, opaque cookie | Keeps identity server-assigned; no credential in body |
| Guest session retry | A valid session of the same role continues its actor under a rotated session: new ID, token and CSRF token, the old session revoked (#434, CHG-DEV-SEC-002); pre-session nonce scopes initial idempotency | Draft middleware cookie must be issued before first session creation, e.g. app HTML response; not a new API endpoint. Rotation instead of reuse: a token planted before consent never reads what is entered after (session fixation) |
| Empty profile | `{ "profile": null }` from `getProfile` | Explicit representation of original “Profile or empty” |
| Profile create revision | `expected_revision=0` when absent; positive on update | Draft concurrency rule; case revisions still start at 1 |
| Context write | `ConfirmedContextWrite` | Accepts user/profile facts only, never arbitrary document ownership or server status. Kinds in the server's own namespaces (`answer:`, `fixture:`, `record:`) are refused with 422 `VALIDATION_FAILED`, field `confirmed_context.kind`, code `reserved` (#433) |
| Case read | `{case, allowed_actions}` | Makes source state-derived action requirement explicit |
| Case delete revision | Required query parameter `expected_revision` | Avoids reliance on DELETE body transport behavior |
| Next-question union | `kind=question` or `kind=review_required` | Exhaustive client discriminant, plus current revision |
| Answer union | Value typed from stored question | Client cannot assert its own question type or choices |
| Fact correction | `corrected_value={value, units}` only for `correct` | Keeps original extraction unchanged |
| Patient document | `DocumentPublic` omits storage key | Persistence and response projections remain distinct |
| Job | Additional `result_type` enum | Original text requires stable result ID and type |
| Provider data | Explicit provenance and plan/location subobjects | Makes unknown/stale eligibility implementable; no quality score |
| Provider preferences | Ordered `plan`, `language`, `visit_type` options | Draft initial optional preference vocabulary; adding choices requires documented contract change |
| Search criteria | `{expected_revision, criteria}` | Case snapshot validation without clinical revision change |
| Scenario load | 201 only after reset completes, 409 while pending | Master requires reset before a new fixture; no second unaudited job endpoint |
| Readiness | 200 for ready/degraded, 503 for unavailable | Body remains only `{readiness}` in all cases |
| Snapshot | Explicit `mode`, nullable unobserved manifest fields | Mock mode cannot masquerade as local inference |
| Numeric/list bounds not specified in master | Defensive transport limits in schemas | Draft implementation defaults; not clinical limits; reconcile before freeze |

Do not implement an incomplete authentication shortcut merely to satisfy a shape. In particular, presenter identity, local account provisioning and the development cookie policy remain deployment decisions. A pre-session nonce is not a user identity, and knowing it does not confer presenter access.

## Common request and response policy

- Validate `Origin` on session creation and all writes. Subsequent writes also require an authenticated session and matching CSRF token. Configure a precise origin allowlist; do not use `*` with credentials.
- Current consent is required before health writes. Saved mode requires an identity established by an approved upstream local authentication layer. A request can never assign actor ID or role.
- Check ownership for every nested ID, including case, fact, question, search, provider membership, export and job. Foreign or missing objects return the same non-disclosing 404 after authentication.
- Clinical mutations use `expected_revision`; return 409 and `current_revision` for stale writes. Never reconcile concurrent medical answers automatically.
- Required `Idempotency-Key` scopes to actor, operation and canonical request hash for 24 hours. Reused key + same payload returns the original committed response; changed payload returns 409. Multipart hashes include bytes. Concurrent duplicates must serialize. Before actor allocation, use the explicitly documented pre-session scope.
- Retryable creations covered: sessions, cases, record uploads, next-question selection, guidance, exports, delete-all, scenario load and reset. Readiness and simple reads do not need keys.
- JSON bodies are capped at 256 KiB. Only `uploadRecord` (`POST /cases/{case_id}/records`, matched by method and whole route) may carry up to 30 MiB, and only with a valid session. A malformed or oversized `Content-Length` is refused before the body is read or parsed, an upload without a session before its body is read, and a chunked body is read only up to the limit (#156, #269, #431). Error bodies never contain model output, original document text, credentials, filenames or a server traceback.
- Request fields are strict JSON types (#463): a boolean is `true`/`false` only, an integer or number is never a string, and `{const: true}` confirmations (`facts_confirmed`, `user_reviewed`) accept only `true`. Coercible values such as `"yes"`, `1` or `"1"` get 422.
- Health/session/job/settings/presenter responses use `Cache-Control: no-store`. Every API response, error or not, also carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY` (#465). Export downloads also use attachment disposition. The application hosts its own assets. `HEAD` on a `GET` resource is answered like `GET` without a body (#464).
- Per-session bounds (#397): a session holds at most 100 open consultations (409 `CASE_LIMIT`), requests at most 10 summaries per 15 minutes (429 `EXPORT_LIMIT` with `Retry-After`), and holds at most 30 records (413 `RECORD_LIMIT`; still 3 per consultation).
- `getJob` polling: 1 second for the first 5 seconds, then 3 seconds with jitter. Stop for succeeded/failed/stale/cancelled or after navigation. Read server state when returning. A disconnected browser must not create replacement work automatically.
- New job records use nonzero request timestamps and measured durations. Null means unmeasured. Do not fabricate timing with fixed sleeps or zero-duration success.

## Error policy

| HTTP | Examples / expected client response |
|---|---|
| 400 | Malformed request (`MALFORMED_REQUEST`, also for a body that cannot be decoded); show recovery without dropping entered answers |
| 401 | No/expired session; clear browser health state and return to A01 |
| 403 | `CONSENT_REQUIRED`, role or CSRF/Origin rejection; no role escalation |
| 404 | Missing/foreign-owned resource or unknown path (`NOT_FOUND`); avoid existence disclosure |
| 405 | `METHOD_NOT_ALLOWED` with `Allow`: the path exists but not for this method (#464) |
| 409 | `REVISION_CONFLICT`, `STATE_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `RESET_PENDING`, `CASE_LIMIT`; reload appropriate server state |
| 413 | File, aggregate pages or request too large; preserve valid prior inputs |
| 415 | Unsupported or mismatched file signature/media type |
| 422 | Field/schema/answer validation; error list identifies safe field names |
| 429 | `QUEUE_FULL` (guidance, and the concern screens of createCase, editCase and a written-urgency loadScenario, #397), `EXPORT_LIMIT`; respect `Retry-After`; no unbounded retries |
| 503 | Required dependency failure, `SERVICE_LIMITED` or `RESET_FAILED`; no cloud fallback |

Every 4xx, including the framework's own refusals (an undecodable body, an unknown path, a wrong method), uses the Error schema (#464). Error code strings above are draft conventions except master-prescribed `CONSENT_REQUIRED`, `STATE_CONFLICT` and `SERVICE_LIMITED`. Final error vocabulary must be frozen with tests. `getReadiness` deliberately returns the small Readiness schema for its 503, rather than exposing diagnostics.

## Cross-field checks beyond JSON Schema

Schema validation cannot compare supplied IDs to owned DB rows, check source applicability, confirm support for a statement, resolve a question's options, enforce token expiry, atomically cap aggregate file counts, or prove deletion completed. Implement these in the owning services and acceptance tests.

Examples: reported allergies need entries; unknown/none-reported have no entries; unknown/skipped answers have null value; correct fact review needs corrected_value and confirm/reject must omit it; required verified plan/language requires a selected value; a supported clinical claim needs evidence IDs; a supported case-fact claim needs fact IDs; an enabled pathway needs approved review records and dates. Service validation adds time validity and reviewer authenticity.

## No deployment implication

Ports are application backend `127.0.0.1:8000`, frontend `127.0.0.1:5173`, and ZRT documented default `127.0.0.1:8080/v1`. At handoff the ZRT endpoint was not yet observed serving a model; the served models are now recorded in `../../infra/model-manifest.json` and `../../infra/fury/model-manifest.json`. No schema file starts services, installs packages or changes the Nano. No passing application test is claimed by the presence of these contracts.
