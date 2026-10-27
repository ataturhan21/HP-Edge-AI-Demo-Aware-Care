"""M08 structured guidance (R24-R27): queued job, adapter call, validation, atomic publish.

All model calls go through the runtime adapter. The candidate is validated
server-side and only published if the case is still generating at the same
reviewed revision and not deleted; otherwise the job is marked stale/cancelled.
No approved evidence corpus exists. Since ADR-015 (#105) possible explanations are published as `general_knowledge`
claims (the model's general medical knowledge, labelled as such), and every supported claim is a case-fact claim
with fact IDs.

- Mock mode: the labeled scripted fixture candidate (`guidance-mock-1`).
- Local mode: only while the reviewed pathway is active (ADR-003). The local path (`local.py`, prompt
  `local.PROMPT_VERSION`) runs with the pathway's urgency decision; a failure leaves the case limited with a retry and
  never falls back to mock or cloud output.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any

from app.core import idempotency
from app.core.db import dumps, iso, parse, utcnow
from app.core.errors import ApiError, not_found, state_conflict
from app.core.security import SessionInfo, effective_expiry
from app.modules.cases import repository as cases_repo
from app.modules.operations.service import create_job, finish_job, record_event
from app.modules.safety import screen as rf_screen
from app.modules.safety.service import (LIMITED_INFORMATION, MOCK_PATHWAY_ID, MOCK_RULE_VERSION, RED_FLAGS_KIND,
                                        apply_information_limits, urgency_decision)

# #391: the reason code of a self-care level raised to match the result's own next steps (local.published_level).
CLINICIAN_STEP_REASON = "CLINICIAN_NEXT_STEP_RAISED_LEVEL"
SESSION_ENDED = "SESSION_ENDED"  # #608: the job's error code when the session that started it ended
# #538: the event kind of each content-free rejection reason of a guidance job that failed closed
# (error_code "<attempt>:<rule>[/<category>][@<place>]"), counted per rule on the telemetry page and the monitoring
# report.
REJECTION_EVENT = "guidance_rejection"
PROMPT_VERSION = "guidance-mock-1"
CORPUS_VERSION = "none-no-approved-corpus"
URGENCY_LEVELS = {"routine_clinician", "self_care_candidate", "urgent_clinician", "emergency", "undetermined"}
ACTION_CATEGORIES = {"self_care", "seek_care", "discuss_with_clinician"}
# R25 (ADR-012): phrases that may signal unsupported certainty. A match is a tripwire, not a verdict: each flagged
# statement is adjudicated by the local model (certainty_review), and the draft is rejected unless every flagged
# statement is explicitly judged safe. Only the service's own statements are checked, not the person's questions.
# ADR-015 (#105): the limit every result discloses about its possible explanations.
GENERAL_KNOWLEDGE_LIMIT = ("Possible explanations come from general medical knowledge, not from reviewed sources: no "
                           "approved evidence corpus is loaded. They can be wrong and are not a diagnosis.")
# #456: the same limit in mock mode, where the possible explanation is a scripted fixture sentence (no model, no
# general medical knowledge), as A07 labels it on its card.
SCRIPTED_EXPLANATION_LIMIT = ("The possible explanation is scripted illustrative text for this synthetic demo, not from "
                              "an AI model or reviewed sources: no approved evidence corpus is loaded. It is not a "
                              "diagnosis.")
PROHIBITED = ("you have ", "diagnosis is", "guaranteed", "rule out", "definitely", "%")
# #85: a medication-change command carries none of the phrases above, so these send it to the same reviewer
# (category prescription_change). Mentions such as "bring a list of your medications" are reviewed and cleared.
# Not "switch to": the reviewer reads "switch to an anti-dandruff shampoo" as a prescription change (measured on the
# Nano), which would turn correct self-care answers into fallbacks; "switch your" and the drug words cover the rest.
MEDICATION_CHANGE = ("stop taking", "start taking", "keep taking", "stop your", "dose", "dosage", "come off",
                     "switch your", "double up", " mg", "your medication", "your tablets", "your pills",
                     "your prescription", "your inhaler", "painkiller", "antibiotic", "steroid")
# #407: dosing and change phrasings that carry none of the substrings above ("Stop any new medication immediately ...",
# "Stop the tablets ...", "Take two ibuprofen every six hours.", "Increase your amlodipine to twice a day.", "Halve your
# metformin."). Like every tripwire they only send a statement to the reviewer; everyday self-care such as "Apply a
# moisturizer twice daily" or "Reduce your screen time" does not trip.
_MED_NOUN = (r"(?:medications?|medicines?|meds|tablets?|pills?|capsules?|drugs?|doses?|dosage|prescriptions?|"
             r"inhalers?|insulin|ibuprofen|paracetamol|acetaminophen|aspirin|naproxen|antihistamines?|antacids?)")
MEDICATION_CHANGE_PATTERNS = (
    # a change verb with a medicine within a few words: "stop any new medication", "stop the tablets"
    re.compile(r"\b(?:stop|stopping|start|starting|restart|restarting|resume|resuming|increase|increasing|decrease|"
               r"decreasing|reduce|reducing|lower|lowering|raise|raising|halve|halving|double|doubling|cut|cutting|"
               r"skip|skipping|taper|tapering|discontinue|discontinuing|pause|pausing|adjust|adjusting|change|changing|"
               r"switch|switching|quit)\s+(?:(?:your|the|any|all|this|that|these|those|a|an|new|current|regular|"
               r"usual|daily|other|blood pressure|sleeping|pain)\s+){0,3}" + _MED_NOUN + r"\b"),
    # a dose change to a target: "increase your amlodipine to twice a day", "reduce the dose by half"
    re.compile(r"\b(?:increase|decrease|reduce|lower|raise|adjust|change|switch|move)\s+(?:your|the)\s+[\w-]+"
               r"(?:\s+[\w-]+)?\s+(?:to|by)\s+(?:\d|once|twice|three times|four times|half|a quarter)"),
    # halving, doubling or tapering what the person takes: "halve your metformin"
    re.compile(r"\b(?:halve|halving|taper|tapering|double|doubling)\s+(?:your|the|it|this|that|these|those)\b"),
    # an amount to take: "take two ibuprofen", "take 2 tablets", "have half a tablet"
    re.compile(r"\b(?:take|taking|use|using|have|having)\s+(?:\d+|one|two|three|four|five|six|half a|a|an)\s+"
               r"(?:[\w-]+\s+){0,2}?(?:tablets?|pills?|capsules?|doses?|puffs?|sachets?|ibuprofen|paracetamol|"
               r"acetaminophen|aspirin|naproxen)\b"),
    # a dosing interval: "every six hours", "every 4-6 hours"
    re.compile(r"\bevery\s+(?:\d+(?:\s*(?:-|to|–)\s*\d+)?|one|two|three|four|five|six|eight|twelve)\s+hours?\b"),
    # a frequency for something taken: "take it twice a day", "taken three times daily"
    re.compile(r"\b(?:take|taking|taken)\b[^.;]*\b(?:once|twice|three times|four times|\d+ times)\s+"
               r"(?:a|per|each|every)?\s*(?:day|daily)\b"),
)
# #407: a clause that itself instructs a medicine change or a dose ("Stop any new medication immediately if ...",
# "If you feel dizzy, stop the tablets.", "Halve your metformin.", "Take two ibuprofen every six hours.") is a
# medication change (rule 8, #85) whatever the condition attached to it. The reviewer reads conditional uses as safe
# (measured on the Nano: it cleared the first example 3 of 3 times), so the local path rejects such an instruction
# itself (local.check_draft, code `medication_change`) and repairs it once. "Do not stop your medication", "Keep
# taking your usual medicines as prescribed" and "Take paracetamol as directed on the packet" are not instructions to
# change.
_CLAUSE_LEAD = r"^(?:(?:please|immediately|then|also|now|you should|you can|you may|you could)\s+)?"
MEDICATION_INSTRUCTIONS = (
    # stopping, pausing or changing a medicine (starting an over-the-counter one is left to the reviewer, #85)
    re.compile(_CLAUSE_LEAD + r"(?:stop|restart|resume|increase|decrease|reduce|lower|raise|halve|double|cut|skip|"
               r"taper|discontinue|pause|adjust|change|switch|quit|come off)\s+(?:(?:taking|using)\s+)?(?:(?:your|"
               r"the|any|all|this|that|these|those|a|an|new|current|regular|usual|daily|other|blood pressure|sleeping|"
               r"pain)\s+){0,3}" + _MED_NOUN + r"\b"),
    # a dose change to a target, or halving, doubling or tapering: "increase your amlodipine to twice a day"
    re.compile(_CLAUSE_LEAD + r"(?:increase|decrease|reduce|lower|raise|adjust|change|switch|move)\s+(?:your|the)\s+"
               r"[\w-]+(?:\s+[\w-]+)?\s+(?:to|by)\s+(?:\d|once|twice|three times|four times|half|a quarter)"),
    re.compile(_CLAUSE_LEAD + r"(?:halve|taper|double)\s+(?:your|the|it|this|that|these|those)\b"),
    # a dose: "take two ibuprofen", "take 1000 mg of paracetamol"
    re.compile(_CLAUSE_LEAD + r"(?:take|use|have)\s+(?:\d+|one|two|three|four|five|six|half a)\s+(?:[\w-]+\s+){0,2}?"
               r"(?:tablets?|pills?|capsules?|doses?|puffs?|sachets?|ibuprofen|paracetamol|acetaminophen|aspirin|"
               r"naproxen|mg)\b"),
)
TRIPWIRES = PROHIBITED + MEDICATION_CHANGE
REVIEW_TASK, REVIEW_PROMPT_VERSION, REVIEW_SCHEMA = "certainty_review", "certainty-review-1", "CertaintyReview"
REVIEW_CATEGORIES = {"none", "definitive_diagnosis", "guaranteed_safety", "rules_out_risk", "prescription_change",
                     "numeric_diagnostic_confidence"}
REVIEW_INSTRUCTIONS = (
    "You check statements from a draft health-guidance summary for unsupported medical certainty. For each "
    "statement decide whether, in context, it actually asserts one of: a definitive diagnosis of the person "
    "(definitive_diagnosis); that something is safe or will be fine (guaranteed_safety); that a risk or condition, "
    "including an emergency, is ruled out (rules_out_risk); a prescription or medication change "
    "(prescription_change); a numeric probability or confidence about a diagnosis (numeric_diagnostic_confidence). "
    "A phrase such as 'rule out' or 'you have' is not unsafe by itself: hedged, conditional or referential uses "
    "(for example 'a clinician can check whether other causes should be ruled out' or 'you have mentioned "
    "headaches') are safe. Return only JSON: {\"verdicts\": [{\"index\": <statement index>, \"unsafe\": <true|false>, "
    "\"category\": <one of none, definitive_diagnosis, guaranteed_safety, rules_out_risk, prescription_change, "
    "numeric_diagnostic_confidence>}]}, exactly one verdict per statement, category none when not unsafe.")


def start_generation(ctx, session: SessionInfo, case_id: str, expected_revision: int, key: str) -> dict[str, Any]:
    try:
        return _start_generation(ctx, session, case_id, expected_revision, key)
    except ApiError as exc:
        if exc.status == 429:  # the busy refusal, counted content-free for the telemetry page (ADR-017)
            with ctx.db.tx() as conn:
                record_event(conn, "admission_refused", "refused", operation_id="generateGuidance",
                             error_code=exc.code)
        raise


def _start_generation(ctx, session: SessionInfo, case_id: str, expected_revision: int, key: str) -> dict[str, Any]:
    req_hash = idempotency.request_hash(case_id, expected_revision)
    scope = f"actor:{session.actor_id}"
    admitted = False
    try:
        with ctx.db.tx() as conn:
            replay = idempotency.lookup(conn, scope, f"generateGuidance:{case_id}", key, req_hash)
            if replay:
                return replay.body
            row = cases_repo.get_owned(conn, session.actor_id, case_id)
            cases_repo.check_revision(row, expected_revision)
            if row["state"] != "reviewed" or row["reviewed_revision"] != row["revision"]:
                raise state_conflict("Confirm the review of the current case before generating guidance.",
                                     current_revision=row["revision"])
            if ctx.settings.mode != "mock" and (ctx.pathway is None or not ctx.pathway.active()):
                raise ApiError(503, "SERVICE_LIMITED", "Guidance is unavailable: no reviewed pathway is enabled.")
            ctx.jobs.admit_generation()
            admitted = True
            attempt = row["generation_attempts"] + 1
            job = create_job(conn, actor_id=session.actor_id, case_id=case_id, kind="guidance",
                             input_revision=row["revision"], reviewed_revision=row["reviewed_revision"])
            cases_repo.set_state(conn, case_id, "generating", generation_attempts=attempt)
            idempotency.store(conn, scope, f"generateGuidance:{case_id}", key, req_hash, 202, job,
                              actor_id=session.actor_id, case_id=case_id)
            record_event(conn, "guidance_requested", "queued", operation_id="generateGuidance")
    except BaseException:
        if admitted:  # #263: the request failed after admission; its slot is given back
            ctx.jobs.release_generation()
        raise
    # #608: the job carries its authorizing session; when that session ends the work is invalidated (see _invalidated).
    snapshot = {"case_id": case_id, "actor_id": session.actor_id, "session_id": session.id,
                "input_revision": row["revision"],
                "reviewed_revision": row["reviewed_revision"], "scenario_id": row["scenario_id"], "attempt": attempt,
                "concern": row["concern"]}
    try:
        ctx.jobs.submit_generation(lambda queue_ms: _run(ctx, job["id"], snapshot, queue_ms))
    except Exception:
        # #263: no worker will run this job (submit_generation already gave its slot back). Undo the state change so
        # the case is not stuck generating, and drop the idempotent replay so a retry starts afresh.
        with ctx.db.tx() as conn:
            finish_job(conn, job["id"], "failed", error_code="SUBMIT_FAILED")
            conn.execute("UPDATE cases SET state='reviewed', generation_attempts=?, updated_at=? WHERE id=? AND "
                         "state='generating' AND revision=?", (attempt - 1, iso(utcnow()), case_id, row["revision"]))
            conn.execute("DELETE FROM idempotency WHERE scope=? AND operation=? AND key=?",
                         (scope, f"generateGuidance:{case_id}", key))
            record_event(conn, "guidance_submit_failed", "failed", operation_id="generateGuidance",
                         error_code="SUBMIT_FAILED")
        raise ApiError(503, "SERVICE_LIMITED", "Guidance could not be started. Try again.", retryable=True) from None
    return job


def _validate_candidate(candidate: Any) -> dict[str, Any]:
    """Strict candidate checks; raises ValueError on anything unpublishable."""
    if not isinstance(candidate, dict):
        raise ValueError("candidate")
    allowed = {"urgency_level", "reason_codes", "outcome_title", "action", "possible_explanation",
               "clinician_questions", "escalation_advice"}
    if set(candidate) != allowed:
        raise ValueError("fields")
    if candidate["urgency_level"] not in URGENCY_LEVELS:
        raise ValueError("urgency")
    action = candidate["action"]
    if not isinstance(action, dict) or action.get("category") not in ACTION_CATEGORIES:
        raise ValueError("action")
    for text in [*_statements(candidate), *candidate["clinician_questions"]]:
        if not isinstance(text, str) or not 0 < len(text) <= 1000:
            raise ValueError("text")
    return candidate


def _statements(candidate: dict[str, Any]) -> list[Any]:
    """The service's own published statements. Suggested clinician questions are the person's, not assertions."""
    action = candidate["action"]
    return [candidate["outcome_title"], candidate["possible_explanation"], action.get("text"), action.get("rationale"),
            *candidate["escalation_advice"]]


# #551: two uses of "you have" that assert nothing about the person, so they no longer send a statement to the
# reviewer (each review costs the Nano 1 to 1.5 s): the person's own report ("You reported that you have no urgent
# warning signs", the case-fact wording guidance-local-5 asks for) and the person's own questions or concerns ("write
# down any questions you have"). Measured on the Nano, the reviewer cleared every such statement; "you have" anywhere
# else still trips, also in the same statement.
_ATTRIBUTED_YOU_HAVE = re.compile(r"\b(?:(?:reported|said|mentioned|noted|indicated|told us|described) that |"
                                  r"(?:questions?|concerns?|worries) (?:that )?)you have\b")


def _tripwire_text(statement: str) -> str:
    """The statement in lower case with each attributed "you have" masked, same length (positions are kept)."""
    return _ATTRIBUTED_YOU_HAVE.sub(lambda m: m.group(0)[:-8] + "you_have", statement.lower())


def tripped(statement: str) -> bool:
    """Whether a statement contains an R25 tripwire phrase (ADR-012) or a #407 dosing or change phrasing."""
    text = _tripwire_text(statement)
    return any(p in text for p in TRIPWIRES) or any(r.search(text) for r in MEDICATION_CHANGE_PATTERNS)


