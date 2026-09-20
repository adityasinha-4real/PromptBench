"""Provider adapters: response normalisation and error classification.

Every provider is driven through an ``httpx.MockTransport``, so these tests
exercise the real request construction and parsing code without a network.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.core.config import settings
from app.core.errors import ErrorCode, ProviderError, classify_http_status
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import GenerationRequest, LLMProvider, estimate_tokens
from app.providers.gemini_provider import GeminiProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.registry import ProviderRegistry

REQUEST = GenerationRequest(
    model="m1", prompt="Explain TCP.", system_prompt="Be brief.", temperature=0.3, max_tokens=128
)


def wire(
    provider: LLMProvider, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Route the provider's HTTP client through a mock transport; capture requests."""
    seen: list[httpx.Request] = []

    def capturing(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(capturing))
    return seen


def json_response(payload: dict, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers or {})


# ----------------------------------------------------------------------
# OpenAI
# ----------------------------------------------------------------------
@pytest.fixture
def openai_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-key-value-123456")


async def test_openai_normalises_a_successful_response(openai_key) -> None:
    provider = OpenAIProvider()
    seen = wire(
        provider,
        lambda _: json_response(
            {
                "id": "chatcmpl-abc",
                "model": "gpt-4o-2024-08-06",
                "system_fingerprint": "fp_1",
                "choices": [
                    {"message": {"content": "Because handshakes."}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
            headers={"x-request-id": "req_123"},
        ),
    )

    result = await provider.generate(REQUEST)

    assert result.provider == "openai"
    assert result.response == "Because handshakes."
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (11, 7, 18)
    assert result.finish_reason == "stop"
    assert result.token_source == "provider"
    assert result.latency_ms >= 0
    assert result.metadata["request_id"] == "req_123"

    body = json.loads(seen[0].content)
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert body["messages"][1]["content"] == "Explain TCP."
    assert body["temperature"] == 0.3
    assert body["max_completion_tokens"] == 128
    assert seen[0].headers["authorization"].startswith("Bearer ")


async def test_openai_omits_temperature_for_reasoning_models(openai_key) -> None:
    provider = OpenAIProvider()
    seen = wire(
        provider,
        lambda _: json_response(
            {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}
        ),
    )
    await provider.generate(GenerationRequest(model="o3-mini", prompt="hi", max_tokens=16))
    body = json.loads(seen[0].content)
    assert "temperature" not in body


async def test_openai_missing_key_is_an_auth_error_before_any_request(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    provider = OpenAIProvider()
    seen = wire(provider, lambda _: json_response({}))

    with pytest.raises(ProviderError) as exc:
        await provider.generate(REQUEST)

    assert exc.value.code == ErrorCode.AUTHENTICATION
    assert exc.value.retryable is False
    assert "OPENAI_API_KEY" in exc.value.message
    assert seen == [], "no HTTP call should be made without a key"


async def test_openai_rate_limit_is_classified_and_retryable(openai_key) -> None:
    provider = OpenAIProvider()
    wire(
        provider,
        lambda _: json_response({"error": {"message": "Rate limit reached"}}, status=429),
    )
    with pytest.raises(ProviderError) as exc:
        await provider.generate(REQUEST)
    assert exc.value.code == ErrorCode.RATE_LIMIT
    assert exc.value.retryable is True
    assert exc.value.status_code_upstream == 429
    assert "Rate limit reached" in exc.value.message


async def test_openai_timeout_is_classified(openai_key) -> None:
    provider = OpenAIProvider()

    def raise_timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    wire(provider, raise_timeout)
    with pytest.raises(ProviderError) as exc:
        await provider.generate(REQUEST)
    assert exc.value.code == ErrorCode.TIMEOUT
    assert exc.value.retryable is True


async def test_openai_empty_choices_raises(openai_key) -> None:
    provider = OpenAIProvider()
    wire(provider, lambda _: json_response({"choices": [], "usage": {}}))
    with pytest.raises(ProviderError):
        await provider.generate(REQUEST)


async def test_display_message_is_human_readable(openai_key) -> None:
    provider = OpenAIProvider()
    wire(provider, lambda _: json_response({"error": {"message": "Invalid key"}}, status=401))
    with pytest.raises(ProviderError) as exc:
        await provider.generate(REQUEST)
    assert exc.value.display_message() == "Openai request failed: Invalid key"
    assert "hint" in exc.value.to_payload()


# ----------------------------------------------------------------------
# Anthropic
# ----------------------------------------------------------------------
async def test_anthropic_concatenates_text_blocks(monkeypatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test-0000000000")
    provider = AnthropicProvider()
    seen = wire(
        provider,
        lambda _: json_response(
            {
                "id": "msg_1",
                "model": "claude-sonnet-4-5",
                "content": [
                    {"type": "text", "text": "Part one. "},
                    {"type": "thinking", "thinking": "ignored"},
                    {"type": "text", "text": "Part two."},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 20, "output_tokens": 9},
            },
            headers={"request-id": "req_ant"},
        ),
    )

    result = await provider.generate(REQUEST)

    assert result.response == "Part one. Part two."
    assert (result.input_tokens, result.output_tokens) == (20, 9)
    assert result.finish_reason == "end_turn"
    body = json.loads(seen[0].content)
    assert body["system"] == "Be brief."
    assert body["max_tokens"] == 128
    assert seen[0].headers["x-api-key"]
    assert seen[0].headers["anthropic-version"]


async def test_anthropic_without_key_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    provider = AnthropicProvider()
    status = await provider.test_connection()
    assert status.available is False
    assert status.code == ErrorCode.AUTHENTICATION
    assert "ANTHROPIC_API_KEY" in status.detail


# ----------------------------------------------------------------------
# Gemini
# ----------------------------------------------------------------------
@pytest.fixture
def gemini_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "AIzaTESTKEY0000000000000")


async def test_gemini_normalises_parts_and_usage(gemini_key) -> None:
    provider = GeminiProvider()
    seen = wire(
        provider,
        lambda _: json_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "A "}, {"text": "B"}]},
                        "finishReason": "STOP",
                        "safetyRatings": [],
                    }
                ],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 4},
                "modelVersion": "gemini-2.5-flash",
            }
        ),
    )

    result = await provider.generate(REQUEST)

    assert result.response == "A B"
    assert (result.input_tokens, result.output_tokens) == (12, 4)
    assert result.finish_reason == "STOP"
    body = json.loads(seen[0].content)
    assert body["systemInstruction"]["parts"][0]["text"] == "Be brief."
    assert body["generationConfig"]["maxOutputTokens"] == 128


