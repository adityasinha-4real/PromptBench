"""OpenAI adapter (Chat Completions API).

Talks to the REST endpoint over ``httpx`` rather than the vendor SDK: one HTTP
client for every provider keeps timeout/retry/error handling uniform and avoids
four SDKs' worth of transitive dependencies. See ARCHITECTURE.md.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ErrorCode, ProviderError
from app.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    ModelInfo,
    ProviderStatus,
)
from app.providers.catalog import OPENAI_MODELS


class OpenAIProvider(LLMProvider):
    id = "openai"
    label = "OpenAI"
    api_key_env = "OPENAI_API_KEY"

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    async def get_models(self) -> list[ModelInfo]:
        return list(OPENAI_MODELS)

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                self.id, False, self.unavailable_reason(), ErrorCode.AUTHENTICATION
            )
        started = time.perf_counter()
        try:
            response = await self.client.get(
                f"{settings.openai_base_url}/models",
                headers=self._headers(),
                timeout=self._timeout(settings.connect_timeout_seconds * 2),
            )
        except httpx.HTTPError as exc:
            return ProviderStatus(
                self.id,
                False,
                f"Could not reach OpenAI: {exc.__class__.__name__}",
                ErrorCode.PROVIDER_UNAVAILABLE,
            )
        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            err = self._http_error(response, model=None)
            return ProviderStatus(self.id, False, err.message, err.code, latency)
        count = len((response.json() or {}).get("data") or [])
        return ProviderStatus(
            self.id,
            True,
            f"Authenticated. {count} models visible to this key.",
            None,
            latency,
            count,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.ensure_configured(request.model)

        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_completion_tokens": request.max_tokens,
        }
        # Reasoning models reject temperature/top_p overrides.
        if not request.model.startswith(("o1", "o3", "o4")):
            payload["temperature"] = request.temperature
            if request.top_p is not None:
                payload["top_p"] = request.top_p

        started = time.perf_counter()
        data, response = await self._post_json(
            f"{settings.openai_base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            model=request.model,
            timeout=request.timeout,
        )

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                "response contained no choices.",
                code=ErrorCode.UNKNOWN,
                provider=self.id,
                model=request.model,
            )
        choice = choices[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}

        return self.build_result(
            request=request,
            text=text,
            started=started,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
            metadata={
                "request_id": response.headers.get("x-request-id") or data.get("id"),
                "response_id": data.get("id"),
                "model_returned": data.get("model"),
                "system_fingerprint": data.get("system_fingerprint"),
                "service_tier": data.get("service_tier"),
                "usage": usage,
            },
        )
