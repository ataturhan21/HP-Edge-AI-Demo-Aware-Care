"""Process-wide application context: settings, store, fixtures, runtime adapter, job runner."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

from app.config import Settings
from app.core.db import Database
from app.core.fixtures import FixturePack
from app.modules.safety.pathway import Pathway

if TYPE_CHECKING:
    from app.modules.operations.service import JobRunner


@dataclass
class AppContext:
    settings: Settings
    db: Database
    fixtures: FixturePack | None
    pathway: Pathway | None  # the enabled reviewed package (ADR-003); None when the registry enables none
    runtime: object  # RuntimeAdapter implementation (mock or zrt)
    jobs: "JobRunner"
    # #548: for the presenter's Logs view, in memory only: the API's recent error responses (time, status, code, method,
    # route template, request ID) and the readiness changes this process observed (time and state).
    recent_errors: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))
    health_changes: deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=50))


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx
