"""Response helpers: every API response is no-store (health/session/job/presenter data)."""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def respond(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})
