"""M10 routes: createExport, downloadExport."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write, require_patient
from app.modules.cases.schemas import ExactlyTrue, Revision
from app.modules.exports import service

router = APIRouter()


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision
    user_reviewed: ExactlyTrue


@router.post("/cases/{case_id}/exports", operation_id="createExport", status_code=202)
def create_export(case_id: str, body: ExportRequest, request: Request, session=Depends(require_health_write),
                  ctx: AppContext = Depends(get_ctx)):
    key = idempotency.require_key(request)
    return respond(service.request_export(ctx, session, case_id, body.expected_revision, key), 202)


@router.get("/exports/{export_id}/download", operation_id="downloadExport")
def download_export(export_id: str, session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    data = service.download(ctx, session, export_id)
    return Response(data, media_type="application/pdf", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="aware-care-appointment-summary.pdf"',
        "X-Content-Type-Options": "nosniff"})