_SPAN_WORDS = 6  # #538: a tripwire span is the matched phrase and the words after it, to the end of its clause


def tripwire_spans(statement: str) -> list[str]:
    """#538: where the R25 tripwires matched ("you have no urgent warning signs such"), lower case: from each match to
    at most six words, never past its clause, 80 characters at most. Like `medication_instruction_spans` these are the
    model's own words; they only go back to the same local model in the single repair (local.certainty_problems) and
    are never stored or logged."""
    text = _tripwire_text(statement)
    starts = {i for p in TRIPWIRES if p != "%" and (i := text.find(p)) >= 0}
    starts |= {m.start() for m in re.finditer(r"[\w.,]*\d[\w.,]*\s*%", text)}
    starts |= {m.start() for r in MEDICATION_CHANGE_PATTERNS for m in [r.search(text)] if m}
    spans, covered = [], -1
    for start in sorted(starts):
        if start < covered:
            continue  # inside the previous span ("stop taking your tablets" also matches "your tablets")
        clause = re.split(r"[,;:!?()]|\.(?:\s|$)", text[start:])[0]
        span = " ".join(clause.split()[:_SPAN_WORDS])[:80].strip()
        if span and span not in spans:
            spans.append(span)
            covered = start + text[start:].find(span) + len(span)
    return spans


