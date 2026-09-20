"""Shared test fixtures.

Each test gets an isolated on-disk SQLite database (not ``:memory:``, because
the engine opens its own sessions from background tasks and must see the same
data) and a registry of scriptable fake providers, so no test touches a network.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.db.session as db_session_module
from app.core.errors import ErrorCode, ProviderError
from app.db.base import Base
from app.db.session import create_engine
from app.main import create_app
from app.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    ModelInfo,
    ProviderStatus,
)
from app.providers.registry import ProviderRegistry, set_registry
from app.services.run_tracker import reset_tracker


# ----------------------------------------------------------------------
# Fake providers
# ----------------------------------------------------------------------
class FakeProvider(LLMProvider):
    """Scriptable adapter: deterministic text, configurable latency and failures."""

    def __init__(
        self,
        provider_id: str = "fake",
        *,
        label: str | None = None,
        configured: bool = True,
        delay: float = 0.0,
        fail_with: ProviderError | None = None,
        fail_times: int = 0,
        text: str = "TCP uses a three-way handshake because both peers must agree on "
        "initial sequence numbers before data flows. The SYN, SYN-ACK and ACK "
        "exchange confirms that each direction of the connection works.",
        input_tokens: int | None = 40,
        output_tokens: int | None = 60,
        is_local: bool = False,
    ) -> None:
        super().__init__()
        self.id = provider_id
        self.label = label or provider_id.title()
        self.is_local = is_local
        self.api_key_env = None if is_local else f"{provider_id.upper()}_API_KEY"
        self._configured = configured
        self.delay = delay
        self.fail_with = fail_with
        self.fail_times = fail_times
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[GenerationRequest] = []

    def is_configured(self) -> bool:
        return self._configured

    async def get_models(self) -> list[ModelInfo]:
        return [ModelInfo(self.id, "m1", "Model One", 8192, local=self.is_local)]

    async def test_connection(self) -> ProviderStatus:
        if not self._configured:
            return ProviderStatus(self.id, False, "not configured", ErrorCode.AUTHENTICATION)
        return ProviderStatus(self.id, True, "ok", None, 5, 1)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with is not None and (
            self.fail_times == 0 or len(self.calls) <= self.fail_times
        ):
            raise self.fail_with
        import time

        started = time.perf_counter() - 0.05  # non-zero latency for tokens/sec
        return self.build_result(
            request=request,
            text=self.text,
            started=started,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            finish_reason="stop",
            metadata={"fake": True, "request_id": f"{self.id}-req"},
        )


class JudgeProvider(FakeProvider):
    """Returns judge-shaped JSON."""

    def __init__(self, payload: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            "judge",
            text=payload
            or '{"relevance": 9, "correctness": 8, "conciseness": 7, '
            '"clarity": 9, "overall": 8.3, "reasoning": "Clear and accurate."}',
            **kwargs,
        )


# ----------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_engine(tmp_path: Any) -> AsyncIterator[Any]:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    original_engine = db_session_module.engine
    original_sessionmaker = db_session_module.SessionLocal
    db_session_module.engine = engine
    db_session_module.SessionLocal = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )
    try:
        yield engine
    finally:
        db_session_module.engine = original_engine
        db_session_module.SessionLocal = original_sessionmaker
        await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine: Any) -> AsyncIterator[Any]:
    async with db_session_module.SessionLocal() as s:
        yield s


# ----------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------
@pytest.fixture
def fake_openai() -> FakeProvider:
    return FakeProvider("openai", label="OpenAI")


@pytest.fixture
def fake_ollama() -> FakeProvider:
    return FakeProvider("ollama", label="Ollama (local)", is_local=True)


@pytest.fixture
def registry(fake_openai: FakeProvider, fake_ollama: FakeProvider) -> ProviderRegistry:
    reg = ProviderRegistry([fake_ollama, fake_openai])
    set_registry(reg)
    yield reg
    set_registry(None)


# ----------------------------------------------------------------------
# App / client
# ----------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(db_engine: Any, registry: ProviderRegistry) -> AsyncIterator[AsyncClient]:
    reset_tracker()
    application = create_app()

    async def _session_override() -> AsyncIterator[Any]:
        async with db_session_module.SessionLocal() as s:
            yield s

    from app.api.deps import db_session as db_session_dep
    from app.api.deps import provider_registry as registry_dep

    application.dependency_overrides[db_session_dep] = _session_override
    application.dependency_overrides[registry_dep] = lambda: registry

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    reset_tracker()


# ----------------------------------------------------------------------
# Payload helpers
# ----------------------------------------------------------------------
def benchmark_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "TCP handshake",
        "prompt": "Explain why TCP uses a three-way handshake.",
        "temperature": 0.2,
        "max_tokens": 256,
        "evaluation_enabled": True,
        "evaluation_mode": "heuristic",
        "models": [
            {"provider": "ollama", "model": "m1"},
            {"provider": "openai", "model": "m1"},
        ],
        "tags": ["networking"],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def payload_factory() -> Any:
    return benchmark_payload
