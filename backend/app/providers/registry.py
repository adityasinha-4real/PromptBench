"""Provider registry.

Registering a new provider is a one-line change here plus one adapter module.
Nothing else in the application enumerates providers.
"""

from __future__ import annotations

import asyncio

from app.core.errors import ErrorCode, ProviderError
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider, ModelInfo, ProviderStatus
from app.providers.gemini_provider import GeminiProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.openai_provider import OpenAIProvider

_PROVIDER_CLASSES: tuple[type[LLMProvider], ...] = (
    OllamaProvider,  # local-first: listed first in the UI
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
)


class ProviderRegistry:
    """Holds one long-lived adapter instance per provider."""

    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        instances = providers if providers is not None else [cls() for cls in _PROVIDER_CLASSES]
        self._providers: dict[str, LLMProvider] = {p.id: p for p in instances}

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.id] = provider

    def all(self) -> list[LLMProvider]:
        return list(self._providers.values())

    def ids(self) -> list[str]:
        return list(self._providers)

    def get(self, provider_id: str) -> LLMProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderError(
                f"unknown provider '{provider_id}'. Known providers: {', '.join(self._providers)}.",
                code=ErrorCode.INVALID_REQUEST,
                provider=provider_id,
                retryable=False,
            ) from None

    async def list_models(self) -> dict[str, list[ModelInfo]]:
        """Models for every provider, fetched concurrently. Never raises."""
        providers = self.all()
        results = await asyncio.gather(*(p.get_models() for p in providers), return_exceptions=True)
        out: dict[str, list[ModelInfo]] = {}
        for provider, result in zip(providers, results, strict=True):
            out[provider.id] = [] if isinstance(result, BaseException) else result
        return out

    async def statuses(self) -> dict[str, ProviderStatus]:
        """Connectivity status for every provider, checked concurrently."""
        providers = self.all()
        results = await asyncio.gather(
            *(p.test_connection() for p in providers), return_exceptions=True
        )
        out: dict[str, ProviderStatus] = {}
        for provider, result in zip(providers, results, strict=True):
            if isinstance(result, BaseException):
                out[provider.id] = ProviderStatus(
                    provider.id,
                    False,
                    f"Status check failed: {result.__class__.__name__}",
                    ErrorCode.UNKNOWN,
                )
            else:
                out[provider.id] = result
        return out

    async def aclose(self) -> None:
        await asyncio.gather(*(p.aclose() for p in self.all()), return_exceptions=True)


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Process-wide registry singleton (also the FastAPI dependency)."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def set_registry(registry: ProviderRegistry | None) -> None:
    """Swap the registry — used by tests to inject fake providers."""
    global _registry
    _registry = registry
