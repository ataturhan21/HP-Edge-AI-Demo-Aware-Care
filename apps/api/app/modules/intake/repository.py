"""M04 question/answer persistence. Slots are unique per case and never reused."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.errors import not_found


def questions(conn: sqlite3.Connection, case_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM questions WHERE case_id=? ORDER BY slot", (case_id,)).fetchall()


def active_question(conn: sqlite3.Connection, case_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM questions WHERE case_id=? AND status='active' ORDER BY slot LIMIT 1",
                        (case_id,)).fetchone()


def owned_question(conn: sqlite3.Connection, case_id: str, question_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM questions WHERE id=? AND case_id=?", (question_id, case_id)).fetchone()
    if row is None:
        raise not_found()
    return row


def answers_by_question(conn: sqlite3.Connection, case_id: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT * FROM answers WHERE case_id=?", (case_id,)).fetchall()
    return {r["question_id"]: {"id": r["id"], "case_id": r["case_id"], "question_id": r["question_id"],
                               "status": r["status"], "value": json.loads(r["value_json"]),
                               "revision": r["revision"], "submitted_at": r["submitted_at"]} for r in rows}