async def test_gemini_sends_key_in_header_not_url(gemini_key) -> None:
    """The key must never appear in a URL, where it would leak into logs."""
    provider = GeminiProvider()
    seen = wire(
        provider,
        lambda _: json_response(
            {"candidates": [{"content": {"parts": [{"text": "x"}]}, "finishReason": "STOP"}]}
        ),
    )
    await provider.generate(REQUEST)
    assert "AIza" not in str(seen[0].url)
    assert seen[0].headers["x-goog-api-key"].startswith("AIza")


async def test_gemini_blocked_prompt_maps_to_content_filter(gemini_key) -> None:
    provider = GeminiProvider()
    wire(provider, lambda _: json_response({"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ProviderError) as exc:
        await provider.generate(REQUEST)
    assert exc.value.code == ErrorCode.CONTENT_FILTER
    assert exc.value.retryable is False


# ----------------------------------------------------------------------
# Ollama
# ----------------------------------------------------------------------
async def test_ollama_uses_provider_token_counts_and_is_free() -> None:
    provider = OllamaProvider()
    seen = wire(
        provider,
        lambda _: json_response(
            {
                "model": "llama3.2",
                "message": {"role": "assistant", "content": "Local answer."},
                "done_reason": "stop",
                "prompt_eval_count": 18,
                "eval_count": 30,
                "total_duration": 1_500_000_000,
                "eval_duration": 900_000_000,
            }
        ),
    )

    result = await provider.generate(
        GenerationRequest(model="llama3.2", prompt="Explain TCP.", max_tokens=64)
    )

    assert result.response == "Local answer."
    assert (result.input_tokens, result.output_tokens) == (18, 30)
    assert result.estimated_cost == 0.0, "local models are genuinely free"
    assert result.metadata["total_duration_ms"] == 1500.0
    body = json.loads(seen[0].content)
    assert body["stream"] is False
    assert body["options"]["num_predict"] == 64


async def test_ollama_lists_pulled_models() -> None:
    provider = OllamaProvider()
    wire(
        provider,
        lambda _: json_response(
            {
                "models": [
                    {
                        "name": "llama3.2:latest",
                        "size": 2_000_000_000,
                        "details": {"parameter_size": "3B", "quantization_level": "Q4_0"},
                    }
                ]
            }
        ),
    )
    models = await provider.get_models()
    assert [m.id for m in models] == ["llama3.2:latest"]
    assert models[0].local is True
    assert "3B" in (models[0].description or "")


async def test_ollama_unreachable_lists_nothing_and_explains_itself() -> None:
    provider = OllamaProvider()

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    wire(provider, refuse)
    assert await provider.get_models() == []
    status = await provider.test_connection()
    assert status.available is False
    assert "ollama serve" in status.detail


async def test_ollama_model_not_pulled_is_an_invalid_request() -> None:
    provider = OllamaProvider()
    wire(provider, lambda _: json_response({"error": 'model "ghost" not found'}, status=404))
    with pytest.raises(ProviderError) as exc:
        await provider.generate(GenerationRequest(model="ghost", prompt="hi"))
    assert exc.value.code == ErrorCode.INVALID_REQUEST
    assert exc.value.retryable is False


# ----------------------------------------------------------------------
# Shared behaviour
# ----------------------------------------------------------------------
async def test_token_estimation_when_provider_reports_no_usage(openai_key) -> None:
    provider = OpenAIProvider()
    wire(
        provider,
        lambda _: json_response(
            {"choices": [{"message": {"content": "a" * 400}, "finish_reason": "stop"}]}
        ),
    )
    result = await provider.generate(REQUEST)
    assert result.token_source == "estimated"
    assert result.output_tokens == estimate_tokens("a" * 400)
    assert result.input_tokens > 0


async def test_tokens_per_second_is_derived_from_latency(openai_key) -> None:
    provider = OpenAIProvider()
    wire(
        provider,
        lambda _: json_response(
            {
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 100},
            }
        ),
    )
    result = await provider.generate(REQUEST)
    assert result.tokens_per_second > 0


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ErrorCode.AUTHENTICATION),
        (403, ErrorCode.AUTHENTICATION),
        (429, ErrorCode.RATE_LIMIT),
        (404, ErrorCode.INVALID_REQUEST),
        (400, ErrorCode.INVALID_REQUEST),
        (408, ErrorCode.TIMEOUT),
        (500, ErrorCode.PROVIDER_UNAVAILABLE),
        (503, ErrorCode.PROVIDER_UNAVAILABLE),
        (529, ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_http_status_classification(status: int, expected: ErrorCode) -> None:
    assert classify_http_status(status, "") is expected


def test_registry_rejects_unknown_provider() -> None:
    registry = ProviderRegistry([OllamaProvider()])
    with pytest.raises(ProviderError) as exc:
        registry.get("nope")
    assert exc.value.code == ErrorCode.INVALID_REQUEST


async def test_registry_statuses_never_raise() -> None:
    class Exploding(OllamaProvider):
        id = "boom"

        async def test_connection(self):  # type: ignore[override]
            raise RuntimeError("kaboom")

    registry = ProviderRegistry([Exploding()])
    statuses = await registry.statuses()
    assert statuses["boom"].available is False
    assert "RuntimeError" in statuses["boom"].detail


def test_default_registry_contains_all_four_providers() -> None:
    assert set(ProviderRegistry().ids()) == {"openai", "anthropic", "gemini", "ollama"}
