"""Sanitized typed errors (Error schema). Never echo model output, document text or tracebacks."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

NO_STORE = {"Cache-Control": "no-store"}
# #465: every API response, success or error, is no-store and carries the browser hardening the pages already have
# (#157): no MIME sniffing of personal-data JSON, no referrer, no framing.
API_HEADERS = {**NO_STORE, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
               "X-Frame-Options": "DENY"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False,
                 current_revision: int | None = None, field_errors: list[dict] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.current_revision = current_revision
        self.field_errors = field_errors or []
        self.headers = headers or {}


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "The requested resource is not available.")


def state_conflict(message: str = "This action is not allowed in the current case state.",
                   current_revision: int | None = None) -> ApiError:
    return ApiError(409, "STATE_CONFLICT", message, current_revision=current_revision)


def revision_conflict(current_revision: int) -> ApiError:
    return ApiError(409, "REVISION_CONFLICT", "The case changed. Reload the current version before continuing.",
                    current_revision=current_revision)


def _body(request: Request, err: ApiError) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": err.code,
        "message": err.message,
        "field_errors": err.field_errors[:50],
        "retryable": err.retryable,
        "request_id": request.state.request_id,
    }
    if err.current_revision is not None:
        body["current_revision"] = err.current_revision
    return body


def note_error(request: Request, status: int, code: str) -> None:
    """#548: keep an error response for the presenter's Logs view (AppContext.recent_errors, memory only): the time,
    status, typed code, method, route template (never the raw path with its IDs) and request ID. No body, header,
    cookie or message."""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return
    route = getattr(request.scope.get("route"), "path", None) or "unmatched"
    ctx.recent_errors.append({"at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "status": status,
                             "code": code, "method": request.method, "route": route[:120],
                             "request_id": getattr(request.state, "request_id", None)})


async def api_error_handler(request: Request, err: ApiError) -> JSONResponse:
    note_error(request, err.status, err.code)
    return JSONResponse(_body(request, err), status_code=err.status, headers={**API_HEADERS, **err.headers})


# #464: the framework's own refusals (a body that cannot be decoded, an unknown path, a method the route does not
# offer) answer in the Error schema with a typed code, like every other 4xx, instead of FastAPI's {"detail": ...}.
HTTP_ERRORS = {
    400: ("MALFORMED_REQUEST", "The request is malformed."),
    404: ("NOT_FOUND", "The requested resource is not available."),
    405: ("METHOD_NOT_ALLOWED", "This method is not allowed for this resource."),
    413: ("REQUEST_TOO_LARGE", "The request is too large."),
}


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = HTTP_ERRORS.get(exc.status_code, ("REQUEST_FAILED", "The request could not be completed."))
    allow = {"Allow": exc.headers["Allow"]} if exc.headers and "Allow" in exc.headers else {}
    return await api_error_handler(request, ApiError(exc.status_code, code, message, headers=allow))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for item in exc.errors()[:50]:
        loc = ".".join(str(p) for p in item.get("loc", ()) if p not in ("body", "query", "path"))
        # Only safe field names and error types; never the submitted value.
        fields.append({"field": loc[:200], "code": str(item.get("type", "invalid"))[:100],
                       "message": "Invalid value."})
    err = ApiError(422, "VALIDATION_FAILED", "Some fields need attention.", field_errors=fields)
    note_error(request, 422, err.code)
    return JSONResponse(_body(request, err), status_code=422, headers=API_HEADERS)


LOG = logging.getLogger("aware_care")


class ContentFreeErrors(logging.Filter):
    """#156: uvicorn logs a re-raised exception with its traceback ("Exception in ASGI application"). Exception
    messages and tracebacks can carry request content, so the record keeps its message and the exception type only;
    `unhandled_error_handler` logs the request ID and route template."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            kind = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
            record.msg, record.args = f"{record.getMessage()} ({kind}; details withheld, content-free log)", ()
            record.exc_info = record.exc_text = None
            record.stack_info = None
        return True


def install_content_free_logging() -> None:
    for name in ("uvicorn.error", "uvicorn.asgi"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, ContentFreeErrors) for f in logger.filters):
            logger.addFilter(ContentFreeErrors())


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    err = ApiError(500, "INTERNAL_ERROR", "Something went wrong. Your entered information was kept.", retryable=True)
    route = getattr(request.scope.get("route"), "path", "unmatched")  # a template, never the raw path with IDs
    LOG.error("unhandled_error type=%s route=%s method=%s request_id=%s", type(exc).__name__, route, request.method,
              getattr(request.state, "request_id", None))
    note_error(request, 500, err.code)
    return JSONResponse(_body(request, err), status_code=500, headers=API_HEADERS)
