# Open decisions and implementation boundaries

| ID | Owner role | Needed decision / evidence | Blocks |
|---|---|---|---|
| ADR-002 | Technical lead | ZRT services/models/help, successful non-clinical inference, selected model revision and context | Connected model adapter readiness |
| ADR-003 | Clinical reviewer | Reviewed scope, question templates, urgent rules, fallback wording and fixture outcomes | Clinical guidance in local mode |
| ADR-004 | Product/data lead | Approved corpus, reuse permissions, support/freshness reviews | Clinical claim publication |
| ADR-005 | Infrastructure lead | Local saved/presenter auth, trusted-network TLS, encryption, roles and egress controls | Multi-user and connected presentation release |
| ADR-006 | Demo owner | Presenter identity and synthetic scenario selection; Dallas/Irving examples remain fictional | Final rehearsal configuration |

Roles are proposed responsibilities, not people appointed by this handoff. Record decision rationale, source, date, affected IDs, and acceptance impact. Do not invent approval dates, signed clinical review, measured latency, or secrets. Mock-only development and generic model smoke tests can proceed while these remain open.

## Status on 2026-10-14 (issue #11)
| ID | Prepared input | Next step |
|---|---|---|
| ADR-002 | [**Accepted 2026-10-15**](ADR-002-model-qualification-protocol.md): `Qwen/Qwen3.6-35B-A3B-FP8` at `95a723d0…` qualified (#45, #48) and pinned in `infra/model-manifest.json` | Wire the qualified model into the guidance service (#51); local guidance still waits on ADR-003 and ADR-004 |
| ADR-003 | [**Accepted 2026-10-15**](ADR-003-clinical-review-packet.md) by the clinical reviewer (role MD): general adult scope, policy (a) self-care first, red flags RF01–RF16, 50 graded answers (`evidence/clinical-review/2026-10-15/`); **amended 2026-10-15**: `general-adult-2` (RF17–RF19, clinician floor when the model is unsure; 5 changed answers graded correct) | Package, checklist and local `generateGuidance` implemented (CHG-DEV-M4-003, #27); release with v0.5.0; connected scenario fixtures in #55 |
| ADR-004 | [**Accepted 2026-10-15**](ADR-004-corpus-review-packet.md): no evidence corpus for the demo (clinical claims suppressed; since [ADR-015](ADR-015-general-knowledge-explanations.md), 2026-10-16, possible explanations from general medical knowledge are shown, labeled), fictional doctor directory, offline only; v2 doctor search from Zocdoc-like directories with structured filters only | v2 needs its own decision on named providers, terms and the outbound gateway |
| ADR-005 | [**Accepted 2026-10-14: option A**](ADR-005-presenter-access-proposal.md) (SSH-gated presenter gateway; amended 2026-10-22, #487: a path of the one loopback gateway instead of a second port). TLS before a customer network and disk encryption remain open | Implement in #14; decide the open follow-ups before any customer-network demo |
| ADR-006 | [Proposal](ADR-006-presenter-identity-and-scenarios-proposal.md): presenter list, the six existing scenarios, reset gate | Demo owner accepts or amends |

ADR-005 option A (2026-10-14), ADR-002, ADR-003, ADR-004 and ADR-012 (2026-10-15) are accepted. The ADR-003 package and
checklist are implemented, so local guidance can be released (v0.5.0).
