"""Analytics, leaderboard and dashboard endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, parse_date
from app.schemas.analytics import AnalyticsResponse, LeaderboardResponse
from app.services import analytics_service
from app.services.analytics_service import LEADERBOARD_METRICS

router = APIRouter(tags=["analytics"])


@router.get("/analytics", response_model=AnalyticsResponse, summary="Aggregate metrics")
async def get_analytics(
    date_from: str | None = Query(default=None, description="ISO-8601 lower bound."),
    date_to: str | None = Query(default=None, description="ISO-8601 upper bound."),
    provider: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=160),
    benchmark_id: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(db_session),
) -> AnalyticsResponse:
    """Totals, per-model and per-provider breakdowns, a daily timeline and error counts."""
    return await analytics_service.build_analytics(
        session,
        date_from=parse_date(date_from),
        date_to=parse_date(date_to),
        provider=provider,
        model=model,
        benchmark_id=benchmark_id,
    )


@router.get("/leaderboard", response_model=LeaderboardResponse, summary="Rank models by one metric")
async def get_leaderboard(
    metric: str = Query(default="quality", description=f"One of: {', '.join(LEADERBOARD_METRICS)}"),
    min_executions: int = Query(default=1, ge=1, le=1000),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    provider: str | None = Query(default=None, max_length=64),
    benchmark_id: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(db_session),
) -> LeaderboardResponse:
    """Ranks models by a single explicit metric.

    There is no composite "best model" score; the response carries the
    methodology so the ranking can be read honestly.
    """
    return await analytics_service.build_leaderboard(
        session,
        metric=metric,
        min_executions=min_executions,
        date_from=parse_date(date_from),
        date_to=parse_date(date_to),
        provider=provider,
        benchmark_id=benchmark_id,
    )


@router.get("/leaderboard/metrics", summary="Available leaderboard metrics")
async def leaderboard_metrics() -> dict[str, Any]:
    return {
        "metrics": [
            {"id": key, "direction": direction, "description": description}
            for key, (direction, description) in LEADERBOARD_METRICS.items()
        ],
        "methodology": analytics_service.METHODOLOGY,
    }


@router.get("/dashboard", summary="Dashboard summary figures")
async def dashboard(session: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    return await analytics_service.dashboard_summary(session)
