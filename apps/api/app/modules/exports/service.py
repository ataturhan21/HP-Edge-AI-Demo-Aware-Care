"""M10 reviewed summary export (R32-R33): explicit review, owned expiring PDF.

The PDF contains reported/confirmed facts, unresolved gaps, guidance labels, the
published suggested level of care, the doctors of the current search (#356) and
timestamps; no diagnosis. Bytes live under an opaque key in the restricted data
directory and are served only by the authorized download endpoint, rechecking
owner, revision, expiry and tombstone at stream time. TTL is 15 minutes.

#417: the A12 preview (apps/web/src/screens/A12.tsx) shows every section printed here, under the same titles (the
text before a heading's parenthesis), from the same server data, so the person reviews what the PDF contains.
"""
from __future__ import annotations

import uuid
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

from app.core import idempotency
from app.core.db import iso, parse, utcnow
from app.core.errors import ApiError, not_found, state_conflict
from app.core.security import SessionInfo
from app.modules.cases import repository as cases_repo
from app.modules.exports import pdf
from app.modules.guidance.service import current_guidance
from app.modules.operations.service import create_job, finish_job, record_event
from app.modules.providers.service import found_doctors

EXPORT_TTL = timedelta(minutes=15)
# #397: summaries one session can request within one export lifetime (15 minutes); each is a PDF file on disk until
# it expires. Past that the request is refused with 429 EXPORT_LIMIT and a Retry-After of when the oldest ages out.
MAX_EXPORTS_PER_TTL = 10
# #395: an answer is labelled by its question (its original_text); every other fact by its kind, in A06's words
# (apps/web/src/screens/A06.tsx, LABELS). A record fact's original_text is the record's extracted source text, kept
# unchanged when the person corrects the value, so it is never a label.
CONTEXT_LABELS = {"age_years": "Age", "history": "Relevant history", "medications": "Current medications",
                  "allergy_status": "Allergies", "allergies": "Reported allergies",
                  "red_flags": "Urgent warning signs checklist",
                  "record:medications": "Medications (from a record you confirmed)",
                  "record:allergies": "Allergies (from a record you confirmed)",
                  "record:lab_result": "Test result (from a record you confirmed)"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# #456: in mock mode the possible explanation is a scripted fixture sentence, never general medical knowledge.
EXPLANATIONS_HEADING = {True: "Possible explanations (scripted illustrative text, not from an AI model or reviewed "
                              "sources; not a diagnosis)",
                        False: "Possible explanations (general medical knowledge, not from reviewed sources; not a "
                               "diagnosis)"}
SOURCES_NOTE = {True: "No approved evidence sources are loaded; the possible explanation is scripted illustrative "
                      "text for this synthetic demo, not from an AI model.",
                False: "No approved evidence sources are loaded; possible explanations come from general medical "
                       "knowledge."}
# #356: the suggested level of care in the same words as A07 (apps/web/src/screens/A07.tsx, URGENCY).
LEVEL_LABELS = {"emergency": "Emergency care", "urgent_clinician": "See a clinician urgently",
                "routine_clinician": "Routine clinician visit",
                "self_care_candidate": "Self-care with monitoring (illustrative)", "undetermined": "Not determined"}


def export_dir(ctx) -> Path:
    path = ctx.settings.data_dir / "exports"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def request_export(ctx, session: SessionInfo, case_id: str, expected_revision: int, key: str) -> dict[str, Any]:
    req_hash = idempotency.request_hash(case_id, expected_revision)
    scope = f"actor:{session.actor_id}"
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, f"createExport:{case_id}", key, req_hash)
        if replay:
            return replay.body
        row = cases_repo.get_owned(conn, session.actor_id, case_id)
        cases_repo.check_revision(row, expected_revision)
        row, guidance = current_guidance(conn, session, case_id)
        _check_export_limit(conn, session)
        job = create_job(conn, actor_id=session.actor_id, case_id=case_id, kind="export",
                         input_revision=row["revision"])
        idempotency.store(conn, scope, f"createExport:{case_id}", key, req_hash, 202, job,
                          actor_id=session.actor_id, case_id=case_id)
        facts = cases_repo.facts(conn, case_id)
        concern = row["concern"]
        doctors = found_doctors(ctx, conn, row)  # #356: the same doctors the A12 preview shows (getCase)
    try:
        ctx.jobs.submit(lambda: _build(ctx, job["id"], session.actor_id, case_id, row["revision"], guidance, facts,
                                       concern, doctors))
    except Exception:
        # #263: no worker will build it; the job fails visibly and a retry with a new key starts afresh.
        with ctx.db.tx() as conn:
            finish_job(conn, job["id"], "failed", error_code="SUBMIT_FAILED")
            conn.execute("DELETE FROM idempotency WHERE scope=? AND operation=? AND key=?",
                         (scope, f"createExport:{case_id}", key))
        raise ApiError(503, "SERVICE_LIMITED", "The summary could not be started. Try again.", retryable=True) from None
    return job