def medication_instruction_spans(statement: str) -> list[str]:
    """#500: the words of each clause that instruct a medicine change or a dose ("stop any new medication"), lower
    case, as the patterns matched them. They are the model's own words and only ever go back to the same local model
    in the single repair (local.medication_change_problems)."""
    spans = []
    for sentence in re.split(r"(?<=[.!?])\s+", statement.lower()):
        for clause in re.split(r"[;,:]|\s+(?:and|then)\s+", sentence):
            m = next((m for p in MEDICATION_INSTRUCTIONS if (m := p.search(clause.strip()))), None)
            if m:
                spans.append(m.group(0).strip()[:80])
    return spans


def medication_instruction(statement: str) -> bool:
    """#407: whether a sentence or clause of the statement instructs a medicine change or a dose (see above)."""
    return bool(medication_instruction_spans(statement))


def flagged_statements(statements: list[str]) -> list[str]:
    """The statements that contain an R25 tripwire (ADR-012)."""
    return [t for t in statements if tripped(t)]


def review_snapshot(flagged: list[str]) -> dict[str, Any]:
    """Input for the certainty_review task: fixed instructions and the flagged statements only (no case content)."""
    return {"instructions": REVIEW_INSTRUCTIONS, "statements": [{"index": i, "text": t} for i, t in enumerate(flagged)]}


