"""M09 routes: searchProviders, getProvider."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write, require_patient
from app.modules.providers import service
from app.modules.providers.schemas import ProviderSearchRequest

router = APIRouter()


@router.post("/cases/{case_id}/provider-search", operation_id="searchProviders")
def search_providers(case_id: str, body: ProviderSearchRequest, session=Depends(require_health_write),
                     ctx: AppContext = Depends(get_ctx)):
    return respond(service.search(ctx, session, case_id, body.expected_revision, body.criteria))


@router.get("/cases/{case_id}/providers/{provider_id}", operation_id="getProvider")
def get_provider(case_id: str, provider_id: str, search_id: Annotated[uuid.UUID, Query()],
                 session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.provider_card(ctx, session, case_id, provider_id, str(search_id)))
