"""Alembic migrations: fresh databases, adopting pre-migration ones, model drift."""

from __future__ import annotations

from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import models
from app.db.base import Base
from app.db.migrate import BASELINE_REVISION, alembic_config, current_revision
from app.db.session import create_engine, init_db

HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


def engine_at(tmp_path: Any) -> AsyncEngine:
    return create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'migrate.db').as_posix()}")


async def revision_of(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        return await conn.run_sync(current_revision)


def drift(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


async def test_a_fresh_database_is_migrated_to_head(tmp_path: Any) -> None:
    engine = engine_at(tmp_path)
    try:
        await init_db(engine)
        assert await revision_of(engine) == HEAD
    finally:
        await engine.dispose()


async def test_migrations_match_the_models(tmp_path: Any) -> None:
    """Fails when a model changes without a migration to go with it."""
    engine = engine_at(tmp_path)
    try:
        await init_db(engine)
        async with engine.connect() as conn:
            differences = await conn.run_sync(drift)
        assert differences == [], (
            "The ORM models and the migrations disagree. Generate a migration with "
            "`alembic revision --autogenerate -m '...'` in backend/. Differences: "
            f"{differences}"
        )
    finally:
        await engine.dispose()


async def test_a_pre_migration_database_is_adopted_with_its_data(tmp_path: Any) -> None:
    engine = engine_at(tmp_path)
    try:
        # What a release before migrations left behind: tables, no version row.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as session:
            session.add(models.Benchmark(name="Kept", prompt="p", models=[], tags=[]))
            await session.commit()
        assert await revision_of(engine) is None

        await init_db(engine)

        assert await revision_of(engine) == HEAD
        async with AsyncSession(engine) as session:
            names = (await session.scalars(select(models.Benchmark.name))).all()
        assert names == ["Kept"]
    finally:
        await engine.dispose()


async def test_startup_migration_is_idempotent(tmp_path: Any) -> None:
    engine = engine_at(tmp_path)
    try:
        await init_db(engine)
        await init_db(engine)
        assert await revision_of(engine) == HEAD
    finally:
        await engine.dispose()


async def test_the_baseline_downgrades_cleanly(tmp_path: Any) -> None:
    engine = engine_at(tmp_path)

    def downgrade_to_base(connection: Connection) -> list[str]:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        return inspect(connection).get_table_names()

    try:
        await init_db(engine)
        async with engine.begin() as conn:
            remaining = await conn.run_sync(downgrade_to_base)
        assert remaining == ["alembic_version"]
    finally:
        await engine.dispose()


def test_the_baseline_is_the_first_revision() -> None:
    # Pre-migration databases are stamped at BASELINE_REVISION; if it were not
    # the root, stamping would skip migrations those databases never ran.
    assert ScriptDirectory.from_config(alembic_config()).get_base() == BASELINE_REVISION
