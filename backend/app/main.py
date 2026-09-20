"""PromptBench API application."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.api.routes.health import VERSION
from app.core.config import settings
from app.core.errors import ErrorCode, PromptBenchError, ProviderError
from app.core.logging import configure_logging, get_logger, redact
from app.db.session import dispose_db, init_db
from app.providers.registry import get_registry

configure_logging()
logger = get_logger(__name__)

DESCRIPTION = """
Local-first LLM prompt benchmarking.

Send one prompt to many models, then compare latency, token usage, estimated
cost and evaluated quality side by side.

* **Local first** — Ollama needs no API key, so the whole product works without
  a paid provider. Providers without credentials report as unavailable instead
  of failing the app.
* **Estimated costs** — every cost figure comes from an operator-maintained
  price table, not from provider billing. Unpriced models report
  "Pricing unavailable" rather than zero.
* **No secrets over the wire** — API keys stay in backend environment
  variables and are never returned by any endpoint.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    registry = get_registry()
    configured = [p.id for p in registry.all() if p.is_configured()]
    logger.info(
        "PromptBench %s starting (env=%s, providers configured: %s)",
        VERSION,
        settings.environment,
        ", ".join(configured) or "none",
    )
    try:
        yield
    finally:
        await registry.aclose()
        await dispose_db()
        logger.info("PromptBench shut down cleanly")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PromptBench API",
        description=DESCRIPTION,
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
        max_age=600,
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    _register_error_handlers(app)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": VERSION,
            "docs": "/docs",
            "api": settings.api_prefix,
        }

    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProviderError)
    async def provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
        payload = exc.to_payload()
        payload["message"] = exc.display_message()
        return JSONResponse(status_code=exc.status_code, content={"error": payload})

    @app.exception_handler(PromptBenchError)
    async def app_error_handler(_: Request, exc: PromptBenchError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_payload()})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in err.get("loc", []) if part != "body"),
                "message": err.get("msg", "invalid value"),
            }
            for err in exc.errors()
        ]
        first = details[0] if details else {"field": "", "message": "invalid request"}
        message = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": str(ErrorCode.INVALID_REQUEST),
                    "message": f"Request validation failed — {message}",
                    "details": details,
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.UNKNOWN
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": str(code), "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Correlate the opaque client-facing message with the full server log.
        incident = uuid.uuid4().hex[:12]
        logger.exception(
            "Unhandled error [%s] on %s %s", incident, request.method, request.url.path
        )
        message = "An unexpected server error occurred."
        if not settings.is_production:
            # Outside production, include the redacted detail to aid debugging.
            message = f"{message} {redact(f'{exc.__class__.__name__}: {exc}')}"
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": str(ErrorCode.UNKNOWN),
                    "message": message,
                    "incident_id": incident,
                }
            },
        )


app = create_app()