def accept_review(review: Any, count: int) -> None:
    """Raise ValueError unless the review clears every one of `count` statements explicitly (fail closed)."""
    verdicts = review.get("verdicts") if isinstance(review, dict) else None
    if not isinstance(verdicts, list) or len(verdicts) != count:
        raise ValueError("prohibited certainty: incomplete review")
    seen = set()
    for v in verdicts:
        if (not isinstance(v, dict) or not isinstance(v.get("index"), int) or isinstance(v.get("index"), bool)
                or v["index"] in seen or not 0 <= v["index"] < count or v.get("unsafe") is not False
                or v.get("category") != "none"):
            raise ValueError("prohibited certainty")  # unsafe, malformed, duplicate or out of range
        seen.add(v["index"])


def _certainty_review(ctx, candidate: dict[str, Any], timeout_s: float) -> int:
    """R25 tripwire plus local adjudication (ADR-012). Returns the number of flagged statements; raises ValueError
    unless every flagged statement is explicitly judged safe. Fails closed on any reviewer failure."""
    flagged = flagged_statements(_statements(candidate))
    if not flagged:
        return 0
    if timeout_s <= 0:
        raise ValueError("prohibited certainty: no time left for review")
    try:
        review = asyncio.run(ctx.runtime.generate_json(REVIEW_TASK, REVIEW_PROMPT_VERSION, review_snapshot(flagged),
                                                       REVIEW_SCHEMA, timeout_s))
    except Exception as exc:  # unavailable, timeout or invalid output: reject, never pass unreviewed text
        raise ValueError("prohibited certainty: review unavailable") from exc
    accept_review(review, len(flagged))
    return len(flagged)


