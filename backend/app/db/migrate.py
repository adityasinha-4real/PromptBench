"""Schema migrations (Alembic), applied automatically at startup.

The migration scripts live inside the ``app`` package so the Docker image,
which copies only ``app/``, always ships them.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect

from app.core.logging import get_logger

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

#: The schema that releases before migrations existed created with
#: ``metadata.create_all``. Such databases are stamped at this revision.
BASELINE_REVISION = "0001"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def upgrade_to_head(connection: Connection) -> None:
    """Migrate the database behind ``connection`` to the latest revision.

    Runs inside the caller's transaction. On PostgreSQL that makes a failed
    migration roll back completely; SQLite's driver commits DDL as it goes, so
    there a failure can leave earlier steps of the same migration applied.
    """
    config = alembic_config()
    config.attributes["connection"] = connection

    tables = set(inspect(connection).get_table_names())
    if "benchmarks" in tables and "alembic_version" not in tables:
        # Created by an earlier release; its tables are exactly the baseline,
        # so adopt it instead of trying to create them a second time.
        logger.info("Adopting an existing database at revision %s", BASELINE_REVISION)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")


def current_revision(connection: Connection) -> str | None:
    """The revision the database is at, or ``None`` if it is unversioned."""
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(connection).get_current_revision()
