"""M04 deterministic intake (R11-R14): serialized slot issuance and typed answers.

- A slot is allocated only when a new question is issued (1..10, unique per case).
- Refetch or same-key retry returns the active question without a new slot.
- Answers/edits never allocate slots; invalidated questions keep their slots.
- Mock mode issues the scenario's fixture templates verbatim, in order. No LLM.
- Local mode issues the reviewed pathway's approved templates (ADR-003) in its R12 order: urgency
  priority, then stable template ID. No LLM either.
Each answer is mirrored as a user-provenance Fact (source_id = question ID) so
review (A06) and guidance claims can reference the current answer.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.core import idempotency
from app.core.db import dumps, iso, utcnow
from app.core.errors import ApiError, state_conflict
from app.core.security import SessionInfo
from app.modules.cases import repository as cases_repo
from app.modules.intake import repository as repo
from app.modules.intake.schemas import AnswerWrite, DurationValue
from app.modules.operations.service import record_event
from app.modules.safety.service import MOCK_RULE_VERSION, is_urgent_fixture_trigger

MAX_SLOTS = 10
TYPE_MAP = {"single": "single_choice", "multi": "multiple_choice", "text": "text", "scale": "scale"}
DURATION_UNITS = ("hours", "days", "weeks", "months", "years")  # QuestionConstraints.allowed_units enum


def _template(ctx, template_id: str) -> dict[str, Any]:
    if ctx.settings.mode == "mock":
        return ctx.fixtures.questions[template_id]
    return ctx.pathway.questions[template_id]


def _pathway_version(ctx) -> str:
    return MOCK_RULE_VERSION if ctx.settings.mode == "mock" else ctx.pathway.version


def _choices(template: dict[str, Any]) -> list[dict[str, Any]]:
    exclusive = set(template.get("mutually_exclusive_seed_choice_ids", []))
    return [{"id": c["id"], "label": c["label"], "exclusive": c["id"] in exclusive}
            for c in template.get("choice_seed_ids", [])]


def _constraints(template: dict[str, Any]) -> dict[str, Any]:
    kind = template["response_type"]
    raw = template.get("constraints", {})
    anchors = raw.get("anchors", {})
    return {
        "minimum": raw.get("minimum") if kind == "scale" else None,
        "maximum": raw.get("maximum") if kind == "scale" else None,
        "min_selections": 1 if kind in {"single_choice", "multiple_choice"} else None,
        "max_selections": (1 if kind == "single_choice" else len(template.get("choice_seed_ids", []))
                           if kind == "multiple_choice" else None),
        "max_characters": raw.get("max_length", 2000) if kind == "text" else None,
        "lower_anchor": anchors.get(str(raw.get("minimum"))) if kind == "scale" else None,
        "upper_anchor": anchors.get(str(raw.get("maximum"))) if kind == "scale" else None,
        "allowed_units": _allowed_units(template) if kind == "duration" else [],
    }


def _allowed_units(template: dict[str, Any]) -> list[str]:
    """Units the issued duration question accepts: the template's list, else every contract unit."""
    units = template.get("constraints", {}).get("allowed_units")
    return [u for u in DURATION_UNITS if u in units] if units else list(DURATION_UNITS)


def question_public(ctx, row) -> dict[str, Any]:
    template = _template(ctx, row["template_id"])
    return {"id": row["id"], "case_id": row["case_id"], "slot": row["slot"], "template_id": row["template_id"],
            "pathway_version": row["pathway_version"], "issued_revision": row["issued_revision"],
            "response_type": template["response_type"], "text": template["text"], "choices": _choices(template),
            "required": bool(template.get("required", False)), "reason": template.get("why", ""),
            "constraints": _constraints(template), "status": row["status"]}


def _unresolved(conn, case_id: str) -> list[str]:
    rows = conn.execute("SELECT original_text FROM facts WHERE case_id=? AND active=1 AND provenance='user' "
                        "AND source_id IS NOT NULL AND value_json='null'", (case_id,)).fetchall()
    return [f"Not answered: {r['original_text']}"[:200] for r in rows]


def _remaining_templates(ctx, conn, case_row) -> list[str]:
    order = (ctx.fixtures.scenarios[case_row["scenario_id"]]["question_template_ids"] if ctx.settings.mode == "mock"
             else ctx.pathway.question_order)
    issued = {q["template_id"] for q in repo.questions(conn, case_row["id"])}
    return [t for t in order if t not in issued]


