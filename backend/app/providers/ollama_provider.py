"""Ollama adapter — local models, no API key, no cost.

This is the provider that makes PromptBench usable with zero paid credentials.
Unlike the hosted adapters it lists models live from ``/api/tags``, because the
set of available models is whatever the user has pulled.
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

#: Ollama is polled often (model page, health, picker); a short TTL keeps the UI
#: responsive without hammering the daemon.
_TAGS_CACHE_TTL_SECONDS = 15.0


def _humanise(model_id: str) -> str:
    base = model_id.split(":", 1)[0]
    return base.replace("-", " ").replace("_", " ").title()


class OllamaProvider(LLMProvider):
    id = "ollama"
    label = "Ollama (local)"
    is_local = True
    api_key_env = None

    def __init__(self) -> None:
        super().__init__()
        self._tags_cache: tuple[float, list[ModelInfo]] | None = None

    def is_configured(self) -> bool:
        # No credential required; reachability is checked at call time.
        return bool(settings.ollama_base_url)

    def unavailable_reason(self) -> str:
        return f"Ollama is not reachable at {settings.ollama_base_url}."

    async def _fetch_tags(self) -> list[dict[str, Any]]:
        try:
            response = await self.client.get(
                f"{settings.ollama_base_url}/api/tags",
                timeout=self._timeout(settings.connect_timeout_seconds),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"could not reach the Ollama daemon at {settings.ollama_base_url}.",
                code=ErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.id,
            ) from exc
        if response.status_code >= 400:
            raise self._http_error(response, model=None)
        return (response.json() or {}).get("models") or []

    async def get_models(self) -> list[ModelInfo]:
        """Models currently pulled locally. Returns ``[]`` when Ollama is down."""
        now = time.monotonic()
        if self._tags_cache and now - self._tags_cache[0] < _TAGS_CACHE_TTL_SECONDS:
            return self._tags_cache[1]
        try:
            raw = await self._fetch_tags()
        except ProviderError:
            return []

        models: list[ModelInfo] = []
        for entry in raw:
            name = entry.get("name") or entry.get("model")
            if not name:
                continue
            details = entry.get("details") or {}
            size_gb = round((entry.get("size") or 0) / 1_000_000_000, 2)
            bits = [
                b for b in (details.get("parameter_size"), details.get("quantization_level")) if b
            ]
            if size_gb:
                bits.append(f"{size_gb} GB")
            models.append(
                ModelInfo(
                    provider=self.id,
                    id=name,
                    label=_humanise(name),
                    description=" · ".join(bits) or None,
                    local=True,
                )
            )
        models.sort(key=lambda m: m.id)
        self._tags_cache = (now, models)
        return models

    async def test_connection(self) -> ProviderStatus:
        started = time.perf_counter()
        try:
            raw = await self._fetch_tags()
        except ProviderError as exc:
            return ProviderStatus(
                self.id,
                False,
                f"{exc.message} Start it with `ollama serve`, then pull a model "
                f"(e.g. `ollama pull llama3.2`).",
                exc.code,
            )
        latency = int((time.perf_counter() - started) * 1000)
        count = len(raw)
        if count == 0:
            return ProviderStatus(
                self.id,
                True,
                "Ollama is running but no models are pulled. Try `ollama pull llama3.2`.",
                None,
                latency,
                0,
            )
        return ProviderStatus(
            self.id, True, f"Ollama is running with {count} local model(s).", None, latency, count
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        options: dict[str, Any] = {
            "temperature": request.temperature,
            "num_predict": request.max_tokens,
        }
        if request.top_p is not None:
            options["top_p"] = request.top_p

        payload = {
            "model": request.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        started = time.perf_counter()
        data, _ = await self._post_json(
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
            model=request.model,
            timeout=request.timeout,
        )

        if data.get("error"):
            raise ProviderError(
                str(data["error"])[:400],
                code=ErrorCode.INVALID_REQUEST,
                provider=self.id,
                model=request.model,
                retryable=False,
            )

        text = (data.get("message") or {}).get("content") or ""
        eval_duration_ns = data.get("eval_duration")

        return self.build_result(
            request=request,
            text=text,
            started=started,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            finish_reason=data.get("done_reason"),
            metadata={
                "model_returned": data.get("model"),
                "total_duration_ms": _ns_to_ms(data.get("total_duration")),
                "load_duration_ms": _ns_to_ms(data.get("load_duration")),
                "prompt_eval_duration_ms": _ns_to_ms(data.get("prompt_eval_duration")),
                "eval_duration_ms": _ns_to_ms(eval_duration_ns),
                "created_at": data.get("created_at"),
            },
        )


def _ns_to_ms(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(value / 1_000_000, 2)
