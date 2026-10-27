# Clinical pathway packages

`registry.json` lists the packages the API loads. Each package is a directory holding three files, plus an optional fourth:
- `pathway.json`, which conforms to `spec/contracts/Pathway.schema.json`;
- `questions.json`, the approved question templates;
- `red-flags.json`, the approved red-flag checklist with its urgent messages;
- `policy.json` (optional), pathway rules such as the clinician floor.

## `general-adult-4` (enabled)
ADR-003 amendment 4 of 2026-10-19 (issue #194), approved by the clinical reviewer (role MD). Record:
`evidence/clinical-review/2026-10-19-amendment-4/`, with the measurement made before release. It expires on
2027-10-15.

| Part | Content |
|---|---|
| Scope, questions, messages, policy (a), clinician floor, red-flag screen | Unchanged from `general-adult-3` |
| Red flags | RF01–RF20: RF20 "Took too much of a medicine, or swallowed something poisonous" (emergency) added. An overdose written in the concern was caught only before guidance, after the questions, because no approved sign named it. |

## `general-adult-3` (superseded, kept for history)
ADR-003 amendment 2 of 2026-10-16 (issue #79), decided by the clinical reviewer (role MD), who chose to review the
measured results after release. Record: `evidence/clinical-review/2026-10-16-amendment-2/`. It expires on 2027-10-15,
like `general-adult-2`.

| Part | Content |
|---|---|
| Scope, questions, red flags, messages, policy (a), clinician floor | Unchanged from `general-adult-2` (RF01–RF19) |
| Red-flag screen (`policy.json`: `red_flag_screen: true`) | In local mode, before any guidance, the local model reads the concern and every answer and returns only the IDs of approved red flags those words describe as present (task `red_flag_screen`, prompt `red-flag-screen-2` since #389, which also counts an emergency happening now to someone the person cares for, `apps/api/app/modules/safety/screen.py`). A match sends the case to urgent help at the highest matched level, as a ticked box does; no guidance is generated. An unavailable or invalid screen fails closed: no guidance, limited state with retry. The qualified guidance prompt `guidance-local-1` is unchanged. |

## `general-adult-2` (superseded, kept for history)
The ADR-003 amendment of 2026-10-15 (issue #73), decided by the clinical reviewer (role MD). Record:
`evidence/clinical-review/2026-10-15-amendment/`. It expires on 2027-10-15. `v0.5.2-demo.1` serves it.

| Part | Content |
|---|---|
| Scope, questions, policy (a) | Unchanged from `general-adult-1` |
| Red flags | RF01–RF19 (15 emergency, 4 urgent clinician). The amendment added RF17 "Coughing up blood" and RF18 "Skin redness that is spreading, with fever" (urgent clinician), and RF19 for possible cauda equina (emergency). |
| Clinician floor (`policy.json`) | When the model answers `undetermined` for a case that reached it, the answer is published as `routine_clinician`, with no self-care advice and reason code `MODEL_UNCERTAIN_CLINICIAN_FLOOR`. It is never repaired toward self-care. |
| Verification | The 50 review cases were re-run: 5 changed level, all borderline and now routine via the floor, and the reviewer graded all 5 correct |

## `general-adult-1` (superseded, kept for history)
Accepted by the clinical reviewer (role MD) on 2026-10-15 in ADR-003 (issue #27). Record:
`evidence/clinical-review/2026-10-15/`. It contains Q01–Q10, RF01–RF16 and policy (a). Releases up to `v0.5.1-demo.1`
serve it.

## Rules the API enforces (M05, `apps/api/app/modules/safety/pathway.py`)
- **Local mode needs an enabled, approved, unexpired package.** Without one, every new case is limited and
  `generateGuidance` answers 503. A malformed package fails startup.
- **Local mode needs the checklist.** A case without a `red_flags` answer is limited, because urgency could not be
  assessed (R17). Unknown red-flag IDs are rejected.
- **The red-flag screen fails closed** (`general-adult-3`). A screen answer other than `{"present": [distinct
  approved IDs]}` is invalid; neither an invalid nor an unavailable screen produces guidance. An invalid
  `red_flag_screen` setting fails startup.
- **Mock mode** still follows its labeled synthetic scenarios (`fixtures/scenarios.json`) and also honors a ticked red
  flag.
- **Changes need a new review.** A package change, a scope change or a red-flag change needs a new review and a new
  version. Do not invent reviewer identities, thresholds or approval dates.
