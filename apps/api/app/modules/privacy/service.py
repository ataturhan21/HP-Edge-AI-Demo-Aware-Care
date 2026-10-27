"""M11 retention, deletion and settings (R34-R36).

Deletion commits a tombstone/`deleting` state first (reads and downloads stop
immediately), cancels queued work, then purges every owned store: export files,
record bytes, derived rows, idempotency cache entries. Late workers find no current case and
cancel. Guest logout/expiry purges the guest actor's health content.

Retention of the content-free rows (#440, #471; spec/engineering/05-privacy-and-security.md):
- job records (status and timing of guidance, export, record, deletion and reset work) keep their owner's actor ID only
  while that actor exists. When the session ends (logout, expiry, presenter reset of a demo patient) they lose it, and
  every time on them is cut to the hour, so no row links to one person's session; the sweep deletes them after 30 days;
- operational events: 30 days; AI usage counts (`model_calls`, hour only): 90 days, both removed by the sweep.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import timedelta
from typing import Any

from app.core import idempotency
from app.core.db import hour, iso, parse, utcnow
from app.core.errors import ApiError
from app.core.security import SessionInfo
from app.modules.cases import repository as cases_repo
from app.modules.exports.service import export_dir
from app.modules.operations.service import create_job, finish_job, record_event
from app.modules.records.service import record_dir
from app.runtime.metering import RETENTION_DAYS

TOKEN_TTL = timedelta(minutes=5)
SWEEP_INTERVAL_S = 300
EVENT_RETENTION = timedelta(days=30)
JOB_RETENTION = timedelta(days=30)  # #440: as long as the operational events they sit beside
AI_USAGE_RETENTION = timedelta(days=RETENTION_DAYS)  # #471: 90 days, removed by the sweep, not only on a new AI call
ENDED_ACTOR = "ended"  # #440: a job row's owner once that owner's session has ended (never an actor ID)
ORPHAN_MIN_AGE_S = 600  # a file this old with no row is an orphan; younger ones may belong to a write in progress


def _mark_deleting(conn, case_ids: list[str]) -> None:
    now = iso(utcnow())
    for case_id in case_ids:
        conn.execute("UPDATE cases SET state='deleting', deleted_at=?, updated_at=? WHERE id=?", (now, now, case_id))
        conn.execute("UPDATE exports SET revoked=1 WHERE case_id=?", (case_id,))
        conn.execute("UPDATE jobs SET status='cancelled', error_code='CASE_DELETED', finished_at=? "
                     "WHERE case_id=? AND status IN ('queued','running') AND kind != 'deletion'", (now, case_id))
        conn.execute("INSERT INTO tombstones (scope_kind, scope_id, generation, created_at) VALUES ('case',?,1,?) "
                     "ON CONFLICT(scope_kind, scope_id) DO UPDATE SET generation=generation+1", (case_id, now))


def _purge(ctx, case_ids: list[str]) -> None:
    with ctx.db.tx() as conn:
        keys = [r["storage_key"] for cid in case_ids for r in
                conn.execute("SELECT storage_key FROM exports WHERE case_id=?", (cid,)).fetchall()]
        record_keys = [r["storage_key"] for cid in case_ids for r in
                       conn.execute("SELECT storage_key FROM documents WHERE case_id=? AND storage_key IS NOT NULL",
                                    (cid,)).fetchall()]
    for key in keys:
        (export_dir(ctx) / key).unlink(missing_ok=True)
    for key in record_keys:
        (record_dir(ctx) / key).unlink(missing_ok=True)
    with ctx.db.tx() as conn:
        for case_id in case_ids:
            conn.execute("DELETE FROM idempotency WHERE case_id=?", (case_id,))
            conn.execute("DELETE FROM cases WHERE id=?", (case_id,))  # cascades facts/questions/answers/...
            # #275 (R36): the case's job rows stay only as content-free timing samples (telemetry and runtime
            # medians). They lose the case, any urgency level and every time finer than the hour. The owner's
            # session ID stays until the session ends, so a browser still polling an in-flight job sees it end
            # (cancelled) rather than vanish; the deletion job itself is untouched.
            conn.execute(
                "UPDATE jobs SET case_id=NULL, result_id=NULL, "
                "error_code=CASE WHEN error_code LIKE 'RED_FLAG_DESCRIBED%' THEN 'RED_FLAG_DESCRIBED' "
                "ELSE error_code END, "
                "created_at=substr(created_at,1,13)||':00:00Z', started_at=substr(started_at,1,13)||':00:00Z', "
                "finished_at=substr(finished_at,1,13)||':00:00Z' WHERE case_id=? AND kind != 'deletion'", (case_id,))
    # #274 (R35): no copy of the deleted rows stays in the write-ahead log (freed pages are zeroed by secure_delete).
    ctx.db.checkpoint()


def release_jobs(conn, actor_ids) -> None:
    """#440 (R36, #275): the job rows of actors whose session has ended keep no link to them: no actor, case or result
    ID, and every time cut to the hour. They stay as content-free timing samples until the sweep deletes them. Also
    run by the sweep for rows whose actor no longer exists (for example rows written before this rule)."""
    for actor_id in actor_ids:
        conn.execute(
            "UPDATE jobs SET actor_id=?, case_id=NULL, result_id=NULL, "
            "error_code=CASE WHEN error_code LIKE 'RED_FLAG_DESCRIBED%' THEN 'RED_FLAG_DESCRIBED' ELSE error_code END, "
            "created_at=substr(created_at,1,13)||':00:00Z', started_at=substr(started_at,1,13)||':00:00Z', "
            "finished_at=substr(finished_at,1,13)||':00:00Z' WHERE actor_id=?", (ENDED_ACTOR, actor_id))


def remove_orphan_files(ctx, min_age_s: float = ORPHAN_MIN_AGE_S) -> int:
    """#272 (R35): remove record and export files that no row references, for example after a crash between a write
    and its commit. The directories are listed before the referenced keys are read: an upload writes its bytes inside
    the transaction that inserts its row, so a file listed here either has a committed row by the time the keys are
    read, or its upload rolled back. Export bytes are written just before their row is inserted, so the periodic sweep
    also leaves files younger than `min_age_s`; at startup nothing is being written and every orphan goes."""
    folders = (record_dir(ctx), export_dir(ctx))
    listed = [(folder, path) for folder in folders for path in folder.iterdir() if path.is_file()]
    with ctx.db.tx() as conn:
        keys = {r["storage_key"] for r in conn.execute(
            "SELECT storage_key FROM documents WHERE storage_key IS NOT NULL UNION ALL "
            "SELECT storage_key FROM exports")}
    removed, cutoff = 0, time.time() - min_age_s
    for _, path in listed:
        try:
            if path.name in keys or path.stat().st_mtime > cutoff:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def _run_deletion(ctx, job_id: str, case_ids: list[str], actor_to_remove: str | None = None) -> None:
    try:
        _purge(ctx, case_ids)
        with ctx.db.tx() as conn:
            finish_job(conn, job_id, "succeeded", result_id=job_id, result_type="deletion_receipt")
            if actor_to_remove:
                conn.execute("DELETE FROM idempotency WHERE actor_id=?", (actor_to_remove,))
                conn.execute("DELETE FROM actors WHERE id=?", (actor_to_remove,))
                release_jobs(conn, [actor_to_remove])  # #440: the session's deletion job included
            record_event(conn, "deletion_completed", "succeeded")
        ctx.db.checkpoint()  # #274: the removed actor's rows leave the WAL too
    except Exception:
        with ctx.db.tx() as conn:
            # Access stays blocked (cases remain `deleting`); a later sweep retries.
            finish_job(conn, job_id, "failed", error_code="PURGE_FAILED")
            record_event(conn, "deletion_failed", "failed", error_code="PURGE_FAILED")


def _start_deletion(ctx, job_id: str, case_ids: list[str], actor_to_remove: str | None = None) -> None:
    """#263: the purge runs in the background; if the job cannot be submitted it runs now, so a committed deletion
    is never left without a worker (access is already blocked by the tombstone)."""
    try:
        ctx.jobs.submit(lambda: _run_deletion(ctx, job_id, case_ids, actor_to_remove))
    except Exception:
        _run_deletion(ctx, job_id, case_ids, actor_to_remove)


def delete_case(ctx, session: SessionInfo, case_id: str, expected_revision: int) -> dict[str, Any]:
    with ctx.db.tx() as conn:
        row = cases_repo.get_owned(conn, session.actor_id, case_id)
        cases_repo.check_revision(row, expected_revision)
        _mark_deleting(conn, [case_id])
        job = create_job(conn, actor_id=session.actor_id, case_id=None, kind="deletion", status="running")
        record_event(conn, "deletion_requested", "running", operation_id="deleteCase")
    _start_deletion(ctx, job["id"], [case_id])
    return {"deletion_job_id": job["id"]}


def _actor_case_ids(conn, actor_id: str) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM cases WHERE actor_id=? AND state != 'deleted'",
                                          (actor_id,)).fetchall()]


def delete_session(ctx, session: SessionInfo) -> dict[str, Any]:
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET revoked=1 WHERE id=?", (session.id,))
        guest = session.mode == "guest"
        case_ids = _actor_case_ids(conn, session.actor_id) if guest else []
        _mark_deleting(conn, case_ids)
        if guest:
            conn.execute("UPDATE actors SET deleting=1 WHERE id=?", (session.actor_id,))
        job = create_job(conn, actor_id=session.actor_id, case_id=None, kind="deletion", status="running")
        record_event(conn, "session_ended", session.mode, operation_id="deleteSession")
    _start_deletion(ctx, job["id"], case_ids, session.actor_id if guest else None)
    return {"deletion_job_id": job["id"]}


def _settings_row(conn, actor_id: str):
    row = conn.execute("SELECT * FROM settings WHERE actor_id=?", (actor_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO settings (actor_id, revision, saved_retention_days) VALUES (?,1,30)", (actor_id,))
        row = conn.execute("SELECT * FROM settings WHERE actor_id=?", (actor_id,)).fetchone()
    return row


def _settings_public(row) -> dict[str, Any]:
    return {"revision": row["revision"], "saved_retention_days": row["saved_retention_days"],
            "guest_idle_minutes": 30, "guest_absolute_hours": 8, "export_retention_minutes": 15,
            "operational_event_retention_days": 30, "patient_backups_enabled": False}


def get_settings(ctx, session: SessionInfo) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + TOKEN_TTL
    with ctx.db.tx() as conn:
        row = _settings_row(conn, session.actor_id)
        conn.execute("INSERT INTO delete_tokens (token_hash, actor_id, expires_at) VALUES (?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), session.actor_id, iso(expires)))
        return {"settings": _settings_public(row), "delete_confirmation_token": token,
                "delete_confirmation_expires_at": iso(expires)}


def update_settings(ctx, session: SessionInfo, expected_revision: int, days: int) -> dict[str, Any]:
    if session.mode != "saved":
        raise ApiError(403, "SAVED_MODE_REQUIRED", "Retention choices apply to saved accounts only.")
    with ctx.db.tx() as conn:
        row = _settings_row(conn, session.actor_id)
        if row["revision"] != expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "Settings changed. Reload and try again.",
                           current_revision=row["revision"])
        conn.execute("UPDATE settings SET revision=revision+1, saved_retention_days=? WHERE actor_id=?",
                     (days, session.actor_id))
        return _settings_public(_settings_row(conn, session.actor_id))


def delete_all(ctx, session: SessionInfo, token: str, key: str) -> dict[str, Any]:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    # #156: a retry with the same Idempotency-Key (the response was lost) returns the original deletion job instead
    # of "confirmation expired" for a deletion that already ran. The token is one-use; only its hash is compared.
    scope, req_hash = f"actor:{session.actor_id}", idempotency.request_hash({"token_sha256": token_hash})
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, "deleteAllHealthData", key, req_hash)
        if replay:
            return replay.body
        row = conn.execute("SELECT * FROM delete_tokens WHERE token_hash=? AND actor_id=?",
                           (token_hash, session.actor_id)).fetchone()
        if row is None or row["used"] or utcnow() >= parse(row["expires_at"]):
            raise ApiError(403, "CONFIRMATION_INVALID", "The confirmation expired. Reload settings and confirm again.")
        conn.execute("UPDATE delete_tokens SET used=1 WHERE token_hash=?", (token_hash,))
        case_ids = _actor_case_ids(conn, session.actor_id)
        _mark_deleting(conn, case_ids)
        job = create_job(conn, actor_id=session.actor_id, case_id=None, kind="deletion", status="running")
        body = {"deletion_job_id": job["id"]}
        idempotency.store(conn, scope, "deleteAllHealthData", key, req_hash, 202, body,
                          actor_id=session.actor_id, case_id=None)
        record_event(conn, "delete_all_requested", "running", operation_id="deleteAllHealthData")
    _start_deletion(ctx, job["id"], case_ids)
    return body


def sweep(ctx) -> None:
    """Remove expired bytes/rows. Access checks already enforce expiry immediately."""
    now = utcnow()
    with ctx.db.tx() as conn:
        sessions = conn.execute("SELECT s.*, a.kind FROM sessions s JOIN actors a ON a.id=s.actor_id").fetchall()
        expired_guests = set()
        for s in sessions:
            idle = parse(s["last_seen_at"]) + timedelta(minutes=30)
            if s["revoked"] or now >= min(idle, parse(s["absolute_expires_at"])):
                conn.execute("UPDATE sessions SET revoked=1 WHERE id=?", (s["id"],))
                if s["mode"] == "guest":
                    expired_guests.add(s["actor_id"])
        live = {s["actor_id"] for s in conn.execute("SELECT actor_id FROM sessions WHERE revoked=0").fetchall()}
        expired_guests -= live
        stale_cases = {a: _actor_case_ids(conn, a) for a in expired_guests}
        for ids in stale_cases.values():
            _mark_deleting(conn, ids)
        leftover = [r["id"] for r in conn.execute("SELECT id FROM cases WHERE state='deleting'").fetchall()]
        expired_exports = conn.execute("SELECT id, storage_key FROM exports WHERE expires_at < ?",
                                       (iso(now),)).fetchall()
        conn.execute("DELETE FROM exports WHERE expires_at < ?", (iso(now),))
        expired_records = conn.execute("SELECT storage_key FROM documents WHERE expires_at < ? AND storage_key IS NOT "
                                       "NULL", (iso(now),)).fetchall()
        conn.execute("UPDATE documents SET storage_key=NULL WHERE expires_at < ?", (iso(now),))
        conn.execute("DELETE FROM idempotency WHERE created_at < ?", (iso(now - timedelta(hours=24)),))
        conn.execute("DELETE FROM events WHERE ts < ?", (iso(now - EVENT_RETENTION),))
        # #471: AI usage counts older than 90 days go with every sweep, whether or not AI calls are still made.
        conn.execute("DELETE FROM model_calls WHERE hour < ?", (hour(now - AI_USAGE_RETENTION),))
        # #440: finished job rows go after 30 days; work still queued or running is never removed under a worker.
        conn.execute("DELETE FROM jobs WHERE created_at < ? AND status IN ('succeeded','failed','stale','cancelled')",
                     (iso(now - JOB_RETENTION),))
        conn.execute("DELETE FROM delete_tokens WHERE expires_at < ?", (iso(now),))
    for e in expired_exports:
        (export_dir(ctx) / e["storage_key"]).unlink(missing_ok=True)
    for r in expired_records:
        (record_dir(ctx) / r["storage_key"]).unlink(missing_ok=True)
    _purge(ctx, leftover)
    with ctx.db.tx() as conn:
        for actor_id in expired_guests:
            conn.execute("DELETE FROM idempotency WHERE actor_id=?", (actor_id,))
            conn.execute("DELETE FROM actors WHERE id=?", (actor_id,))
        # #440: the expired sessions' job rows, and any whose actor is gone, keep no link to a person.
        gone = [r["actor_id"] for r in conn.execute(
            "SELECT DISTINCT actor_id FROM jobs WHERE actor_id != ? AND actor_id NOT IN (SELECT id FROM actors)",
            (ENDED_ACTOR,)).fetchall()]
        release_jobs(conn, gone)
    remove_orphan_files(ctx)
    ctx.db.checkpoint()  # #274: expired rows leave the WAL too


class Sweeper:
    def __init__(self, ctx):
        self._ctx = ctx
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="retention-sweep", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(SWEEP_INTERVAL_S):
            try:
                sweep(self._ctx)
            except Exception:
                pass  # retried next interval; access checks stay authoritative

    def stop(self) -> None:
        self._stop.set()

