"""M01 routes: createSession. (deleteSession is owned by M11.)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import COOKIE_PATH, PRESENTER_COOKIE, SESSION_COOKIE, check_origin, optional_session
from app.modules.access import presenter
from app.modules.access import service
from app.modules.access.schemas import CreateSessionRequest

router = APIRouter()


@router.post("/sessions", operation_id="createSession", status_code=201)
def create_session(body: CreateSessionRequest, request: Request, ctx: AppContext = Depends(get_ctx),
                   existing=Depends(optional_session)):
    check_origin(request, ctx)
    key = idempotency.require_key(request)
    out, token, csrf = service.create_session(ctx, request, body, key, existing)
    response = respond(out, 201, {"X-CSRF-Token": csrf, "X-Session-Expires-At": out["expires_at"]})
    if token:
        # The service has already refused invalid assertions, so presence means a presenter session.
        name = PRESENTER_COOKIE if presenter.present(request) else SESSION_COOKIE
        response.set_cookie(name, token, httponly=True, samesite="strict",
                            secure=ctx.settings.cookie_secure, path=COOKIE_PATH)
    lineage = getattr(request.state, "presenter_lineage", None)
    if lineage and presenter.lineage_token(request) != lineage:
        # #396: the presenter browser's lineage, kept across its presenter sessions (presenter gateway only).
        response.set_cookie(presenter.LINEAGE_COOKIE, lineage, httponly=True, samesite="strict",
                            secure=ctx.settings.cookie_secure, path=COOKIE_PATH, max_age=presenter.LINEAGE_MAX_AGE)
    return response
