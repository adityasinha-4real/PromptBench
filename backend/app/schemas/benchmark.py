"""Benchmark request/response schemas.

These are the public contract. ORM objects are never returned directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.models.benchmark import EvaluationMode
from app.schemas.common import ORMModel


class ModelSelection(BaseModel):
    """One benchmark target."""

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=160)

    @field_validator("provider", "model")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


class PromptVariantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1)

    @field_validator("prompt")
    @classmethod
    def _limit_prompt(cls, value: str) -> str:
        if len(value) > settings.max_prompt_chars:
            raise ValueError(f"prompt exceeds {settings.max_prompt_chars} characters")
        return value

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()


class PromptVariantOut(ORMModel):
    id: int
    name: str
    prompt: str
    position: int


class BenchmarkBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    prompt: str = Field(min_length=1)
    system_prompt: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    evaluation_enabled: bool = True
    # Read per request, so EVALUATION_DEFAULT_MODE is honoured.
    evaluation_mode: EvaluationMode = Field(
        default_factory=lambda: EvaluationMode(settings.evaluation_default_mode)
    )
    judge_provider: str | None = Field(default=None, max_length=64)
    judge_model: str | None = Field(default=None, max_length=160)
    models: list[ModelSelection] = Field(min_length=1)
    variants: list[PromptVariantIn] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("prompt")
    @classmethod
    def _limit_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        if len(value) > settings.max_prompt_chars:
            raise ValueError(f"prompt exceeds the {settings.max_prompt_chars} character limit")
        return value

    @field_validator("system_prompt")
    @classmethod
    def _limit_system_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > settings.max_system_prompt_chars:
            raise ValueError(
                f"system prompt exceeds the {settings.max_system_prompt_chars} character limit"
            )
        return value or None

    @field_validator("max_tokens")
    @classmethod
    def _limit_max_tokens(cls, value: int) -> int:
        if value > settings.max_output_tokens_limit:
            raise ValueError(f"max_tokens exceeds the {settings.max_output_tokens_limit} limit")
        return value

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for tag in value:
            cleaned = tag.strip().lower()[:40]
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        if len(seen) > 20:
            raise ValueError("at most 20 tags are allowed")
        return seen

    @model_validator(mode="after")
    def _check_collections(self) -> BenchmarkBase:
        if len(self.models) > settings.max_models_per_benchmark:
            raise ValueError(f"at most {settings.max_models_per_benchmark} models per benchmark")
        keys = [m.key for m in self.models]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate provider/model selections are not allowed")

        if len(self.variants) > settings.max_variants_per_benchmark:
            raise ValueError(
                f"at most {settings.max_variants_per_benchmark} prompt variants per benchmark"
            )
        names = [v.name.lower() for v in self.variants]
        if len(names) != len(set(names)):
            raise ValueError("prompt variant names must be unique")

        if self.evaluation_enabled and self.evaluation_mode == EvaluationMode.LLM_JUDGE:
            configured = (self.judge_provider and self.judge_model) or (
                settings.judge_provider and settings.judge_model
            )
            if not configured:
                raise ValueError(
                    "llm_judge mode requires judge_provider and judge_model "
                    "(or the JUDGE_PROVIDER / JUDGE_MODEL environment variables)"
                )
        return self


class BenchmarkCreate(BenchmarkBase):
    """Create a benchmark. Set ``run_immediately`` to start a run in the same call."""

    run_immediately: bool = False


class BenchmarkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [t.strip().lower()[:40] for t in value if t.strip()][:20]


class EvaluationOut(ORMModel):
    id: int
    relevance: float
    correctness: float
    conciseness: float
    clarity: float
    overall: float
    reasoning: str | None
    mode: str
    evaluator_model: str | None
    created_at: datetime


class ModelResultOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    variant_id: int | None
    variant_name: str
    provider: str
    model: str
    status: str
    response: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    tokens_per_second: float | None
    estimated_cost: float | None
    cost_per_1k_tokens: float | None = None
    finish_reason: str | None
    token_source: str | None
    error_code: str | None
    error_message: str | None
    attempts: int
    request_params: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="extra_metadata")
    evaluation: EvaluationOut | None = None
    created_at: datetime


class BenchmarkRunOut(ORMModel):
    id: int
    benchmark_id: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None = None
    error_message: str | None
    params_snapshot: dict[str, Any]
    results: list[ModelResultOut] = Field(default_factory=list)


class RunSummary(ORMModel):
    """Compact run row for list views."""

    id: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    result_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_latency_ms: float | None = None
    total_cost: float | None = None
    avg_quality: float | None = None


class BenchmarkOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    name: str
    description: str | None
    prompt: str
    system_prompt: str | None
    temperature: float
    max_tokens: int
    top_p: float | None
    evaluation_enabled: bool
    evaluation_mode: str
    judge_provider: str | None
    judge_model: str | None
    models: list[ModelSelection]
    tags: list[str]
    variants: list[PromptVariantOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BenchmarkDetail(BenchmarkOut):
    runs: list[RunSummary] = Field(default_factory=list)
    latest_run: BenchmarkRunOut | None = None


class BenchmarkListItem(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    name: str
    description: str | None
    prompt_excerpt: str
    tags: list[str]
    model_count: int
    variant_count: int
    run_count: int
    evaluation_mode: str
    created_at: datetime
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    avg_quality: float | None = None
    total_cost: float | None = None


class RunRequest(BaseModel):
    """Overrides applied to a single run without editing the benchmark."""

    models: list[ModelSelection] | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    evaluation_mode: EvaluationMode | None = None
    variant_ids: list[int] | None = None

    @field_validator("max_tokens")
    @classmethod
    def _limit(cls, value: int | None) -> int | None:
        if value is not None and value > settings.max_output_tokens_limit:
            raise ValueError(f"max_tokens exceeds the {settings.max_output_tokens_limit} limit")
        return value


class RunTaskState(BaseModel):
    """Live per-target execution state, streamed while a run is in flight."""

    key: str
    provider: str
    model: str
    variant_name: str
    status: str
    latency_ms: int | None = None
    attempts: int = 0
    error_code: str | None = None
    error_message: str | None = None
    result_id: int | None = None


class RunProgress(BaseModel):
    run_id: int
    benchmark_id: int
    status: str
    total: int
    completed: int
    succeeded: int
    failed: int
    tasks: list[RunTaskState]
    started_at: datetime | None = None
    completed_at: datetime | None = None
