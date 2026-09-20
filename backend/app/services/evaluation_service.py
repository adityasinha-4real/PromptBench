"""Standalone (post-run) evaluation of stored results."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.evaluation.base import EvaluationError, Evaluator
from app.evaluation.factory import build_evaluator, build_manual_evaluator
from app.models.benchmark import (
    Benchmark,
    BenchmarkRun,
    Evaluation,
    EvaluationMode,
    ModelResult,
    PromptVariant,
    ResultStatus,
)
from app.providers.registry import ProviderRegistry
from app.schemas.benchmark import EvaluationOut
from app.schemas.evaluation import EvaluateRequest, EvaluateResponse

logger = get_logger(__name__)


async def _prompt_for_result(session: AsyncSession, result: ModelResult) -> tuple[str, str | None]:
    """Resolve the exact prompt text this result was generated from."""
    if result.variant_id is not None:
        variant = await session.get(PromptVariant, result.variant_id)
        if variant is not None:
            benchmark = await session.get(Benchmark, variant.benchmark_id)
            return variant.prompt, benchmark.system_prompt if benchmark else None

    run = await session.get(BenchmarkRun, result.benchmark_run_id)
    if run is None:
        raise NotFoundError(f"Run for result {result.id} is missing.")
    benchmark = await session.get(Benchmark, run.benchmark_id)
    if benchmark is None:
        raise NotFoundError(f"Benchmark for run {run.id} is missing.")
    return benchmark.prompt, benchmark.system_prompt


async def _load_targets(session: AsyncSession, request: EvaluateRequest) -> list[ModelResult]:
    if request.model_result_id is not None:
        result = (
            await session.execute(
                select(ModelResult)
                .options(selectinload(ModelResult.evaluation))
                .where(ModelResult.id == request.model_result_id)
            )
        ).scalar_one_or_none()
        if result is None:
            raise NotFoundError(f"Model result {request.model_result_id} was not found.")
        return [result]

    results = list(
        (
            await session.execute(
                select(ModelResult)
                .options(selectinload(ModelResult.evaluation))
                .where(ModelResult.benchmark_run_id == request.run_id)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    if not results:
        raise NotFoundError(f"Run {request.run_id} has no results to evaluate.")
    return results


async def evaluate(
    session: AsyncSession, request: EvaluateRequest, registry: ProviderRegistry
) -> EvaluateResponse:
    """Score one result or a whole run, replacing existing scores when asked."""
    targets = await _load_targets(session, request)

    evaluator: Evaluator
    if request.mode == EvaluationMode.MANUAL:
        assert request.scores is not None  # guaranteed by schema validation
        payload = request.scores.model_dump(exclude_none=True)
        evaluator = build_manual_evaluator(payload, request.reviewer)
    else:
        try:
            built = build_evaluator(
                str(request.mode),
                registry=registry,
                judge_provider=request.judge_provider,
                judge_model=request.judge_model,
            )
        except EvaluationError as exc:
            raise ValidationError(exc.message) from exc
        if built is None:
            raise ValidationError(f"Mode '{request.mode}' does not produce scores.")
        evaluator = built

    evaluations: list[EvaluationOut] = []
    errors: list[str] = []
    failed = 0

    for result in targets:
        label = f"{result.provider}:{result.model} ({result.variant_name})"

        if result.status != ResultStatus.SUCCESS or not (result.response or "").strip():
            errors.append(f"{label}: skipped — no successful response to score.")
            failed += 1
            continue
        if result.evaluation is not None and not request.overwrite:
            errors.append(f"{label}: skipped — already scored and overwrite is off.")
            continue

        prompt, system_prompt = await _prompt_for_result(session, result)
        try:
            scores = await evaluator.evaluate(
                prompt=prompt, response=result.response or "", system_prompt=system_prompt
            )
        except EvaluationError as exc:
            errors.append(f"{label}: {exc.message}")
            failed += 1
            continue
        except Exception as exc:
            logger.exception("Evaluator crashed on result %s", result.id)
            errors.append(f"{label}: evaluator raised {exc.__class__.__name__}.")
            failed += 1
            continue

        await session.execute(delete(Evaluation).where(Evaluation.model_result_id == result.id))
        row = Evaluation(
            model_result_id=result.id,
            relevance=scores.relevance,
            correctness=scores.correctness,
            conciseness=scores.conciseness,
            clarity=scores.clarity,
            overall=scores.overall,
            reasoning=scores.reasoning,
            mode=evaluator.mode,
            evaluator_model=evaluator.evaluator_model,
        )
        session.add(row)
        await session.flush()
        evaluations.append(EvaluationOut.model_validate(row))

    await session.commit()
    return EvaluateResponse(
        evaluated=len(evaluations), failed=failed, evaluations=evaluations, errors=errors
    )
