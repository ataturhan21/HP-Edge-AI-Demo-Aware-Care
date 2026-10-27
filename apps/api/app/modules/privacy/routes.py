"""M11 routes: deleteSession, deleteCase, getSettings, updateSettings, deleteAllHealthData."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import COOKIE_PATH, PRESENTER_COOKIE, SESSION_COOKIE, require_patient, require_write
from app.modules.cases.schemas import Revision
from app.modules.privacy import service

router = APIRouter()


class SettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision
    saved_retention_days: Literal[7, 30]


class DeleteAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_token: Annotated[str, Field(min_length=1, max_length=512)]


@router.delete("/sessions/current", operation_id="deleteSession", status_code=202)
def delete_session(request: Request, session=Depends(require_write), ctx: AppContext = Depends(get_ctx)):
    response = respond(service.delete_session(ctx, session), 202)
    request.state.session_expires_at = None  # the session has ended: no expiry to report (#42)
    response.delete_cookie(PRESENTER_COOKIE if session.role == "presenter" else SESSION_COOKIE, path=COOKIE_PATH)
    return response


@router.delete("/cases/{case_id}", operation_id="deleteCase", status_code=202)
def delete_case(case_id: str, expected_revision: Annotated[int, Query(ge=1)], session=Depends(require_write),
                ctx: AppContext = Depends(get_ctx)):
    return respond(service.delete_case(ctx, session, case_id, expected_revision), 202)


@router.get("/settings", operation_id="getSettings")
def get_settings(session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.get_settings(ctx, session))


@router.put("/settings", operation_id="updateSettings")
def update_settings(body: SettingsWrite, session=Depends(require_write), ctx: AppContext = Depends(get_ctx)):
    return respond(service.update_settings(ctx, session, body.expected_revision, body.saved_retention_days))


@router.post("/privacy/delete-all", operation_id="deleteAllHealthData", status_code=202)
def delete_all(body: DeleteAllRequest, request: Request, session=Depends(require_write),
               ctx: AppContext = Depends(get_ctx)):
    key = idempotency.require_key(request)
    return respond(service.delete_all(ctx, session, body.confirmation_token, key), 202)
