"""Benchmark execution engine.

Responsibilities:

* expand a benchmark into ``model x prompt variant`` tasks,
* execute them concurrently under a semaphore,
* apply per-provider timeouts and bounded exponential-backoff retries,
* isolate failures so one dead provider never fails the whole run,
* support cancellation of in-flight requests,
* persist normalised results and evaluations,
* publish live progress to the SSE stream.

The engine knows nothing about specific providers or evaluators — it receives
them through the registry and the evaluator factory.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode, NotFoundError, ProviderError
from app.core.logging import get_logger
from app.core.pricing import cost_per_1k_tokens
from app.db.session import session_scope
from app.evaluation.base import EvaluationError, EvaluationScores, Evaluator
from app.evaluation.factory import build_evaluator
from app.models.benchmark import (
    Benchmark,
    BenchmarkRun,
    Evaluation,
    EvaluationMode,
    ModelResult,
    ResultStatus,
    RunStatus,
)
from app.providers.base import GenerationRequest, GenerationResult
from app.providers.registry import ProviderRegistry, get_registry
from app.services.run_tracker import RunState, RunTracker, TaskState, get_tracker

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One unit of work: a single model answering a single prompt variant."""

    key: str
    result_id: int
    provider_id: str
    model: str
    variant_id: int | None
    variant_name: str
    prompt: str


@dataclass(frozen=True, slots=True)
class RunConfig:
    system_prompt: str | None
    temperature: float
    max_tokens: int
    top_p: float | None
    timeout: float
    max_retries: int
    retry_base_delay: float
    max_concurrency: int


