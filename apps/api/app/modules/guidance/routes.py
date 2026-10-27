"""M08 routes: generateGuidance, getGuidance."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write, require_patient
from app.modules.cases.schemas import RevisionRequest
from app.modules.guidance import service

router = APIRouter()


@router.post("/cases/{case_id}/guidance", operation_id="generateGuidance", status_code=202)
def generate_guidance(case_id: str, body: RevisionRequest, request: Request, session=Depends(require_health_write),
                      ctx: AppContext = Depends(get_ctx)):
    key = idempotency.require_key(request)
    return respond(service.start_generation(ctx, session, case_id, body.expected_revision, key), 202)


@router.get("/cases/{case_id}/guidance", operation_id="getGuidance")
def get_guidance(case_id: str, session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.get_guidance(ctx, session, case_id))
