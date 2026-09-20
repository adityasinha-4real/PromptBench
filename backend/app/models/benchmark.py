"""SQLAlchemy ORM models.

Relationships::

    Benchmark 1---* PromptVariant
    Benchmark 1---* BenchmarkRun
    BenchmarkRun 1---* ModelResult   (one row per model x prompt variant)
    ModelResult 1---1 Evaluation
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResultStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationMode(StrEnum):
    DISABLED = "disabled"
    HEURISTIC = "heuristic"
    LLM_JUDGE = "llm_judge"
    MANUAL = "manual"


class Benchmark(Base):
    """A saved prompt + generation configuration, re-runnable over time."""

    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    top_p: Mapped[float | None] = mapped_column(Float)
    evaluation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evaluation_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EvaluationMode.HEURISTIC
    )
    judge_provider: Mapped[str | None] = mapped_column(String(64))
    judge_model: Mapped[str | None] = mapped_column(String(128))
    #: Selected targets: ``[{"provider": "ollama", "model": "llama3.2"}, ...]``
    models: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    variants: Mapped[list[PromptVariant]] = relationship(
        back_populates="benchmark",
        cascade="all, delete-orphan",
        order_by="PromptVariant.position",
        lazy="selectin",
    )
    runs: Mapped[list[BenchmarkRun]] = relationship(
        back_populates="benchmark",
        cascade="all, delete-orphan",
        order_by="BenchmarkRun.id.desc()",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("temperature >= 0 AND temperature <= 2", name="ck_benchmark_temperature"),
        CheckConstraint("max_tokens > 0", name="ck_benchmark_max_tokens"),
        Index("ix_benchmarks_created_at", "created_at"),
        Index("ix_benchmarks_name", "name"),
    )


class PromptVariant(Base):
    """One prompt phrasing under a benchmark.

    Every benchmark has at least one variant; single-prompt benchmarks get an
    implicit variant named ``"Default"``. Results form a model x variant matrix.
    """

    __tablename__ = "prompt_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(
        ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    benchmark: Mapped[Benchmark] = relationship(back_populates="variants")

    __table_args__ = (Index("ix_prompt_variants_benchmark_id", "benchmark_id"),)


class BenchmarkRun(Base):
    """A single execution of a benchmark against the selected models."""

    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(
        ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=RunStatus.PENDING)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    #: Snapshot of the generation params actually used, so history stays truthful
    #: even after the parent benchmark is edited.
    params_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    benchmark: Mapped[Benchmark] = relationship(back_populates="runs")
    results: Mapped[list[ModelResult]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ModelResult.id",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_benchmark_runs_benchmark_id", "benchmark_id"),
        Index("ix_benchmark_runs_started_at", "started_at"),
        Index("ix_benchmark_runs_status", "status"),
    )

    @property
    def duration_ms(self) -> int | None:
        if self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds() * 1000)


class ModelResult(Base):
    """Normalised outcome of one (model x prompt variant) execution."""

    __tablename__ = "model_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_run_id: Mapped[int] = mapped_column(
        ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_variants.id", ondelete="SET NULL")
    )
    variant_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Default")

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ResultStatus.QUEUED)

    response: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_per_second: Mapped[float | None] = mapped_column(Float)
    #: ``None`` means "pricing unavailable" — never treat it as zero.
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    token_source: Mapped[str | None] = mapped_column(String(32))

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    request_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    run: Mapped[BenchmarkRun] = relationship(back_populates="results")
    evaluation: Mapped[Evaluation | None] = relationship(
        back_populates="model_result",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_model_results_run_id", "benchmark_run_id"),
        Index("ix_model_results_provider_model", "provider", "model"),
        Index("ix_model_results_created_at", "created_at"),
    )


class Evaluation(Base):
    """Quality scores (0-10) attached to one model result."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_result_id: Mapped[int] = mapped_column(
        ForeignKey("model_results.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    relevance: Mapped[float] = mapped_column(Float, nullable=False)
    correctness: Mapped[float] = mapped_column(Float, nullable=False)
    conciseness: Mapped[float] = mapped_column(Float, nullable=False)
    clarity: Mapped[float] = mapped_column(Float, nullable=False)
    overall: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default=EvaluationMode.HEURISTIC)
    evaluator_model: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    model_result: Mapped[ModelResult] = relationship(back_populates="evaluation")

    __table_args__ = (
        CheckConstraint("overall >= 0 AND overall <= 10", name="ck_evaluation_overall_range"),
        Index("ix_evaluations_model_result_id", "model_result_id"),
    )
