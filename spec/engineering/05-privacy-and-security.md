# 05 Identity, privacy and lifecycle controls

Owners M01/M02/M03/M11 with M07/M12. Requirements R01-R10 and R23/R33-R40. Synthetic data only for this demonstration. This design makes no HIPAA, clinical efficacy or production certification claim.

## Identity boundary

Use opaque server-side sessions. Session creation (consent) always issues a new token: a valid session of the same role already in the browser continues its actor under a new session ID, token and CSRF token, and the old session is revoked, so a token planted before consent cannot read what is entered after (session fixation, #434). HTTPS deployment cookies are Secure, HttpOnly and SameSite. Every write checks Origin and CSRF; creation checks Origin before identity exists. Configure precise deployment origins. For HTTP over a loopback SSH tunnel, either provide a supported local HTTPS setup or document a strictly development-only cookie exception; never assume browser treatment of localhost is the production policy.

Saved access uses preprovisioned local accounts behind an approved authentication layer. Presenter role is separately authorized. The session body cannot assign role/actor. Do not hardcode a presenter password, bypass authentication based on a URL flag, expose a model API key to the frontend or add a production login shortcut for the demo.

Server queries must verify the actor and every nested object's ownership. Guessing an ID gives no access. A hidden frontend button or CORS policy is not authorization. Presenter reset authority is limited to the owned demo context, never all saved users.

## Retention defaults

| Resource | Policy |
|---|---|
| Guest session/content | 30 minutes idle or 8 hours absolute, whichever comes first |
| Guest warning | Show 2 minutes before applicable expiry |
| Guest logout/reset | Revoke session and purge guest health content |
| Saved logout | Revoke session only |
| Saved synthetic profile/cases | 30 days default; selectable 7 or 30 days |
| Export bytes | 15 minutes; also invalidate on clinical edit/deletion |
| Content-free operational events | 30 days |
| Content-free job records (status and timing of each task) | Owner, case and result IDs removed and times cut to the hour when the owner's session ends; deleted 30 days after creation (#440) |
| Content-free AI usage counts (`model_calls`, hour only) | 90 days, removed by the cleanup sweep (ADR-017, #471) |
| Cleanup sweep | Every 5 minutes |
| Patient-content backup | Disabled for demo |
| Delete-confirmation token | Actor-bound, one-use, 5 minutes |
| Idempotency cache | 24 hours maximum, but health-bearing entries purge with their owner/case |

A cleanup sweep does not grant an extra five minutes of access. Access checks enforce expiry immediately; the sweep removes expired bytes. The user must explicitly confirm bulk deletion after receiving a token. The token alone is not consent to delete.

## Deletion transaction and worker races

1. Validate owner, explicit confirmation and expected revision where relevant.
2. Commit a deleting tombstone/generation and revoke reads/download permissions immediately.
3. Cancel queued work and signal running tasks. Every worker checks cancellation and tombstone before publishing.
4. Purge documents, previews, extraction, confirmed facts, patient-specific indexes, guidance, provider searches and exports.
5. Remove health database rows and sensitive idempotency response cache entries; preserve only minimal content-free completion metadata.
6. Collect acknowledgments from all owned stores and mark deletion complete. Failed purge retries use bounded backoff while access stays blocked.

Late model/extraction/export output cannot recreate deleted content. Tombstone lifetime must cover outstanding worker and retry horizons; choose and test that duration with the job implementation. Completion cannot be reported just because a SQL delete succeeded while files or queued jobs remain.

Presenter reset jobs belong to the presenter actor, so completion remains observable after the guest session is revoked. Do not replace the presenter cookie with a guest cookie when loading scenarios. A failed reset blocks another fixture load. Ordinary guest logout need not keep a revoked session alive solely to poll its deletion job.

## Browser and file boundary

Keep health state in temporary memory. No health content in localStorage, IndexedDB, service-worker cache, analytics, URLs or third-party error monitoring. Query/filter preferences that reveal health context are also sensitive. Clear in-memory state on session expiry/deletion and enforce server guards on browser back/refresh/deep links.

Static assets and fonts are bundled locally. If a service worker is introduced, explicitly exclude `/api`, health response payloads and exports. Sensitive responses use no-store. Serve downloads with attachment disposition and a sanitized filename. A downloaded browser PDF is outside server deletion; disclose that specific boundary.

Store uploaded bytes in a restricted directory outside publicly served assets, under server-generated opaque paths. Do not follow a user-supplied filesystem path. Worker accounts receive only necessary directory and model access. Validate file type/signature and content limits before expensive parsing wherever possible.

## Logging and operations

Operational events contain IDs, requirement IDs, timing, status, manifest references and bounded error codes only. Exclude names, raw symptoms, original filenames, prompts, outputs, clinical fact values, full URLs and outbound query values. Do not add a free-form `metadata` map to bypass strict Event schemas.

Runtime diagnostics remain presenter-only. Public readiness returns only ready/degraded/unavailable. Record observed device and model details truthfully, null/unverified for missing measurements. Benefit views say “Not measured” for clinical outcomes, avoided visits and insurer savings. An export download is not an appointment or an avoided visit.

Use local least-privilege runtime accounts, trusted-network TLS and deployment-supported disk encryption. Confirm actual encryption and outbound controls through evidence rather than assuming “local” implies protection. Keep credentials in deployment-managed secrets, never Git, specifications or frontend environment variables.

## Coding-assistant boundary

Claude Code is a development tool, not the healthcare application's inference provider. Source files, terminal outputs and supplied context may be processed by its configured provider. Keep real patient data and runtime credentials out of the coding repository and assistant context. This boundary is operationally separate from ZRT's local inference.

`CLAUDE.md` is guidance; it is not an access-control mechanism. Apply actual filesystem permissions, sanitized fixtures, backend-only secrets, schema checks and tests. The handoff package must never claim that writing an instruction automatically prevents data exposure.

## Verification required before a customer demonstration

Test foreign actor/nested object access; expired sessions; forged role/state; CSRF/Origin failures; stale revisions; queue saturation; file rejection; unknown/stale provider attributes; cloud-fallback absence; outbound rejection; deletion during extraction/generation/export; failed reset; browser back navigation; no sensitive browser persistence; and no patient content in logs.

Capture evidence against the pinned build. All reviewed urgent fixtures, ownership, boundary and deletion checks must pass. Execute 10 actual-device rehearsals including failure recovery. Static pack validation only proves the pack is internally readable; it does not satisfy those release gates.
