"""Read-only settings surface.

Deliberately read-only for credentials: API keys live in environment variables,
never in the database and never in an API response. This endpoint reports which
variables are *set* and what the effective limits are, so the Settings page can
tell the user exactly what to configure without ever handling a secret.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import provider_registry
from app.core.config import settings
from app.core.pricing import get_pricing_table, pricing_metadata, reload_pricing_table
from app.evaluation.factory import available_modes
from app.providers.registry import ProviderRegistry

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", summary="Effective configuration (no secrets)")
async def get_settings_view(
    registry: ProviderRegistry = Depends(provider_registry),
) -> dict[str, Any]:
    table = get_pricing_table()
    return {
        "application": {
            "name": settings.app_name,
            "environment": settings.environment,
            "debug": settings.debug,
            "database_backend": settings.database_url.split(":", 1)[0],
            "cors_origins": settings.cors_origin_list,
        },
        "providers": [
            {
                "id": provider.id,
                "label": provider.label,
                "is_local": provider.is_local,
                "api_key_env": provider.api_key_env,
                # Only ever a boolean — the value itself never leaves the backend.
                "credential_present": provider.is_configured(),
                "base_url": _base_url_for(provider.id),
            }
            for provider in registry.all()
        ],
        "evaluation": {
            "modes": available_modes(),
            "default_mode": settings.evaluation_default_mode,
            "judge_provider": settings.judge_provider,
            "judge_model": settings.judge_model,
        },
        "pricing": {
            **pricing_metadata(),
            "file": str(settings.pricing_path),
            "models_priced": sum(len(models) for models in table.providers.values()),
            "table": {
                provider: {
                    model: {
                        "input_per_1m": price.input_per_1m,
                        "output_per_1m": price.output_per_1m,
                        "note": price.note,
                    }
                    for model, price in models.items()
                }
                for provider, models in table.providers.items()
            },
        },
        "limits": {
            "max_prompt_chars": settings.max_prompt_chars,
            "max_system_prompt_chars": settings.max_system_prompt_chars,
            "max_output_tokens": settings.max_output_tokens_limit,
            "max_models_per_benchmark": settings.max_models_per_benchmark,
            "max_variants_per_benchmark": settings.max_variants_per_benchmark,
            "max_concurrency": settings.max_concurrency,
            "request_timeout_seconds": settings.request_timeout_seconds,
            "max_retries": settings.max_retries,
        },
    }


@router.post("/pricing/reload", summary="Reload the pricing table from disk")
async def reload_pricing() -> dict[str, Any]:
    """Picks up edits to ``pricing.json`` without restarting the API."""
    table = reload_pricing_table()
    return {
        "reloaded": True,
        "as_of": table.as_of,
        "models_priced": sum(len(models) for models in table.providers.values()),
    }


def _base_url_for(provider_id: str) -> str | None:
    return {
        "openai": settings.openai_base_url,
        "anthropic": settings.anthropic_base_url,
        "gemini": settings.gemini_base_url,
        "ollama": settings.ollama_base_url,
    }.get(provider_id)
