# ADR-004 review packet: Evidence corpus and provider directory sources

Status: **Accepted 2026-10-15 by the maintainer, acting as product and data lead** (issue #28). Owner roles: product
and data leads (product.md D03). Packet prepared 2026-10-14 (issue #11). Affected IDs: R21, R22, R23, R28–R30, R34; A08,
A09–A11, O02; M07, M08, M09; `content/corpus/`, `fixtures/providers.json`.

Before this decision, `content/corpus/manifest.json` was `unconfigured` (`clinical_use_enabled: false`, no sources). The product's
references S1–S7 (CMS value-based care, AHRQ care coordination, HealthIT engagement playbook, HP ZGX Nano, MedlinePlus
checklist, CMS NPI fact sheet, NIST generative AI profile) are **background references, not corpus candidates**. The
corpus README already says so.

## Decisions requested

| # | Item | What approval must contain |
|---|---|---|
| 1 | **Corpus sources** | For each source: publisher, title, permitted use (licence or terms allowing local copying and display), topic mapping to the ADR-003 pathway scope, source publication date, retrieval date, content hash, locator granularity (section or page) |
| 2 | **Review and expiry** | Reviewer role, review date and review expiry for each source. Expired sources cannot support new claims (R22). |
| 3 | **Retrieval limits** | Confirm the defaults (8 candidates, 5 passages, 6000-token budget) or set others once ADR-002 fixes the context size |
| 4 | **Refresh policy** | Presenter-controlled ingest of approved source IDs only; how often; who approves new versions |
| 5 | **Outbound allowlist** (R23) | Enumerated endpoints and query schemas, if any connected retrieval or provider lookup is wanted. Otherwise confirm offline-only. |
| 6 | **Provider directory** | Keep the **fictional** directory for the demo (labeled on every card), or name attributable real sources with permitted reuse (NPI is identity, not licensure proof [S6]) |

## Dependencies
- The corpus scope must match the ADR-003 pathway scope.
- The token budget must fit the ADR-002 context limit.

## Acceptance impact
T-R21-S01/S02 and T-R22-S01/S02 (also clinician-dependent) and the corpus parts of O02 become testable only with an
approved, versioned corpus snapshot.

## Decision (2026-10-15)
**How it was decided:** the maintainer stated the decision in the Claude Code chat on 2026-10-15:
- the path C message, items 1–6;
- answer C, "zocdoc and similar websites";
- answer D, "for now it is a synthetic demo";
- approval of the step plan, which stated the v2 query boundary below ("go to step 3").

**The demo stays without an evidence corpus**, as #28 allows explicitly.

| # | Item | Decision |
|---|---|---|
| 1 | Corpus sources | **None for the demo.** `content/corpus/manifest.json` records `declined_for_demo`. The maintainer's sources ("reliable websites with knowledge about doctors", "Zocdoc and similar websites") are **doctor directories, not evidence**: they belong to item 6 (v2), not to a clinical corpus. The product references S1–S7 stay background references. |
| 2 | Review and expiry | Defaults approved for any future corpus: one reviewer role and review date per source, 12-month expiry; expired sources cannot support new claims (R22). |
| 3 | Retrieval limits | Defaults approved: 8 candidates, 5 passages, 6,000 tokens. The measured worst case with the full budget fits the 16,384-token context (ADR-002). |
| 4 | Refresh policy | Default approved: presenter-controlled, approved source IDs only, manual. |
| 5 | Outbound allowlist (R23) | **Demo: offline only**, with no outbound lookups. **v2:** a doctor search may call an approved directory search API. Only structured filters are sent: specialty, location, distance, insurance plan, language, visit type. The person's concern, answers, records and any condition text **never leave the device**. Specialty is chosen on the device from the reviewed result. |
| 6 | Provider directory | **Demo: keep the fictional directory**, labeled on every card. **v2:** real clinician data from Zocdoc-like directories and similar reliable sources, each used only under its terms of use or an API agreement that permits the reuse, with attribution and freshness shown. NPI is identity, not licensure proof [S6]. |

**What this means now:**
- **Evidence:** local guidance publishes no clinical explanation. Clinical claims are `suppressed`, and the guidance
  says that no approved evidence corpus is loaded. *Superseded on 2026-10-16 by
  [ADR-015](ADR-015-general-knowledge-explanations.md): every result now shows 1 to 3 possible explanations from the
  model's general medical knowledge, labeled `general_knowledge` and never cited. Still no corpus.*
- **Supported claims:** only case facts with confirmed references are supported.
- **Readiness:** a missing corpus does not block local readiness. It blocks only clinical claims.
- **Retrieval:** stays `unavailable` in the runtime facts.

**Not decided, needed before v2:**
- the named directory providers, with their terms or API agreements;
- the outbound gateway design and its consent screen;
- a privacy review of the enumerated query fields.

These are new decisions with their own issue, not part of this record.

**Acceptance impact:**
- **Can be met with no corpus:** T-R21-S02 ("no valid local evidence → limited result explaining the limitation").
- **Not applicable to the demo:** T-R21-S01 and T-R22-S01/S02 need an approved corpus.
- Both are recorded for #55.
