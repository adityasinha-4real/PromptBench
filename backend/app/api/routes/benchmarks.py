"""Benchmark CRUD, execution, live progress and history."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import benchmark_engine, db_session, parse_date, run_tracker
from app.core.errors import ConflictError
from app.core.logging import get_logger
from app.models.benchmark import RunStatus
from app.schemas.benchmark import (
    BenchmarkCreate,
    BenchmarkDetail,
    BenchmarkListItem,
    BenchmarkRunOut,
    BenchmarkUpdate,
    RunProgress,
    RunRequest,
)
from app.schemas.common import Page
from app.schemas.comparison import RunComparison
from app.services import benchmark_service, comparison_service
from app.services.engine import BenchmarkEngine
from app.services.run_tracker import RunTracker

logger = get_logger(__name__)

router = APIRouter(tags=["benchmarks"])

#: Heartbeat cadence for the SSE stream, keeping proxies from idling it out.
SSE_HEARTBEAT_SECONDS = 15.0


# ----------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------
@router.post(
    "/benchmarks",
    response_model=BenchmarkDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a benchmark",
)
async def create_benchmark(
    payload: BenchmarkCreate,
    session: AsyncSession = Depends(db_session),
    engine: BenchmarkEngine = Depends(benchmark_engine),
) -> BenchmarkDetail:
    """Creates a benchmark. With ``run_immediately`` it also starts the first run."""
    benchmark = await benchmark_service.create_benchmark(session, payload)
    if payload.run_immediately:
        await engine.launch(session, benchmark.id)
        benchmark = await benchmark_service.get_benchmark(session, benchmark.id)
    return benchmark_service.serialize_detail(benchmark)


@router.get("/benchmarks", response_model=Page[BenchmarkListItem], summary="List benchmarks")
async def list_benchmarks(
    search: str | None = Query(default=None, max_length=200, description="Name/prompt substring."),
    tag: str | None = Query(default=None, max_length=40),
    provider: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=160),
    run_status: str | None = Query(default=None, max_length=32, alias="status"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    sort: str = Query(default="created_at", pattern="^(created_at|updated_at|name)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
) -> Page[BenchmarkListItem]:
    """Searchable, filterable, sortable history listing."""
    items, total = await benchmark_service.list_benchmarks(
        session,
        search=search,
        tag=tag,
        provider=provider,
        model=model,
        status=run_status,
        date_from=parse_date(date_from),
        date_to=parse_date(date_to),
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return Page[BenchmarkListItem](items=items, total=total, limit=limit, offset=offset)


@router.get("/benchmarks/{benchmark_id}", response_model=BenchmarkDetail, summary="Get a benchmark")
async def get_benchmark(
    benchmark_id: int, session: AsyncSession = Depends(db_session)
) -> BenchmarkDetail:
    benchmark = await benchmark_service.get_benchmark(session, benchmark_id)
    return benchmark_service.serialize_detail(benchmark)


@router.patch(
    "/benchmarks/{benchmark_id}", response_model=BenchmarkDetail, summary="Update metadata"
)
async def update_benchmark(
    benchmark_id: int,
    payload: BenchmarkUpdate,
    session: AsyncSession = Depends(db_session),
) -> BenchmarkDetail:
    """Updates name, description and tags. Prompt and model config are immutable
    so that stored runs stay a truthful record of what was executed."""
    benchmark = await benchmark_service.update_benchmark(session, benchmark_id, payload)
    return benchmark_service.serialize_detail(benchmark)


@router.delete(
    "/benchmarks/{benchmark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a benchmark and all of its runs",
)
async def delete_benchmark(
    benchmark_id: int,
    session: AsyncSession = Depends(db_session),
    tracker: RunTracker = Depends(run_tracker),
) -> Response:
    for run_id in tracker.active_run_ids():
        state = tracker.get(run_id)
        if state and state.benchmark_id == benchmark_id:
            raise ConflictError(
                f"Benchmark {benchmark_id} has run {run_id} in flight. Cancel it first."
            )
    await benchmark_service.delete_benchmark(session, benchmark_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
@router.post(
    "/benchmarks/{benchmark_id}/run",
    response_model=RunProgress,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a run",
)
async def run_benchmark(
    benchmark_id: int,
    payload: RunRequest | None = None,
    wait: bool = Query(default=False, description="Block until the run finishes."),
    session: AsyncSession = Depends(db_session),
    engine: BenchmarkEngine = Depends(benchmark_engine),
) -> RunProgress:
    """Starts execution and returns immediately with the initial progress snapshot.

    Models run concurrently. Follow progress on
    ``GET /api/runs/{run_id}/stream`` (SSE) or poll ``GET /api/runs/{run_id}``.
    """
    overrides = payload or RunRequest()
    snapshot = await engine.launch(
        session,
        benchmark_id,
        models=[m.model_dump() for m in overrides.models] if overrides.models else None,
        temperature=overrides.temperature,
        max_tokens=overrides.max_tokens,
        evaluation_mode=str(overrides.evaluation_mode) if overrides.evaluation_mode else None,
        variant_ids=overrides.variant_ids,
        wait=wait,
    )
    return RunProgress.model_validate(snapshot)


@router.post(
    "/benchmarks/{benchmark_id}/rerun",
    response_model=RunProgress,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a benchmark with its saved configuration",
)
async def rerun_benchmark(
    benchmark_id: int,
    wait: bool = Query(default=False),
    session: AsyncSession = Depends(db_session),
    engine: BenchmarkEngine = Depends(benchmark_engine),
) -> RunProgress:
    """Executes the benchmark again exactly as saved, producing a new run to compare against."""
    snapshot = await engine.launch(session, benchmark_id, wait=wait)
    return RunProgress.model_validate(snapshot)


@router.get("/benchmarks/{benchmark_id}/runs", summary="List runs for a benchmark")
async def list_runs(
    benchmark_id: int, session: AsyncSession = Depends(db_session)
) -> list[dict[str, Any]]:
    benchmark = await benchmark_service.get_benchmark(session, benchmark_id)
    runs = sorted(benchmark.runs, key=lambda r: r.id, reverse=True)
    return [benchmark_service.summarise_run(r).model_dump(mode="json") for r in runs]


@router.get(
    "/benchmarks/{benchmark_id}/compare",
    response_model=RunComparison,
    summary="Compare two runs of a benchmark",
)
async def compare_runs(
    benchmark_id: int,
    base_run_id: int | None = Query(default=None, description="Older run. Defaults to previous."),
    target_run_id: int | None = Query(default=None, description="Newer run. Defaults to latest."),
    session: AsyncSession = Depends(db_session),
) -> RunComparison:
    """Per-model movement in quality, latency, cost and tokens between two runs.

    Defaults to the two most recent runs. Each metric is judged on its own —
    there is no composite score — and a missing value is reported as unknown
    rather than counted as zero.
    """
    return await comparison_service.compare_runs(
        session, benchmark_id, base_run_id=base_run_id, target_run_id=target_run_id
    )


@router.get("/runs/{run_id}", response_model=BenchmarkRunOut, summary="Get a run with results")
async def get_run(run_id: int, session: AsyncSession = Depends(db_session)) -> BenchmarkRunOut:
    run = await benchmark_service.get_run(session, run_id)
    return benchmark_service.serialize_run(run)


@router.get("/runs/{run_id}/matrix", summary="Model x prompt-variant result matrix")
async def get_matrix(run_id: int, session: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    run = await benchmark_service.get_run(session, run_id)
    return benchmark_service.build_matrix(run)


@router.get("/runs/{run_id}/progress", response_model=RunProgress, summary="Poll run progress")
async def get_progress(
    run_id: int,
    session: AsyncSession = Depends(db_session),
    tracker: RunTracker = Depends(run_tracker),
) -> RunProgress:
    """Live snapshot for an in-flight run; falls back to the database once finished."""
    state = tracker.get(run_id)
    if state is not None:
        return RunProgress.model_validate(state.snapshot())
    return RunProgress.model_validate(await _snapshot_from_db(session, run_id))


@router.post("/runs/{run_id}/cancel", summary="Cancel an in-flight run")
async def cancel_run(
    run_id: int,
    session: AsyncSession = Depends(db_session),
    tracker: RunTracker = Depends(run_tracker),
) -> dict[str, Any]:
    """Aborts in-flight provider requests. Results already stored are kept."""
    if tracker.cancel(run_id):
        return {"run_id": run_id, "cancelled": True, "detail": "Cancellation signalled."}
    run = await benchmark_service.get_run(session, run_id)
    return {
        "run_id": run_id,
        "cancelled": False,
        "detail": f"Run is not in flight (status: {run.status}).",
    }


@router.get("/runs/{run_id}/stream", summary="Server-sent progress events")
async def stream_run(
    run_id: int,
    session: AsyncSession = Depends(db_session),
    tracker: RunTracker = Depends(run_tracker),
) -> StreamingResponse:
    """Streams a `progress` event on every state change, then a final `done` event.

    Clients that cannot use SSE should poll ``/runs/{run_id}/progress`` instead.
    """
    state = tracker.get(run_id)
    if state is None:
        snapshot = await _snapshot_from_db(session, run_id)

        async def finished() -> AsyncIterator[bytes]:
            yield _sse("progress", snapshot)
            yield _sse("done", snapshot)

        return StreamingResponse(finished(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def events() -> AsyncIterator[bytes]:
        queue = tracker.subscribe(state)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                terminal = payload.pop("_terminal", False)
                yield _sse("progress", payload)
                if terminal or payload.get("status") in _TERMINAL_STATUSES:
                    yield _sse("done", payload)
                    return
        except asyncio.CancelledError:  # client disconnected
            raise
        finally:
            tracker.unsubscribe(state, queue)

    return StreamingResponse(events(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.delete(
    "/results/{result_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove one model result from a comparison",
)
async def delete_result(result_id: int, session: AsyncSession = Depends(db_session)) -> Response:
    await benchmark_service.remove_result(session, result_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a run")
async def delete_run(run_id: int, session: AsyncSession = Depends(db_session)) -> Response:
    await benchmark_service.delete_run(session, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
_TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n".encode()


async def _snapshot_from_db(session: AsyncSession, run_id: int) -> dict[str, Any]:
    """Reconstruct a progress snapshot for a run that is no longer tracked in memory."""
    run = await benchmark_service.get_run(session, run_id)  # raises NotFoundError -> 404
    tasks = [
        {
            "key": f"{r.variant_name}::{r.provider}:{r.model}",
            "provider": r.provider,
            "model": r.model,
            "variant_name": r.variant_name,
            "status": r.status,
            "latency_ms": r.latency_ms,
            "attempts": r.attempts,
            "error_code": r.error_code,
            "error_message": r.error_message,
            "result_id": r.id,
        }
        for r in run.results
    ]
    return {
        "run_id": run.id,
        "benchmark_id": run.benchmark_id,
        "status": run.status,
        "total": len(tasks),
        "completed": sum(1 for t in tasks if t["status"] in ("success", "failed", "cancelled")),
        "succeeded": sum(1 for t in tasks if t["status"] == "success"),
        "failed": sum(1 for t in tasks if t["status"] == "failed"),
        "tasks": tasks,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }
