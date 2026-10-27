"""M03 routes: createCase, listCases, getCase, editCase, confirmReview."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write, require_patient
from app.modules.cases import service
from app.modules.cases.schemas import CaseEdit, CaseWrite, ReviewRequest

router = APIRouter()


@router.post("/cases", operation_id="createCase", status_code=201)
def create_case(body: CaseWrite, request: Request, session=Depends(require_health_write),
                ctx: AppContext = Depends(get_ctx)):
    status, payload = service.create_case(ctx, session, body, idempotency.require_key(request))
    return respond(payload, status)


@router.get("/cases", operation_id="listCases")
def list_cases(session=Depends(require_patient), ctx: AppContext = Depends(get_ctx),
               limit: Annotated[int, Query(ge=1, le=service.LIST_MAX)] = service.LIST_DEFAULT,
               cursor: Annotated[str | None, Query(min_length=1, max_length=1000)] = None):
    return respond(service.list_cases(ctx, session, limit, cursor))


@router.get("/cases/{case_id}", operation_id="getCase")
def get_case(case_id: str, session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.read_case(ctx, session, case_id))


@router.patch("/cases/{case_id}", operation_id="editCase")
def edit_case(case_id: str, body: CaseEdit, session=Depends(require_health_write),
              ctx: AppContext = Depends(get_ctx)):
    return respond(service.edit_case(ctx, session, case_id, body))


@router.post("/cases/{case_id}/review", operation_id="confirmReview")
def confirm_review(case_id: str, body: ReviewRequest, session=Depends(require_health_write),
                   ctx: AppContext = Depends(get_ctx)):
    return respond(service.confirm_review(ctx, session, case_id, body))
