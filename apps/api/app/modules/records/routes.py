"""M06 routes: uploadRecord, listRecords, reviewFact."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write, require_patient
from app.modules.records import service
from app.modules.records.schemas import FactReview

router = APIRouter()


@router.post("/cases/{case_id}/records", operation_id="uploadRecord", status_code=202)
def upload_record(case_id: str, request: Request, file: Annotated[UploadFile, File()],
                  expected_revision: Annotated[int, Form(ge=1)], session=Depends(require_health_write),
                  ctx: AppContext = Depends(get_ctx)):
    # #272: a plain function, so FastAPI runs it in its thread pool: reading, hashing, scanning and writing the file
    # never block the event loop that serves every other request.
    key = idempotency.require_key(request)
    # Read at most one byte past the limit so oversized uploads are refused without buffering them whole.
    data = file.file.read(service.MAX_BYTES + 1)
    file.file.close()
    return respond(service.upload_record(ctx, session, case_id, expected_revision, key, file.content_type,
                                         file.filename, data), 202)


@router.get("/cases/{case_id}/records", operation_id="listRecords")
def list_records(case_id: str, session=Depends(require_patient), ctx: AppContext = Depends(get_ctx)):
    return respond(service.list_records(ctx, session, case_id))


@router.patch("/cases/{case_id}/facts/{fact_id}", operation_id="reviewFact")
def review_fact(case_id: str, fact_id: str, body: FactReview, session=Depends(require_health_write),
                ctx: AppContext = Depends(get_ctx)):
    corrected = body.corrected_value.model_dump() if body.corrected_value else None
    return respond(service.review_fact(ctx, session, case_id, fact_id, body.expected_revision, body.action,
                                       corrected))
