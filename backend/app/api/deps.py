"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.providers.registry import ProviderRegistry, get_registry
from app.services.engine import BenchmarkEngine
from app.services.run_tracker import RunTracker, get_tracker


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def provider_registry() -> ProviderRegistry:
    return get_registry()


def run_tracker() -> RunTracker:
    return get_tracker()


def benchmark_engine(
    registry: ProviderRegistry = Depends(provider_registry),
    tracker: RunTracker = Depends(run_tracker),
) -> BenchmarkEngine:
    return BenchmarkEngine(registry=registry, tracker=tracker)


def parse_date(value: str | None) -> datetime | None:
    """Parse an ISO-8601 date/datetime filter, defaulting naive values to UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


DateFrom = Query(default=None, description="ISO-8601 lower bound (inclusive).")
DateTo = Query(default=None, description="ISO-8601 upper bound (inclusive).")