def next_question(ctx, session: SessionInfo, case_id: str, expected_revision: int, key: str) -> dict[str, Any]:
    req_hash = idempotency.request_hash(case_id, expected_revision)
    scope = f"actor:{session.actor_id}"
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, f"nextQuestion:{case_id}", key, req_hash)
        if replay:
            return _with_earlier(ctx, conn, replay.body)
        row = cases_repo.get_owned(conn, session.actor_id, case_id)
        cases_repo.check_revision(row, expected_revision)
        if row["state"] == "limited" and row["limited_reason"] == "generation_failed_recoverable":
            # Explicit recoverable retry: limited -> intake; answers are preserved.
            cases_repo.set_state(conn, case_id, "intake", limited_reason=None)
            row = cases_repo.get_owned(conn, session.actor_id, case_id)
        if row["state"] not in {"intake", "review"}:
            raise state_conflict(current_revision=row["revision"])
        active = repo.active_question(conn, case_id)
        if active is not None:
            result = {"kind": "question", "question": question_public(ctx, active), "case_revision": row["revision"]}
        elif row["issued_slots"] >= MAX_SLOTS or not _remaining_templates(ctx, conn, row):
            if row["state"] == "intake":
                cases_repo.set_state(conn, case_id, "review")
            result = {"kind": "review_required", "unresolved_gaps": _unresolved(conn, case_id),
                      "case_revision": row["revision"]}
        else:
            template_id = _remaining_templates(ctx, conn, row)[0]
            slot = row["issued_slots"] + 1
            question_id = str(uuid.uuid4())
            conn.execute("INSERT INTO questions (id, case_id, slot, template_id, pathway_version, issued_revision, "
                         "status) VALUES (?,?,?,?,?,?,'active')",
                         (question_id, case_id, slot, template_id, _pathway_version(ctx), row["revision"]))
            conn.execute("UPDATE cases SET issued_slots=?, updated_at=? WHERE id=?", (slot, iso(utcnow()), case_id))
            q = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
            result = {"kind": "question", "question": question_public(ctx, q), "case_revision": row["revision"]}
            record_event(conn, "question_issued", "active", operation_id="nextQuestion")
        idempotency.store(conn, scope, f"nextQuestion:{case_id}", key, req_hash, 200, result,
                          actor_id=session.actor_id, case_id=case_id)
        return _with_earlier(ctx, conn, result)


def _with_earlier(ctx, conn, result: dict[str, Any]) -> dict[str, Any]:
    """#357: a question response also carries the earlier issued questions of this case with their current answers,
    in slot order, so A05 can show "Previous question" with the saved answer filled in (also after a reload).

    Read fresh on every response, replays included, and never stored with the idempotency record, so no answer value
    is copied into another table. Invalidated prompts are left out (they took no answer). Changing one of these
    answers keeps every later question and answer: the issue order (fixture order in mock mode, the reviewed
    pathway's R12 order in local mode) does not depend on answers, so nothing later becomes obsolete.
    """
    if result.get("kind") != "question":
        return result
    current = result["question"]
    answers = repo.answers_by_question(conn, current["case_id"])
    earlier = [{"question": question_public(ctx, q), "answer": answers[q["id"]]}
               for q in repo.questions(conn, current["case_id"])
               if q["slot"] < current["slot"] and q["status"] in {"answered", "skipped"} and q["id"] in answers]
    return {**result, "earlier_questions": earlier}


def _validate(template: dict[str, Any], body: AnswerWrite) -> tuple[Any, Any]:
    """Return (stored typed value, fact display value) validated against the issued question."""
    if body.status == "unknown" and not template.get("unknown_allowed", False):
        raise _invalid("status", "unknown_not_allowed")
    if body.status == "skipped" and not template.get("skip_allowed", False):
        raise _invalid("status", "skip_not_allowed")
    if body.status != "answered":
        return None, None
    kind = template["response_type"]
    value = body.value
    choices = {c["id"]: c["label"] for c in template.get("choice_seed_ids", [])}
    if kind == "single_choice":
        if not isinstance(value, str) or value not in choices:
            raise _invalid("value", "unknown_choice")
        return value, choices[value]
    if kind == "multiple_choice":
        if not isinstance(value, list) or not value or len(set(value)) != len(value) or not set(value) <= set(choices):
            raise _invalid("value", "invalid_choices")
        exclusive = set(template.get("mutually_exclusive_seed_choice_ids", []))
        if set(value) & exclusive and len(value) > 1:
            raise _invalid("value", "exclusive_choice_combined")
        return value, [choices[v] for v in value]
    if kind == "text":
        if not isinstance(value, str):
            raise _invalid("value", "text_required")
        trimmed = value.strip()
        limit = template.get("constraints", {}).get("max_length", 2000)
        if not 1 <= len(trimmed) <= limit:
            raise _invalid("value", "text_length")
        return trimmed, trimmed
    if kind == "scale":
        raw = template.get("constraints", {})
        if isinstance(value, bool) or not isinstance(value, int) or not raw["minimum"] <= value <= raw["maximum"]:
            raise _invalid("value", "out_of_range")
        return value, value
    if kind == "duration":
        if not isinstance(value, DurationValue):
            raise _invalid("value", "duration_required")
        if value.unit not in _allowed_units(template):
            raise _invalid("value.unit", "unit_not_allowed")
        return value.model_dump(), f"{value.amount:g} {value.unit}"
    raise _invalid("value", "unsupported_type")


