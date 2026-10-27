"""Aware Care API entry point: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.

Mounts the 31 baseline operations under /api/v1. Default AWARECARE_MODE=mock
uses the synthetic fixture pack and never contacts ZRT. Local mode selects the
ZRT adapter and serves guidance only while the reviewed pathway (ADR-003) is
active; otherwise it reports unavailable instead of falling back to mock or
cloud output.
"""
from __future__ import annotations

import re
import secrets
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, load_settings
from app.core.context import AppContext
from app.core.db import Database
from app.core.errors import (API_HEADERS, ApiError, api_error_handler, http_error_handler,
                             install_content_free_logging, unhandled_error_handler, validation_error_handler)
from app.core.security import COOKIE_PATH, _load_session
from app.core.fixtures import load_fixture_pack
from app.modules.safety.pathway import load_registry
from app.modules.operations.telemetry import record_release_start
from app.runtime.metering import MeteredRuntime
from app.modules.access import routes as access_routes
from app.modules.access.service import PRESESSION_COOKIE
from app.modules.cases import routes as cases_routes
from app.modules.evidence import routes as evidence_routes
from app.modules.exports import routes as exports_routes
from app.modules.guidance import routes as guidance_routes
from app.modules.intake import routes as intake_routes
from app.modules.operations import routes as operations_routes
from app.modules.operations.service import JobRunner, recover_interrupted
from app.modules.privacy import routes as privacy_routes
from app.modules.privacy.service import Sweeper, remove_orphan_files
from app.modules.profiles import routes as profiles_routes
from app.modules.providers import routes as providers_routes
from app.modules.records import routes as records_routes
from app.runtime.mock_provider import MockRuntimeAdapter
from app.runtime.zrt_provider import ZrtRuntimeAdapter

API_PREFIX = "/api/v1"
JSON_BODY_LIMIT = 256 * 1024
UPLOAD_BODY_LIMIT = 3 * 10 * 1024 * 1024
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# #431: the 30 MiB allowance belongs to one operation, uploadRecord (POST /cases/{case_id}/records), matched by method
# and the whole route. Every other request, whatever its last path segment, is capped at 256 KiB.
UPLOAD_ROUTE = re.compile(rf"{API_PREFIX}/cases/[^/]+/records")


def body_limit(method: str, path: str) -> int:
    return UPLOAD_BODY_LIMIT if method == "POST" and UPLOAD_ROUTE.fullmatch(path) else JSON_BODY_LIMIT


def _refusal(status: int, code: str, message: str, request_id: str | None = None) -> JSONResponse:
    request_id = request_id or str(uuid.uuid4())
    body = {"code": code, "message": message, "field_errors": [], "retryable": False, "request_id": request_id}
    return JSONResponse(body, status_code=status, headers={**API_HEADERS, "X-Request-ID": request_id})


async def _upload_without_session(scope) -> bool:
    """#431: an upload is refused before its body is read when no valid session sent it. The lookup is the session
    dependency's own (without touching the session) and runs in a worker thread, off the event loop."""
    request = Request(scope)
    ctx = request.app.state.ctx
    return await run_in_threadpool(lambda: _load_session(request, ctx, touch=False) is None)


