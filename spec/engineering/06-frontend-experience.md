# 06 Frontend implementation and screen parity

Product baseline 2.0; handoff 1.0.0. Screens are implemented in `apps/web/src/screens/`. `../screens.json` owns exact routes, IDs, owner modules, primary actions, guards and exception states. `../mockups/README.md` explains the original visual references and their limitations.

## One responsive application

Use the existing repository's compatible frontend structure where possible. The screen files are `apps/web/src/screens/<ID>.tsx`, with a shared route registry in `apps/web/src/routes.tsx`. Preserve all 25 routes (the 24 source routes and W06, ADR-017) and their parameter names. Native mobile clients are future scope. Component reuse is expected; neither one requirement per file nor one file per visual state is required.

| Screen group | IDs | Main obligation |
|---|---|---|
| Public information | W01-W05 | Explain purpose, process, bounded benefits, privacy and help without claiming clinical outcomes |
| Setup | A01-A04 | Versioned consent, explicit unknown profile facts, required concern and optional records |
| Assessment | A05-A08 | Issued-slot progress, typed answers, current-revision review, guidance and claim-linked sources |
| Navigation | A09-A12 | Explicit criteria, deterministic factual matches, deliberate external contact, reviewed export |
| Continuity and limits | A13-A16 | Owned history, deletion/retention, immediate urgent interruption and honest service limits |
| Presenter | O01-O03 | Separately authorized runtime, control evidence and isolated synthetic scenarios |

Routes use frontend names such as `caseId`; API payloads use the contract's snake_case fields and UUIDs. The sample aliases `demo-001`, `p01`, and similar identifiers are not valid backend IDs. `fixtures/id-map.json` documents a translation for stable synthetic seeds; each live session must still have isolated owned records.

## Shared design system

The product master owns the palette: canvas `#F7FAFC`, surface `#FFFFFF`, text `#132B3A`, primary `#024AD8` (HP blue, gradient to `#2D3FCF`; `#087BA8` before the HP-branded redesign), teal `#008779` (`#00796C` for small text), accent `#D5714E`, borders `#CBDDE5`. Validate actual text/background contrast and adjust shades where required. Archived images may retain older colors or the HealthGuide name. The application name is **Aware Care**.

Use local or system sans-serif fonts, at least 16px body text and a 1.5 line height. Use spacing tokens 4, 8, 12, 16, 24, 32 and 48. The main content maximum is 1120px; the intake column maximum is 680px. Prefer semantic native controls. Product screens must not expose internal configuration, model endpoints, stack traces or JSON schemas.

| Component | Behavior contract |
|---|---|
| Button | Visible keyboard focus; real disabled/pending state; no duplicate submission |
| TextField | Associated label, helpful instructions, announced validation error, preserved input on recoverable failure |
| ChoiceGroup | Correct radio/checkbox semantics; issued option IDs; clear unknown and none choices |
| StepProgress | Actual issued slots, never a fabricated percentage or a promise of exactly ten prompts |
| SourceLink | Claim-linked approved source, date/locator and an honest unavailable state |
| ProviderCard | Synthetic/source labels, confirmed facts, unknowns and ranking reasons; no invented match percentage |
| StatusBanner | Text and icon as well as color; clear urgency, stale, cached, limited or failed meaning |
| ConfirmDialog | Keyboard focus containment and return; explicit destructive/external action; no implicit consent |
| EmptyState | Explains absence and an allowed next action without fabricating content |
| LoadingState | Actual request/job state; no timer-based claims of completed inference |

These proposed paths and many-to-many requirement/screen relationships are in `../traceability.yaml`, in each requirement's `code` list. When adding a component, register its actual dependencies rather than copying unrelated IDs. Shared controls render behavior; owner services retain authorization, clinical rules, provider ranking and persistence.

## State and transport

The server owns session identity, case revision/state, issued question slots, jobs and derived-result validity. Use the contract's allowed actions and responses. A frontend route guard improves the experience but never replaces server authorization. Direct navigation, refresh, Back/Forward and polling must enforce the same state boundaries as buttons.

- Use relative `/api/v1/...` URLs through the same-origin gateway. Development Vite proxies `/api` to `127.0.0.1:8000` without dropping the prefix.
- Generate TypeScript API types from the conformed OpenAPI export. Do not maintain a second handwritten DTO vocabulary.
- Keep CSRF tokens in memory and use the approved opaque session cookie. Do not put session, presenter or model credentials in frontend environment variables.
- Use a stable idempotency key for a retry of the same logical creation. Do not generate new work because a browser reconnects or a response is slow.
- Send `expected_revision` on applicable mutations. A 409 reloads current state and requests reconciliation; it does not silently overwrite another edit.
- Poll jobs at the documented cadence. Stop on terminal state/navigation; read the existing job when returning. A stale or cancelled result cannot become current guidance.
- On 401/expiry, clear in-memory health state and return to A01. Guest reset and deletion must wait for server completion before reusing a fixture.
- Do not store health content in localStorage, IndexedDB, service-worker caches or third-party analytics. Host application assets locally.

## Exception states that must work

Every asynchronous screen needs meaningful loading, recoverable failure/retry, authorization/expiry and stale-state handling as applicable. Keep completed answers on recoverable validation errors. A screen without data needs a truthful empty state. Do not hide missing implementation behind a permanent spinner or a decorative success message.

| Flow | Required exception behavior |
|---|---|
| A01 consent | Health writes remain blocked until current consent; roles are server-assigned |
| A04 records | Reject limits safely; show extraction/review status; unconfirmed facts never become clinical inputs |
| A05 intake | No eleventh issued slot; invalidated prompts still count; urgent signals interrupt immediately |
| A06 review | Confirmation applies only to the current revision; edits invalidate derived results |
| A07/A08 result | Distinguish clinical limits from service failure; never show raw invalid model text or fabricated citations |
| A09/A10 provider search | Unknown required criteria fail eligibility; no-match offers explicit user-approved changes |
| A11 contact | External HTTPS handoff contains no case payload/referrer; simulated contact is visibly labeled |
| A12 export | Explicit review, owned expiring download, no automatic sending or booking |
| A14 deletion | Clear confirmation, immediate blocked access, pending/failed purge and truthful completion |
| A15 urgent | Routine guidance and doctor matching remain blocked; generic help is available without exposing a private case |
| O01-O03 presenter | Guest direct URLs rejected; runtime values come from observed state; reset failures block reuse |

## Mock and local identity

Mock mode deliberately uses synthetic fixture outcomes and never calls a model server. Typed free text in a mock must not be represented as a medical assessment that produced its scripted outcome. Local mode uses the actual configured ZRT adapter and reviewed-content gates. An unavailable local dependency must not switch the screen into a scripted successful result.

The original browser mock is a design aid: its in-memory history, simulated delay, public presenter controls, printing and scripted extraction are not implementations of the backend requirements. Preserve its visual intent while implementing the actual contracts.

## UI evidence

UI tests are `tests/ui/<ID>.spec.ts` plus cross-cutting specs (`routes.layout.spec.ts`, `a11y.spec.ts`). Check at 360px, 768px and 1440px, plus the 390px source mockup size. Include keyboard completion, visible focus, semantic headings, announced updates/errors, reduced motion, 200% zoom and no horizontal page scrolling. Test focus after a question change and after a modal closes. Primary actions must remain reachable without covering content.

Record the exact build, screen/requirement IDs and actual test results. Screenshots show visual parity; they do not establish API security, clinical correctness or local inference. CI runs the UI suite in mock mode on every pull request; device runs are recorded separately ([Testing](../../docs/wiki/Testing.md)).
