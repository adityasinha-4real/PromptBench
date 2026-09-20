"""Schemas for the models / providers endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PricingOut(BaseModel):
    input_per_1m: float
    output_per_1m: float
    note: str | None = None


class ModelOut(BaseModel):
    provider: str
    id: str
    label: str
    context_window: int | None = None
    description: str | None = None
    local: bool = False
    #: ``None`` renders as "Pricing unavailable" — never as free.
    pricing: PricingOut | None = None
    available: bool = Field(description="True when the owning provider is usable right now.")


class ProviderOut(BaseModel):
    id: str
    label: str
    is_local: bool
    configured: bool = Field(description="Credentials/base URL present.")
    available: bool = Field(description="Configured AND reachable at last check.")
    status_detail: str
    api_key_env: str | None = None
    error_code: str | None = None
    latency_ms: int | None = None
    models: list[ModelOut] = Field(default_factory=list)


class ModelsResponse(BaseModel):
    providers: list[ProviderOut]
    models: list[ModelOut]
    pricing: dict[str, Any]


class TestConnectionRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=160)


class TestConnectionResponse(BaseModel):
    provider: str
    model: str | None = None
    available: bool
    detail: str
    error_code: str | None = None
    latency_ms: int | None = None
    model_count: int | None = None
    #: Present when a specific model was probed with a 1-token generation.
    generation_ok: bool | None = None
