"""Analytics aggregation and the model leaderboard.

Aggregation happens in Python over a filtered result set rather than in SQL.
For a local-first tool the row counts are small (thousands, not millions), and
keeping the arithmetic in one readable place avoids four dialect-specific
aggregate queries. If this ever needs to scale, the filters below are already
pushed into SQL — only the reduction step would move.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pricing import cost_per_1k_tokens
from app.models.benchmark import Benchmark, BenchmarkRun, Evaluation, ModelResult, ResultStatus
from app.schemas.analytics import (
    AnalyticsResponse,
    AnalyticsTotals,
    ErrorStat,
    LeaderboardEntry,
    LeaderboardResponse,
    ModelStat,
    ProviderStat,
    TimelinePoint,
)

#: metric -> (sort direction, human description)
LEADERBOARD_METRICS: dict[str, tuple[str, str]] = {
    "quality": ("desc", "Mean overall evaluation score (0-10) across scored executions."),
    "latency": ("asc", "Mean wall-clock latency in milliseconds per successful execution."),
    "cost": ("asc", "Mean estimated USD cost per execution. Unpriced models are excluded."),
    "cost_per_1k": ("asc", "Blended estimated USD cost per 1,000 tokens."),
    "throughput": ("desc", "Mean output tokens per second."),
    "success_rate": ("desc", "Share of executions that completed without an error."),
    "token_efficiency": (
        "asc",
        "Mean output tokens per execution - lower means a more compact answer "
        "for the same prompt. Read it alongside quality, never alone.",
    ),
}

METHODOLOGY = (
    "PromptBench does not compute a single composite 'best model' score, because any "
    "weighting of quality against cost and latency encodes a preference that belongs to "
    "you, not to the tool. Pick the metric that matters for your workload and read the "
    "raw values next to it. Quality comes from the evaluation mode recorded on each run "
    "and is only comparable across rows scored the same way. Costs are estimates from "
    "the configured pricing table, and models with no configured price are excluded from "
    "cost metrics rather than counted as free."
)


def _mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean, or ``None`` for an empty sequence.

    Rounded to 10 decimal places rather than a display precision: per-request
    costs are routinely below 1e-4, and rounding here would collapse a paid
    model to 0.0 and make it look free on the leaderboard. Formatting is the
    UI's job.
    """
    return round(sum(values) / len(values), 10) if values else None


def _percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 2)


async def _fetch_results(
    session: AsyncSession,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    provider: str | None,
    model: str | None,
    benchmark_id: int | None,
) -> list[ModelResult]:
    query = (
        select(ModelResult)
        .options(selectinload(ModelResult.evaluation))
        .join(BenchmarkRun, ModelResult.benchmark_run_id == BenchmarkRun.id)
    )
    if date_from:
        query = query.where(BenchmarkRun.started_at >= date_from)
    if date_to:
        query = query.where(BenchmarkRun.started_at <= date_to)
    if provider:
        query = query.where(ModelResult.provider == provider)
    if model:
        query = query.where(ModelResult.model == model)
    if benchmark_id:
        query = query.where(BenchmarkRun.benchmark_id == benchmark_id)
    return list((await session.execute(query)).unique().scalars().all())


