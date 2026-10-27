# ADR-007: Development mock-mode build interpretations

Status: engineering decisions for the development build, pending product/technical review.
Date: 2026-10-13. Change record: CHG-DEV-APP-001 (`../change-records-archive.md`).
Affected IDs: R01-R03, R11-R17, R18-R20, R24-R27, R31, R37-R39; A01, A02, A04, A05, A07, A15, A16, O01-O03;
createSession, saveProfile, uploadRecord, nextQuestion, generateGuidance, loadScenario, resetDemo, getRuntime, getControls.

These choices fill gaps where the baseline is silent or depends on open decisions. None of them changes a
requirement, route, operation ID or schema. Each should be confirmed or replaced by the named owner.

| # | Topic | Decision in this build | Reason / open dependency |
|---|---|---|---|
| 1 | Mock scenario for patient-created cases | `POST /cases` in mock mode binds the case to the `routine` fixture scenario. Other scenarios (selfcare, urgent, unsupported, nomatch, failure) are reachable only through presenter `loadScenario`. `nomatch` can also be reproduced by a patient explicitly requiring `Demo Exclusive Plan` on A09. | `CaseWrite` has no scenario field and free text must not select outcomes. Presenter selection is the only specified selector. |
| 2 | Presenter identity | No presenter session can be created; all presenter operations return 403 and O01-O03 show the unauthorized state. Service logic is exercised by acceptance tests with a test-only presenter row. | ADR-005 (open) — no approved local authentication layer. No password, URL flag or bypass was added. |
| 3 | Saved mode | `createSession` with `mode=saved` returns 403 `SAVED_MODE_UNAVAILABLE`; `saveProfile` returns 403 `SAVED_MODE_REQUIRED`; `getProfile` returns `{ "profile": null }`. A02 keeps details in browser memory for the session and sends them as `origin=user` confirmed context. | ADR-005 (open). |
| 4 | Record extraction (superseded by ADR-009 #1) | `uploadRecord` returns 503 `SERVICE_LIMITED` after ownership/consent checks; `listRecords` is empty; `reviewFact` finds no document facts (404). A04 offers skip. | No restricted extraction worker/OCR is installed; scripted extraction would fabricate facts. |
| 5 | Recoverable generation failure retry | Failure moves `generating → limited` with a recoverable reason (allowed action `retry`). The explicit retry is `nextQuestion`, which performs `limited → intake`, then `review_required` (`intake → review`); the user re-confirms review and regenerates. | Uses only transitions in the 02-state-and-intake table; avoids an unlisted `limited → generating` edge. Costs one extra confirmation. |
| 6 | Answers as facts | Each saved answer is mirrored as a `user`-provenance Fact (`kind=answer:<template>`, `source_id=question id`, `original_text=question text`). | No operation lists questions/answers; A06 review and case-fact claims need the current answers. |
| 7 | CSRF recovery after reload | Authenticated responses echo `X-CSRF-Token`; the browser keeps it in memory only. | The token is memory-only, so a reload would otherwise block all writes. Same-origin only (no CORS). |
| 8 | Pre-session nonce | Any `/api` response sets an HttpOnly `awarecare_presession` cookie when absent; `createSession` idempotency is scoped by its hash. A replay rotates the session token for the same session. | Draft wire detail; the Vite dev server serves no app HTML through the API. |
| 9 | Clinical claims without corpus | Mock guidance publishes clinical explanations only with `validation_status=suppressed` and no evidence; supported claims are case-fact claims with fact IDs. `getCaseSources.evidence` is empty. | No approved corpus (ADR-004). |
| 10 | Provider stable tie-break | After distance, ties order by the synthetic directory order (p01, p02, p03), matching `fixtures/provider-filter-cases.json` (PC08). Selected-but-unranked plan/language preferences are appended after explicit ranked preferences. | Fixture ordering assumptions; "stable UUID/alias mapping". |
| 11 | Expired export status | Download after expiry returns 409 `EXPORT_EXPIRED`. | 410 is not in the API error table. |
| 12 | Dev cookies | `Secure` is off by default (`AWARECARE_COOKIE_SECURE=false`) for HTTP over the loopback SSH tunnel; cookies are HttpOnly, SameSite=Strict, Path=/api (Path=/ since #487). | Development-only exception per 05-privacy-and-security; TLS deployments must enable it. |
| 13 | Allowed origin | Default allowlist is exactly `http://127.0.0.1:15173` (SSH-tunnel browser origin confirmed by the user). Override with `AWARECARE_ALLOWED_ORIGINS`. | User instruction 2026-10-13. |
| 14 | Local mode (superseded 2026-10-15 by ADR-003/ADR-004 and CHG-DEV-M4-003: local guidance runs behind the reviewed pathway) | Selecting `AWARECARE_MODE=local` uses the ZRT adapter, but with no reviewed pathway new cases are `limited`, guidance returns 503 `SERVICE_LIMITED`, and readiness is `unavailable`. No mock or cloud fallback. | ADR-002/003/004 open. ZRT was observed serving `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` at `GET /v1/models` (2026-10-13, no auth required for that read); no inference request was sent and the manifest stays unconfigured. |
| 15 | Mock timing | Mock jobs run without artificial sleeps; recorded timings are actual measured durations. `simulated_delay_ms` from fixtures is not applied. | API README: no fabricated timing. |