def _display_units(template: dict[str, Any], display: Any) -> str | None:
    """#215: a scale answer is stored with its range, so every reader shows "4 on a 0–10 scale" instead of a bare "4"
    (A06, A12 and the PDF already append a fact's units). Only the display: the local model reads the value alone."""
    if template["response_type"] != "scale" or display is None:
        return None
    raw = template.get("constraints", {})
    return f"on a {raw['minimum']}–{raw['maximum']} scale"


def _invalid(field: str, code: str) -> ApiError:
    return ApiError(422, "ANSWER_INVALID", "This answer does not match the question.",
                    field_errors=[{"field": field, "code": code, "message": "Check this answer."}])


def save_answer(ctx, session: SessionInfo, case_id: str, question_id: str, body: AnswerWrite) -> dict[str, Any]:
    with ctx.db.tx() as conn:
        row = cases_repo.get_owned(conn, session.actor_id, case_id)
        cases_repo.check_revision(row, body.expected_revision)
        if row["state"] not in {"intake", "review", "reviewed", "generating", "guided"}:
            raise state_conflict(current_revision=row["revision"])
        question = repo.owned_question(conn, case_id, question_id)
        if question["status"] == "invalidated":
            raise state_conflict("This question is no longer current.", current_revision=row["revision"])
        if row["state"] == "intake" and is_urgent_fixture_trigger(ctx.settings.mode, body.status, body.value):
            return _interrupt_urgent(conn, row, question)
        template = _template(ctx, question["template_id"])
        stored, display = _validate(template, body)
        now = iso(utcnow())
        revision = cases_repo.bump_clinical_revision(conn, row, "intake")
        conn.execute("INSERT INTO answers (id, case_id, question_id, status, value_json, revision, submitted_at) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET status=excluded.status, "
                     "value_json=excluded.value_json, revision=excluded.revision, submitted_at=excluded.submitted_at",
                     (str(uuid.uuid4()), case_id, question_id, body.status, dumps(stored), revision, now))
        conn.execute("UPDATE questions SET status=? WHERE id=?",
                     ("answered" if body.status == "answered" else "skipped", question_id))
        conn.execute("UPDATE facts SET active=0 WHERE case_id=? AND source_id=?", (case_id, question_id))
        conn.execute("INSERT INTO facts (id, case_id, kind, value_json, units, provenance, source_id, page, status, "
                     "original_text, confirmed_at) VALUES (?,?,?,?,?,'user',?,NULL,'confirmed',?,?)",
                     (str(uuid.uuid4()), case_id, f"answer:{question['template_id']}", dumps(display),
                      _display_units(template, display), question_id, template["text"], now))
        # R15 after an answer: Q01-Q10 carry no red-flag semantics (the reviewed checklist is answered with the
        # concern), and free text is not evaluated here; with general-adult-3, M08 screens the concern and every answer
        # for red flags before guidance (safety/screen.py). Mock mode also honors the explicit fixture trigger above.
        record_event(conn, "answer_saved", body.status, operation_id="saveAnswer")
        has_active = repo.active_question(conn, case_id) is not None
        next_action = "next_question" if (has_active or (
            row["issued_slots"] < MAX_SLOTS and _remaining_templates(ctx, conn, row))) else "review"
        return {"case_revision": revision, "next_action": next_action}


def _interrupt_urgent(conn, row, question) -> dict[str, Any]:
    """R15: explicit synthetic urgent signal at an answer interrupts intake before the next action.

    The prompt is invalidated but keeps its issued slot (R11); no answer value is stored.
    The case moves intake -> urgent with a new revision, which also invalidates any
    derived searches/exports. A restart requires a new case.
    """
    now = iso(utcnow())
    revision = cases_repo.bump_clinical_revision(conn, row, "urgent")
    conn.execute("UPDATE questions SET status='invalidated' WHERE id=?", (question["id"],))
    conn.execute("INSERT INTO facts (id, case_id, kind, value_json, units, provenance, source_id, page, status, "
                 "original_text, confirmed_at) VALUES (?,?,?,?,NULL,'user',NULL,NULL,'confirmed',?,?)",
                 (str(uuid.uuid4()), row["id"], "fixture:urgent_signal", dumps("Synthetic urgent signal selected"),
                  "Simulated urgent answer (synthetic demo fixture)", now))
    record_event(conn, "urgent_interrupt", "urgent", operation_id="saveAnswer")
    return {"case_revision": revision, "next_action": "urgent"}
