"""Declarative base and shared column types."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime that round-trips correctly on SQLite.

    SQLite drops tzinfo, so we normalise to UTC on write and re-attach UTC on
    read. On Postgres this behaves like ``TIMESTAMP WITH TIME ZONE``.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    """Timezone-aware 'now', used as the default for every timestamp column."""
    return datetime.now(UTC)