def _check_export_limit(conn, session: SessionInfo) -> None:
    since = utcnow() - EXPORT_TTL
    recent = [parse(r["created_at"]) for r in conn.execute(
        "SELECT created_at FROM jobs WHERE actor_id=? AND kind='export' AND created_at >= ? ORDER BY created_at",
        (session.actor_id, iso(since))).fetchall()]
    if len(recent) >= MAX_EXPORTS_PER_TTL:
        wait = max(1, int((recent[-MAX_EXPORTS_PER_TTL] - since).total_seconds()) + 1)
        raise ApiError(429, "EXPORT_LIMIT", f"Up to {MAX_EXPORTS_PER_TTL} summaries can be created in 15 minutes. Use "
                                            "the latest one, or try again later.", retryable=True,
                       headers={"Retry-After": str(wait)})


def fact_label(fact: dict[str, Any]) -> str:
    """#395: the label a confirmed fact is printed under, as A06 and the A12 preview show it."""
    if fact["kind"].startswith("answer:"):
        return fact["original_text"] or fact["kind"]
    return CONTEXT_LABELS.get(fact["kind"], fact["kind"])


def generated_at(created: str) -> str:
    """#459: the product's date and time style (#347), in UTC: "22 Oct 2026, 03:13 UTC"."""
    t = parse(created).astimezone(UTC)
    return f"{t.day} {MONTHS[t.month - 1]} {t.year}, {t:%H:%M} UTC"