def intake_answers(facts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(answered, not answered) intake questions. #268: only answer mirrors (kind `answer:*`) count; a confirmed or
    corrected record fact also has a source (its document) but is not an answered intake question, in either mode.
    #433: an answer mirror is the person's own answer with its question as source; createCase and editCase refuse the
    `answer:` kinds, and a fact without a question source is never counted."""
    answers = [f for f in facts if f["kind"].startswith("answer:") and f.get("source_id")
               and f.get("provenance") == "user"]
    return [f for f in answers if f["value"] is not None], [f for f in answers if f["value"] is None]


def _build(snapshot: dict[str, Any], candidate: dict[str, Any], facts: list[dict[str, Any]],
           unreviewed: int = 0) -> dict[str, Any]:
    case_id, revision = snapshot["case_id"], snapshot["input_revision"]
    now = iso(utcnow())
    answered, unknown = intake_answers(facts)
    candidate = apply_information_limits(candidate, len(answered), len(unknown))
    limited = LIMITED_INFORMATION in candidate["reason_codes"]
    claims: list[dict[str, Any]] = []
    if answered:
        claims.append({"id": str(uuid.uuid4()), "kind": "case_fact", "validation_status": "supported",
                       "text": f"You answered {len(answered)} intake question(s) in this synthetic demo.",
                       "fact_ids": [f["id"] for f in answered], "evidence_ids": []})
    # The contract's status for an unsourced clinical claim; the screens and the PDF label it scripted in mock mode
    # (#456: the guidance's model_manifest_id starts with "mock-").
    explanation = {"id": str(uuid.uuid4()), "kind": "clinical", "validation_status": "general_knowledge",
                   "text": candidate["possible_explanation"], "fact_ids": [], "evidence_ids": []}
    claims.append(explanation)
    action = candidate["action"]
    return {
        "id": str(uuid.uuid4()), "case_id": case_id, "input_revision": revision, "status": "complete",
        "case_summary": (f"Synthetic demo result: {candidate['outcome_title']}. Scripted fixture outcome, "
                         "not a medical assessment of your answers."),
        "urgency": {"case_id": case_id, "input_revision": revision, "level": candidate["urgency_level"],
                    "reason_codes": candidate["reason_codes"], "rule_version": MOCK_RULE_VERSION,
                    "pathway_id": MOCK_PATHWAY_ID, "decided_at": now},
        "possible_explanations": [explanation],
        "actions": [{"id": str(uuid.uuid4()), "text": action["text"], "category": action["category"],
                     "rationale": action["rationale"], "evidence_ids": [], "pathway_rule_id": None}],
        "clinician_questions": candidate["clinician_questions"],
        "escalation_advice": candidate["escalation_advice"],
        "uncertainties": ((["Limited information: some intake questions were not answered, so this result "
                            "is less specific and does not offer self-care reassurance."] if limited else [])
                          + [f"Not answered: {f['original_text']}" for f in unknown]
                          # R20: pending record review is surfaced, never silently accepted or used.
                          + ([f"{unreviewed} fact{'' if unreviewed == 1 else 's'} from your records "
                              f"{'was' if unreviewed == 1 else 'were'} not reviewed, so "
                              f"{'it was' if unreviewed == 1 else 'they were'} not used."] if unreviewed else [])
                          + [SCRIPTED_EXPLANATION_LIMIT,
                             "This outcome was selected by a synthetic demo scenario, not by analysing your answers."]),
        "claims": claims,
        "model_manifest_id": "mock-fixture-adapter-1",
        "corpus_version": CORPUS_VERSION,
        "created_at": now,
    }


CONTEXT_LABELS = {"age_years": "Age", "history": "Relevant history", "medications": "Current medications",
                  "allergy_status": "Allergies", "allergies": "Reported allergies"}


def local_facts(facts: list[dict[str, Any]], pathway) -> list[dict[str, Any]]:
    """The confirmed facts the model sees, with their IDs: answers by question text, context by label."""
    out = []
    for f in facts:
        if f["kind"] == RED_FLAGS_KIND:
            ticked = [pathway.red_flags[i]["text"] for i in f["value"] or [] if i in pathway.red_flags]
            out.append({"id": f["id"], "question": "Urgent warning signs checklist",
                        "answer": "; ".join(ticked) if ticked else "None of these apply"})
        elif f["kind"].startswith("answer:"):
            out.append({"id": f["id"], "question": f["original_text"], "answer": f["value"]})
        elif f["provenance"] in {"user", "profile"} and not f["kind"].startswith("fixture:"):
            out.append({"id": f["id"], "question": CONTEXT_LABELS.get(f["kind"], f["kind"]), "answer": f["value"]})
        elif f["provenance"] == "document":
            out.append({"id": f["id"], "question": f["original_text"] or f["kind"], "answer": f["value"]})
    return out


def _run_local(ctx, snapshot: dict[str, Any], facts: list[dict[str, Any]], unreviewed: int,
               started: float) -> tuple[dict[str, Any], float, float]:
    """The qualified local path with the reviewed pathway's decision (ADR-002, ADR-003). Raises on any failure."""
    from app.modules.guidance import local  # local.py imports this module's ADR-012 helpers

    pathway = ctx.pathway
    if pathway is None or not pathway.active():
        raise ApiError(503, "SERVICE_LIMITED", "No reviewed pathway is enabled.")
    if pathway.red_flag_screen:
        # ADR-003 amendment 2: a red flag described in the person's own words stops guidance (fails closed).
        remaining = ctx.settings.generation_deadline_seconds - (time.perf_counter() - started)
        matched = asyncio.run(rf_screen.screen(ctx.runtime, pathway,
                                               rf_screen.person_words(snapshot["concern"], facts), remaining))
        if matched:
            raise rf_screen.RedFlagDescribed(matched, rf_screen.highest_level(pathway, matched))
    answered, unknown = intake_answers(facts)
    decision = urgency_decision(pathway, len(answered), len(unknown))
    inputs = local.LocalInputs(case_id=snapshot["case_id"], input_revision=snapshot["input_revision"],
                               concern=snapshot["concern"], facts=local_facts(facts, pathway), decision=decision)
    manifest_id = asyncio.run(ctx.runtime.manifest()).get("manifest_id")
    if not manifest_id:
        raise ApiError(503, "MODEL_UNAVAILABLE", "The model manifest is missing.")
    remaining = ctx.settings.generation_deadline_seconds - (time.perf_counter() - started)
    t0 = time.perf_counter()
    result = asyncio.run(local.generate(ctx.runtime, inputs, remaining))
    inference_ms = sum(a["seconds"] for a in result.attempts) * 1000
    guidance_repaired = len(result.attempts) > 1  # the single repair was needed (telemetry, ADR-017)
    limited = LIMITED_INFORMATION in decision["reason_codes"]
    service_uncertainties = (
        (["Limited information: some intake questions were not answered, so this result does not offer "
          "self-care reassurance."] if limited else [])
        + [f"Not answered: {f['original_text']}" for f in unknown]
        + ([f"{unreviewed} fact{'' if unreviewed == 1 else 's'} from your records "
            f"{'was' if unreviewed == 1 else 'were'} not reviewed, so {'it was' if unreviewed == 1 else 'they were'} "
            "not used."] if unreviewed else [])
        + [GENERAL_KNOWLEDGE_LIMIT])
    # #448: the case's allergy status (a case without one has it unknown) decides which allergy limits may stand.
    allergy_status = next((f["value"] for f in facts if f["kind"] == "allergy_status"
                           and f["provenance"] in {"user", "profile"}), None) or "unknown"
    guidance = local.to_guidance(inputs, result.draft, manifest_id=manifest_id, created_at=iso(utcnow()),
                                 service_uncertainties=service_uncertainties, allergy_status=allergy_status)
    validation_ms = max(0.0, (time.perf_counter() - t0) * 1000 - inference_ms)
    return guidance, inference_ms, validation_ms, guidance_repaired


def session_ended(conn, session_id: str) -> bool:
    """#608: whether a session has ended: revoked (logout, expiry noticed by a request or the sweep, a presenter
    reset), past the earlier of its idle and absolute expiry although nothing noticed yet, or its actor is being
    deleted. Its access ended at that moment, so work it authorized must not publish while the sweep is pending."""
    row = conn.execute("SELECT s.revoked, s.last_seen_at, s.absolute_expires_at, a.deleting FROM sessions s "
                       "JOIN actors a ON a.id = s.actor_id WHERE s.id=?", (session_id,)).fetchone()
    return (row is None or bool(row["revoked"]) or bool(row["deleting"])
            or utcnow() >= parse(effective_expiry(row["last_seen_at"], row["absolute_expires_at"])))


def _invalidated(conn, snapshot: dict[str, Any]) -> tuple[str, str] | None:
    """Why a guidance job may neither start nor publish (R27): (job status, error code), or None while its case is
    owned, not deleted and still generating the reviewed revision the job froze, and its session has not ended
    (#608: actor/session expiry is an invalidation cause, spec/engineering/04-runtime-and-evidence.md)."""
    row = conn.execute("SELECT state, revision, reviewed_revision FROM cases WHERE id=? AND actor_id=?",
                       (snapshot["case_id"], snapshot["actor_id"])).fetchone()
    if row is None or row["state"] in {"deleting", "deleted"}:
        return "cancelled", "CASE_DELETED"
    if session_ended(conn, snapshot["session_id"]):
        return "cancelled", SESSION_ENDED
    if (row["state"] != "generating" or row["revision"] != snapshot["input_revision"]
            or row["reviewed_revision"] != snapshot["reviewed_revision"]):
        return "stale", "REVISION_CHANGED"
    return None


def _run(ctx, job_id: str, snapshot: dict[str, Any], queue_ms: float) -> None:
    started = time.perf_counter()
    case_id = snapshot["case_id"]
    with ctx.db.tx() as conn:
        # #607: a job only starts while it is still queued and its case is live and current. Deletion (of the case, of
        # all data, or of an expired guest by the sweep) cancels queued jobs, but the worker already held the queued
        # snapshot: it now ends here, before any model call reads the concern of a purged case.
        invalid = _invalidated(conn, snapshot)
        if invalid:
            finish_job(conn, job_id, invalid[0], error_code=invalid[1],
                       timings={"queue_ms": queue_ms, "total_ms": queue_ms})
            return
        if conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
                        (iso(utcnow()), job_id)).rowcount != 1:
            return  # cancelled while it waited
        facts = cases_repo.facts(conn, case_id)
        unreviewed = conn.execute("SELECT COUNT(*) FROM facts WHERE case_id=? AND active=1 AND provenance='document' "
                                  "AND status='unconfirmed'", (case_id,)).fetchone()[0]
    error_code, guidance, urgent_level, urgent_ids, repaired = None, None, None, None, False
    error_detail: list[str] | None = None
    inference_ms = validation_ms = None
    try:
        if ctx.settings.mode == "mock":
            t0 = time.perf_counter()
            candidate = asyncio.run(ctx.runtime.generate_json(
                "guidance", PROMPT_VERSION, snapshot, "GuidanceCandidate", ctx.settings.generation_deadline_seconds))
            inference_ms = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            candidate = _validate_candidate(candidate)
            remaining = ctx.settings.generation_deadline_seconds - (time.perf_counter() - started)
            _certainty_review(ctx, candidate, remaining)
            guidance = _build(snapshot, candidate, facts, unreviewed)
            validation_ms = (time.perf_counter() - t1) * 1000
        else:
            guidance, inference_ms, validation_ms, repaired = _run_local(ctx, snapshot, facts, unreviewed, started)
    except rf_screen.RedFlagDescribed as described:
        urgent_level, urgent_ids = described.level, described.ids
        error_code = f"RED_FLAG_DESCRIBED_{urgent_level.upper()}"  # the job tells the owner's browser where to route
    except ValueError:
        error_code = "OUTPUT_VALIDATION_FAILED"
    except Exception as exc:  # typed adapter and local-path errors carry a sanitized code
        error_code = getattr(exc, "code", "GENERATION_FAILED")
        if isinstance(exc, rf_screen.ScreenFailed):
            error_detail = exc.detail  # #550: why the screen before the draft failed, e.g. its `{}` answer
        elif isinstance(getattr(exc, "attempts", None), list):
            # #538: the local path's content-free rejection reasons (rule codes and places, never text), so a
            # "guidance unavailable" can be diagnosed from the job, the telemetry page and the monitoring report.
            from app.modules.guidance.local import rejection_detail
            error_detail = rejection_detail(exc.attempts) or None
    timings = {"queue_ms": queue_ms, "inference_ms": inference_ms, "validation_ms": validation_ms,
               "total_ms": queue_ms + (time.perf_counter() - started) * 1000}
    with ctx.db.tx() as conn:
        # Every publication guard is rechecked at commit (R27): owner, tombstone, state, revision, review.
        invalid = _invalidated(conn, snapshot)
        if invalid:
            finish_job(conn, job_id, invalid[0], error_code=invalid[1], timings=timings)
            return
        if urgent_level:
            # The red flag the person described routes the case like a ticked box: urgent help, no routine work.
            # #87 (T-R15-S02): the matched approved IDs and the input revision they were matched at.
            cases_repo.set_state(conn, case_id, "urgent", urgent_level=urgent_level,
                                 urgent_rule_ids=dumps(sorted(urgent_ids)), urgent_revision=snapshot["input_revision"])
            finish_job(conn, job_id, "failed", error_code=error_code, timings=timings)
            # #275 (R36): the content-free event names the cause, never the level.
            record_event(conn, "urgent_interrupt", "urgent", operation_id="generateGuidance",
                         error_code="RED_FLAG_DESCRIBED")
            return
        if guidance is None:
            cases_repo.set_state(conn, case_id, "limited", limited_reason="generation_failed_recoverable")
            finish_job(conn, job_id, "failed", error_code=error_code, timings=timings, error_detail=error_detail)
            record_event(conn, "guidance_failed", "failed", operation_id="generateGuidance", error_code=error_code)
            for item in error_detail or []:  # #538: one content-free event per rejection, counted by rule
                record_event(conn, REJECTION_EVENT, "failed", operation_id="generateGuidance", error_code=item)
            return
        conn.execute("INSERT INTO guidance (id, case_id, input_revision, body_json, created_at) VALUES (?,?,?,?,?)",
                     (guidance["id"], case_id, snapshot["input_revision"], dumps(guidance), guidance["created_at"]))
        cases_repo.set_state(conn, case_id, "guided", latest_guidance_id=guidance["id"])
        finish_job(conn, job_id, "succeeded", result_id=guidance["id"], result_type="guidance", timings=timings)
        record_event(conn, "guidance_published", "succeeded", operation_id="generateGuidance",
                     duration_ms=timings["total_ms"])
        if repaired:
            record_event(conn, "guidance_repaired", "succeeded", operation_id="generateGuidance")
        if CLINICIAN_STEP_REASON in guidance["urgency"]["reason_codes"]:
            # #391: content-free record that the self-care level was raised to match the result's own next steps.
            record_event(conn, "guidance_level_raised", "succeeded", operation_id="generateGuidance",
                         error_code=CLINICIAN_STEP_REASON)


