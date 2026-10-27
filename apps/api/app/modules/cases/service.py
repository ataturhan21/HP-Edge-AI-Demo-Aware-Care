"""M03 case lifecycle (R07-R10): creation, revisions, review confirmation, history.

Mock mode binds each patient-created case to the `routine` fixture scenario
(ADR-007). Typed concern text is stored but never evaluated to pick an outcome.
The structured red-flag checklist answer (ADR-003) is checked on creation and on
every context edit (R15): any ticked item routes the case to urgent.
In local mode (#153, ADR-003 amendment 3) the red-flag screen also reads the concern on creation and on a concern
edit, so a written emergency interrupts intake at once. The case records the reviewed level that routed it. #387: it
reads the profile free text (relevant history, current medications, reported allergies) with the concern, on creation
and on an edit that changes either.
Then (#154) a concern that describes no health matter at all is refused, so the person is asked to describe one.
#397: those model calls pass the central admission's screening lane (one at a time, three waiting, one per session;
429 QUEUE_FULL with Retry-After beyond), and a session holds at most MAX_OPEN_CASES consultations (409 CASE_LIMIT).
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import unicodedata
import uuid
from typing import Any

from app.core import idempotency
from app.core.db import dumps, iso, utcnow
from app.core.errors import ApiError, state_conflict
from app.core.security import SessionInfo
from app.modules.cases import concern_check
from app.modules.cases import repository as repo
from app.modules.cases.schemas import CaseEdit, CaseWrite, ConfirmedContextWrite, ReviewRequest
from app.modules.operations.service import record_event
from app.modules.providers.service import found_doctors
from app.modules.safety import screen as rf_screen
from app.modules.safety.service import RED_FLAGS_KIND, check_red_flags, initial_gate, red_flag_answer

DEFAULT_MOCK_SCENARIO = "routine"
EDITABLE_STATES = {"intake", "review", "reviewed", "generating", "guided"}
# #264: a case limited only because the warning-sign checklist was not answered can be corrected by editing it; the
# initial gate then runs again with the new answer (spec/engineering/02-state-and-intake.md: limited -> intake on
# corrected supported inputs). Every other limited reason stays final.
CORRECTABLE_LIMIT = "urgency_not_assessed"
URGENT_LEVELS = {"emergency", "urgent_clinician"}
# #275 (R36): the urgent-interrupt event names the cause only, never the person's urgency level.
DESCRIBED_EVENT_CODE = "RED_FLAG_DESCRIBED"
# #397: consultations one session can hold at once (deleted ones do not count). Bounds what a single guest session can
# store; far above a person's use (the History page lists 20 per page).
MAX_OPEN_CASES = 100


def editable(row) -> bool:
    return row["state"] in EDITABLE_STATES or (row["state"] == "limited" and row["limited_reason"] == CORRECTABLE_LIMIT)


def allowed_actions(row, guidance_level: str | None = None) -> list[str]:
    """`guidance_level` is the urgency level of the current guidance: doctor matching is not offered for an urgent
    level, because searchProviders refuses it (#269)."""
    state = row["state"]
    current_guidance = row["latest_guidance_id"] is not None
    actions: list[str] = []
    if state in EDITABLE_STATES:
        actions += ["edit", "save_answer"]
    if state == "intake":
        actions += ["upload_record", "next_question"]
    if state == "review":
        actions += ["confirm_review", "next_question"]
    if state == "reviewed" and row["reviewed_revision"] == row["revision"]:
        actions.append("generate_guidance")
    if state == "guided" and current_guidance:
        actions += ["view_guidance", "view_sources"]
        if guidance_level not in URGENT_LEVELS:
            actions.append("search_providers")
        actions += ["view_summary", "create_export"]
    if state == "urgent":
        actions.append("view_urgent")
    if state == "limited":
        if row["limited_reason"] == CORRECTABLE_LIMIT:
            actions.append("edit")
        actions.append("view_limits")
        if row["limited_reason"] == "generation_failed_recoverable":
            actions.append("retry")
    actions += ["view_history", "delete"]
    return actions


# #452: characters that render as nothing. Unicode's Default_Ignorable_Code_Point ranges (Python's unicodedata has no
# such property), which include the Hangul fillers U+115F, U+1160, U+3164 and U+FFA0, plus the Braille blank U+2800.
# A03 uses the same set (\p{Default_Ignorable_Code_Point} and U+2800).
INVISIBLE_RANGES = ((0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
                    (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x2800, 0x2800),
                    (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8),
                    (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))


def _invisible(ch: str) -> bool:
    if ch.isspace() or unicodedata.category(ch) in {"Cf", "Cc"}:
        return True
    code = ord(ch)
    return any(low <= code <= high for low, high in INVISIBLE_RANGES)


def meaningful(text: str) -> bool:
    """#305: a concern needs at least one visible character. Whitespace, invisible format characters (such as U+200B,
    U+2060 or U+FEFF) and control characters alone count as empty; #452: so do the other default-ignorable characters
    (such as U+00AD or U+180E) and the blank-looking Braille blank and Hangul fillers."""
    return any(not _invisible(ch) for ch in text)


def _clean_concern(raw: str, allow_empty: bool = False) -> str:
    """#392 (R15): with a reviewed warning sign ticked (`allow_empty`), a concern that was not written is stored empty,
    so the case goes to urgent help at once instead of asking for text first."""
    concern = raw.strip()
    if not meaningful(concern):
        if allow_empty:
            return ""
        raise ApiError(422, "VALIDATION_FAILED", "Describe one main concern to continue.",
                       field_errors=[{"field": "concern", "code": "empty", "message": "Required."}])
    return concern


ALLERGY_STATUSES = {"unknown", "none_reported", "reported"}
TEXT_KINDS = {"history", "medications", "allergies"}
# #433 (R04, R14): the server's own fact namespaces. Answer facts are written only by saveAnswer, fixture signals only
# by the A05 trigger or a scripted record, and record facts only by record extraction; a client context item in one of
# them would be counted as an answered question or a server signal, so it is refused.
RESERVED_KIND_PREFIXES = ("answer:", "fixture:", "record:")


def _context_error(field: str, code: str, message: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", message,
                    field_errors=[{"field": f"confirmed_context.{field}", "code": code, "message": message}])


def _normalize_context(items: list[ConfirmedContextWrite]) -> list[ConfirmedContextWrite]:
    """Server-side semantics for profile context (R04): unknown is never stored as a denial."""
    kinds = [i.kind for i in items]
    if any(k.startswith(RESERVED_KIND_PREFIXES) for k in kinds):
        raise _context_error("kind", "reserved", "Give profile details only; answers and record facts are added by "
                                                 "the questions and the record review.")
    if len(kinds) != len(set(kinds)):
        raise _context_error("kind", "duplicate", "Each detail can be given once.")
    by_kind = {i.kind: i for i in items}
    # null is an explicit unknown (R04) and is stored as such, never as zero or "none".
    if "age_years" in by_kind and by_kind["age_years"].value is not None:
        age = by_kind["age_years"].value
        # #262: a wrong type or a non-finite number is a field error, never a 500.
        if (isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or age != int(age)
                or not 18 <= age <= 130):
            raise _context_error("age_years", "out_of_range", "Age must be a whole number from 18 to 130.")
    for kind in TEXT_KINDS & by_kind.keys():
        value = by_kind[kind].value
        if value is None and kind != "allergies":
            continue
        if not isinstance(value, str) or not value.strip():
            raise _context_error(kind, "text_required", "Enter text or mark this detail unknown.")
    status = by_kind.get("allergy_status")
    if status is not None and (not isinstance(status.value, str) or status.value not in ALLERGY_STATUSES):
        raise _context_error("allergy_status", "invalid", "Choose an allergy option.")
    reported = status is not None and status.value == "reported"
    if reported != ("allergies" in by_kind):
        raise _context_error("allergies", "mismatch", "List allergies only when you report having them.")
    if status is None:
        # A skipped allergy question is persisted as explicit unknown, never as "no allergies".
        items = [*items, ConfirmedContextWrite(kind="allergy_status", value="unknown", units=None, origin="user",
                                               profile_revision=None)]
    return items


def _insert_context(conn, case_id: str, items: list[ConfirmedContextWrite]) -> None:
    now = iso(utcnow())
    for item in _normalize_context(items):
        if item.origin == "profile":
            # Guests have no saved profile; saved profiles need ADR-005 identity.
            raise ApiError(422, "VALIDATION_FAILED", "Profile-origin context requires a saved profile.",
                           field_errors=[{"field": "confirmed_context.origin", "code": "profile_unavailable",
                                          "message": "No saved profile is available in this session."}])
        conn.execute("INSERT INTO facts (id, case_id, kind, value_json, units, provenance, source_id, page, status, "
                     "original_text, confirmed_at) VALUES (?,?,?,?,?,?,NULL,NULL,'confirmed',NULL,?)",
                     (str(uuid.uuid4()), case_id, item.kind, dumps(item.value), item.units, item.origin, now))


def model_checks_concern(ctx) -> bool:
    """Whether a new or edited concern is read by the local model (#153 screen, #154 check): local mode with the
    reviewed pathway active. Mock mode never calls a model."""
    return ctx.settings.mode != "mock" and ctx.pathway is not None and ctx.pathway.active()


def count_refusal(ctx, exc: ApiError, operation: str) -> None:
    """A busy refusal (429) is counted content-free for the telemetry page (ADR-017), as for generateGuidance."""
    if exc.status == 429:
        with ctx.db.tx() as conn:
            record_event(conn, "admission_refused", "refused", operation_id=operation, error_code=exc.code)


def _replay(ctx, scope: str, operation: str, key: str, req_hash: str) -> tuple[int, dict[str, Any]] | None:
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, operation, key, req_hash)
    return (replay.status_code, replay.body) if replay else None


def _check_case_limit(conn, session: SessionInfo) -> None:
    open_cases = conn.execute("SELECT COUNT(*) FROM cases WHERE actor_id=? AND state NOT IN ('deleting','deleted')",
                              (session.actor_id,)).fetchone()[0]
    if open_cases >= MAX_OPEN_CASES:
        raise ApiError(409, "CASE_LIMIT", f"This session already holds {MAX_OPEN_CASES} consultations. Delete one in "
                                          "History, or end the session, to start another.")


def create_case(ctx, session: SessionInfo, body: CaseWrite, key: str, scenario_id: str | None = None
                ) -> tuple[int, dict[str, Any]]:
    try:
        return _create_case(ctx, session, body, key, scenario_id)
    except ApiError as exc:
        count_refusal(ctx, exc, "createCase")
        raise


def _create_case(ctx, session: SessionInfo, body: CaseWrite, key: str, scenario_id: str | None
                 ) -> tuple[int, dict[str, Any]]:
    flags = red_flag_answer(body.confirmed_context)
    if flags is not None:
        check_red_flags(flags, ctx.pathway)
    # #392 (R15): a ticked reviewed warning sign routes to urgent help whatever else is missing, so the concern may then
    # be empty. Without a ticked sign it is required as before.
    concern = _clean_concern(body.concern, allow_empty=bool(flags))
    _normalize_context(body.confirmed_context)  # #262: field errors before any model call
    req_hash = idempotency.request_hash(body.model_dump(mode="json"))
    scope = f"actor:{session.actor_id}"
    # #153: with "none of these apply" ticked, the concern itself is screened before the case exists (no ticked item
    # already routes to urgent help; an unanswered checklist limits the case). #387: with the profile free text.
    if flags != [] or not model_checks_concern(ctx):
        return _store_case(ctx, session, body, key, req_hash, concern, flags, scenario_id, [], None, None)
    # #397: a retry of a stored creation, a changed payload under a used key, and a session at its case limit are
    # answered before admission, without a model call.
    replay = _replay(ctx, scope, "createCase", key, req_hash)
    if replay:
        return replay
    with ctx.db.read() as conn:
        _check_case_limit(conn, session)
    with ctx.jobs.screening(session.actor_id, (scope, "createCase", key),
                            ctx.settings.concern_screen_timeout_seconds) as admitted:
        if not admitted:  # a duplicate that waited for the first request with this key: its response, replayed
            replay = _replay(ctx, scope, "createCase", key, req_hash)
            if replay:
                return replay
            raise ctx.jobs.busy()
        described, deferred = rf_screen.screen_concern(ctx, concern, body.confirmed_context)
        checked_deferred = _require_health_concern(ctx, concern, "createCase") if not described else None
        # Stored inside the lane, so a waiting duplicate finds the response when it is let go.
        return _store_case(ctx, session, body, key, req_hash, concern, flags, scenario_id, described, deferred,
                           checked_deferred)


def _store_case(ctx, session: SessionInfo, body: CaseWrite, key: str, req_hash: str, concern: str,
                flags: list[str] | None, scenario_id: str | None, described: list[str], deferred: str | None,
                checked_deferred: str | None) -> tuple[int, dict[str, Any]]:
    scope = f"actor:{session.actor_id}"
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, "createCase", key, req_hash)
        if replay:
            return replay.status_code, replay.body
        _check_case_limit(conn, session)
        scenario = scenario_id or DEFAULT_MOCK_SCENARIO
        gate = initial_gate(ctx.settings.mode, scenario, ctx.pathway, flags)
        level = rf_screen.ticked_level(ctx.pathway, flags) or (
            rf_screen.highest_level(ctx.pathway, described) if described else None)
        state = "urgent" if described else gate.state
        case_id = str(uuid.uuid4())
        now = iso(utcnow())
        rule_ids = flags or described  # #87: the IDs behind the urgent level, recorded with revision 1
        conn.execute("INSERT INTO cases (id, actor_id, revision, state, concern, scenario_id, limited_reason, "
                     "created_at, updated_at, urgent_level, urgent_rule_ids, urgent_revision) "
                     "VALUES (?,?,1,?,?,?,?,?,?,?,?,?)",
                     (case_id, session.actor_id, state, concern, scenario, gate.limited_reason, now, now, level,
                      dumps(sorted(rule_ids)) if level else None, 1 if level else None))
        _insert_context(conn, case_id, body.confirmed_context)
        row = repo.get_owned(conn, session.actor_id, case_id)
        payload = repo.case_public(conn, row, session.expires_at)
        idempotency.store(conn, scope, "createCase", key, req_hash, 201, payload,
                          actor_id=session.actor_id, case_id=case_id)
        record_event(conn, "case_created", state, operation_id="createCase")
        if flags:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="createCase")
        if described:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="createCase", error_code=DESCRIBED_EVENT_CODE)
        if deferred:
            record_event(conn, "concern_screen_deferred", "deferred", operation_id="createCase", error_code=deferred)
        if checked_deferred:
            record_event(conn, "concern_check_deferred", "deferred", operation_id="createCase",
                         error_code=checked_deferred)
    return 201, payload


