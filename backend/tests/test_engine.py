"""Benchmark execution engine: concurrency, isolation, retries, cancellation."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core.config import settings
from app.core.errors import ErrorCode, ProviderError
from app.models.benchmark import (
    Benchmark,
    BenchmarkRun,
    ModelResult,
    PromptVariant,
    ResultStatus,
    RunStatus,
)
from app.providers.registry import ProviderRegistry
from app.services.engine import BenchmarkEngine
from app.services.run_tracker import RunTracker
from tests.conftest import FakeProvider, JudgeProvider

PROMPT = "Explain why TCP uses a three-way handshake."


async def make_benchmark(session, providers, **kwargs) -> Benchmark:
    benchmark = Benchmark(
        name=kwargs.pop("name", "bench"),
        prompt=kwargs.pop("prompt", PROMPT),
        temperature=0.2,
        max_tokens=128,
        models=[{"provider": p, "model": "m1"} for p in providers],
        evaluation_enabled=kwargs.pop("evaluation_enabled", True),
        evaluation_mode=kwargs.pop("evaluation_mode", "heuristic"),
        **kwargs,
    )
    session.add(benchmark)
    await session.commit()
    await session.refresh(benchmark)
    return benchmark


async def load_results(session, run_id: int) -> list[ModelResult]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    rows = (
        await session.execute(
            select(ModelResult)
            .options(selectinload(ModelResult.evaluation))
            .where(ModelResult.benchmark_run_id == run_id)
            .order_by(ModelResult.id)
        )
    ).scalars()
    return list(rows)


def engine_for(*providers) -> tuple[BenchmarkEngine, RunTracker]:
    tracker = RunTracker()
    return BenchmarkEngine(registry=ProviderRegistry(list(providers)), tracker=tracker), tracker


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------
async def test_runs_every_model_and_persists_normalised_results(session) -> None:
    engine, _ = engine_for(FakeProvider("a"), FakeProvider("b"))
    benchmark = await make_benchmark(session, ["a", "b"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)

    results = await load_results(session, snapshot["run_id"])
    assert len(results) == 2
    assert {r.provider for r in results} == {"a", "b"}
    for result in results:
        assert result.status == ResultStatus.SUCCESS
        assert result.response
        assert result.input_tokens == 40
        assert result.output_tokens == 60
        assert result.total_tokens == 100
        assert result.latency_ms is not None and result.latency_ms >= 0
        assert result.tokens_per_second and result.tokens_per_second > 0
        assert result.finish_reason == "stop"
        assert result.evaluation is not None

    run = await session.get(BenchmarkRun, snapshot["run_id"])
    await session.refresh(run)
    assert run.status == RunStatus.COMPLETED
    assert run.completed_at is not None


async def test_models_execute_concurrently_not_sequentially(session) -> None:
    """Four 150ms models must finish in well under the 600ms a serial run would take."""
    providers = [FakeProvider(f"p{i}", delay=0.15) for i in range(4)]
    engine, _ = engine_for(*providers)
    benchmark = await make_benchmark(session, [p.id for p in providers])

    started = time.perf_counter()
    snapshot = await engine.launch(session, benchmark.id, wait=True)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.45, f"took {elapsed:.2f}s — models did not run concurrently"
    results = await load_results(session, snapshot["run_id"])
    assert all(r.status == ResultStatus.SUCCESS for r in results)


async def test_concurrency_is_bounded_by_the_configured_limit(session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrency", 2)
    in_flight = 0
    peak = 0

    class Counting(FakeProvider):
        async def generate(self, request):  # type: ignore[override]
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.05)
                return await super().generate(request)
            finally:
                in_flight -= 1

    providers = [Counting(f"p{i}") for i in range(6)]
    engine, _ = engine_for(*providers)
    benchmark = await make_benchmark(session, [p.id for p in providers])

    await engine.launch(session, benchmark.id, wait=True)
    assert peak <= 2, f"peak concurrency was {peak}, limit was 2"


# ----------------------------------------------------------------------
# Failure isolation
# ----------------------------------------------------------------------
async def test_one_provider_failure_does_not_fail_the_run(session) -> None:
    """GPT ok, Claude ok, Gemini timeout, Ollama ok — the run still completes."""
    engine, _ = engine_for(
        FakeProvider("gpt"),
        FakeProvider("claude"),
        FakeProvider(
            "gemini",
            fail_with=ProviderError(
                "request timed out after 120s.", code=ErrorCode.TIMEOUT, provider="gemini"
            ),
        ),
        FakeProvider("ollama", is_local=True),
    )
    benchmark = await make_benchmark(session, ["gpt", "claude", "gemini", "ollama"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = {r.provider: r for r in await load_results(session, snapshot["run_id"])}

    assert results["gpt"].status == ResultStatus.SUCCESS
    assert results["claude"].status == ResultStatus.SUCCESS
    assert results["ollama"].status == ResultStatus.SUCCESS

    failed = results["gemini"]
    assert failed.status == ResultStatus.FAILED
    assert failed.error_code == ErrorCode.TIMEOUT
    assert "Gemini request failed" in (failed.error_message or "")
    assert failed.response is None

    run = await session.get(BenchmarkRun, snapshot["run_id"])
    await session.refresh(run)
    assert run.status == RunStatus.COMPLETED
    assert "1 of 4" in (run.error_message or "")


async def test_run_is_marked_failed_only_when_everything_fails(session) -> None:
    error = ProviderError("down.", code=ErrorCode.PROVIDER_UNAVAILABLE, provider="a")
    engine, _ = engine_for(FakeProvider("a", fail_with=error), FakeProvider("b", fail_with=error))
    benchmark = await make_benchmark(session, ["a", "b"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    run = await session.get(BenchmarkRun, snapshot["run_id"])
    await session.refresh(run)
    assert run.status == RunStatus.FAILED


async def test_unknown_provider_is_recorded_not_raised(session) -> None:
    engine, _ = engine_for(FakeProvider("a"))
    benchmark = await make_benchmark(session, ["a", "does-not-exist"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = {r.provider: r for r in await load_results(session, snapshot["run_id"])}
    assert results["a"].status == ResultStatus.SUCCESS
    assert results["does-not-exist"].status == ResultStatus.FAILED
    assert results["does-not-exist"].error_code == ErrorCode.INVALID_REQUEST


async def test_adapter_crash_is_contained(session) -> None:
    class Exploding(FakeProvider):
        async def generate(self, request):  # type: ignore[override]
            raise RuntimeError("adapter bug")

    engine, _ = engine_for(Exploding("boom"), FakeProvider("ok"))
    benchmark = await make_benchmark(session, ["boom", "ok"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = {r.provider: r for r in await load_results(session, snapshot["run_id"])}
    assert results["ok"].status == ResultStatus.SUCCESS
    assert results["boom"].status == ResultStatus.FAILED
    assert results["boom"].error_code == ErrorCode.UNKNOWN


# ----------------------------------------------------------------------
# Retries
# ----------------------------------------------------------------------
async def test_retryable_failure_is_retried_then_succeeds(session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_retries", 2)
    monkeypatch.setattr(settings, "retry_base_delay_seconds", 0.0)

    flaky = FakeProvider(
        "flaky",
        fail_with=ProviderError("rate limited.", code=ErrorCode.RATE_LIMIT, provider="flaky"),
        fail_times=1,  # fail the first call only
    )
    engine, _ = engine_for(flaky)
    benchmark = await make_benchmark(session, ["flaky"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])

    assert results[0].status == ResultStatus.SUCCESS
    assert results[0].attempts == 2
    assert len(flaky.calls) == 2


async def test_non_retryable_failure_is_not_retried(session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_retries", 3)
    monkeypatch.setattr(settings, "retry_base_delay_seconds", 0.0)

    provider = FakeProvider(
        "auth",
        fail_with=ProviderError(
            "API key is missing.", code=ErrorCode.AUTHENTICATION, provider="auth", retryable=False
        ),
    )
    engine, _ = engine_for(provider)
    benchmark = await make_benchmark(session, ["auth"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])

    assert results[0].status == ResultStatus.FAILED
    assert results[0].attempts == 1
    assert len(provider.calls) == 1, "authentication errors must not be retried"


async def test_retries_are_bounded(session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_retries", 2)
    monkeypatch.setattr(settings, "retry_base_delay_seconds", 0.0)

    provider = FakeProvider(
        "always",
        fail_with=ProviderError("busy.", code=ErrorCode.RATE_LIMIT, provider="always"),
    )
    engine, _ = engine_for(provider)
    benchmark = await make_benchmark(session, ["always"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])

    assert len(provider.calls) == 3, "initial attempt plus exactly max_retries"
    assert results[0].attempts == 3
    assert results[0].status == ResultStatus.FAILED


# ----------------------------------------------------------------------
# Cancellation
# ----------------------------------------------------------------------
async def test_cancelling_a_run_aborts_in_flight_requests(session) -> None:
    providers = [FakeProvider(f"slow{i}", delay=5.0) for i in range(3)]
    engine, tracker = engine_for(*providers)
    benchmark = await make_benchmark(session, [p.id for p in providers])

    snapshot = await engine.launch(session, benchmark.id)
    run_id = snapshot["run_id"]

    await asyncio.sleep(0.05)
    assert tracker.cancel(run_id) is True

    started = time.perf_counter()
    await asyncio.wait_for(engine.drain(), timeout=5)
    assert time.perf_counter() - started < 2.0, "cancellation did not abort the in-flight calls"

    run = await session.get(BenchmarkRun, run_id)
    await session.refresh(run)
    assert run.status == RunStatus.CANCELLED

    results = await load_results(session, run_id)
    assert all(r.status == ResultStatus.CANCELLED for r in results)


async def test_cancelling_an_unknown_run_is_a_no_op() -> None:
    tracker = RunTracker()
    assert tracker.cancel(999) is False


# ----------------------------------------------------------------------
# Prompt variants
# ----------------------------------------------------------------------
async def test_variants_produce_a_model_by_variant_matrix(session) -> None:
    engine, _ = engine_for(FakeProvider("a"), FakeProvider("b"))
    benchmark = await make_benchmark(session, ["a", "b"])
    benchmark.variants.append(PromptVariant(name="Plain", prompt="Explain TCP.", position=0))
    benchmark.variants.append(
        PromptVariant(name="Analogy", prompt="Explain TCP with an analogy.", position=1)
    )
    await session.commit()

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])

    assert len(results) == 4, "2 models x 2 variants"
    assert {(r.provider, r.variant_name) for r in results} == {
        ("a", "Plain"),
        ("a", "Analogy"),
        ("b", "Plain"),
        ("b", "Analogy"),
    }


async def test_variant_subset_can_be_selected(session) -> None:
    engine, _ = engine_for(FakeProvider("a"))
    benchmark = await make_benchmark(session, ["a"])
    benchmark.variants.append(PromptVariant(name="One", prompt="p1", position=0))
    benchmark.variants.append(PromptVariant(name="Two", prompt="p2", position=1))
    await session.commit()
    await session.refresh(benchmark)
    chosen = benchmark.variants[0].id

    snapshot = await engine.launch(session, benchmark.id, variant_ids=[chosen], wait=True)
    results = await load_results(session, snapshot["run_id"])
    assert [r.variant_name for r in results] == ["One"]


# ----------------------------------------------------------------------
# Evaluation integration
# ----------------------------------------------------------------------
async def test_evaluation_disabled_stores_no_scores(session) -> None:
    engine, _ = engine_for(FakeProvider("a"))
    benchmark = await make_benchmark(
        session, ["a"], evaluation_enabled=False, evaluation_mode="disabled"
    )
    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])
    assert results[0].status == ResultStatus.SUCCESS
    assert results[0].evaluation is None


async def test_llm_judge_scores_are_recorded(session) -> None:
    engine, _ = engine_for(FakeProvider("a"), JudgeProvider())
    benchmark = await make_benchmark(
        session, ["a"], evaluation_mode="llm_judge", judge_provider="judge", judge_model="j1"
    )
    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])
    assert results[0].evaluation is not None
    assert results[0].evaluation.overall == 8.3
    assert results[0].evaluation.mode == "llm_judge"
    assert results[0].evaluation.evaluator_model == "judge:j1"


async def test_broken_judge_does_not_lose_the_generation(session) -> None:
    engine, _ = engine_for(FakeProvider("a"), JudgeProvider(payload="not json"))
    benchmark = await make_benchmark(
        session, ["a"], evaluation_mode="llm_judge", judge_provider="judge", judge_model="j1"
    )
    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])

    assert results[0].status == ResultStatus.SUCCESS
    assert results[0].response
    assert results[0].evaluation is None
    assert "evaluation_error" in results[0].extra_metadata


async def test_misconfigured_judge_still_runs_the_generations(session) -> None:
    engine, _ = engine_for(FakeProvider("a"))
    benchmark = await make_benchmark(
        session, ["a"], evaluation_mode="llm_judge", judge_provider="missing", judge_model="j1"
    )
    snapshot = await engine.launch(session, benchmark.id, wait=True)
    results = await load_results(session, snapshot["run_id"])
    assert results[0].status == ResultStatus.SUCCESS
    assert "evaluation_error" in results[0].extra_metadata


# ----------------------------------------------------------------------
# Tracker / progress
# ----------------------------------------------------------------------
async def test_progress_snapshot_tracks_completion(session) -> None:
    engine, tracker = engine_for(FakeProvider("a"), FakeProvider("b"))
    benchmark = await make_benchmark(session, ["a", "b"])

    snapshot = await engine.launch(session, benchmark.id, wait=True)
    state = tracker.get(snapshot["run_id"])
    assert state is not None
    final = state.snapshot()
    assert final["total"] == 2
    assert final["completed"] == 2
    assert final["succeeded"] == 2
    assert final["failed"] == 0
    assert final["status"] == RunStatus.COMPLETED


async def test_subscribers_receive_progress_updates(session) -> None:
    engine, tracker = engine_for(FakeProvider("a", delay=0.05), FakeProvider("b", delay=0.05))
    benchmark = await make_benchmark(session, ["a", "b"])

    snapshot = await engine.launch(session, benchmark.id)
    state = tracker.get(snapshot["run_id"])
    assert state is not None
    queue = tracker.subscribe(state)

    await engine.drain()

    frames = []
    while not queue.empty():
        frames.append(queue.get_nowait())
    assert len(frames) >= 2
    assert frames[-1]["status"] in (RunStatus.COMPLETED, RunStatus.RUNNING)


async def test_launch_rejects_a_missing_benchmark(session) -> None:
    from app.core.errors import NotFoundError

    engine, _ = engine_for(FakeProvider("a"))
    with pytest.raises(NotFoundError):
        await engine.launch(session, 4242, wait=True)


async def test_launch_rejects_a_benchmark_with_no_models(session) -> None:
    from app.core.errors import NotFoundError

    engine, _ = engine_for(FakeProvider("a"))
    benchmark = await make_benchmark(session, [])
    with pytest.raises(NotFoundError):
        await engine.launch(session, benchmark.id, wait=True)


async def test_params_snapshot_records_what_actually_ran(session) -> None:
    engine, _ = engine_for(FakeProvider("a"))
    benchmark = await make_benchmark(session, ["a"])

    snapshot = await engine.launch(session, benchmark.id, temperature=1.5, max_tokens=64, wait=True)
    run = await session.get(BenchmarkRun, snapshot["run_id"])
    await session.refresh(run)

    assert run.params_snapshot["temperature"] == 1.5
    assert run.params_snapshot["max_tokens"] == 64
    results = await load_results(session, run.id)
    assert results[0].request_params["temperature"] == 1.5
