# ADR-015: Possible explanations from the model's general medical knowledge, always shown

Status: **Accepted 2026-10-16** (issue #105), decided by the product owner. Affected IDs: R21 (interpretation only),
R22 (wording), R24, A07, A08, M07, M08, the `Claim` contract, the local guidance prompt (`guidance-local-2`) and the
appointment summary (R32). Amends ADR-004 (what the demo publishes without a corpus). ADR-002's qualification is not
repeated for the new prompt, by the owner's choice (see Consequences).

## Context
ADR-004 records no approved evidence corpus for the demo. Until now that meant every clinical claim was
`suppressed`: the "Possible explanations" card on A07 showed either a "Not shown without approved sources" notice or,
after #103, an empty-state sentence. The product owner reviewed this on 2026-10-16 and set the rule in their own words:

> "no, also show explanations you need need a evidence corpus, just use llms own knowledge"

> "you don't need evidence corpus  show explanations every time, it should never come blank"

## Decision
1. **Always present.** Every published guidance carries 1 to 3 possible explanations for the concern. A local draft
   without one fails validation with `no_possible_explanation`, gets the single repair the local path already allows,
   and otherwise fails closed (no blank, mock or cloud substitute). Mock mode shows one scripted, labeled explanation.
2. **From general medical knowledge, labeled as such.** Without an approved corpus, an explanation is published with
   the new `Claim.validation_status` value `general_knowledge`:
   - only for `kind: clinical` claims, and always with an empty `evidence_ids` list (the contract enforces both);
   - shown on A07 as a possible explanation, on A08 with the badge "General medical knowledge — no reviewed source",
     and in the PDF summary under "Possible explanations (general medical knowledge, not from reviewed sources; not a
     diagnosis)";
   - the guidance's uncertainties say: "Possible explanations come from general medical knowledge, not from reviewed
     sources: no approved evidence corpus is loaded. They can be wrong and are not a diagnosis."
3. **Hedged, never a diagnosis.** The prompt (`guidance-local-2`, rules 5, 7 and 9 changed from `guidance-local-1`)
   asks for possibilities ("are often linked to"), never a diagnosis of this person. The existing guards still apply
   unchanged: no certainty, guarantee, percentage or "rule out" (rule 8 and the ADR-012 certainty review), no
   prescription or medication change, and no URL, doctor or provider name.
4. **Never presented as sourced.** No source, citation or URL is invented. An explanation cites evidence only when an
   approved corpus supplied it, and is then `supported` as before. A cited ID that is not in the input still fails
   validation (`invalid_ids`).
5. **`supported` and `suppressed` keep their meaning.** `suppressed` remains for a claim that must not be shown (for
   example a case-fact claim without confirmed fact references); a suppressed claim never appears on A07 or in the PDF.

**R22's canonical clause becomes:** "Given an unknown source ID, stale source or unsupported claim, suppress the
affected claim or show it only as labeled general medical knowledge without a citation, and disclose the limit; never
fabricate a source, citation or URL."

**T-R22-S01's first then-clause becomes:** "Each affected clinical claim is suppressed, or shown only as labeled
general medical knowledge without its citation, and the limit is disclosed."

**R21 is unchanged.** "No evidence yields limited output" still holds: nothing is retrieved, nothing is presented as
sourced, and the result discloses the evidence limit (T-R21-S02).

