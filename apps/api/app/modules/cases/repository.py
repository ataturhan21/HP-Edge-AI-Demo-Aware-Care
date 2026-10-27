"""M03 case persistence: actor-qualified reads, revisions and derived-artifact invalidation."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.db import iso, utcnow
from app.core.errors import not_found, revision_conflict

ACTIVE_STATES = {"draft", "intake", "review", "reviewed", "generating", "guided", "urgent", "limited"}


def get_owned(conn: sqlite3.Connection, actor_id: str, case_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cases WHERE id=? AND actor_id=?", (case_id, actor_id)).fetchone()
    if row is None or row["state"] in {"deleting", "deleted"}:
        raise not_found()
    return row


def check_revision(row: sqlite3.Row, expected: int) -> None:
    if row["revision"] != expected:
        raise revision_conflict(row["revision"])


def facts(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    """Confirmed facts only (R20): the case projection, guidance and exports never see
    unconfirmed or rejected document extractions as current context.

    #449: answers are listed in question (slot) order. A changed answer is stored as a new fact, so in insertion order it
    would move after the answers given before the change; the answers keep their places among the other facts and are
    sorted among themselves by the slot of their question."""
    rows = conn.execute("SELECT f.*, q.slot AS question_slot FROM facts f LEFT JOIN questions q "
                        "ON q.id = f.source_id AND q.case_id = f.case_id AND f.kind LIKE 'answer:%' "
                        "WHERE f.case_id=? AND f.active=1 AND f.status='confirmed' ORDER BY f.rowid",
                        (case_id,)).fetchall()
    places = [i for i, r in enumerate(rows) if r["question_slot"] is not None]
    answers = sorted((rows[i] for i in places), key=lambda r: r["question_slot"])
    ordered = list(rows)
    for place, row in zip(places, answers):
        ordered[place] = row
    return [fact_public(r) for r in ordered]


def document_facts(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    """All active document-provenance facts with their review status (A04 review list)."""
    rows = conn.execute("SELECT * FROM facts WHERE case_id=? AND active=1 AND provenance='document' ORDER BY rowid",
                        (case_id,)).fetchall()
    return [fact_public(r) for r in rows]


def fact_public(r: sqlite3.Row) -> dict[str, Any]:
    out = {"id": r["id"], "case_id": r["case_id"], "kind": r["kind"], "value": json.loads(r["value_json"]),
           "units": r["units"], "provenance": r["provenance"], "source_id": r["source_id"], "page": r["page"],
           "status": r["status"], "original_text": r["original_text"], "confirmed_at": r["confirmed_at"]}
    if r["reference_range"] is not None:
        out["reference_range"] = r["reference_range"]
    return out


def case_public(conn: sqlite3.Connection, row: sqlite3.Row, expires_at: str) -> dict[str, Any]:
    return {"id": row["id"], "actor_id": row["actor_id"], "revision": row["revision"], "state": row["state"],
            "concern": row["concern"], "confirmed_context": facts(conn, row["id"]),
            "issued_slots": row["issued_slots"], "reviewed_revision": row["reviewed_revision"],
            "latest_guidance_id": row["latest_guidance_id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "expires_at": expires_at, "deleted_at": row["deleted_at"],
            "urgent_level": row["urgent_level"]}


def bump_clinical_revision(conn: sqlite3.Connection, row: sqlite3.Row, new_state: str) -> int:
    """Apply a clinical mutation: one revision increment, review cleared, derived results invalidated."""
    revision = row["revision"] + 1
    conn.execute("UPDATE cases SET revision=?, state=?, reviewed_revision=NULL, latest_guidance_id=NULL, "
                 "updated_at=? WHERE id=?", (revision, new_state, iso(utcnow()), row["id"]))
    conn.execute("UPDATE provider_searches SET current=0 WHERE case_id=?", (row["id"],))
    conn.execute("UPDATE exports SET revoked=1 WHERE case_id=?", (row["id"],))
    return revision


def set_state(conn: sqlite3.Connection, case_id: str, state: str, **fields: Any) -> None:
    assignments = ", ".join(f"{k}=?" for k in fields)
    sql = f"UPDATE cases SET state=?, updated_at=?{', ' + assignments if assignments else ''} WHERE id=?"
    conn.execute(sql, (state, iso(utcnow()), *fields.values(), case_id))
