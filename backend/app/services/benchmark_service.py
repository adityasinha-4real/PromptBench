"""Benchmark CRUD, listing and serialisation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.benchmark import (
    Benchmark,
    BenchmarkRun,
    Evaluation,
    EvaluationMode,
    ModelResult,
    PromptVariant,
    ResultStatus,
)
from app.schemas.benchmark import (
    BenchmarkCreate,
    BenchmarkDetail,
    BenchmarkListItem,
    BenchmarkRunOut,
    BenchmarkUpdate,
    EvaluationOut,
    ModelResultOut,
    RunSummary,
)
from app.services.engine import attach_cost_per_1k

PROMPT_EXCERPT_CHARS = 220

SORTABLE_FIELDS = {
    "created_at": Benchmark.created_at,
    "name": Benchmark.name,
    "updated_at": Benchmark.updated_at,
}


# ----------------------------------------------------------------------
# Serialisation
# ----------------------------------------------------------------------
def serialize_result(result: ModelResult) -> ModelResultOut:
    out = ModelResultOut.model_validate(result)
    out.cost_per_1k_tokens = attach_cost_per_1k(result)
    if result.evaluation is not None:
        out.evaluation = EvaluationOut.model_validate(result.evaluation)
    return out


def serialize_run(run: BenchmarkRun) -> BenchmarkRunOut:
    out = BenchmarkRunOut.model_validate(run)
    out.duration_ms = run.duration_ms
    out.results = [serialize_result(r) for r in run.results]
    return out


def summarise_run(run: BenchmarkRun) -> RunSummary:
    results = list(run.results)
    successes = [r for r in results if r.status == ResultStatus.SUCCESS]
    latencies = [r.latency_ms for r in successes if r.latency_ms is not None]
    costs = [r.estimated_cost for r in successes if r.estimated_cost is not None]
    qualities = [r.evaluation.overall for r in successes if r.evaluation is not None]
    return RunSummary(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        result_count=len(results),
        success_count=len(successes),
        failure_count=sum(1 for r in results if r.status == ResultStatus.FAILED),
        avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else None,
        total_cost=round(sum(costs), 8) if costs else None,
        avg_quality=round(sum(qualities) / len(qualities), 2) if qualities else None,
    )


def serialize_detail(benchmark: Benchmark, include_latest_run: bool = True) -> BenchmarkDetail:
    detail = BenchmarkDetail.model_validate(benchmark)
    runs = sorted(benchmark.runs, key=lambda r: r.id, reverse=True)
    detail.runs = [summarise_run(r) for r in runs]
    if include_latest_run and runs:
        detail.latest_run = serialize_run(runs[0])
    return detail


# ----------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------
def _detail_query() -> Select[tuple[Benchmark]]:
    return select(Benchmark).options(
        selectinload(Benchmark.variants),
        selectinload(Benchmark.runs)
        .selectinload(BenchmarkRun.results)
        .selectinload(ModelResult.evaluation),
    )


async def get_benchmark(session: AsyncSession, benchmark_id: int) -> Benchmark:
    benchmark = (
        await session.execute(_detail_query().where(Benchmark.id == benchmark_id))
    ).scalar_one_or_none()
    if benchmark is None:
        raise NotFoundError(f"Benchmark {benchmark_id} was not found.")
    return benchmark


async def create_benchmark(session: AsyncSession, payload: BenchmarkCreate) -> Benchmark:
    benchmark = Benchmark(
        name=payload.name,
        description=payload.description,
        prompt=payload.prompt,
        system_prompt=payload.system_prompt,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        top_p=payload.top_p,
        evaluation_enabled=payload.evaluation_enabled,
        evaluation_mode=(
            payload.evaluation_mode if payload.evaluation_enabled else EvaluationMode.DISABLED
        ),
        judge_provider=payload.judge_provider,
        judge_model=payload.judge_model,
        models=[m.model_dump() for m in payload.models],
        tags=payload.tags,
    )
    for position, variant in enumerate(payload.variants):
        benchmark.variants.append(
            PromptVariant(name=variant.name, prompt=variant.prompt, position=position)
        )
    session.add(benchmark)
    await session.commit()
    await session.refresh(benchmark)
    return await get_benchmark(session, benchmark.id)


async def update_benchmark(
    session: AsyncSession, benchmark_id: int, payload: BenchmarkUpdate
) -> Benchmark:
    benchmark = await get_benchmark(session, benchmark_id)
    if payload.name is not None:
        benchmark.name = " ".join(payload.name.split())
    if payload.description is not None:
        benchmark.description = payload.description or None
    if payload.tags is not None:
        benchmark.tags = payload.tags
    await session.commit()
    return await get_benchmark(session, benchmark_id)


async def delete_benchmark(session: AsyncSession, benchmark_id: int) -> None:
    existing = await session.get(Benchmark, benchmark_id)
    if existing is None:
        raise NotFoundError(f"Benchmark {benchmark_id} was not found.")
    # Explicit DELETE relies on the ON DELETE CASCADE foreign keys.
    await session.execute(delete(Benchmark).where(Benchmark.id == benchmark_id))
    await session.commit()


async def list_benchmarks(
    session: AsyncSession,
    *,
    search: str | None = None,
    tag: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[BenchmarkListItem], int]:
    """Filtered, sorted, paginated history listing."""
    query = _detail_query()
    count_query = select(func.count()).select_from(Benchmark)
    conditions = []

    if search:
        pattern = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(Benchmark.name).like(pattern),
                func.lower(Benchmark.prompt).like(pattern),
                func.lower(func.coalesce(Benchmark.description, "")).like(pattern),
            )
        )
    if tag:
        # JSON arrays are stored as text on SQLite; a LIKE on the serialised
        # form is the portable way to filter without a JSON operator.
        conditions.append(
            func.lower(func.cast(Benchmark.tags, String)).like(f'%"{tag.strip().lower()}"%')
        )
    if provider or model:
        needle = provider or model or ""
        conditions.append(
            func.lower(func.cast(Benchmark.models, String)).like(f"%{needle.strip().lower()}%")
        )
    if date_from:
        conditions.append(Benchmark.created_at >= date_from)
    if date_to:
        conditions.append(Benchmark.created_at <= date_to)
    if status:
        sub = select(BenchmarkRun.benchmark_id).where(BenchmarkRun.status == status)
        conditions.append(Benchmark.id.in_(sub))

    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    column = SORTABLE_FIELDS.get(sort, Benchmark.created_at)
    query = query.order_by(column.asc() if order == "asc" else column.desc())
    query = query.limit(max(1, min(limit, 100))).offset(max(0, offset))

    total = int((await session.execute(count_query)).scalar_one())
    benchmarks = list((await session.execute(query)).unique().scalars().all())
    return [_to_list_item(b) for b in benchmarks], total


def _to_list_item(benchmark: Benchmark) -> BenchmarkListItem:
    runs = sorted(benchmark.runs, key=lambda r: r.id, reverse=True)
    latest = runs[0] if runs else None

    qualities: list[float] = []
    costs: list[float] = []
    if latest:
        for result in latest.results:
            if result.evaluation is not None:
                qualities.append(result.evaluation.overall)
            if result.estimated_cost is not None:
                costs.append(result.estimated_cost)

    prompt = benchmark.prompt.strip().replace("\n", " ")
    excerpt = prompt[:PROMPT_EXCERPT_CHARS] + ("…" if len(prompt) > PROMPT_EXCERPT_CHARS else "")

    return BenchmarkListItem(
        id=benchmark.id,
        name=benchmark.name,
        description=benchmark.description,
        prompt_excerpt=excerpt,
        tags=list(benchmark.tags or []),
        model_count=len(benchmark.models or []),
        variant_count=len(benchmark.variants),
        run_count=len(runs),
        evaluation_mode=benchmark.evaluation_mode,
        created_at=benchmark.created_at,
        last_run_at=latest.started_at if latest else None,
        last_run_status=latest.status if latest else None,
        avg_quality=round(sum(qualities) / len(qualities), 2) if qualities else None,
        total_cost=round(sum(costs), 8) if costs else None,
    )


async def get_run(session: AsyncSession, run_id: int) -> BenchmarkRun:
    run = (
        await session.execute(
            select(BenchmarkRun)
            .options(selectinload(BenchmarkRun.results).selectinload(ModelResult.evaluation))
            .where(BenchmarkRun.id == run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError(f"Run {run_id} was not found.")
    return run


async def get_model_result(session: AsyncSession, result_id: int) -> ModelResult:
    result = (
        await session.execute(
            select(ModelResult)
            .options(selectinload(ModelResult.evaluation))
            .where(ModelResult.id == result_id)
        )
    ).scalar_one_or_none()
    if result is None:
        raise NotFoundError(f"Model result {result_id} was not found.")
    return result


async def delete_run(session: AsyncSession, run_id: int) -> None:
    run = await session.get(BenchmarkRun, run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} was not found.")
    await session.execute(delete(BenchmarkRun).where(BenchmarkRun.id == run_id))
    await session.commit()


async def remove_result(session: AsyncSession, result_id: int) -> None:
    """Drop one model result from a comparison (used by 'remove from comparison')."""
    result = await session.get(ModelResult, result_id)
    if result is None:
        raise NotFoundError(f"Model result {result_id} was not found.")
    await session.execute(delete(Evaluation).where(Evaluation.model_result_id == result_id))
    await session.execute(delete(ModelResult).where(ModelResult.id == result_id))
    await session.commit()


def build_matrix(run: BenchmarkRun) -> dict[str, Any]:
    """Variant x model matrix used by the comparison grid."""
    variants: list[str] = []
    targets: list[str] = []
    cells: dict[str, dict[str, int]] = {}
    for result in run.results:
        if result.variant_name not in variants:
            variants.append(result.variant_name)
        key = f"{result.provider}:{result.model}"
        if key not in targets:
            targets.append(key)
        cells.setdefault(result.variant_name, {})[key] = result.id
    return {"variants": variants, "targets": targets, "cells": cells}