def _require_health_concern(ctx, concern: str, operation: str) -> str | None:
    """#154: refuse a concern with no health matter (422, field `concern`); return a deferral code when the check
    could not run. Nothing is stored for a refused concern except a content-free event."""
    health, deferred = concern_check.check(ctx, concern)
    if not health:
        with ctx.db.tx() as conn:
            record_event(conn, "concern_not_health", "refused", operation_id=operation,
                         error_code="NOT_HEALTH_CONCERN")
        message = "Describe a health concern, for example a symptom and when it started."
        raise ApiError(422, "VALIDATION_FAILED", message,
                       field_errors=[{"field": "concern", "code": concern_check.NOT_HEALTH, "message": message}])
    return deferred


LIST_DEFAULT, LIST_MAX = 20, 50


def _encode_cursor(row) -> str:
    raw = json.dumps([row["created_at"], row["id"]], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        created_at, case_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(created_at, str) or not isinstance(case_id, str):
            raise ValueError
        return created_at, case_id
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise ApiError(422, "VALIDATION_FAILED", "The page link is not valid. Reload the list.",
                       field_errors=[{"field": "cursor", "code": "invalid", "message": "Invalid value."}]) from None


def list_cases(ctx, session: SessionInfo, limit: int = LIST_DEFAULT, cursor: str | None = None) -> dict[str, Any]:
    """#266: newest first, `limit` per page (default 20, at most 50), with a keyset cursor on (created_at, id) that
    reaches every owned case. The cursor holds no health content."""
    limit = max(1, min(limit, LIST_MAX))
    where, params = "", []
    if cursor:
        created_at, case_id = _decode_cursor(cursor)
        where, params = " AND (created_at < ? OR (created_at = ? AND id < ?))", [created_at, created_at, case_id]
    with ctx.db.read() as conn:
        rows = conn.execute("SELECT * FROM cases WHERE actor_id=? AND state NOT IN ('deleting','deleted')" + where
                            + " ORDER BY created_at DESC, id DESC LIMIT ?",
                            (session.actor_id, *params, limit + 1)).fetchall()
    page = rows[:limit]
    items = [{"id": r["id"], "revision": r["revision"], "state": r["state"], "created_at": r["created_at"],
              "updated_at": r["updated_at"], "expires_at": session.expires_at} for r in page]
    return {"items": items, "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None}


def read_case(ctx, session: SessionInfo, case_id: str) -> dict[str, Any]:
    with ctx.db.read() as conn:
        row = repo.get_owned(conn, session.actor_id, case_id)
        level = None
        if row["state"] == "guided" and row["latest_guidance_id"]:
            g = conn.execute("SELECT body_json FROM guidance WHERE id=?", (row["latest_guidance_id"],)).fetchone()
            level = json.loads(g["body_json"])["urgency"]["level"] if g else None
        read = {"case": repo.case_public(conn, row, session.expires_at), "allowed_actions": allowed_actions(row, level)}
        # #356: the doctors of the current search, so the summary preview shows what the PDF prints.
        doctors = found_doctors(ctx, conn, row)
        if doctors is not None:
            read["found_doctors"] = doctors
        return read


def _stored_profile(conn, case_id: str) -> list[dict[str, Any]]:
    """#387: the client context on the case now (never answers or record facts), for its profile free text."""
    rows = conn.execute("SELECT kind, value_json FROM facts WHERE case_id=? AND active=1 AND status='confirmed' "
                        "AND provenance IN ('user','profile') AND source_id IS NULL ORDER BY rowid",
                        (case_id,)).fetchall()
    return [{"kind": r["kind"], "value": json.loads(r["value_json"])} for r in rows]


def _stored_flags(conn, case_id: str) -> list[str] | None:
    row = conn.execute("SELECT value_json FROM facts WHERE case_id=? AND kind=? AND active=1 AND status='confirmed' "
                       "ORDER BY rowid DESC LIMIT 1", (case_id, RED_FLAGS_KIND)).fetchone()
    return None if row is None else json.loads(row["value_json"])


def _check_editable(row, expected_revision: int) -> None:
    repo.check_revision(row, expected_revision)
    if not editable(row):
        raise state_conflict(current_revision=row["revision"])


def edit_case(ctx, session: SessionInfo, case_id: str, body: CaseEdit) -> dict[str, Any]:
    try:
        return _edit_case(ctx, session, case_id, body)
    except ApiError as exc:
        count_refusal(ctx, exc, "editCase")
        raise


def _edit_case(ctx, session: SessionInfo, case_id: str, body: CaseEdit) -> dict[str, Any]:
    flags = red_flag_answer(body.confirmed_context) if body.confirmed_context is not None else None
    if flags is not None:
        check_red_flags(flags, ctx.pathway)
    new_concern = _clean_concern(body.concern) if body.concern is not None else None
    if body.confirmed_context is not None:
        _normalize_context(body.confirmed_context)  # #262: field errors before any model call
    # #273: revision and state are checked before any model call, so a stale or non-editable edit gets its 409
    # without costing a model call. They are checked again in the transaction below.
    with ctx.db.read() as conn:
        current = repo.get_owned(conn, session.actor_id, case_id)
        _check_editable(current, body.expected_revision)
        regate = current["state"] == "limited"  # #264: only the correctable limit gets here
        effective_flags = flags if flags is not None else _stored_flags(conn, case_id)
        stored_profile = _stored_profile(conn, case_id)
        # #411: a concern saved unchanged, with no other change, changes nothing: no new revision, the state, review and
        # derived results stay as they are.
        if body.confirmed_context is None and new_concern == current["concern"]:
            return repo.case_public(conn, current, session.expires_at)
    concern_after = new_concern if new_concern is not None else current["concern"]
    profile_after = body.confirmed_context if body.confirmed_context is not None else stored_profile
    # #153: a changed concern is screened again unless this edit ticks a red flag (already urgent). #264: a case that
    # was limited for the missing checklist had its concern never screened; with "none of these apply" now answered,
    # it is screened as at creation. #387: so is a changed profile free text, with the concern. Done before the
    # transaction so no lock is held during the model call.
    described, deferred, checked_deferred = [], None, None
    concern_changed = new_concern is not None and new_concern != current["concern"]
    profile_changed = rf_screen.profile_words(profile_after) != rf_screen.profile_words(stored_profile)
    screen_now = ((concern_changed or profile_changed) and not flags) or (regate and effective_flags == [])
    if screen_now and model_checks_concern(ctx):
        # #397: through the screening lane (429 QUEUE_FULL with Retry-After when it is full); nothing is changed then.
        with ctx.jobs.screening(session.actor_id, None, ctx.settings.concern_screen_timeout_seconds):
            described, deferred = rf_screen.screen_concern(ctx, concern_after, profile_after)
            if not described and (concern_changed or regate):
                checked_deferred = _require_health_concern(ctx, concern_after, "editCase")
    with ctx.db.tx() as conn:
        row = repo.get_owned(conn, session.actor_id, case_id)
        _check_editable(row, body.expected_revision)
        if new_concern is not None:
            conn.execute("UPDATE cases SET concern=? WHERE id=?", (new_concern, case_id))
        if body.confirmed_context is not None:
            # Replace profile context only: answer mirrors (source_id = question) and fixture signals stay, and so
            # does the red-flag answer unless this edit answers the checklist again.
            keep_flags = "" if flags is not None else f" AND kind != '{RED_FLAGS_KIND}'"
            conn.execute("UPDATE facts SET active=0 WHERE case_id=? AND provenance IN ('user','profile') "
                         "AND source_id IS NULL AND kind NOT LIKE 'answer:%' AND kind NOT LIKE 'fixture:%'"
                         + keep_flags, (case_id,))
            _insert_context(conn, case_id, body.confirmed_context)
        # R15: a newly ticked red flag, or one described in the new concern (#153), routes to urgent. Any in-flight
        # generation for the old revision becomes stale at commit time.
        limited_reason = row["limited_reason"]
        if flags or described:
            new_state = "urgent"
        elif row["state"] == "limited":
            # #264: the initial gate again, with the checklist answer as it stands after this edit.
            gate = initial_gate(ctx.settings.mode, row["scenario_id"], ctx.pathway, effective_flags)
            new_state, limited_reason = gate.state, gate.limited_reason
        else:
            new_state = "intake"
        revision = repo.bump_clinical_revision(conn, row, new_state)
        if limited_reason != row["limited_reason"]:
            conn.execute("UPDATE cases SET limited_reason=? WHERE id=?", (limited_reason, case_id))
        level = rf_screen.ticked_level(ctx.pathway, flags) or (
            rf_screen.highest_level(ctx.pathway, described) if described else None)
        if level:
            # #87: the IDs behind the level, with the new input revision.
            conn.execute("UPDATE cases SET urgent_level=?, urgent_rule_ids=?, urgent_revision=? WHERE id=?",
                         (level, dumps(sorted(flags or described)), revision, case_id))
        record_event(conn, "case_edited", new_state, operation_id="editCase")
        if flags:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="editCase")
        elif described:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="editCase", error_code=DESCRIBED_EVENT_CODE)
        if deferred:
            record_event(conn, "concern_screen_deferred", "deferred", operation_id="editCase", error_code=deferred)
        if checked_deferred:
            record_event(conn, "concern_check_deferred", "deferred", operation_id="editCase",
                         error_code=checked_deferred)
        return repo.case_public(conn, repo.get_owned(conn, session.actor_id, case_id), session.expires_at)


def confirm_review(ctx, session: SessionInfo, case_id: str, body: ReviewRequest) -> dict[str, Any]:
    with ctx.db.tx() as conn:
        row = repo.get_owned(conn, session.actor_id, case_id)
        repo.check_revision(row, body.expected_revision)
        if row["state"] != "review":
            raise state_conflict(current_revision=row["revision"])
        repo.set_state(conn, case_id, "reviewed", reviewed_revision=row["revision"])
        record_event(conn, "review_confirmed", "reviewed", operation_id="confirmReview")
        return repo.case_public(conn, repo.get_owned(conn, session.actor_id, case_id), session.expires_at)
