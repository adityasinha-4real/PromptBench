"""Analytics and leaderboard schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsTotals(BaseModel):
    total_benchmarks: int
    total_runs: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    avg_latency_ms: float | None
    avg_cost: float | None
    total_cost: float | None
    avg_quality: float | None
    #: Executions whose model had no configured price, so cost totals exclude them.
    unpriced_executions: int = 0


class ModelStat(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str
    model: str
    executions: int
    successes: int
    failures: int
    success_rate: float
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    avg_tokens_per_second: float | None
    avg_input_tokens: float | None
    avg_output_tokens: float | None
    total_tokens: int
    avg_cost: float | None
    total_cost: float | None
    cost_per_1k_tokens: float | None
    avg_quality: float | None
    avg_relevance: float | None = None
    avg_correctness: float | None = None
    avg_conciseness: float | None = None
    avg_clarity: float | None = None
    priced: bool = True


class TimelinePoint(BaseModel):
    date: str
    runs: int
    executions: int
    avg_latency_ms: float | None
    total_cost: float | None
    avg_quality: float | None


class ProviderStat(BaseModel):
    provider: str
    executions: int
    successes: int
    failures: int
    avg_latency_ms: float | None
    total_cost: float | None
    avg_quality: float | None


class ErrorStat(BaseModel):
    code: str
    count: int


class AnalyticsResponse(BaseModel):
    totals: AnalyticsTotals
    by_model: list[ModelStat]
    by_provider: list[ProviderStat]
    timeline: list[TimelinePoint]
    errors: list[ErrorStat]
    filters_applied: dict[str, str | None] = Field(default_factory=dict)
    generated_at: datetime


class LeaderboardEntry(ModelStat):
    rank: int


class LeaderboardResponse(BaseModel):
    metric: str
    direction: str = Field(description="'asc' (lower is better) or 'desc' (higher is better).")
    min_executions: int
    entries: list[LeaderboardEntry]
    methodology: str
