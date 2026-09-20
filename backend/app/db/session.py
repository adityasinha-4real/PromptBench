"""Async engine and session management.

SQLite is the default. Pointing ``DATABASE_URL`` at
``postgresql+asyncpg://user:pass@host/db`` is the only change needed to run on
Postgres — no model or query changes are required.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base


def _engine_kwargs(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        # check_same_thread is a SQLite-only knob; pooling is handled by aiosqlite.
        return {"connect_args": {"check_same_thread": False, "timeout": 30}}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}


def create_engine(url: str | None = None) -> AsyncEngine:
    """Build an async engine for ``url`` (defaults to the configured database)."""
    target = url or settings.database_url
    engine = create_async_engine(target, echo=False, future=True, **_engine_kwargs(target))

    if target.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            # WAL keeps concurrent benchmark writes from blocking readers.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


engine: AsyncEngine = create_engine()
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
)


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Create tables if they do not exist.

    A single-file local tool does not warrant a migration runner; the schema is
    created from the declarative metadata at startup. ARCHITECTURE.md records
    this decision and the upgrade path to Alembic.
    """
    # Import for the side effect of registering models on Base.metadata.
    from app import models  # noqa: F401

    async with (target_engine or engine).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db(target_engine: AsyncEngine | None = None) -> None:
    await (target_engine or engine).dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Standalone session for background tasks (outside the request lifecycle)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
