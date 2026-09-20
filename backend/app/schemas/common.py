"""Shared response envelopes."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for schemas read from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable error category.")
    message: str
    hint: str | None = None
    provider: str | None = None
    model: str | None = None
    retryable: bool | None = None
    upstream_status: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str = Field(description="'ok' or a short failure description.")
    providers: dict[str, bool] = Field(
        default_factory=dict, description="Provider id -> configured (not necessarily reachable)."
    )
    details: dict[str, Any] = Field(default_factory=dict)
