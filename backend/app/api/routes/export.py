"""Benchmark export endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.errors import NotFoundError, ValidationError
from app.services import benchmark_service, export_service

router = APIRouter(prefix="/export", tags=["export"])


@router.get(
    "/{benchmark_id}",
    summary="Export a benchmark run as JSON, CSV, Markdown or HTML",
    responses={
        200: {
            "content": {
                "application/json": {},
                "text/csv": {},
                "text/markdown": {},
                "text/html": {},
            }
        }
    },
)
async def export_benchmark(
    benchmark_id: int,
    format: str = Query(default="json", description="json | csv | markdown | html"),
    run_id: int | None = Query(default=None, description="Defaults to the most recent run."),
    download: bool = Query(default=True, description="Send a Content-Disposition attachment."),
    session: AsyncSession = Depends(db_session),
) -> Response:
    """Every export carries the prompt, model, provider, response, latency, tokens,
    cost, evaluation scores and timestamps."""
    benchmark = await benchmark_service.get_benchmark(session, benchmark_id)

    runs = sorted(benchmark.runs, key=lambda r: r.id, reverse=True)
    if run_id is not None:
        run = next((r for r in runs if r.id == run_id), None)
        if run is None:
            raise NotFoundError(f"Run {run_id} does not belong to benchmark {benchmark_id}.")
    elif runs:
        run = runs[0]
    else:
        raise NotFoundError(f"Benchmark {benchmark_id} has no runs to export.")

    try:
        content, media_type, filename = export_service.render_export(benchmark, run, format)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    headers = {}
    if download:
        # `filename` is sanitised in export_service.safe_filename.
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/{benchmark_id}/formats", summary="Supported export formats")
async def list_formats(benchmark_id: int) -> dict[str, list[str]]:
    return {"formats": list(export_service.SUPPORTED_FORMATS)}
