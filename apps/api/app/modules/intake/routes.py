"""M04 routes: nextQuestion, saveAnswer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core import idempotency
from app.core.context import AppContext, get_ctx
from app.core.http import respond
from app.core.security import require_health_write
from app.modules.cases.schemas import RevisionRequest
from app.modules.intake import service
from app.modules.intake.schemas import AnswerWrite

router = APIRouter()


@router.post("/cases/{case_id}/questions/next", operation_id="nextQuestion")
def next_question(case_id: str, body: RevisionRequest, request: Request, session=Depends(require_health_write),
                  ctx: AppContext = Depends(get_ctx)):
    key = idempotency.require_key(request)
    return respond(service.next_question(ctx, session, case_id, body.expected_revision, key))


@router.put("/cases/{case_id}/answers/{question_id}", operation_id="saveAnswer")
def save_answer(case_id: str, question_id: str, body: AnswerWrite, session=Depends(require_health_write),
                ctx: AppContext = Depends(get_ctx)):
    return respond(service.save_answer(ctx, session, case_id, question_id, body))