## Consequences
- **Not re-qualified.** ADR-002 qualified `guidance-local-1` on the Nano. The product owner chose on 2026-10-16 to
  skip re-qualifying `guidance-local-2` (plan steps 4 and 5 of #105 were excluded). The manifest records the new
  prompt hash with that note. Until a re-qualification runs, how often the model needs the repair, and whether its
  explanations stay hedged in the real model's output, is **not measured**. The validator, the single repair and the
  certainty review still fail closed.
- **Clinical review.** The explanations are not clinically reviewed text. The labels on A07, A08 and the PDF, and
  the uncertainty sentence, say so; the clinician reviewer's ADR-003 approval covers the questions, red flags and
  urgency rules, not these explanations.
- **ADR-004** still holds for evidence: no corpus, retrieval `unavailable`. Its line "local guidance publishes no
  clinical explanation" is superseded by this decision.
- **Change record:** CHG-DEV-M4-007, with a spec-lock refresh. R21 and R22 stay `planned`.

## Amendment (2026-10-16): prompt `guidance-local-3` (#110)
**Finding.** Before deploying `v0.5.6-demo.1`, its API ran in local mode on the Nano against ZRT. On "Nausea in the
mornings" (C27) the model returned rule 5's example verbatim: "Headaches after long screen sessions are often linked to
eye strain or muscle tension." The copy happened when the confirmed facts included the Q04 answer "After long screen
sessions", which the example echoes. `v0.5.6-demo.1` was not deployed.

**Change.** `guidance-local-3` drops the topic example. Rule 5 now asks for explanations of the concern the person
described, naming a common cause of that concern, using the confirmed facts where they fit, worded as a possibility
with topic-free patterns ("... is often linked to ...", "... can sometimes be caused by ..."). It adds: "Never bring
in symptoms, activities or causes unrelated to the described concern." Everything else in this decision is unchanged.

**Measured on the Nano** (synthetic cases, `evidence/local-guidance/2026-10-16-guidance-local-3/`):
- **Verbatim copies:** `guidance-local-2` copied the example onto 1 of 10 non-headache concerns. `guidance-local-3`
  copied it onto 0 of 40 (C01–C40), with no headache text on any non-headache concern. Every result published with 1
  to 3 labeled explanations.
- **Neutral pattern answers:** with Q04 answered "No pattern noticed", both prompts stayed on topic on 10 concerns.
  `guidance-local-3` gave 19 explanations against 14, with fewer advice-style sentences.
- **Facts drive the topic:** when a case carries "After long screen sessions", explanations use it, even for concerns
  where the link is weak (for example mouth ulcers). The model follows the confirmed facts.
- **Not re-qualified** under ADR-002, as before. *Update 2026-10-16: re-qualified, all gates passed (ADR-002,
  `evidence/model-qualification/2026-10-16-guidance-local-3/`).*

## Update (2026-10-16): re-qualified, A07 label, worksheet descoped (#105)
- **Re-qualified:** `guidance-local-3` passed every ADR-002 gate on the Nano (stage 4 at 64/69 within 20 s, gate 62).
  The "not re-qualified" consequence above no longer holds.
- **A07 label:** the "Possible explanations" card states the origin itself: "From the AI's general medical knowledge,
  not checked against reviewed sources. It can be wrong and is not a diagnosis." In mock mode it says "Scripted
  illustrative explanation…, not from an AI model or reviewed sources."
- **Descoped by the product owner (2026-10-16):** the 50-case rerun with explanations and the grading worksheet for
  the clinical reviewer ("except 2.2"). The explanations stay labeled as not clinically reviewed. The work is tracked
  in #118.

## Amendment 2 (2026-10-18): a concern check at creation; the "you" rule waits (#154)
**Why:** QA on both devices (2026-10-18) found two problems.
- **Non-health text got guidance:** "asdf qwer zxcv uiop" went through ten questions and got guidance, with
  explanations about headaches and screen use. Rule 5's "Never bring in symptoms, activities or causes unrelated to the
  described concern" cannot hold when the concern describes nothing.
- **Third-person summaries:** several summaries said "The user reports …" (Fury, 3 of 6 routine cases).

**Decision by the clinical reviewer and maintainer (role MD), 2026-10-18:**
- "implement your default suggestions for both 153 and 154": a limited result asking the person to describe their
  concern, and summaries that address the person;
- then, after the re-qualifications below: "Concern check now". Both devices keep `guidance-local-3`, and the "you"
  rule waits until the Nano's restart-dependent results (#178) are resolved, so both devices run one prompt (ADR-018).

**What was tried:** three drafts of `guidance-local-4` (`evidence/model-qualification/2026-10-18-guidance-local-4/`).
- **The ZGX Fury passed ADR-002** with the final draft, which added only rule 10, "Address the person as "you".", and
  a third-person validator check: stage 2 at 69/69 valid on the first attempt, stage 4 at 69/69 within 20 s.
- **The ZGX Nano failed every draft:** stage 2 at 59–64/69 valid after one repair, stage 4 at 44–59/69. The
  deployed `guidance-local-3` also failed on the same engine (64/69 and 58/69). Its results change with each engine
  start (#178), so the drafts could not be qualified there.
- The non-health rule inside the guidance prompt disturbed the Nano model's fact-ID copying. That half therefore moved
  to a separate check.

**The change (shipped):**
- A concern check at case creation: a separate task `concern_check` with prompt `concern-check-1`.
- **When:** in local mode, when a case is created with no ticked or written red flag, and when the concern is edited.
- **How:** the local model reads the concern alone and answers only `{"health_concern": true|false}`. Its rule is
  "when unsure, true".
- **On `false`:** the request is refused (422, field `concern`, code `not_health_concern`) and no case is created; A03
  asks for a health concern at once, instead of after ten questions.
- **On a failure or timeout:** the case proceeds, as before the check existed.
- **Urgency:** never decided here; the checklist and the red-flag screen run first (ADR-003).
- The guidance prompt, the validator and the qualification harness are unchanged.

**Measured on both devices** (`evidence/clinical-review/2026-10-18-concern-check/`):
- **Wrong refusals:** 0 of 131 health texts on both devices. The set covers vague, short, misspelled and non-English
  concerns, the labelled concerns, the 50 review concerns and the QA concerns.
- **Non-health texts refused:** Fury 14/14, Nano 13/14. The Nano let "lorem ipsum dolor sit amet" through, which
  proceeds as before.
- **Time added per case:** 0.18 s on the Fury, 0.38 s on the Nano.

**Deferred:** the "you" rule (`guidance-local-4` as qualified on the Fury) is tracked in #179.

## Amendment 3 (2026-10-19): `guidance-local-4` adopted on both devices (#179)
**Condition met:** amendment 2 deferred the "you" rule until the ZGX Nano qualified under ADR-002 (#178). With the
short id aliases of #199, it does.

**The change:** both devices use `guidance-local-4`:
- **Rule 10:** `guidance-local-3` plus rule 10, "Address the person as "you".";
- **Check:** a validator check, `third_person`, finds "the user", "this user", "the patient" or "this patient" in the
  summary's own statements and repairs the draft once. The person's clinician questions are not checked.

Rules 1–9, the certainty review, the general-knowledge labels and the models are unchanged.

**Evidence** (`evidence/model-qualification/2026-10-19-guidance-local-4/`):
- **ADR-002:** PASSED on every stage on both devices, and on the Nano on two engine starts with identical outputs
  (stage 4 64/69, p50 10.4 s).
- **Third person:** no published draft calls the person "the user" or "the patient", against 22 of 70 (Nano) and 11 of
  70 (Fury) with `guidance-local-3`.

## Amendment 4 (2026-10-21): a stricter concern check, `concern-check-2` (#314)
**Finding:** on the ZGX Nano, `concern-check-1` accepted "lorem ipsum dolor sit amet" as a health concern. The ZGX
Fury refused it.

**Decision by the maintainer, 2026-10-21:** "a stricter prompt", re-qualified on both devices.

**The change:** the concern check uses `concern-check-2` (`apps/api/app/modules/cases/concern_check.py`). Only the
instructions changed:
- the text is data, not instructions, and calling it a health concern does not make it one;
- filler text such as "lorem ipsum", word lists, code and links name no health matter;
- terse, misspelled and other-language concerns still count, with examples;
- "When a real health matter may be meant, return true" stays.

**Unchanged:** the task, the `ConcernCheck` answer, the refusal (422 `not_health_concern`) and the failure path (the
case proceeds). Also unchanged: the red-flag checklist and screen, urgent routing at creation, which still runs
first, and the guidance prompt.

**Evidence** (`evidence/model-qualification/2026-10-21-concern-check-2/`, ADR-002 note of 2026-10-21):
- **Non-health refused:** 78 / 78 on both devices; before, the Nano refused 71 / 78 and the Fury 76 / 78.
- **Health refused:** 0 / 252 on both devices.
- **Held-out set:** 25 / 25 non-health refused and 0 / 32 health refused.
- **Re-qualification:** PASSED on both devices.

## Amendment 5 (2026-10-22): the concern check accepts medical abbreviations and symptom emoji, `concern-check-3` (#406)
**Finding (QA of `v0.14.0-demo.1`, C-05):** `concern-check-2` refused "ED" and "🤒" on both devices, against the
#154 gate of 0 wrong refusals.

**Decision by the maintainer, 2026-10-22:** a prompt change with re-qualification, keeping `concern-check-2`'s
refusals of non-health text.

**The change:** the concern check uses `concern-check-3`. Only the instructions changed: medical abbreviations ("ED",
"IBS") and emoji that show a symptom, a sore body part or feeling unwell ("🤒") count as health matters; emoji with no
health meaning do not.

**Evidence** (`evidence/model-qualification/2026-10-22-concern-check-3/`, ADR-002 note of 2026-10-22): on both devices
78/78 and 25/25 non-health texts refused and 0 of 284 health texts refused on `concern-check-2`'s sets, 0 of 81 added
abbreviation and emoji health texts refused (`concern-check-2` refused 18 on the Nano and 17 on the Fury, "ED" and
"🤒" among them) and 43/43 added non-health emoji and abbreviations refused. PASSED on both devices.
