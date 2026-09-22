"""Compare two runs of the same benchmark.

Re-running a benchmark only answers "what changed?" if something lines the two
runs up. That is this module: it matches results by (provider, model, variant)
and reports each metric's movement.

Two rules carry through every function here:

* A missing value is missing, never zero. A model with no price or no score
  produces an ``unknown`` direction, and is left out of averages.
* "Better" is per metric — higher quality is better, lower latency and cost are
  better — and is never collapsed into a single composite score.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.benchmark import BenchmarkRun, ModelResult, ResultStatus
from app.schemas.comparison import (
    ComparisonEntry,
    ComparisonRunRef,
    ComparisonSummary,
    EntryChange,
    MetricDelta,
    RunComparison,
)
from app.services import benchmark_service

#: Movements smaller than this are reported as unchanged rather than as noise.
QUALITY_EPSILON = 0.05
RELATIVE_EPSILON = 0.01  # 1% for latency, cost and tokens


def result_key(result: ModelResult) -> str:
    return f"{result.variant_name}::{result.provider}:{result.model}"


def _delta(
    base: float | None,
    target: float | None,
    *,
    higher_is_better: bool,
    epsilon: float,
    relative: bool,
) -> MetricDelta:
    metric = MetricDelta(base=base, target=target)
    if base is None or target is None:
        return metric

    metric.delta = round(target - base, 8)
    if base:
        metric.percent_change = round((target - base) / abs(base) * 100, 2)

    threshold = abs(base) * epsilon if relative else epsilon
    if abs(metric.delta) <= threshold:
        metric.direction = "unchanged"
    elif (metric.delta > 0) == higher_is_better:
        metric.direction = "better"
    else:
        metric.direction = "worse"
    return metric


def _quality_of(result: ModelResult | None) -> float | None:
    if result is None or result.evaluation is None:
        return None
    return result.evaluation.overall


def _metric_of(result: ModelResult | None, attribute: str) -> float | None:
    # Only a successful result has meaningful metrics; a failure's latency is
    # the time spent failing, which would read as an improvement.
    if result is None or result.status != ResultStatus.SUCCESS:
        return None
    value = getattr(result, attribute)
    return float(value) if value is not None else None


def _classify(entry: ComparisonEntry) -> tuple[EntryChange, str | None]:
    """Fold the per-metric directions into one verdict for the row."""
    if entry.base_status is None:
        return "added", "Only in the newer run."
    if entry.target_status is None:
        return "removed", "Only in the older run."

    was_ok = entry.base_status == ResultStatus.SUCCESS
    is_ok = entry.target_status == ResultStatus.SUCCESS
    if was_ok and not is_ok:
        return "regressed", "Succeeded before, failed in the newer run."
    if not was_ok and is_ok:
        return "improved", "Failed before, succeeded in the newer run."
    if not was_ok and not is_ok:
        return "unchanged", "Failed in both runs."

    directions = [
        entry.quality.direction,
        entry.latency_ms.direction,
        entry.estimated_cost.direction,
    ]
    better = directions.count("better")
    worse = directions.count("worse")
    if better and worse:
        return "mixed", None
    if better:
        return "improved", None
    if worse:
        return "regressed", None
    return "unchanged", None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _run_ref(run: BenchmarkRun) -> ComparisonRunRef:
    modes = {r.evaluation.mode for r in run.results if r.evaluation is not None}
    return ComparisonRunRef(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        result_count=len(run.results),
        evaluation_modes=sorted(modes),
    )


def build_comparison(base: BenchmarkRun, target: BenchmarkRun) -> RunComparison:
    """Compare ``target`` against ``base``, oldest run first."""
    base_results = {result_key(r): r for r in base.results}
    target_results = {result_key(r): r for r in target.results}

    base_ref = _run_ref(base)
    target_ref = _run_ref(target)
    # Heuristic and LLM-judge scores are not on the same scale; saying a score
    # rose when the scorer changed would be a lie.
    comparable = not (
        base_ref.evaluation_modes
        and target_ref.evaluation_modes
        and base_ref.evaluation_modes != target_ref.evaluation_modes
    )

    entries: list[ComparisonEntry] = []
    for key in _ordered_keys(base.results, target.results):
        base_result = base_results.get(key)
        target_result = target_results.get(key)
        sample = target_result or base_result
        if sample is None:  # unreachable: a key comes from one of the two sides
            continue

        entry = ComparisonEntry(
            key=key,
            provider=sample.provider,
            model=sample.model,
            variant_name=sample.variant_name,
            base_status=base_result.status if base_result else None,
            target_status=target_result.status if target_result else None,
            quality=_delta(
                _quality_of(base_result) if comparable else None,
                _quality_of(target_result) if comparable else None,
                higher_is_better=True,
                epsilon=QUALITY_EPSILON,
                relative=False,
            ),
            latency_ms=_delta(
                _metric_of(base_result, "latency_ms"),
                _metric_of(target_result, "latency_ms"),
                higher_is_better=False,
                epsilon=RELATIVE_EPSILON,
                relative=True,
            ),
            estimated_cost=_delta(
                _metric_of(base_result, "estimated_cost"),
                _metric_of(target_result, "estimated_cost"),
                higher_is_better=False,
                epsilon=RELATIVE_EPSILON,
                relative=True,
            ),
            total_tokens=_delta(
                _metric_of(base_result, "total_tokens"),
                _metric_of(target_result, "total_tokens"),
                higher_is_better=False,
                epsilon=RELATIVE_EPSILON,
                relative=True,
            ),
        )
        entry.change, entry.note = _classify(entry)
        entries.append(entry)

    return RunComparison(
        benchmark_id=target.benchmark_id,
        base=base_ref,
        target=target_ref,
        entries=entries,
        summary=_summarise(entries),
        quality_comparable=comparable,
        notes=_notes(base_ref, target_ref, comparable),
    )


def _ordered_keys(base: Iterable[ModelResult], target: Iterable[ModelResult]) -> list[str]:
    """Target order first (what the user is looking at), then base-only rows."""
    keys = [result_key(r) for r in target]
    seen = set(keys)
    keys.extend(result_key(r) for r in base if result_key(r) not in seen)
    return keys


def _summarise(entries: list[ComparisonEntry]) -> ComparisonSummary:
    summary = ComparisonSummary()
    for entry in entries:
        setattr(summary, entry.change, getattr(summary, entry.change) + 1)
        was_ok = entry.base_status == ResultStatus.SUCCESS
        is_ok = entry.target_status == ResultStatus.SUCCESS
        if was_ok and entry.target_status is not None and not is_ok:
            summary.new_failures += 1
        if entry.base_status is not None and not was_ok and is_ok:
            summary.fixed_failures += 1

    summary.avg_quality_delta = _mean(
        [e.quality.delta for e in entries if e.quality.delta is not None]
    )
    summary.avg_latency_delta_ms = _mean(
        [e.latency_ms.delta for e in entries if e.latency_ms.delta is not None]
    )
    costs = [e.estimated_cost.delta for e in entries if e.estimated_cost.delta is not None]
    summary.total_cost_delta = round(sum(costs), 8) if costs else None
    return summary


def _notes(base: ComparisonRunRef, target: ComparisonRunRef, comparable: bool) -> list[str]:
    notes: list[str] = []
    if not comparable:
        notes.append(
            "Quality is not compared: these runs were scored in different evaluation "
            f"modes ({', '.join(base.evaluation_modes)} vs "
            f"{', '.join(target.evaluation_modes)})."
        )
    for ref, label in ((base, "older"), (target, "newer")):
        if ref.status != "completed":
            notes.append(f"The {label} run is {ref.status}, so its figures may be partial.")
    return notes


async def compare_runs(
    session: AsyncSession,
    benchmark_id: int,
    *,
    base_run_id: int | None = None,
    target_run_id: int | None = None,
) -> RunComparison:
    """Compare two runs, defaulting to the two most recent ones.

    Raises:
        NotFoundError: when the benchmark or either run does not exist.
        ValidationError: when a run belongs to another benchmark, fewer than two
            runs exist, or both ids are the same run.
    """
    benchmark = await benchmark_service.get_benchmark(session, benchmark_id)
    run_ids = [r.id for r in sorted(benchmark.runs, key=lambda r: r.id)]

    if target_run_id is None or base_run_id is None:
        if len(run_ids) < 2:
            raise ValidationError(
                f"Benchmark {benchmark_id} has {len(run_ids)} run(s); comparing needs two. "
                "Re-run it to produce a second one."
            )
        target_run_id = target_run_id if target_run_id is not None else run_ids[-1]
        base_run_id = base_run_id if base_run_id is not None else run_ids[-2]

    if base_run_id == target_run_id:
        raise ValidationError("Choose two different runs to compare.")

    base = await benchmark_service.get_run(session, base_run_id)
    target = await benchmark_service.get_run(session, target_run_id)
    for run in (base, target):
        if run.benchmark_id != benchmark_id:
            raise ValidationError(
                f"Run {run.id} belongs to benchmark {run.benchmark_id}, not {benchmark_id}."
            )

    # Always oldest first, so "delta" reads as "what the re-run changed",
    # whichever order the caller passed them in.
    if base.id > target.id:
        base, target = target, base
    return build_comparison(base, target)


__all__ = ["build_comparison", "compare_runs", "result_key"]
