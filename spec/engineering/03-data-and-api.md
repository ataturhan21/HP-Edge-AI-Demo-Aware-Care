# 03 Data, API and factual care navigation

Baseline 2.0. See `../api/openapi.json` for all 33 operations (31 baseline plus `getTelemetry`, ADR-017, and the presenter-only `getLogs`, #548) and `../contracts/registry.json` for 76 schemas. `../api/README.md` explicitly records wire refinements not fully specified in the original master. The backend implements these contracts, and CI checks the generated web types against `openapi.json`.

## Persistence design

Use UUID primary keys and UTC timestamps. Every health resource carries an ownership chain back to an actor. Application services always use actor-qualified queries; a UUID is not an authorization token. Foreign objects return non-disclosing 404. Never use a source filename as a path.

| Entity | Key relations / uniqueness | Lifecycle |
|---|---|---|
| actor/session | Session references actor; server-assigned role | Guest idle/absolute expiry; saved logout only revokes session |
| profile | One active saved profile per actor; revision | Explicit save; relevant facts reconfirmed per case |
| case | actor, revision, state, reviewed_revision | All clinical edits versioned; tombstone precedes purge |
| fact | case, provenance, source document/profile | Source and corrected values remain distinguishable |
| question | case + slot unique; template and issued revision | Slots retained when invalidated; never above 10 |
| answer | question + one current answer | Typed value, uncertainty and submission revision |
| document | actor + case, opaque storage key, hash | Rejected bytes purged; other bytes follow case retention |
| job | owner actor, input case/revision, result pointer | Atomic current-result commit; terminal states immutable |
| guidance | case + input revision + model/corpus manifests | Only one current pointer; stale output never current |
| evidence snapshot | corpus version + immutable source hash | Global approved corpus separate from patient data (*Future design: not built (ADR-004); local mode needs no corpus today*) |
| provider search | case revision + criteria version + directory snapshot | Invalidate on clinical edit; preserve deterministic ordering |
| export | actor/case/revision/guidance | 15-minute TTL and no stale download |
| idempotency | actor/presession scope + operation + key | Request hash and exact original response for 24 hours; purge health-bearing cached responses when associated content is deleted |
| deletion tombstone | actor/case scope + generation | Enough content-free state to block late writes; no health content |

Database migrations should enforce foreign keys, uniqueness and limits where possible. Test deletion cascades against file and worker stores as well as the SQL database. The implementation uses SQLite (`apps/api/app/core/db.py`, `<AWARECARE_DATA_DIR>/awarecare.sqlite3`), configured for transactions and serialized writes; database selection is an implementation decision, not a requirement that justifies rewriting existing functioning persistence.

## API binding

Generate backend request validators from the strict schema intent and compare exported OpenAPI before generating the frontend client. `apps/web` must not duplicate API types by hand. Frontend routes remain the exact W/A/O inventory. The API root is `/api/v1`; the model service is separate.

All writes use Origin and CSRF validation; health writes additionally require current consent. Clinical writes carry expected_revision. Retryable creations carry an actor/operation/payload-scoped idempotency key. Presenter APIs require presenter role regardless of route visibility. Error responses are sanitized typed objects, never raw model output or stack traces.

Reads expose only authorized current projections. `getCase` returns server-derived allowed_actions. A client cannot POST a state, urgency decision, issued-slot counter, role or latest-guidance ID. GET guidance/download/provider search must recheck revision/state even if the user navigated from a valid screen.

## Record processing

Accepted types: PDF, PNG, JPEG. Limits: 3 files/case, 10 MiB/file, 30 parsed pages/case, 40 decoded megapixels/image, 60-second processing timeout. Reserve aggregate count/page capacity atomically so concurrent uploads cannot bypass limits.

Check file signature and declared type, byte limit and page count. Reject encrypted/malformed PDFs. Reject malformed images before storing a byte, so they use up no record slot: a PNG needs an intact first IHDR (non-zero width and height, valid depth and colour type), at least one IDAT, a final IEND and a correct CRC on every chunk; a JPEG needs a frame header with non-zero dimensions (#466). Besides the 3 files per case, a session holds at most 30 records (#397). Prefer native PDF extraction; use local OCR if needed. Restrict the worker's network and executable capabilities. Render previews with stripped metadata; never execute embedded active content or instructions. Store under an opaque generated key.

Extracted facts preserve document ID, page, exact original text, units and reference range where available. Missing units remain unknown. No inferred conversion is called original data. Until confirmed, an extracted fact cannot support clinical conclusions. Confirm/correct/reject records a separate review event; correction does not rewrite source bytes. The service invalidates a worker result computed before a conflicting clinical edit or deletion.

An unreadable file produces a useful failed state with replacement/manual-input/skip options. It does not produce a fabricated summary. General logs omit original filenames and document text.

## Provider eligibility and ranking

Provider data is factual and versioned. Every displayed attribute needs source, checked time and verification status; synthetic cards explicitly say synthetic. NPI, identity, credentials, exact-plan participation, telehealth jurisdiction and availability are distinct fields. Unknown is never converted to confirmed.

Eligibility runs before ranking:

1. Require current non-urgent guidance and an allowed case state.
2. Normalize the selected location using stored location information.
3. Filter relevant specialty and selected visit type.
4. Apply radius to in-person services and verified jurisdiction to telehealth.
5. Apply exact plan and language as hard filters only when required by the user. Unknown or stale required verification fails eligibility.

Order eligible providers lexicographically by reviewed specialty relevance tier, optional preferences in the user's order, data freshness, in-person distance and stable provider ID. Missing optional values follow confirmed ones. There is no AI quality probability, fabricated match percentage, rating, paid placement or unverified “best doctor” score.

Return at most 10 matches, with confirmed matches, unknowns, exclusions/rank explanation, distance when known and snapshot date. Filter changes create a new criteria version. Zero results produce one explicit proposed relaxation at a time. Never relax a required filter automatically. Same case revision + filters + dataset + rule version must yield the same IDs and order.

The first directory may be entirely synthetic. Real directory adoption requires source permissions and verification policies. An offline valid snapshot can still produce dated cached results. Stale insurance or availability cannot become current merely because the cached record is displayed.

## Contact and export

A11 shows destination before an approved HTTPS browser handoff. Use `noopener` and `noreferrer`; send no case payload or query data. Synthetic cards must not accidentally contact real doctors. No automatic appointment booking, confirmation, clinician message, EHR write or email delivery exists in the baseline.

A12's PDF is an appointment-preparation summary. Require current reviewed guidance and explicit user review. Include reported/confirmed facts, unresolved gaps, source references, generated timestamp and AI labels. Do not add a diagnosis or unsupported facts. A job exposes an export ID and type; only the authorized download endpoint serves bytes with attachment and no-store headers.

Check owner, current revision, expiry and tombstone again when streaming. Revoke after 15 minutes or a clinical edit/deletion. Explain that a PDF already downloaded to the laptop is outside server deletion.

## Required database/service checks

Enforce case/slot uniqueness, one current answer, no stale publish, immutable source provenance, schema field limits, complete nested ownership, and atomic deletion. Tests must assert behavior, not merely snapshot a schema. Static schema validity and referential integrity checks in this handoff are preparation checks; no API execution or real-device performance is established by them.
