"""M07 routes: getCaseSources."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_patient
from app.modules.evidence import service

router = APIRouter()


@router.get("/cases/{case_id}/sources", operation_id="getCaseSources")
def get_case_sources(case_id: str, session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.case_sources(ctx, session, case_id))
