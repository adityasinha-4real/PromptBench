"""Alembic environment.

At startup the app passes in an open connection (see ``app.db.migrate``).
From the command line, run inside ``backend/``::

    alembic upgrade head
    alembic revision --autogenerate -m "describe the change"

and it connects to ``DATABASE_URL`` itself.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from alembic import context
from sqlalchemy import Connection

from app import models  # noqa: F401  (registers every table on the metadata)
from app.core.config import settings
from app.db.base import Base, UTCDateTime
from app.db.session import create_engine

target_metadata = Base.metadata


def _render_item(type_: str, obj: Any, _autogen_context: Any) -> str | Literal[False]:
    # Keep generated migrations free of app imports: a migration must keep
    # working even after the model code it was generated from has changed.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        # SQLite cannot ALTER most column properties; batch mode rebuilds the
        # table instead, and is a no-op cost on Postgres.
        render_as_batch=True,
        compare_type=True,
        render_item=_render_item,
        **kwargs,
    )


def _run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_standalone() -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    _configure(url=settings.database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (shared := context.config.attributes.get("connection")) is not None:
    _run(shared)
else:
    asyncio.run(_run_standalone())