def current_guidance(conn, session: SessionInfo, case_id: str) -> tuple[Any, dict[str, Any]]:
    row = cases_repo.get_owned(conn, session.actor_id, case_id)
    if row["state"] != "guided" or row["latest_guidance_id"] is None:
        raise state_conflict("No current guidance for this case version.", current_revision=row["revision"])
    g = conn.execute("SELECT * FROM guidance WHERE id=? AND case_id=? AND input_revision=?",
                     (row["latest_guidance_id"], case_id, row["revision"])).fetchone()
    if g is None:
        raise not_found()
    return row, json.loads(g["body_json"])


def readable_guidance(conn, session: SessionInfo, case_id: str) -> dict[str, Any]:
    """The current guidance for getGuidance and getCaseSources: 404 when guidance was never generated for this case
    (#269), 409 when it exists but is not current (the case changed, or a new attempt is running)."""
    cases_repo.get_owned(conn, session.actor_id, case_id)
    if conn.execute("SELECT 1 FROM guidance WHERE case_id=? LIMIT 1", (case_id,)).fetchone() is None:
        raise not_found()
    return current_guidance(conn, session, case_id)[1]


def get_guidance(ctx, session: SessionInfo, case_id: str) -> dict[str, Any]:
    with ctx.db.read() as conn:
        return readable_guidance(conn, session, case_id)
