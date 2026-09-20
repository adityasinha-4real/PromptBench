"""Provider/model discovery and connection testing."""

from __future__ import annotations

import asyncio

from app.core.errors import ErrorCode, ProviderError
from app.core.pricing import pricing_metadata
from app.providers.base import GenerationRequest
from app.providers.registry import ProviderRegistry
from app.schemas.model import (
    ModelOut,
    ModelsResponse,
    PricingOut,
    ProviderOut,
    TestConnectionResponse,
)

#: A one-token generation is enough to prove a specific model id actually works.
PROBE_PROMPT = "Reply with the single word: ok"
PROBE_MAX_TOKENS = 5


async def list_models(registry: ProviderRegistry, *, probe: bool = True) -> ModelsResponse:
    """All providers with their models and live availability.

    ``probe=False`` skips network checks and reports configuration only — used
    by the health endpoint, which must stay fast.
    """
    providers = registry.all()

    if probe:
        statuses, model_map = await asyncio.gather(registry.statuses(), registry.list_models())
    else:
        statuses = {}
        model_map = {p.id: [] for p in providers}

    provider_rows: list[ProviderOut] = []
    all_models: list[ModelOut] = []

    for provider in providers:
        status = statuses.get(provider.id)
        configured = provider.is_configured()
        available = bool(status.available) if status else configured
        if status is not None:
            detail = status.detail
        else:
            detail = "Configured." if configured else provider.unavailable_reason()

        models: list[ModelOut] = []
        for info in model_map.get(provider.id, []):
            pricing = info.pricing_dict()
            models.append(
                ModelOut(
                    provider=info.provider,
                    id=info.id,
                    label=info.label,
                    context_window=info.context_window,
                    description=info.description,
                    local=info.local,
                    pricing=PricingOut(**pricing) if pricing else None,
                    available=available,
                )
            )

        provider_rows.append(
            ProviderOut(
                id=provider.id,
                label=provider.label,
                is_local=provider.is_local,
                configured=configured,
                available=available,
                status_detail=detail,
                api_key_env=provider.api_key_env,
                error_code=str(status.code) if status and status.code else None,
                latency_ms=status.latency_ms if status else None,
                models=models,
            )
        )
        all_models.extend(models)

    return ModelsResponse(providers=provider_rows, models=all_models, pricing=pricing_metadata())


async def test_connection(
    registry: ProviderRegistry, provider_id: str, model: str | None = None
) -> TestConnectionResponse:
    """Check a provider, and optionally prove one model id with a tiny generation."""
    try:
        provider = registry.get(provider_id)
    except ProviderError as exc:
        return TestConnectionResponse(
            provider=provider_id,
            model=model,
            available=False,
            detail=exc.message,
            error_code=str(exc.code),
        )

    status = await provider.test_connection()
    response = TestConnectionResponse(
        provider=provider.id,
        model=model,
        available=status.available,
        detail=status.detail,
        error_code=str(status.code) if status.code else None,
        latency_ms=status.latency_ms,
        model_count=status.model_count,
    )

    if not model or not status.available:
        return response

    try:
        result = await provider.generate(
            GenerationRequest(
                model=model,
                prompt=PROBE_PROMPT,
                temperature=0.0,
                max_tokens=PROBE_MAX_TOKENS,
                timeout=45.0,
            )
        )
    except ProviderError as exc:
        response.available = False
        response.generation_ok = False
        response.error_code = str(exc.code)
        response.detail = exc.display_message()
        return response
    except Exception:
        response.available = False
        response.generation_ok = False
        response.error_code = str(ErrorCode.UNKNOWN)
        response.detail = f"{provider.label} probe failed unexpectedly."
        return response

    response.generation_ok = True
    response.latency_ms = result.latency_ms
    response.detail = f"{provider.label} responded with '{model}' in {result.latency_ms} ms."
    return response