class BodyPolicy:
    """Request-body policy, run before any route reads or parses a body (#156, #269, #431):

    - a Content-Length that is not a number is a malformed request (400 MALFORMED_REQUEST, #269);
    - a declared length past the route's limit is refused at once (413 REQUEST_TOO_LARGE);
    - an upload without a valid session is refused (401 SESSION_REQUIRED) before its body is read;
    - a chunked body (no Content-Length, #156) is read only up to the route's limit and answered 413 past it; within
      the limit it is replayed to the app unchanged.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = body_limit(scope["method"], scope["path"])
        length = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"content-length"), None)
        if length is not None and not (length.isascii() and length.isdigit()):
            return await _refusal(400, "MALFORMED_REQUEST", "The request is malformed.")(scope, receive, send)
        if length is not None and int(length) > limit:
            return await _refusal(413, "REQUEST_TOO_LARGE", "The request is too large.")(scope, receive, send)
        if scope["method"] not in WRITE_METHODS:
            return await self.app(scope, receive, send)
        if limit == UPLOAD_BODY_LIMIT and await _upload_without_session(scope):
            return await _refusal(401, "SESSION_REQUIRED", "Your session has ended. Start again to continue.")(
                scope, receive, send)
        if length is not None:
            return await self.app(scope, receive, send)
        messages, total = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                messages.append(message)
                break
            total += len(message.get("body", b""))
            if total > limit:
                return await _refusal(413, "REQUEST_TOO_LARGE", "The request is too large.")(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        return await self.app(scope, replay, send)


class HeadAsGet:
    """#464 (RFC 9110 9.1): HEAD on a resource is answered as GET would be, without the body. The routes declare GET
    only; this layer runs the GET and drops the body, keeping the status and every header (Content-Length included)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "HEAD":
            return await self.app(scope, receive, send)

        async def headers_only(message):
            if message["type"] == "http.response.body":
                if message.get("more_body", False):
                    return
                message = {"type": "http.response.body", "body": b"", "more_body": False}
            await send(message)

        return await self.app({**scope, "method": "GET"}, receive, headers_only)


def build_context(settings: Settings) -> AppContext:
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = Database(settings.data_dir / "awarecare.sqlite3", mode=settings.mode)
    # Both modes load the synthetic pack. Local mode uses its fictional provider directory (ADR-004) and, for presenter
    # scenarios, only each scenario's synthetic concern and checklist answer; the rest runs live (ADR-016). Scripted
    # records, scripted outcomes and the mock adapter stay mock-only.
    fixtures = load_fixture_pack(settings.fixtures_dir)
    pathway = load_registry(settings.pathways_dir)
    adapter = (MockRuntimeAdapter(fixtures) if settings.mode == "mock"
               else ZrtRuntimeAdapter(settings.model_base_url, settings.model_id, settings.model_manifest,
                                   settings.model_catalog))
    # W06 telemetry (ADR-017): every model call is metered content-free; power comes from the host sampler's files.
    runtime = MeteredRuntime(adapter, db, settings.mode, settings.data_dir / "power")
    record_release_start(db)
    jobs = JobRunner(settings.active_generation_limit, settings.queued_generation_limit,
                     settings.queue_retry_after_seconds)
    return AppContext(settings=settings, db=db, fixtures=fixtures, pathway=pathway, runtime=runtime, jobs=jobs)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = build_context(settings)
        app.state.ctx = ctx
        # #263/#272: settle the work a previous process left unfinished and remove files no row references, before
        # the first request (no worker is running yet, so nothing is being written).
        recover_interrupted(ctx)
        remove_orphan_files(ctx, min_age_s=0)
        sweeper = Sweeper(ctx)
        sweeper.start()
        try:
            yield
        finally:
            sweeper.stop()
            ctx.jobs.shutdown()
            ctx.db.close()

    app = FastAPI(title="Aware Care API", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def transport_policy(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        request.state.csrf_token = None
        request.state.session_expires_at = None
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        for name, value in API_HEADERS.items():  # #465: no-store and the browser hardening on every API response
            response.headers.setdefault(name, value)
        if request.state.csrf_token and "X-CSRF-Token" not in response.headers:
            response.headers["X-CSRF-Token"] = request.state.csrf_token
        if request.state.session_expires_at and response.status_code != 401:
            response.headers["X-Session-Expires-At"] = request.state.session_expires_at
        if PRESESSION_COOKIE not in request.cookies and request.url.path.startswith("/api/"):
            response.set_cookie(PRESESSION_COOKIE, secrets.token_urlsafe(24), httponly=True, samesite="strict",
                                secure=settings.cookie_secure, path=COOKIE_PATH)
        return response

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # #464
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_middleware(BodyPolicy)  # runs before any route reads the body
    app.add_middleware(HeadAsGet)  # outermost: HEAD becomes a GET without a body
    install_content_free_logging()
    for module in (access_routes, profiles_routes, cases_routes, intake_routes, records_routes, guidance_routes,
                   evidence_routes, providers_routes, exports_routes, privacy_routes, operations_routes):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
