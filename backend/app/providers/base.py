"""Provider adapter interface.

Everything above this layer — the benchmark engine, the API, the UI — speaks
only in :class:`GenerationRequest` / :class:`GenerationResult`. Adding a
provider means writing one subclass of :class:`LLMProvider` and registering it;
no engine code changes.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ErrorCode, ProviderError, classify_http_status
from app.core.logging import get_logger, redact
from app.core.pricing import estimate_cost, get_price

logger = get_logger(__name__)

#: Characters per token for the fallback estimator. Roughly correct for English
#: across GPT/Claude/Gemini tokenizers; results are flagged ``token_source="estimated"``.
CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Rough token count used only when a provider reports no usage data."""
    if not text:
        return 0
    return max(1, round(len(text) / CHARS_PER_TOKEN))


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Provider-agnostic generation request."""

    model: str
    prompt: str
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float | None = None
    timeout: float | None = None

    def as_params(self) -> dict[str, Any]:
        """Parameter snapshot recorded alongside the result."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "has_system_prompt": bool(self.system_prompt),
        }


@dataclass(slots=True)
class GenerationResult:
    """Normalised successful generation, identical in shape for every provider."""

    provider: str
    model: str
    response: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    tokens_per_second: float
    estimated_cost: float | None
    finish_reason: str | None = None
    #: ``"provider"`` when usage came from the API, ``"estimated"`` when derived.
    token_source: str = "provider"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "response": self.response,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "tokens_per_second": self.tokens_per_second,
            "estimated_cost": self.estimated_cost,
            "finish_reason": self.finish_reason,
            "token_source": self.token_source,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """A model a provider can serve."""

    provider: str
    id: str
    label: str
    context_window: int | None = None
    description: str | None = None
    local: bool = False

    def pricing_dict(self) -> dict[str, Any] | None:
        price = get_price(self.provider, self.id)
        if price is None:
            return None
        return {
            "input_per_1m": price.input_per_1m,
            "output_per_1m": price.output_per_1m,
            "note": price.note,
        }


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Result of a connectivity / configuration check."""

    provider: str
    available: bool
    detail: str
    code: ErrorCode | None = None
    latency_ms: int | None = None
    model_count: int | None = None


class LLMProvider(abc.ABC):
    """Abstract adapter every provider implements."""

    #: Stable machine id used in the database and the API.
    id: str = "base"
    #: Human label for the UI.
    label: str = "Base"
    #: True when the provider runs on the user's machine (no API key, no cost).
    is_local: bool = False
    #: Environment variable holding this provider's credential, if any.
    api_key_env: str | None = None

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    # ---- configuration -------------------------------------------------
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True when the adapter has everything it needs to attempt a call."""

    def unavailable_reason(self) -> str:
        if self.api_key_env:
            return f"{self.api_key_env} is not set."
        return "Provider is not configured."

    # ---- capabilities ---------------------------------------------------
    @abc.abstractmethod
    async def get_models(self) -> list[ModelInfo]:
        """Models this provider can serve right now."""

    @abc.abstractmethod
    async def test_connection(self) -> ProviderStatus:
        """Check credentials / reachability without running a generation."""

    @abc.abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Run one generation and return a normalised result.

        Raises:
            ProviderError: for every failure mode, already classified.
        """

    # ---- shared helpers --------------------------------------------------
    def _timeout(self, override: float | None = None) -> httpx.Timeout:
        total = override or settings.request_timeout_seconds
        return httpx.Timeout(total, connect=settings.connect_timeout_seconds)

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily created, connection-pooled HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout(),
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
                follow_redirects=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def ensure_configured(self, model: str | None = None) -> None:
        if not self.is_configured():
            raise ProviderError(
                self.unavailable_reason(),
                code=ErrorCode.AUTHENTICATION,
                provider=self.id,
                model=model,
                retryable=False,
            )

    async def _post_json(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], httpx.Response]:
        """POST JSON and translate every transport/HTTP failure into ProviderError."""
        try:
            response = await self.client.post(
                url, json=json, headers=headers, timeout=self._timeout(timeout)
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"request timed out after {timeout or settings.request_timeout_seconds:.0f}s.",
                code=ErrorCode.TIMEOUT,
                provider=self.id,
                model=model,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"could not connect to {self.label}.",
                code=ErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.id,
                model=model,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"network error: {redact(str(exc)) or exc.__class__.__name__}",
                code=ErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.id,
                model=model,
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response, model=model)

        try:
            return response.json(), response
        except ValueError as exc:
            raise ProviderError(
                "response was not valid JSON.",
                code=ErrorCode.UNKNOWN,
                provider=self.id,
                model=model,
            ) from exc

    def _http_error(self, response: httpx.Response, *, model: str | None) -> ProviderError:
        body = response.text[:2000]
        code = classify_http_status(response.status_code, body)
        message = self._extract_error_message(body) or f"HTTP {response.status_code}"
        return ProviderError(
            redact(message),
            code=code,
            provider=self.id,
            model=model,
            status_code_upstream=response.status_code,
        )

    @staticmethod
    def _extract_error_message(body: str) -> str | None:
        """Pull a readable message out of a provider's JSON error envelope."""
        import json as _json

        try:
            parsed = _json.loads(body)
        except ValueError:
            return body.strip()[:400] or None
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                msg = error.get("message") or error.get("status") or error.get("type")
                if msg:
                    return str(msg)[:400]
            if isinstance(error, str):
                return error[:400]
            for key in ("message", "detail", "error_message"):
                if parsed.get(key):
                    return str(parsed[key])[:400]
        return body.strip()[:400] or None

    def build_result(
        self,
        *,
        request: GenerationRequest,
        text: str,
        started: float,
        input_tokens: int | None,
        output_tokens: int | None,
        finish_reason: str | None,
        metadata: dict[str, Any],
    ) -> GenerationResult:
        """Assemble a :class:`GenerationResult`, filling in derived metrics.

        This is the single place where latency, tokens/sec and cost are computed,
        so every provider reports them identically.
        """
        elapsed_seconds = max(time.perf_counter() - started, 0.0)
        latency_ms = int(elapsed_seconds * 1000)

        token_source = "provider"
        if input_tokens is None or output_tokens is None:
            token_source = "estimated"
            prompt_text = f"{request.system_prompt or ''}\n{request.prompt}"
            if input_tokens is None:
                input_tokens = estimate_tokens(prompt_text)
            output_tokens = output_tokens if output_tokens is not None else estimate_tokens(text)

        input_tokens = max(0, int(input_tokens))
        output_tokens = max(0, int(output_tokens))
        total_tokens = input_tokens + output_tokens

        # Derived from the raw elapsed time, not the rounded millisecond value —
        # otherwise a sub-millisecond response would report 0 tokens/sec.
        tokens_per_second = (
            round(output_tokens / elapsed_seconds, 2) if elapsed_seconds > 0 else 0.0
        )

        return GenerationResult(
            provider=self.id,
            model=request.model,
            response=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            tokens_per_second=tokens_per_second,
            estimated_cost=estimate_cost(self.id, request.model, input_tokens, output_tokens),
            finish_reason=finish_reason,
            token_source=token_source,
            metadata=metadata,
        )
