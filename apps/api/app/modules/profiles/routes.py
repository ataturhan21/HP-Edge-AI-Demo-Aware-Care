"""M02 routes: getProfile, saveProfile."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write, require_patient
from app.modules.profiles import service

router = APIRouter()


@router.get("/profile", operation_id="getProfile")
def get_profile(session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.get_profile(ctx, session))


@router.put("/profile", operation_id="saveProfile")
def save_profile(session=Depends(require_health_write), ctx: AppContext = Depends(get_ctx)):
    return respond(service.save_profile(ctx, session))
