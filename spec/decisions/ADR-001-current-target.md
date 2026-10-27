# ADR-001: Current product target and resolved precedence

Status: explicit user decisions recorded; engineering defaults identified separately.
Date: 2026-10-13. Source: current conversation plus original master v2.0.

| Topic | Effective instruction | Basis |
|---|---|---|
| Product name | Aware Care | User selected this name after HealthGuide mockups were created |
| Target | One HP ZGX Nano, GB10, Ubuntu ARM64 | User-selected device and supplied terminal output |
| Serving interface | ZRT 0.39.0; do not independently deploy Ollama or vLLM | Explicit user instruction; ZRT CLI describes its internal vLLM engine |
| Model API | Default documented URL http://127.0.0.1:8080/v1; discovery and successful request still required | Installed ZRT help; no serving models in observed status |
| App API | Proposed http://127.0.0.1:8000, prefix /api/v1 | Corrects earlier assistant port-8080 collision; engineering default |
| Frontend | Proposed http://127.0.0.1:5173 | Development default |
| SSH | Existing listener `<ssh-port>` (default 22) | User-supplied `ss` output; do not modify |
| Data | Synthetic demo data; default mock mode | User scope and original PMD |
| Local mode | Explicit ZRT adapter, validated output, no cloud or mock fallback | User selection and R26/R34 |
| Mobile | Responsive web layouts for these 24 routes | Master baseline; native clients are future scope |
| Intake | Up to 10 issued prompts; early completion and urgent interruption | R11-R17; invalidated prompts retain their slots |
| Contact | A11 external handoff or visibly simulated contact dialog | R31; no booking API, extra route or real appointment confirmation |
| Metrics | Runtime values measured; healthcare savings unmeasured | R37-R39 |

The previous assistant starter prompt's “mock appointment confirmation” is narrowed to the existing A11 simulated contact dialog. It does not authorize appointment scheduling or a 25th screen. The earlier /health/live suggestion is not added to the baseline's 31 operations; readiness remains GET /api/v1/health/ready.

The legacy browser mock uses different labels, simplified auth, in-memory state, timer-driven mock generation, and simulated documents/exports. Those differences are permitted only in that historical reference. They cannot override persistent-session, server authorization, record processing, revision, PDF-export or deletion requirements for the implemented local app.

The original master palette is the default token authority; slightly different legacy mockup colors are visual references. Preserve supplied design intent while meeting contrast and accessibility requirements. Do not claim the package is an export of the most recently published Sites design.

## Still unresolved
No model has been selected and validated on this device. ZRT environment setup completion, API authentication/TLS configuration, corpus/pathway clinical review, local saved/presenter authentication, storage encryption, and release test execution remain to be established. Their absence does not block building the synthetic mock interface or testing non-clinical ZRT connectivity. It blocks claims of connected clinical guidance readiness.

## Amendment (2026-10-18): a second device (ADR-018)
The single-device target above is amended by [ADR-018](ADR-018-second-device-zgx-fury.md): the same repository and
release images also deploy to an HP ZGX Fury (GB300) as environment `demo-zgx-fury`, with its own qualified model
(Qwen3.8-Flash-Next-FP8). The Nano remains a target, unchanged.

## Amendment (2026-10-19): status of the facts recorded above (#293)
The table and "Still unresolved" above are the record of 2026-10-13 and are kept as written. Later decisions and
observations supersede these parts of it:
- **Routes and operations:** [ADR-017](ADR-017-telemetry-page.md) (accepted 2026-10-16) adds the public screen W06
  `/telemetry` as route 25 and `getTelemetry` as operation 32. "These 24 routes" and "the baseline's 31 operations"
  now read 25 routes and 32 operations (33 since `getLogs`, #548; `spec/screens.json`, `spec/api/openapi.json`, checked by
  `scripts/check_traceability.py`). The A11 simulated contact dialog is still not a screen of its own.
- **Serving interface:** ZRT stays the only serving interface. The Nano was upgraded from ZRT 0.39.0 to **0.43.0**
  (2026-10-15, #75; `infra/model-manifest.json` `zrt_version_observed`), and the ZGX Fury runs ZRT 0.43.0
  (`infra/fury/model-manifest.json`). `infra/device-inventory.json` stays the 2026-10-13 snapshot that observed 0.39.0.
  The observed ZRT proxy authentication is `none`, bound to 127.0.0.1 only (`infra/model-manifest.json`).
- **Model:** [ADR-002](ADR-002-model-qualification-protocol.md) (accepted 2026-10-15) selected and qualified
  `Qwen/Qwen3.6-35B-A3B-FP8` on the Nano. [ADR-018](ADR-018-second-device-zgx-fury.md) qualified
  `Qwen3.8-Flash-Next-FP8` on the Fury. Each model is qualified only on its own device.
- **Clinical content:** the pathway was reviewed under [ADR-003](ADR-003-clinical-review-packet.md); `general-adult-4`
  is enabled (`content/pathways/registry.json`). No evidence corpus is approved
  ([ADR-004](ADR-004-corpus-review-packet.md)); possible explanations come from general medical knowledge, labeled
  ([ADR-015](ADR-015-general-knowledge-explanations.md)).
- **Early completion:** `general-adult-4` has no early-stop rule (its completion predicate is
  `all_eligible_questions_issued`, with 10 eligible questions), so local intake issues every eligible question. The
  10-slot limit and urgent interruption are unchanged.
- **Presenter authentication:** [ADR-005](ADR-005-presenter-access-proposal.md) option A (SSH-gated presenter gateway)
  is accepted and implemented. Saved patient accounts, TLS for a customer network and disk encryption stay open, and
  so does release test execution: no requirement is `verified`.
