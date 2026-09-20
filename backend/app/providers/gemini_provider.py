"""Google Gemini adapter (Generative Language API).

The key is sent in the ``x-goog-api-key`` header rather than as a query
parameter so it never lands in a URL, proxy log or error string.
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
from app.providers.catalog import GEMINI_MODELS


class GeminiProvider(LLMProvider):
    id = "gemini"
    label = "Google Gemini"
    api_key_env = "GEMINI_API_KEY"

    def is_configured(self) -> bool:
        return bool(settings.gemini_api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": settings.gemini_api_key or "",
            "Content-Type": "application/json",
        }

    async def get_models(self) -> list[ModelInfo]:
        return list(GEMINI_MODELS)

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                self.id, False, self.unavailable_reason(), ErrorCode.AUTHENTICATION
            )
        started = time.perf_counter()
        try:
            response = await self.client.get(
                f"{settings.gemini_base_url}/models",
                headers=self._headers(),
                timeout=self._timeout(settings.connect_timeout_seconds * 2),
            )
        except httpx.HTTPError as exc:
            return ProviderStatus(
                self.id,
                False,
                f"Could not reach Gemini: {exc.__class__.__name__}",
                ErrorCode.PROVIDER_UNAVAILABLE,
            )
        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            err = self._http_error(response, model=None)
            return ProviderStatus(self.id, False, err.message, err.code, latency)
        count = len((response.json() or {}).get("models") or [])
        return ProviderStatus(
            self.id, True, f"Authenticated. {count} models available.", None, latency, count
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.ensure_configured(request.model)

        generation_config: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.top_p is not None:
            generation_config["topP"] = request.top_p

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": generation_config,
        }
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}

        model_path = (
            request.model if request.model.startswith("models/") else f"models/{request.model}"
        )

        started = time.perf_counter()
        data, response = await self._post_json(
            f"{settings.gemini_base_url}/{model_path}:generateContent",
            json=payload,
            headers=self._headers(),
            model=request.model,
            timeout=request.timeout,
        )

        candidates = data.get("candidates") or []
        if not candidates:
            # Gemini reports prompt-level blocks here instead of as an HTTP error.
            feedback = data.get("promptFeedback") or {}
            reason = feedback.get("blockReason")
            raise ProviderError(
                f"prompt was blocked ({reason})."
                if reason
                else "response contained no candidates.",
                code=ErrorCode.CONTENT_FILTER if reason else ErrorCode.UNKNOWN,
                provider=self.id,
                model=request.model,
                retryable=False,
            )

        candidate = candidates[0]
        text = "".join(
            part.get("text", "")
            for part in ((candidate.get("content") or {}).get("parts") or [])
            if isinstance(part, dict)
        )
        usage = data.get("usageMetadata") or {}

        return self.build_result(
            request=request,
            text=text,
            started=started,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            finish_reason=candidate.get("finishReason"),
            metadata={
                "request_id": response.headers.get("x-goog-request-id"),
                "model_returned": data.get("modelVersion"),
                "safety_ratings": candidate.get("safetyRatings"),
                "prompt_feedback": data.get("promptFeedback"),
                "usage": usage,
            },
        )
