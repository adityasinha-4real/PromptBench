"""Initial schema.

Identical to what ``Base.metadata.create_all`` produced before migrations were
introduced, which is what lets ``app.db.migrate`` stamp those databases at this
revision instead of recreating their tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("evaluation_enabled", sa.Boolean(), nullable=False),
        sa.Column("evaluation_mode", sa.String(length=32), nullable=False),
        sa.Column("judge_provider", sa.String(length=64), nullable=True),
        sa.Column("judge_model", sa.String(length=128), nullable=True),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("max_tokens > 0", name="ck_benchmark_max_tokens"),
        sa.CheckConstraint(
            "temperature >= 0 AND temperature <= 2", name="ck_benchmark_temperature"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_benchmarks_created_at", "benchmarks", ["created_at"])
    op.create_index("ix_benchmarks_name", "benchmarks", ["name"])

    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("benchmark_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("params_snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_benchmark_runs_benchmark_id", "benchmark_runs", ["benchmark_id"])
    op.create_index("ix_benchmark_runs_started_at", "benchmark_runs", ["started_at"])
    op.create_index("ix_benchmark_runs_status", "benchmark_runs", ["status"])

    op.create_table(
        "prompt_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("benchmark_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_variants_benchmark_id", "prompt_variants", ["benchmark_id"])

    op.create_table(
        "model_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("benchmark_run_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("variant_name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_per_second", sa.Float(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("token_source", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["benchmark_run_id"], ["benchmark_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variant_id"], ["prompt_variants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_results_created_at", "model_results", ["created_at"])
    op.create_index("ix_model_results_provider_model", "model_results", ["provider", "model"])
    op.create_index("ix_model_results_run_id", "model_results", ["benchmark_run_id"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_result_id", sa.Integer(), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("correctness", sa.Float(), nullable=False),
        sa.Column("conciseness", sa.Float(), nullable=False),
        sa.Column("clarity", sa.Float(), nullable=False),
        sa.Column("overall", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("evaluator_model", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("overall >= 0 AND overall <= 10", name="ck_evaluation_overall_range"),
        sa.ForeignKeyConstraint(["model_result_id"], ["model_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_result_id"),
    )
    op.create_index("ix_evaluations_model_result_id", "evaluations", ["model_result_id"])


def downgrade() -> None:
    # Children before parents, so foreign keys never dangle mid-downgrade.
    op.drop_table("evaluations")
    op.drop_table("model_results")
    op.drop_table("prompt_variants")
    op.drop_table("benchmark_runs")
    op.drop_table("benchmarks")
