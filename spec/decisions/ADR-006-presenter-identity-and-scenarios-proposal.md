# ADR-006 (proposal): Presenter identity and synthetic scenario selection

Status: **Proposed, awaiting the demo owner's decision.** Depends on ADR-005. Nothing here is implemented.

Status amendment (2026-10-19, #293): still **proposed**; the demo owner has not decided. "Nothing here is implemented"
no longer holds for the parts that ADR-005 option A and ADR-016 built:
- the presenter gateway and presenter sessions (`apps/api/app/modules/access/presenter.py`,
  `infra/deploy/presenter.conf.template`, since #487 `presenter-api.conf.template` of the one gateway);
- O03 offers exactly the six existing scenario IDs of `fixtures/scenarios.json`, in fixture order, not the proposed
  story order (`apps/web/src/screens/O03.tsx`);
- a load first completes a reset of the presenter's previous demo, and a pending or failed reset blocks a new load
  (`apps/api/app/modules/operations/scenarios.py`);
- in local mode a scenario only starts a synthetic case that runs live, and `failure` is unavailable
  ([ADR-016](ADR-016-live-presenter-scenarios.md)).

Not decided: the presenter population list (an organizational control outside Git), the story order and the
fictional location wording.

Date: 2026-10-14. Issue: #11. Owner role: demo owner (product.md D05).
Affected IDs: R37, R39, R40; O01, O03; M12; loadScenario, resetDemo, getRuntime. No ID, route, operation or
schema change.

## Questions to decide
1. Who may act as presenter, and how is that recorded?
2. Which synthetic scenarios O03 offers, and in what order for the five-minute story?
3. What a reset must guarantee before a new guest demo starts.
4. Which fictional location the provider directory presents.

## Proposal

| Topic | Proposed decision | Basis |
|---|---|---|
| Presenter population | People with an SSH account on the demo Nano who are named on a presenter list kept by the demo owner (outside Git, for example the team roster). With ADR-005 option A, technical access equals SSH access, so the list is an organizational control, not a technical one. | Smallest change consistent with ADR-005 A; no new identity store |
| Presenter attribution | Each presenter session records only a generated presenter actor ID in content-free events. Names are not stored in the app. | ENG-05 logging rules; no personal data needed |
| Scenario catalogue | Offer exactly the six existing IDs from `fixtures/scenarios.json`: `routine` (Find the right clinician), `selfcare`, `urgent` (Urgent interruption), `unsupported`, `nomatch`, `failure`. Recommended story order: **routine → urgent → nomatch → failure**. `selfcare` and `unsupported` are available but not in the default story. | IDs are stable (verification.md); no new fixtures invented |
| Labeling | Every scenario card and the resulting patient screens show the existing synthetic/mock labels. O03 shows the mode (`mock`) and the release tag from the runtime snapshot. | R37 |
| Load semantics | `loadScenario` first completes a reset of the presenter's previous synthetic context, then creates an isolated synthetic session and case (existing contract, `reset=true`). | product.md line 478 |
| Reset gate | A failed or unfinished reset blocks loading a new scenario and starting a new guest demo from O03, shown as the O03 required exception. Recovery is retrying the reset; no data is reused while it is pending. | O03 contract; R37-S02 |
| Metrics on O01/O03 | Show measured timings only (no fabricated values) and "not measured" for every benefit or outcome. Scenario runs are never counted as avoided visits or savings. | R38, R39 |
| Fictional location | Keep the existing fictional directory and its city labels (Dallas/Irving examples remain **fictional**, as already noted in open decisions). Every provider card stays labeled fictional. | product.md line 635; open-decisions ADR-006 note |

## Acceptance impact if accepted with ADR-005 A
- **Now testable:** the presenter parts of R37-S01 and R37-S02, R39-S01, and O03 load/reset UI tests.
- **Still not covered:** R39-S02 (future pilot review) is not affected.

## Decision needed
The demo owner confirms the presenter population rule, the scenario order and the fictional location wording,
or amends them. Accepted text then replaces "Proposed" with the decision date and owner.