def _lines(concern: str, facts: list[dict[str, Any]], guidance: dict[str, Any], created: str,
           doctors: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    def show(value: Any) -> str:
        if value is None:
            return "Not answered / unknown"
        if isinstance(value, list) and not value:
            return "None"
        if value in ("unknown", "none_reported", "reported"):
            return {"unknown": "Unknown", "none_reported": "None reported", "reported": "Reported"}[value]
        return ", ".join(value) if isinstance(value, list) else str(value)

    def fact_value(fact: dict[str, Any]) -> str:
        units = f" {fact['units']}" if fact["units"] and fact["value"] is not None else ""
        reference = fact.get("reference_range")
        if fact["kind"] != "record:lab_result" and reference is None:
            return f"{show(fact['value'])}{units}"
        # #395: a test result keeps its printed unit and reference range, or says they were not readable (as A06).
        unreadable = " (unit not readable)" if fact["units"] is None and fact["value"] is not None else ""
        return f"{show(fact['value'])}{units}{unreadable}; reference range {reference or 'not readable'}"

    mock = guidance["model_manifest_id"].startswith("mock-")
    lines: list[tuple[str, str]] = [
        ("h1", "Aware Care - appointment preparation summary"),
        ("p", "SYNTHETIC DEMO DOCUMENT. Not a diagnosis, referral, prescription or appointment."),
        ("p", f"Generated {generated_at(created)}. Case version {guidance['input_revision']}. "
              + ("AI-assisted content is labeled; mock mode used scripted synthetic fixtures." if mock else
                 "Guidance was generated on this device by an AI model and can contain mistakes.")),
        ("h2", "Main concern (as you described it)"), ("p", concern),
        ("h2", "What you reported"),
    ]
    for fact in facts:
        label = fact_label(fact)
        if fact["kind"] == "red_flags":
            lines.append(("p", f"- {label}: {'Some apply' if fact['value'] else 'None of these apply'}"))
            continue
        lines.append(("p", f"- {label}: {fact_value(fact)}"))
    lines += [("h2", "Unresolved or unknown details")]
    lines += [("p", f"- {u}") for u in guidance["uncertainties"]] or [("p", "- None recorded")]
    level = (guidance.get("urgency") or {}).get("level")
    if level in LEVEL_LABELS:  # #356: only the published guidance's level; never one made up here
        lines += [("h2", "Suggested level of care (synthetic scripted outcome)" if mock else
                   "Suggested level of care (AI-generated, check with a clinician)"), ("p", LEVEL_LABELS[level])]
    lines += [("h2", "Suggested next step (synthetic scripted outcome)" if mock else
               "Suggested next steps (AI-generated, check with a clinician)")]
    lines += [("p", f"- {a['text']}") for a in guidance["actions"]]
    # ADR-015 (#105): possible explanations are shown with their origin; a suppressed claim never appears.
    shown = [c for c in guidance["possible_explanations"] if c["validation_status"] in ("supported", "general_knowledge")]
    if shown:
        lines += [("h2", EXPLANATIONS_HEADING[mock])]
        lines += [("p", f"- {c['text']}") for c in shown]
    lines += [("h2", "Questions for a clinician")]
    lines += [("p", f"- {q}") for q in guidance["clinician_questions"]]
    lines += [("h2", "When to seek help sooner")]
    lines += [("p", f"- {e}") for e in guidance["escalation_advice"]]
    if doctors and doctors["doctors"]:
        # #356: at most the first three eligible matches of the latest search, with the facts A10 showed.
        lines += [("h2", "Doctors you found (fictional doctors from a synthetic directory)"),
                  ("p", "Fictional doctors only. Nothing was booked or sent; availability and credentials are unknown.")]
        for d in doctors["doctors"]:
            where = f" · {d['distance_miles']} mi (fictional)" if d["distance_miles"] is not None else ""
            lines.append(("p", f"- {d['name']} · {', '.join(d['specialties'])} · {d['practice']}{where}"))
            lines += [("p", f"  Confirmed: {fact}") for fact in d["confirmed_matches"]]
    lines += [("h2", "Sources"), ("p", SOURCES_NOTE[mock])]
    lines += [("p", "A downloaded copy is outside Aware Care's server deletion controls.")]
    return lines


def _build(ctx, job_id: str, actor_id: str, case_id: str, revision: int, guidance: dict[str, Any],
           facts: list[dict[str, Any]], concern: str, doctors: dict[str, Any] | None = None) -> None:
    try:
        _render_and_publish(ctx, job_id, actor_id, case_id, revision, guidance, facts, concern, doctors)
    except Exception:
        with ctx.db.tx() as conn:  # a failed build never leaves the job queued
            finish_job(conn, job_id, "failed", error_code="EXPORT_FAILED")


def _render_and_publish(ctx, job_id: str, actor_id: str, case_id: str, revision: int, guidance: dict[str, Any],
                        facts: list[dict[str, Any]], concern: str, doctors: dict[str, Any] | None = None) -> None:
    now = utcnow()
    data = pdf.render(_lines(concern, facts, guidance, iso(now), doctors))
    storage_key = uuid.uuid4().hex
    target = export_dir(ctx) / storage_key
    # #592: the PDF is written before its export row commits. Until that commit no row points to it, so a case
    # deletion (which finds export files through their rows) cannot remove it: a publication that fails on the way
    # (a partial write, a failed INSERT or COMMIT) removes the file itself.
    try:
        target.write_bytes(data)
        target.chmod(0o600)
        with ctx.db.tx() as conn:
            row = conn.execute("SELECT * FROM cases WHERE id=? AND actor_id=?", (case_id, actor_id)).fetchone()
            # Every publication guard is rechecked at commit (R27): owner, tombstone, revision, review, state and
            # that the rendered guidance is still the case's current guidance.
            if (row is None or row["state"] in {"deleting", "deleted"} or row["revision"] != revision
                    or row["state"] != "guided" or row["reviewed_revision"] != revision
                    or row["latest_guidance_id"] != guidance["id"]):
                target.unlink(missing_ok=True)
                finish_job(conn, job_id, "stale" if row is not None and row["state"] not in {"deleting", "deleted"}
                           else "cancelled", error_code="REVISION_CHANGED")
                return
            export_id = str(uuid.uuid4())
            conn.execute("INSERT INTO exports (id, actor_id, case_id, input_revision, guidance_id, storage_key, "
                         "created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                         (export_id, actor_id, case_id, revision, guidance["id"], storage_key, iso(now),
                          iso(now + EXPORT_TTL)))
            finish_job(conn, job_id, "succeeded", result_id=export_id, result_type="export")
            record_event(conn, "export_created", "succeeded", operation_id="createExport")
    except BaseException:
        target.unlink(missing_ok=True)  # its row never committed
        raise


def download(ctx, session: SessionInfo, export_id: str) -> bytes:
    with ctx.db.read() as conn:
        e = conn.execute("SELECT * FROM exports WHERE id=? AND actor_id=?", (export_id, session.actor_id)).fetchone()
        if e is None:
            raise not_found()
        case = conn.execute("SELECT * FROM cases WHERE id=? AND actor_id=?", (e["case_id"], session.actor_id)).fetchone()
    if case is None or case["state"] in {"deleting", "deleted"}:
        raise not_found()
    if e["revoked"] or case["revision"] != e["input_revision"]:
        raise state_conflict("This summary is out of date. Create a new one.", current_revision=case["revision"])
    if utcnow() >= parse(e["expires_at"]):
        raise ApiError(409, "EXPORT_EXPIRED", "This download link expired. Create a new summary.")
    try:
        return (export_dir(ctx) / e["storage_key"]).read_bytes()
    except OSError as exc:
        raise not_found() from exc
