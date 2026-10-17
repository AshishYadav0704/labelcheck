"""ASGI application factory (Starlette).

Run locally (from the backend folder):
    uvicorn app.main:app --reload
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings, get_settings
from .db import Database
from .ratelimit import RateLimiter
from .routers import api
from .services.ai import AIClient, AIError, build_ai_client
from .services.label import LabelError
from .services.ocr import OCRReader
from .services.openfoodfacts import OpenFoodFactsClient, OpenFoodFactsError
from .services.report import ReportService
from .services.standards import get_standards

log = logging.getLogger("labelcheck")

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https://*.openfoodfacts.org; "
    "media-src 'self' blob:; "
    "connect-src 'self' https://cdn.jsdelivr.net; "
    "worker-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def error_response(status: int, message: str, request_id: str | None = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": message}
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=status, content=body, headers=headers)


class RequestContextMiddleware:
    """Request IDs, upload size guard, security headers and access logs.

    Pure ASGI (not BaseHTTPMiddleware) so video files stream without buffering."""

    def __init__(self, app: ASGIApp, max_body: int, hsts: bool):
        self.app = app
        self.max_body = max_body
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = request_id
        path: str = scope["path"]
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > self.max_body:
            await error_response(413, "Upload too large.", request_id)(scope, receive, send)
            return

        # Uploads without Content-Length (chunked) are counted as they stream in;
        # the HTTPException becomes a JSON 413 via the app's exception handler.
        received = 0
        max_body = self.max_body

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_body:
                    raise HTTPException(status_code=413, detail="Upload too large.")
            return message

        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = request_id
                h["X-Content-Type-Options"] = "nosniff"
                h["Referrer-Policy"] = "strict-origin-when-cross-origin"
                h["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
                if self.hsts:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                if path.startswith("/api/"):
                    if "cache-control" not in h:
                        h["Cache-Control"] = "no-store"
                else:
                    h["Content-Security-Policy"] = CSP
                    h["X-Frame-Options"] = "DENY"
            await send(message)

        try:
            await self.app(scope, limited_receive, send_with_headers)
        finally:
            if path.startswith("/api/"):
                log.info("%s %s %s %.0fms rid=%s", scope["method"], path, status["code"],
                         (time.perf_counter() - started) * 1000, request_id)


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _label_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(getattr(exc, "status", 422), str(exc), _rid(request))


async def _off_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(503, "Product database temporarily unavailable.", _rid(request))


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    return error_response(exc.status_code, str(exc.detail), _rid(request), dict(exc.headers or {}))


async def _input_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, str(exc), _rid(request))


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    rid = _rid(request)
    log.exception("Unhandled error rid=%s", rid)
    return error_response(500, "Something went wrong on our side. Please try again.", rid)


def create_app(settings: Settings | None = None, *, ai: AIClient | None = None,
               off: OpenFoodFactsClient | None = None, ocr: OCRReader | None = None) -> Starlette:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    standards = get_standards()
    db = Database(settings.db_path)
    db.cache_prune()
    ai = ai or build_ai_client(settings)
    ocr = ocr or OCRReader(settings.ocr_enabled, settings.ocr_languages)
    off = off or OpenFoodFactsClient(settings, db)
    reports = ReportService(settings, db, ai, off, standards)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        log.info("LabelCheck %s starting (env=%s, label reader=%s, ocr=%s)", api.APP_VERSION, settings.app_env,
                 ai.provider if ai.enabled else "none", "on" if ocr.enabled else "off")
        yield
        reports.close()
        db.close()

    routes: list[Any] = list(api.routes)
    web_dir = settings.web_dir
    if web_dir.is_dir():
        index = web_dir / "index.html"

        async def spa(request: Request) -> FileResponse:
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        routes.append(Route("/r/{report_id}", spa, methods=["GET"]))
        routes.append(Mount("/", app=StaticFiles(directory=web_dir, html=True), name="web"))
    else:
        log.warning("Web app folder not found at %s; serving the API only.", web_dir)

    max_body = settings.max_upload_mb * settings.max_images * 1024 * 1024 + 1024 * 1024
    middleware = [Middleware(RequestContextMiddleware, max_body=max_body, hsts=settings.is_production)]
    if settings.cors_origins:
        middleware.append(Middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                                     allow_headers=["*"], max_age=3600))

    app = Starlette(
        routes=routes,
        middleware=middleware,
        exception_handlers={
            LabelError: _label_error,
            AIError: _label_error,
            OpenFoodFactsError: _off_error,
            HTTPException: _http_error,
            api.InputError: _input_error,
            json.JSONDecodeError: _input_error,
            Exception: _unhandled,
        },
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.standards = standards
    app.state.db = db
    app.state.ai = ai
    app.state.ocr = ocr
    app.state.off = off
    app.state.reports = reports
    app.state.limiter = RateLimiter()
    return app


app = create_app()