class BenchmarkEngine:
    """Executes benchmark runs."""

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        tracker: RunTracker | None = None,
    ) -> None:
        self.registry = registry or get_registry()
        self.tracker = tracker or get_tracker()
        self._background: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Launching
    # ------------------------------------------------------------------
    async def launch(
        self,
        session: AsyncSession,
        benchmark_id: int,
        *,
        models: list[dict[str, str]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        evaluation_mode: str | None = None,
        variant_ids: list[int] | None = None,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Create a run, schedule execution, and return the initial progress snapshot.

        With ``wait=True`` the coroutine only returns once the run has finished —
        used by tests and by the synchronous ``run_immediately`` path.
        """
        benchmark = await session.get(Benchmark, benchmark_id)
        if benchmark is None:
            raise NotFoundError(f"Benchmark {benchmark_id} was not found.")

        targets = models if models is not None else list(benchmark.models or [])
        targets = [t for t in targets if t.get("provider") and t.get("model")]
        if not targets:
            raise NotFoundError(f"Benchmark {benchmark_id} has no models selected.")

        variants = list(benchmark.variants)
        if variant_ids:
            wanted = set(variant_ids)
            variants = [v for v in variants if v.id in wanted]
        # Benchmarks without explicit variants run the base prompt once.
        variant_pairs: list[tuple[int | None, str, str]] = (
            [(v.id, v.name, v.prompt) for v in variants]
            if variants
            else [(None, "Default", benchmark.prompt)]
        )

        mode = evaluation_mode or (
            benchmark.evaluation_mode if benchmark.evaluation_enabled else EvaluationMode.DISABLED
        )
        config = RunConfig(
            system_prompt=benchmark.system_prompt,
            temperature=temperature if temperature is not None else benchmark.temperature,
            max_tokens=max_tokens if max_tokens is not None else benchmark.max_tokens,
            top_p=benchmark.top_p,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
            retry_base_delay=settings.retry_base_delay_seconds,
            max_concurrency=settings.max_concurrency,
        )

        run = BenchmarkRun(
            benchmark_id=benchmark.id,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            params_snapshot={
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "top_p": config.top_p,
                "system_prompt_present": bool(config.system_prompt),
                "evaluation_mode": str(mode),
                "models": targets,
                "timeout_seconds": config.timeout,
                "max_retries": config.max_retries,
            },
        )
        session.add(run)
        await session.flush()

        specs: list[TaskSpec] = []
        task_states: list[TaskState] = []
        for variant_id, variant_name, prompt in variant_pairs:
            for target in targets:
                provider_id = str(target["provider"])
                model_id = str(target["model"])
                result = ModelResult(
                    benchmark_run_id=run.id,
                    variant_id=variant_id,
                    variant_name=variant_name,
                    provider=provider_id,
                    model=model_id,
                    status=ResultStatus.QUEUED,
                    request_params={
                        "temperature": config.temperature,
                        "max_tokens": config.max_tokens,
                        "top_p": config.top_p,
                    },
                    extra_metadata={},
                )
                session.add(result)
                await session.flush()
                key = f"{variant_name}::{provider_id}:{model_id}"
                specs.append(
                    TaskSpec(
                        key=key,
                        result_id=result.id,
                        provider_id=provider_id,
                        model=model_id,
                        variant_id=variant_id,
                        variant_name=variant_name,
                        prompt=prompt,
                    )
                )
                task_states.append(
                    TaskState(
                        key=key,
                        provider=provider_id,
                        model=model_id,
                        variant_name=variant_name,
                        result_id=result.id,
                    )
                )

        await session.commit()

        state = await self.tracker.create(run.id, benchmark.id, task_states)
        state.status = RunStatus.RUNNING
        state.started_at = run.started_at

        coro = self._execute_run(run.id, specs, config, str(mode), benchmark)
        if wait:
            await coro
        else:
            task = asyncio.create_task(coro, name=f"benchmark-run-{run.id}")
            self._background.add(task)
            task.add_done_callback(self._background.discard)

        return state.snapshot()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    async def _execute_run(
        self,
        run_id: int,
        specs: list[TaskSpec],
        config: RunConfig,
        mode: str,
        benchmark: Benchmark,
    ) -> None:
        state = self.tracker.get(run_id)
        if state is None:  # pragma: no cover - defensive
            logger.error("Run %s vanished from the tracker before execution", run_id)
            return

        evaluator: Evaluator | None = None
        evaluator_error: str | None = None
        try:
            evaluator = build_evaluator(
                mode,
                registry=self.registry,
                judge_provider=benchmark.judge_provider,
                judge_model=benchmark.judge_model,
            )
        except EvaluationError as exc:
            # A misconfigured evaluator must not prevent generations from running.
            evaluator_error = exc.message
            logger.warning("Run %s: evaluation disabled - %s", run_id, exc.message)

        semaphore = asyncio.Semaphore(max(1, config.max_concurrency))
        results = await asyncio.gather(
            *(
                self._execute_task(spec, state, semaphore, config, evaluator, evaluator_error)
                for spec in specs
            ),
            return_exceptions=True,
        )
        for outcome in results:
            if isinstance(outcome, BaseException) and not isinstance(
                outcome, asyncio.CancelledError
            ):
                logger.exception("Unhandled task error in run %s", run_id, exc_info=outcome)

        await self._finalise_run(run_id, state)

    async def _execute_task(
        self,
        spec: TaskSpec,
        state: RunState,
        semaphore: asyncio.Semaphore,
        config: RunConfig,
        evaluator: Evaluator | None,
        evaluator_error: str | None,
    ) -> None:
        task_state = state.tasks[spec.key]

        if state.cancelled:
            await self._persist_cancelled(spec, task_state, state)
            return

        async with semaphore:
            if state.cancelled:
                await self._persist_cancelled(spec, task_state, state)
                return

            task_state.status = ResultStatus.RUNNING
            self.tracker.publish(state)

            request = GenerationRequest(
                model=spec.model,
                prompt=spec.prompt,
                system_prompt=config.system_prompt,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                timeout=config.timeout,
            )

            result, error, attempts = await self._generate_with_retries(
                spec, request, state, config
            )
            task_state.attempts = attempts

            if error is not None:
                task_state.status = (
                    ResultStatus.CANCELLED
                    if error.code == ErrorCode.CANCELLED
                    else ResultStatus.FAILED
                )
                task_state.error_code = str(error.code)
                task_state.error_message = error.display_message()
                await self._persist_failure(spec, error, attempts)
                self.tracker.publish(state)
                return

            assert result is not None
            scores: EvaluationScores | None = None
            eval_error: str | None = evaluator_error
            if evaluator is not None and not state.cancelled:
                try:
                    scores = await evaluator.evaluate(
                        prompt=spec.prompt,
                        response=result.response,
                        system_prompt=config.system_prompt,
                    )
                except EvaluationError as exc:
                    eval_error = exc.message
                    logger.warning("Evaluation failed for %s: %s", spec.key, exc.message)
                except Exception as exc:  # never let a bad evaluator kill a result
                    eval_error = f"Evaluator raised {exc.__class__.__name__}."
                    logger.exception("Unexpected evaluator failure for %s", spec.key)

            await self._persist_success(spec, result, attempts, scores, evaluator, eval_error)

            task_state.status = ResultStatus.SUCCESS
            task_state.latency_ms = result.latency_ms
            self.tracker.publish(state)

    async def _generate_with_retries(
        self,
        spec: TaskSpec,
        request: GenerationRequest,
        state: RunState,
        config: RunConfig,
    ) -> tuple[GenerationResult | None, ProviderError | None, int]:
        """Call the provider, retrying transient failures with jittered backoff."""
        try:
            provider = self.registry.get(spec.provider_id)
        except ProviderError as exc:
            return None, exc, 0

        last_error: ProviderError | None = None
        attempts = 0

        for attempt in range(config.max_retries + 1):
            if state.cancelled:
                return (
                    None,
                    ProviderError(
                        "cancelled before completion.",
                        code=ErrorCode.CANCELLED,
                        provider=spec.provider_id,
                        model=spec.model,
                        retryable=False,
                    ),
                    attempts,
                )

            attempts = attempt + 1
            try:
                result = await self._race_cancel(provider.generate(request), state)
            except _Cancelled:
                return (
                    None,
                    ProviderError(
                        "cancelled before completion.",
                        code=ErrorCode.CANCELLED,
                        provider=spec.provider_id,
                        model=spec.model,
                        retryable=False,
                    ),
                    attempts,
                )
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= config.max_retries:
                    break
                delay = config.retry_base_delay * (2**attempt)
                delay += random.uniform(0, config.retry_base_delay)
                logger.info(
                    "Retrying %s after %s (attempt %d/%d, sleeping %.2fs)",
                    spec.key,
                    exc.code,
                    attempts,
                    config.max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            except Exception as exc:  # adapter bug - surface it, do not crash the run
                logger.exception("Adapter %s raised unexpectedly", spec.provider_id)
                last_error = ProviderError(
                    f"unexpected adapter error: {exc.__class__.__name__}",
                    code=ErrorCode.UNKNOWN,
                    provider=spec.provider_id,
                    model=spec.model,
                    retryable=False,
                )
                break
            else:
                return result, None, attempts

        return (
            None,
            last_error
            or ProviderError(
                "failed for an unknown reason.",
                code=ErrorCode.UNKNOWN,
                provider=spec.provider_id,
                model=spec.model,
            ),
            attempts,
        )

    @staticmethod
    async def _race_cancel(coro: Any, state: RunState) -> GenerationResult:
        """Await ``coro`` but abort it as soon as the run is cancelled."""
        gen_task: asyncio.Task[GenerationResult] = asyncio.ensure_future(coro)
        cancel_task = asyncio.ensure_future(state.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {gen_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if gen_task in done:
                return gen_task.result()
            gen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await gen_task
            raise _Cancelled
        finally:
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    async def _persist_success(
        self,
        spec: TaskSpec,
        result: GenerationResult,
        attempts: int,
        scores: EvaluationScores | None,
        evaluator: Evaluator | None,
        eval_error: str | None,
    ) -> None:
        async with session_scope() as session:
            row = await session.get(ModelResult, spec.result_id)
            if row is None:  # pragma: no cover - defensive
                return
            row.status = ResultStatus.SUCCESS
            row.response = result.response
            row.input_tokens = result.input_tokens
            row.output_tokens = result.output_tokens
            row.total_tokens = result.total_tokens
            row.latency_ms = result.latency_ms
            row.tokens_per_second = result.tokens_per_second
            row.estimated_cost = result.estimated_cost
            row.finish_reason = result.finish_reason
            row.token_source = result.token_source
            row.attempts = attempts
            metadata = dict(result.metadata)
            if eval_error:
                metadata["evaluation_error"] = eval_error
            row.extra_metadata = metadata

            if scores is not None and evaluator is not None:
                session.add(
                    Evaluation(
                        model_result_id=row.id,
                        relevance=scores.relevance,
                        correctness=scores.correctness,
                        conciseness=scores.conciseness,
                        clarity=scores.clarity,
                        overall=scores.overall,
                        reasoning=scores.reasoning,
                        mode=evaluator.mode,
                        evaluator_model=evaluator.evaluator_model,
                    )
                )

    async def _persist_failure(self, spec: TaskSpec, error: ProviderError, attempts: int) -> None:
        async with session_scope() as session:
            row = await session.get(ModelResult, spec.result_id)
            if row is None:  # pragma: no cover - defensive
                return
            row.status = (
                ResultStatus.CANCELLED if error.code == ErrorCode.CANCELLED else ResultStatus.FAILED
            )
            row.error_code = str(error.code)
            row.error_message = error.display_message()
            row.attempts = attempts
            row.extra_metadata = {
                "upstream_status": error.status_code_upstream,
                "retryable": error.retryable,
            }

    async def _persist_cancelled(
        self, spec: TaskSpec, task_state: TaskState, state: RunState
    ) -> None:
        task_state.status = ResultStatus.CANCELLED
        task_state.error_code = str(ErrorCode.CANCELLED)
        task_state.error_message = "Run was cancelled before this model started."
        async with session_scope() as session:
            row = await session.get(ModelResult, spec.result_id)
            if row is not None:
                row.status = ResultStatus.CANCELLED
                row.error_code = str(ErrorCode.CANCELLED)
                row.error_message = task_state.error_message
        self.tracker.publish(state)

    async def _finalise_run(self, run_id: int, state: RunState) -> None:
        completed_at = datetime.now(UTC)
        async with session_scope() as session:
            run = await session.get(BenchmarkRun, run_id)
            if run is None:  # pragma: no cover - defensive
                return
            statuses = [t.status for t in state.tasks.values()]
            if state.cancelled:
                status = RunStatus.CANCELLED
            elif statuses and all(s == ResultStatus.FAILED for s in statuses):
                status = RunStatus.FAILED
            else:
                status = RunStatus.COMPLETED
            run.status = status
            run.completed_at = completed_at
            failures = sum(1 for s in statuses if s == ResultStatus.FAILED)
            if failures and status == RunStatus.COMPLETED:
                run.error_message = f"{failures} of {len(statuses)} model calls failed."
            elif status == RunStatus.FAILED:
                run.error_message = "Every model call failed."

        state.status = status
        state.completed_at = completed_at
        self.tracker.finish(state)
        logger.info("Run %s finished with status %s", run_id, status)

    async def drain(self) -> None:
        """Await outstanding background runs (used on shutdown and in tests)."""
        if self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)


class _Cancelled(Exception):
    """Internal signal: the run was cancelled while a request was in flight."""


def attach_cost_per_1k(result: ModelResult) -> float | None:
    """Blended cost per 1K tokens for a stored result (``None`` when unpriced)."""
    if result.input_tokens is None or result.output_tokens is None:
        return None
    return cost_per_1k_tokens(
        result.provider, result.model, result.input_tokens, result.output_tokens
    )


async def load_run(session: AsyncSession, run_id: int) -> BenchmarkRun:
    run = (
        await session.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError(f"Run {run_id} was not found.")
    return run
