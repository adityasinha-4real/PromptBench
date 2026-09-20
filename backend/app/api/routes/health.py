"""Health and readiness."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, provider_registry
from app.core.config import settings
from app.core.pricing import pricing_metadata
from app.providers.registry import ProviderRegistry
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])

VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness and configuration check")
async def health(
    session: AsyncSession = Depends(db_session),
    registry: ProviderRegistry = Depends(provider_registry),
) -> HealthResponse:
    """Reports process, database and provider-configuration state.

    Deliberately performs no outbound provider calls, so it stays fast and
    works offline. Use ``POST /api/models/test`` for real connectivity checks.
    """
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        database = f"unavailable: {exc.__class__.__name__}"

    providers = {p.id: p.is_configured() for p in registry.all()}
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=VERSION,
        environment=settings.environment,
        database=database,
        providers=providers,
        details={
            "local_providers": [p.id for p in registry.all() if p.is_local],
            "any_provider_configured": any(providers.values()),
            "pricing": pricing_metadata(),
            "limits": {
                "max_prompt_chars": settings.max_prompt_chars,
                "max_output_tokens": settings.max_output_tokens_limit,
                "max_models_per_benchmark": settings.max_models_per_benchmark,
                "max_variants_per_benchmark": settings.max_variants_per_benchmark,
                "max_concurrency": settings.max_concurrency,
                "request_timeout_seconds": settings.request_timeout_seconds,
            },
        },
    )
