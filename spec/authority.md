# Authority, versions, and change control

Product baseline: **2.0**. Handoff package: **1.0.0**, prepared 2026-10-13.

## Read in this order
1. `decisions/ADR-001-current-target.md`: explicit later user decisions and observed device facts.
2. `product.md`: original complete product baseline, including R01-R40, all screen contracts, module ownership, retention, safety, and API semantics.
3. `requirements.json`, `screens.json`, `modules.json`, `api/openapi.json`, `contracts/`, and `engineering/`: implementable registries and wire-contract elaborations of that baseline.
4. `acceptance.json`, `verification.md`, and `traceability.yaml`: planned verification and linkage.
5. `mockups/` and `visuals/`: visual/interaction references. Original browser mocks are not backend architecture or security authority.

Current user decisions supersede earlier planning assumptions. A later assistant suggestion alone does not amend the baseline. Requirements, routes, operations, scope, and safety invariants cannot be silently changed by a mockup or generated code.

The exact R01-R40, W01-W05, A01-A16, O01-O03, M01-M12, B01-B08, and F01-F12 namespaces are preserved. Contract definitions use original names. Derived T-Rxx acceptance IDs are handoff aliases, not invented original IDs. Document types D01-D05 and old decision labels D01-D05 are distinct namespaces; new decisions use ADR identifiers.

## Human documents and executable specifications
The five document types remain: D01 solution brief, D02 product master and screen experience, D03 engineering specification, D04 verification/release plan, D05 operations playbook. This repository decomposes them into focused Markdown and machine-readable files; five document types do not imply only five physical files.

`product.md` preserves all substantive source text. `source/Product_Master_v2.0_original.docx` preserves original bytes and page visuals. This handoff is an engineering expansion, not a clinical approval or a new approved production baseline. Wire refinements are marked draft-for-implementation; resolve substantive conflicts in a named decision before affected implementation. Routine internal code choices can proceed within these contracts.

## Change control (lean, ADR-019)
State the affected requirement, screen, operation, schema and test IDs in the PR. Change a source contract and its
derived representations together (for example `openapi.json` and the generated web types, `npm run gen:api`), and run
the traceability and contract checks. There is no hash lock and no change record: the PR and git history are the
record. Write an ADR only for a real decision (security model, model choice, a boundary). Archived source documents
remain provenance, not silently edited; superseded change records are in `change-records-archive.md`.

`screens.json` is the one route registry. `traceability.yaml` uses JSON-compatible YAML so its checks run with the
Python standard library. The OpenAPI contract is JSON and the source for the generated API client; generated clients
are never hand-maintained duplicates.

## Truthful status
All product requirements start planned. All application acceptance cases start NOT_EXECUTED. The only executable checks supplied here validate the handoff, contracts, and import process. No application, ZRT model, clinical pathway, security boundary, outcome, or latency is marked verified by package checks.
