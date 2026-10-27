"""Session, Origin, CSRF, consent and role guards (M01; R01-R03).

Opaque session token lives only in an HttpOnly cookie; the DB stores its hash.
CSRF token is returned in X-CSRF-Token and must be echoed on every write.
Role and actor are server-assigned and never read from the request body.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request

from app.core.context import AppContext, get_ctx
from app.core.db import iso, parse, utcnow
from app.core.errors import ApiError

SESSION_COOKIE = "awarecare_session"
# ADR-005 option A: presenter sessions use their own cookie, so one browser can hold a patient session (requests under
# /api) and a presenter session (requests under /presenter-api, which the gateway signs) at once.
PRESENTER_COOKIE = "awarecare_presenter"
# #487 (ADR-005 amendment): one gateway serves both roles on one origin, the patient API under /api and the presenter
# API under /presenter-api (both proxied to this API's /api). Every cookie is scoped to "/" so both prefixes receive it,
# as both ports did before (browsers share cookies across ports). The API still picks the cookie by the verified
# assertion alone (_load_session); a cookie never grants a role.
COOKIE_PATH = "/"
CSRF_HEADER = "X-CSRF-Token"
CURRENT_CONSENT_VERSION = "aware-care-demo-consent-1.0"
GUEST_IDLE = timedelta(minutes=30)
GUEST_ABSOLUTE = timedelta(hours=8)


@dataclass(frozen=True)
class SessionInfo:
    id: str
    actor_id: str
    mode: str
    role: str
    consent_version: str
    consent_at: str
    adult_eligible: bool
    created_at: str
    last_seen_at: str
    expires_at: str
    csrf_token: str

    def public(self) -> dict:
        return {"id": self.id, "actor_id": self.actor_id, "mode": self.mode, "role": self.role,
                "consent_version": self.consent_version, "consent_at": self.consent_at,
                "adult_eligible": self.adult_eligible, "created_at": self.created_at,
                "last_seen_at": self.last_seen_at, "expires_at": self.expires_at}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def effective_expiry(last_seen: str, absolute: str) -> str:
    idle = parse(last_seen) + GUEST_IDLE
    return iso(min(idle, parse(absolute)))


def check_origin(request: Request, ctx: AppContext) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin not in ctx.settings.allowed_origins:
        raise ApiError(403, "ORIGIN_REJECTED", "This request origin is not allowed.")


def through_presenter_gateway(request: Request, ctx: AppContext) -> bool:
    """A fresh, valid presenter assertion: the request came through the presenter gateway."""
    from app.modules.access import presenter
    return presenter.verify(request, ctx.settings)


def session_cookie_name(request: Request, ctx: AppContext) -> str:
    return PRESENTER_COOKIE if through_presenter_gateway(request, ctx) else SESSION_COOKIE


def _load_session(request: Request, ctx: AppContext, touch: bool) -> SessionInfo | None:
    # The gateway decides which cookie (and so which role) applies; the other cookie is ignored.
    presenter_request = through_presenter_gateway(request, ctx)
    token = request.cookies.get(PRESENTER_COOKIE if presenter_request else SESSION_COOKIE)
    if not token:
        return None
    now = utcnow()
    with ctx.db.tx() as conn:
        row = conn.execute(
            "SELECT s.*, a.deleting FROM sessions s JOIN actors a ON a.id = s.actor_id "
            "WHERE s.token_hash = ? AND s.revoked = 0", (hash_token(token),)).fetchone()
        if row is None or row["deleting"] or (row["role"] == "presenter") != presenter_request:
            return None
        expires = parse(effective_expiry(row["last_seen_at"], row["absolute_expires_at"]))
        if now >= expires:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (row["id"],))
            return None
        last_seen = iso(now) if touch else row["last_seen_at"]
        if touch:
            conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (last_seen, row["id"]))
    return SessionInfo(
        id=row["id"], actor_id=row["actor_id"], mode=row["mode"], role=row["role"],
        consent_version=row["consent_version"], consent_at=row["consent_at"],
        adult_eligible=bool(row["adult_eligible"]), created_at=row["created_at"],
        last_seen_at=last_seen, expires_at=effective_expiry(last_seen, row["absolute_expires_at"]),
        csrf_token=row["csrf_token"])


def optional_session(request: Request, ctx: AppContext = Depends(get_ctx)) -> SessionInfo | None:
    return _load_session(request, ctx, touch=False)


def require_session(request: Request, ctx: AppContext = Depends(get_ctx)) -> SessionInfo:
    session = _load_session(request, ctx, touch=True)
    if session is None:
        raise ApiError(401, "SESSION_REQUIRED", "Your session has ended. Start again to continue.")
    # Lets an in-memory client recover its CSRF token after a page reload. The
    # header is readable only by same-origin scripts (no CORS is configured).
    request.state.csrf_token = session.csrf_token
    # #42 (R36, ADR-013): the session's current expiry after this request, the earlier of the 30-minute idle and the
    # 8-hour absolute limit, so the browser can warn 2 minutes before it ends.
    request.state.session_expires_at = session.expires_at
    return session


def same_token(supplied: str, expected: str) -> bool:
    """Constant-time token comparison over bytes (#156): `hmac.compare_digest` raises TypeError on a non-ASCII str,
    which turned a malformed X-CSRF-Token into a 500 instead of a 403."""
    return hmac.compare_digest(supplied.encode("utf-8", "surrogateescape"), expected.encode("utf-8"))


def require_write(request: Request, session: SessionInfo = Depends(require_session),
                  ctx: AppContext = Depends(get_ctx)) -> SessionInfo:
    check_origin(request, ctx)
    supplied = request.headers.get(CSRF_HEADER, "")
    if not same_token(supplied, session.csrf_token):
        raise ApiError(403, "CSRF_REJECTED", "This request could not be verified. Reload and try again.")
    return session


def require_health_write(session: SessionInfo = Depends(require_write)) -> SessionInfo:
    if session.role != "patient" or not session.adult_eligible or session.consent_version != CURRENT_CONSENT_VERSION:
        raise ApiError(403, "CONSENT_REQUIRED", "Current consent is required before entering health information.")
    return session


def require_patient(session: SessionInfo = Depends(require_session)) -> SessionInfo:
    if session.role != "patient":
        raise ApiError(403, "ROLE_REQUIRED", "This view is for patient sessions.")
    return session


def require_presenter(request: Request, session: SessionInfo = Depends(require_session),
                      ctx: AppContext = Depends(get_ctx)) -> SessionInfo:
    # ADR-005 option A: the role is issued only through the presenter gateway, and every presenter request must
    # still arrive through it with a fresh assertion. A presenter cookie alone (for example sent to the patient
    # gateway, which strips the header) never authorizes presenter operations.
    if session.role != "presenter" or not through_presenter_gateway(request, ctx):
        raise ApiError(403, "PRESENTER_REQUIRED", "Presenter authorization is required.")
    return session


def require_presenter_write(request: Request, session: SessionInfo = Depends(require_presenter),
                            ctx: AppContext = Depends(get_ctx)) -> SessionInfo:
    check_origin(request, ctx)
    if not same_token(request.headers.get(CSRF_HEADER, ""), session.csrf_token):
        raise ApiError(403, "CSRF_REJECTED", "This request could not be verified. Reload and try again.")
    return session
