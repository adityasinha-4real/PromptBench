"""Anthropic adapter (Messages API)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ErrorCode
from app.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    ModelInfo,
    ProviderStatus,
)
from app.providers.catalog import ANTHROPIC_MODELS


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic"
    api_key_env = "ANTHROPIC_API_KEY"

    def is_configured(self) -> bool:
        return bool(settings.anthropic_api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": settings.anthropic_version,
            "Content-Type": "application/json",
        }

    async def get_models(self) -> list[ModelInfo]:
        return list(ANTHROPIC_MODELS)

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                self.id, False, self.unavailable_reason(), ErrorCode.AUTHENTICATION
            )
        started = time.perf_counter()
        try:
            response = await self.client.get(
                f"{settings.anthropic_base_url}/models",
                headers=self._headers(),
                timeout=self._timeout(settings.connect_timeout_seconds * 2),
            )
        except httpx.HTTPError as exc:
            return ProviderStatus(
                self.id,
                False,
                f"Could not reach Anthropic: {exc.__class__.__name__}",
                ErrorCode.PROVIDER_UNAVAILABLE,
            )
        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            err = self._http_error(response, model=None)
            return ProviderStatus(self.id, False, err.message, err.code, latency)
        count = len((response.json() or {}).get("data") or [])
        return ProviderStatus(
            self.id, True, f"Authenticated. {count} models available.", None, latency, count
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.ensure_configured(request.model)

        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if request.top_p is not None:
            payload["top_p"] = request.top_p

        started = time.perf_counter()
        data, response = await self._post_json(
            f"{settings.anthropic_base_url}/messages",
            json=payload,
            headers=self._headers(),
            model=request.model,
            timeout=request.timeout,
        )

        # `content` is a list of typed blocks; concatenate the text ones.
        text = "".join(
            block.get("text", "")
            for block in (data.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = data.get("usage") or {}

        return self.build_result(
            request=request,
            text=text,
            started=started,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            finish_reason=data.get("stop_reason"),
            metadata={
                "request_id": response.headers.get("request-id"),
                "response_id": data.get("id"),
                "model_returned": data.get("model"),
                "stop_sequence": data.get("stop_sequence"),
                "usage": usage,
            },
        )