def _model_stat(provider: str, model: str, results: list[ModelResult]) -> ModelStat:
    successes = [r for r in results if r.status == ResultStatus.SUCCESS]
    failures = [r for r in results if r.status == ResultStatus.FAILED]

    latencies = [float(r.latency_ms) for r in successes if r.latency_ms is not None]
    tps = [float(r.tokens_per_second) for r in successes if r.tokens_per_second]
    inputs = [float(r.input_tokens) for r in successes if r.input_tokens is not None]
    outputs = [float(r.output_tokens) for r in successes if r.output_tokens is not None]
    costs = [float(r.estimated_cost) for r in successes if r.estimated_cost is not None]
    total_tokens = sum(int(r.total_tokens) for r in successes if r.total_tokens is not None)

    evaluations = [r.evaluation for r in successes if r.evaluation is not None]
    qualities = [e.overall for e in evaluations]

    per_1k: list[float] = []
    for r in successes:
        if r.input_tokens is None or r.output_tokens is None:
            continue
        value = cost_per_1k_tokens(r.provider, r.model, r.input_tokens, r.output_tokens)
        if value is not None:
            per_1k.append(value)

    return ModelStat(
        provider=provider,
        model=model,
        executions=len(results),
        successes=len(successes),
        failures=len(failures),
        success_rate=round(len(successes) / len(results), 4) if results else 0.0,
        avg_latency_ms=_mean(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        avg_tokens_per_second=_mean(tps),
        avg_input_tokens=_mean(inputs),
        avg_output_tokens=_mean(outputs),
        total_tokens=total_tokens,
        avg_cost=_mean(costs),
        total_cost=round(sum(costs), 8) if costs else None,
        cost_per_1k_tokens=_mean(per_1k),
        avg_quality=_mean(qualities),
        avg_relevance=_mean([e.relevance for e in evaluations]),
        avg_correctness=_mean([e.correctness for e in evaluations]),
        avg_conciseness=_mean([e.conciseness for e in evaluations]),
        avg_clarity=_mean([e.clarity for e in evaluations]),
        priced=bool(costs),
    )


async def build_analytics(
    session: AsyncSession,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    provider: str | None = None,
    model: str | None = None,
    benchmark_id: int | None = None,
) -> AnalyticsResponse:
    results = await _fetch_results(
        session,
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        model=model,
        benchmark_id=benchmark_id,
    )

    total_benchmarks = int((await session.execute(select(func.count(Benchmark.id)))).scalar_one())
    run_ids = {r.benchmark_run_id for r in results}

    successes = [r for r in results if r.status == ResultStatus.SUCCESS]
    latencies = [float(r.latency_ms) for r in successes if r.latency_ms is not None]
    costs = [float(r.estimated_cost) for r in successes if r.estimated_cost is not None]
    qualities = [r.evaluation.overall for r in successes if r.evaluation is not None]
    input_tokens = sum(int(r.input_tokens or 0) for r in successes)
    output_tokens = sum(int(r.output_tokens or 0) for r in successes)

    totals = AnalyticsTotals(
        total_benchmarks=total_benchmarks,
        total_runs=len(run_ids),
        total_executions=len(results),
        successful_executions=len(successes),
        failed_executions=sum(1 for r in results if r.status == ResultStatus.FAILED),
        total_tokens=input_tokens + output_tokens,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        avg_latency_ms=_mean(latencies),
        avg_cost=_mean(costs),
        total_cost=round(sum(costs), 8) if costs else None,
        avg_quality=_mean(qualities),
        unpriced_executions=sum(1 for r in successes if r.estimated_cost is None),
    )

    grouped: dict[tuple[str, str], list[ModelResult]] = defaultdict(list)
    by_provider_raw: dict[str, list[ModelResult]] = defaultdict(list)
    for result in results:
        grouped[(result.provider, result.model)].append(result)
        by_provider_raw[result.provider].append(result)

    by_model = [_model_stat(p, m, rows) for (p, m), rows in grouped.items()]
    by_model.sort(key=lambda s: s.executions, reverse=True)

    by_provider: list[ProviderStat] = []
    for provider_id, rows in by_provider_raw.items():
        ok = [r for r in rows if r.status == ResultStatus.SUCCESS]
        by_provider.append(
            ProviderStat(
                provider=provider_id,
                executions=len(rows),
                successes=len(ok),
                failures=sum(1 for r in rows if r.status == ResultStatus.FAILED),
                avg_latency_ms=_mean([float(r.latency_ms) for r in ok if r.latency_ms is not None]),
                total_cost=round(
                    sum(float(r.estimated_cost) for r in ok if r.estimated_cost is not None), 8
                )
                or None,
                avg_quality=_mean([r.evaluation.overall for r in ok if r.evaluation is not None]),
            )
        )
    by_provider.sort(key=lambda s: s.executions, reverse=True)

    timeline = _build_timeline(results)

    error_counts: dict[str, int] = defaultdict(int)
    for result in results:
        if result.status == ResultStatus.FAILED and result.error_code:
            error_counts[result.error_code] += 1
    errors = [ErrorStat(code=code, count=count) for code, count in error_counts.items()]
    errors.sort(key=lambda e: e.count, reverse=True)

    return AnalyticsResponse(
        totals=totals,
        by_model=by_model,
        by_provider=by_provider,
        timeline=timeline,
        errors=errors,
        filters_applied={
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "provider": provider,
            "model": model,
            "benchmark_id": str(benchmark_id) if benchmark_id else None,
        },
        generated_at=datetime.now(UTC),
    )


def _build_timeline(results: list[ModelResult]) -> list[TimelinePoint]:
    by_day: dict[str, list[ModelResult]] = defaultdict(list)
    runs_by_day: dict[str, set[int]] = defaultdict(set)
    for result in results:
        day = result.created_at.date().isoformat()
        by_day[day].append(result)
        runs_by_day[day].add(result.benchmark_run_id)

    points: list[TimelinePoint] = []
    for day in sorted(by_day):
        rows = by_day[day]
        ok = [r for r in rows if r.status == ResultStatus.SUCCESS]
        day_costs = [float(r.estimated_cost) for r in ok if r.estimated_cost is not None]
        points.append(
            TimelinePoint(
                date=day,
                runs=len(runs_by_day[day]),
                executions=len(rows),
                avg_latency_ms=_mean([float(r.latency_ms) for r in ok if r.latency_ms is not None]),
                total_cost=round(sum(day_costs), 8) if day_costs else None,
                avg_quality=_mean([r.evaluation.overall for r in ok if r.evaluation is not None]),
            )
        )
    return points


def _sort_key(stat: ModelStat, metric: str) -> tuple[int, float]:
    """Return (missing_flag, value); rows with no data always sort last."""
    value: float | None
    if metric == "quality":
        value = stat.avg_quality
    elif metric == "latency":
        value = stat.avg_latency_ms
    elif metric == "cost":
        value = stat.avg_cost
    elif metric == "cost_per_1k":
        value = stat.cost_per_1k_tokens
    elif metric == "throughput":
        value = stat.avg_tokens_per_second
    elif metric == "success_rate":
        value = stat.success_rate
    elif metric == "token_efficiency":
        value = stat.avg_output_tokens
    else:
        value = stat.avg_quality
    return (1, 0.0) if value is None else (0, value)


async def build_leaderboard(
    session: AsyncSession,
    *,
    metric: str = "quality",
    min_executions: int = 1,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    provider: str | None = None,
    benchmark_id: int | None = None,
) -> LeaderboardResponse:
    if metric not in LEADERBOARD_METRICS:
        metric = "quality"
    direction, description = LEADERBOARD_METRICS[metric]

    analytics = await build_analytics(
        session,
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        benchmark_id=benchmark_id,
    )
    stats = [s for s in analytics.by_model if s.executions >= max(1, min_executions)]
    stats.sort(key=lambda s: _sort_key(s, metric), reverse=(direction == "desc"))
    # `reverse=True` would also flip the "missing data last" flag; re-partition.
    if direction == "desc":
        present = [s for s in stats if _sort_key(s, metric)[0] == 0]
        missing = [s for s in stats if _sort_key(s, metric)[0] == 1]
        stats = present + missing

    entries = [
        LeaderboardEntry(rank=index + 1, **stat.model_dump()) for index, stat in enumerate(stats)
    ]
    return LeaderboardResponse(
        metric=metric,
        direction=direction,
        min_executions=min_executions,
        entries=entries,
        methodology=f"{description}\n\n{METHODOLOGY}",
    )


async def dashboard_summary(session: AsyncSession) -> dict[str, Any]:
    """Compact figures for the dashboard landing page."""
    analytics = await build_analytics(session)
    recent = (
        (
            await session.execute(
                select(Benchmark)
                .options(selectinload(Benchmark.runs))
                .order_by(Benchmark.created_at.desc())
                .limit(5)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    scored = int((await session.execute(select(func.count(Evaluation.id)))).scalar_one())
    return {
        "totals": analytics.totals.model_dump(),
        "top_models": [s.model_dump() for s in analytics.by_model[:5]],
        "evaluations_recorded": scored,
        "recent_benchmark_ids": [b.id for b in recent],
    }
