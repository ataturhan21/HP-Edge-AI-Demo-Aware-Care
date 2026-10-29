"""M12 routes: getJob, getRuntime, getControls, getLogs, loadScenario, resetDemo, getReadiness, getTelemetry."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.errors import ApiError
from app.core.http import respond
from app.core.security import (COOKIE_PATH, SESSION_COOKIE, require_presenter, require_presenter_write,
                               require_session)
from app.modules.operations import logs, scenarios, service, telemetry

router = APIRouter()


class LoadScenarioRequest(BaseModel):
    """#316 (CHG-DEV-API-002): `reset=false` adds the case to the presenter's live demo; `prepare="result"` readies a
    quick demo (reviewed questions with synthetic answers, guidance, doctor search) in a presenter-owned job."""
    model_config = ConfigDict(extra="forbid")
    reset: StrictBool
    prepare: Literal["start", "result"] = "start"
    # #358 (CHG-DEV-API-006): "written" gives the case only the written concern (checklist: none apply), so the
    # red-flag screen of the concern decides, as for a patient who writes an emergency in their own words.
    urgency_input: Literal["checklist", "written"] = "checklist"


@router.get("/jobs/{job_id}", operation_id="getJob")
def get_job(job_id: str, session=Depends(require_session), ctx: AppContext = Depends(get_ctx)):
    job = service.get_job(ctx.db, session.actor_id, job_id)
    job["stage"] = scenarios.prepare_stage(ctx, job)
    return respond(job)


@router.get("/presenter/runtime", operation_id="getRuntime")
def get_runtime(session=Depends(require_presenter), ctx: AppContext = Depends(get_ctx)):
    return respond(service.runtime_snapshot(ctx, session.actor_id))


@router.get("/presenter/controls", operation_id="getControls")
def get_controls(session=Depends(require_presenter), ctx: AppContext = Depends(get_ctx)):
    return respond(service.controls(ctx))


@router.get("/presenter/logs", operation_id="getLogs")
def get_logs(since: datetime | None = None,
             level: list[Literal["ok", "warn", "fail", "info"]] | None = Query(None),
             kind: Literal[logs.KINDS] | None = None,  # type: ignore[valid-type]
             q: str | None = Query(None, max_length=logs.MAX_QUERY),
             before: str | None = Query(None, max_length=logs.MAX_CURSOR),
             limit: int = Query(200, ge=1, le=logs.MAX_LIMIT),
             session=Depends(require_presenter), ctx: AppContext = Depends(get_ctx)):
    """#548: the presenter's Logs view (O01): recent jobs, model calls, events, readiness and API errors, newest first,
    content-free (codes, job IDs, statuses and timings only). #577: level (repeatable), kind and the text search q
    filter every kept row; `before` is the previous page's next_before ("Load older")."""
    cursor = None
    if before is not None:
        try:
            cursor = logs.decode_cursor(before)
        except logs.BadCursor:
            raise ApiError(422, "VALIDATION_FAILED", "Some fields need attention.",
                           field_errors=[{"field": "before", "code": "invalid_cursor", "message": "Invalid value."}]) from None
    return respond(logs.logs_snapshot(ctx, since=since, level=level, kind=kind, limit=limit, q=q, before=cursor))


@router.post("/presenter/scenarios/{scenario_id}/load", operation_id="loadScenario", status_code=201)
def load_scenario(scenario_id: str, body: LoadScenarioRequest, request: Request,
                  session=Depends(require_presenter_write), ctx: AppContext = Depends(get_ctx)):
    body, token = scenarios.load(ctx, session, scenario_id, idempotency.require_key(request), reset=body.reset,
                                 prepare=body.prepare, urgency_input=body.urgency_input,
                                 patient_token=request.cookies.get(SESSION_COOKIE))
    response = respond(body, 201)
    # The loaded synthetic patient session goes to the patient cookie; the presenter cookie is not touched. #673: no
    # token when the browser's patient cookie already holds that demo patient's session (it stays as it is).
    if token is not None:
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict",
                            secure=ctx.settings.cookie_secure, path=COOKIE_PATH)
    return response


@router.post("/presenter/reset", operation_id="resetDemo", status_code=202)
def reset_demo(request: Request, session=Depends(require_presenter_write), ctx: AppContext = Depends(get_ctx)):
    return respond(scenarios.reset(ctx, session, idempotency.require_key(request)), 202)


@router.get("/telemetry", operation_id="getTelemetry")
def get_telemetry(period: Literal["24h", "7d", "release"] = "7d", ctx: AppContext = Depends(get_ctx)):
    """W06 (ADR-017): public, content-free aggregates; no session needed and no patient data in the response."""
    return respond(telemetry.telemetry_snapshot(ctx, period))


@router.get("/health/ready", operation_id="getReadiness")
def get_readiness(ctx: AppContext = Depends(get_ctx)):
    state = service.readiness(ctx)
    return respond({"readiness": state}, 503 if state == "unavailable" else 200)
