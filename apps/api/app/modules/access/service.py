"""M01 sessions and consent (R01-R03).

Saved mode needs an approved upstream local identity layer and is refused rather
than faked. Role is `patient` unless the request carries a valid, single-use
presenter gateway assertion (ADR-005 option A, `presenter.py`); then a separate
presenter actor and session are created. A request carrying an invalid assertion
is refused instead of silently becoming a patient session.
#434 (session fixation): accepting consent with a valid session of the same role already in the browser continues
that actor (its cases stay owned, no second actor), but always under a new session: a new ID, token and CSRF token,
and the old session is revoked. A token planted in the browser before consent can never read what is entered after.
Idempotency for creation is scoped by an HttpOnly pre-session nonce cookie.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request

from app.core import idempotency
from app.core.db import iso, utcnow
from app.core.errors import ApiError
from app.core.security import (CURRENT_CONSENT_VERSION, GUEST_ABSOLUTE, SessionInfo, effective_expiry,
                               hash_token, new_token)
from app.modules.access import presenter
from app.modules.access.schemas import CreateSessionRequest
from app.modules.operations.service import record_event

PRESESSION_COOKIE = "awarecare_presession"


def _issue(conn, actor_id: str, body: CreateSessionRequest, role: str = "patient") -> tuple[dict, str, str]:
    now = utcnow()
    token, csrf = new_token(), new_token()
    session_id = str(uuid.uuid4())
    conn.execute("INSERT INTO sessions (id, actor_id, token_hash, csrf_token, mode, role, consent_version, "
                 "consent_at, adult_eligible, created_at, last_seen_at, absolute_expires_at) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (session_id, actor_id, hash_token(token), csrf, body.mode, role, body.consent_version, iso(now),
                  int(body.adult_eligible), iso(now), iso(now), iso(now + GUEST_ABSOLUTE)))
    body_out = {"session_id": session_id, "actor_id": actor_id,
                "expires_at": effective_expiry(iso(now), iso(now + GUEST_ABSOLUTE))}
    return body_out, token, csrf


def create_session(ctx, request: Request, body: CreateSessionRequest, key: str,
                   existing: SessionInfo | None) -> tuple[dict[str, Any], str | None, str]:
    """Return (response body, new cookie token or None, csrf token)."""
    if body.mode == "saved":
        raise ApiError(403, "SAVED_MODE_UNAVAILABLE",
                       "Saved accounts need an approved local sign-in, which this demo build does not provide.")
    if not body.adult_eligible:
        raise ApiError(403, "ADULT_ELIGIBILITY_REQUIRED", "This demonstration is limited to adults.")
    if body.consent_version != CURRENT_CONSENT_VERSION:
        raise ApiError(403, "CONSENT_REQUIRED", "Please review and accept the current consent.")
    as_presenter = presenter.present(request)
    if as_presenter and not presenter.verify(request, ctx.settings):
        raise ApiError(403, "PRESENTER_REQUIRED", "Presenter authorization is required.")
    role = "presenter" if as_presenter else "patient"
    continuing = existing is not None and existing.role == role
    # #396: a presenter session belongs to its browser's lineage (cookie set by the route when it was missing).
    lineage = (presenter.lineage_token(request) or new_token()) if as_presenter else None
    request.state.presenter_lineage = lineage
    nonce = request.cookies.get(PRESESSION_COOKIE)
    if not nonce and not continuing:
        raise ApiError(400, "PRESESSION_REQUIRED", "Reload the page and try again.", retryable=True)
    scope = f"presession:{hash_token(nonce)}" if nonce else None
    operation = "createPresenterSession" if as_presenter else "createSession"
    req_hash = idempotency.request_hash(body.model_dump())
    with ctx.db.tx() as conn:
        if as_presenter and not presenter.consume(conn, request, ctx.settings):
            raise ApiError(403, "PRESENTER_REQUIRED", "Presenter authorization is required.")
        replay = idempotency.lookup(conn, scope, operation, key, req_hash) if scope else None
        if replay:
            # Response was lost: rotate the token of the same session for this browser.
            session_id = replay.body["session_id"]
            row = conn.execute("SELECT * FROM sessions WHERE id=? AND revoked=0", (session_id,)).fetchone()
            if row is None:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "That session has ended. Start again.")
            token = new_token()
            conn.execute("UPDATE sessions SET token_hash=? WHERE id=?", (hash_token(token), session_id))
            return replay.body, token, row["csrf_token"]
        if continuing:
            # #434: the same actor under a fresh session; the session the browser held ends now.
            live = conn.execute("SELECT 1 FROM sessions WHERE id=? AND revoked=0", (existing.id,)).fetchone()
            if live is None:  # ended (or rotated by a concurrent request) since it was read: start a new actor
                continuing = False
        if continuing:
            conn.execute("UPDATE sessions SET revoked=1 WHERE id=?", (existing.id,))
            if lineage:
                presenter.record_lineage(conn, existing.actor_id, lineage)
            out, token, csrf = _issue(conn, existing.actor_id, body, role=role)
            if scope:
                idempotency.store(conn, scope, operation, key, req_hash, 201, out, actor_id=existing.actor_id,
                                  case_id=None)
            record_event(conn, "session_rotated", "presenter" if as_presenter else "guest",
                         operation_id="createSession")
            return out, token, csrf
        if not nonce:
            raise ApiError(400, "PRESESSION_REQUIRED", "Reload the page and try again.", retryable=True)
        actor_id = str(uuid.uuid4())
        kind = "presenter" if as_presenter else "guest"
        conn.execute("INSERT INTO actors (id, kind, created_at) VALUES (?, ?, ?)", (actor_id, kind, iso(utcnow())))
        if lineage:
            presenter.record_lineage(conn, actor_id, lineage)
        out, token, csrf = _issue(conn, actor_id, body, role=role)
        idempotency.store(conn, scope, operation, key, req_hash, 201, out, actor_id=actor_id, case_id=None)
        record_event(conn, "session_started", kind, operation_id="createSession")
    return out, token, csrf
