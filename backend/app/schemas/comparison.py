"""Schemas for comparing two runs of the same benchmark."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: How a metric moved. "unknown" is used whenever either side is missing —
#: an absent cost or score is never treated as zero.
Direction = Literal["better", "worse", "unchanged", "unknown"]

#: What happened to one (provider, model, variant) between the two runs.
EntryChange = Literal["improved", "regressed", "unchanged", "added", "removed", "mixed"]


class MetricDelta(BaseModel):
    """One metric on both sides, with the change between them."""

    base: float | None = None
    target: float | None = None
    #: ``target - base``; ``None`` when either side is missing.
    delta: float | None = None
    #: ``None`` when the base is missing or zero, rather than infinity.
    percent_change: float | None = None
    direction: Direction = "unknown"


class ComparisonEntry(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    key: str
    provider: str
    model: str
    variant_name: str
    base_status: str | None = None
    target_status: str | None = None
    quality: MetricDelta = Field(default_factory=MetricDelta)
    latency_ms: MetricDelta = Field(default_factory=MetricDelta)
    estimated_cost: MetricDelta = Field(default_factory=MetricDelta)
    total_tokens: MetricDelta = Field(default_factory=MetricDelta)
    change: EntryChange = "unchanged"
    #: Plain-language reason, e.g. a target-only target or a new failure.
    note: str | None = None


class ComparisonRunRef(BaseModel):
    id: int
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    result_count: int = 0
    evaluation_modes: list[str] = Field(default_factory=list)


class ComparisonSummary(BaseModel):
    improved: int = 0
    regressed: int = 0
    unchanged: int = 0
    mixed: int = 0
    added: int = 0
    removed: int = 0
    #: Averaged over targets present and successful in both runs.
    avg_quality_delta: float | None = None
    avg_latency_delta_ms: float | None = None
    total_cost_delta: float | None = None
    new_failures: int = 0
    fixed_failures: int = 0


class RunComparison(BaseModel):
    benchmark_id: int
    base: ComparisonRunRef
    target: ComparisonRunRef
    entries: list[ComparisonEntry] = Field(default_factory=list)
    summary: ComparisonSummary = Field(default_factory=ComparisonSummary)
    #: False when the two runs were scored in different evaluation modes, whose
    #: scores are not comparable.
    quality_comparable: bool = True
    notes: list[str] = Field(default_factory=list)
