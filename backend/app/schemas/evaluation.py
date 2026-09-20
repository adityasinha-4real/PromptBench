"""Evaluation endpoint schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.models.benchmark import EvaluationMode
from app.schemas.benchmark import EvaluationOut


class ManualScores(BaseModel):
    relevance: float = Field(ge=0, le=10)
    correctness: float = Field(ge=0, le=10)
    conciseness: float = Field(ge=0, le=10)
    clarity: float = Field(ge=0, le=10)
    overall: float | None = Field(default=None, ge=0, le=10)
    reasoning: str | None = Field(default=None, max_length=4000)


class EvaluateRequest(BaseModel):
    """Score one stored result, or re-score every result in a run."""

    model_result_id: int | None = None
    run_id: int | None = None
    mode: EvaluationMode = EvaluationMode.HEURISTIC
    judge_provider: str | None = Field(default=None, max_length=64)
    judge_model: str | None = Field(default=None, max_length=160)
    scores: ManualScores | None = None
    reviewer: str | None = Field(default=None, max_length=80)
    overwrite: bool = True

    @model_validator(mode="after")
    def _check(self) -> EvaluateRequest:
        if (self.model_result_id is None) == (self.run_id is None):
            raise ValueError("provide exactly one of model_result_id or run_id")
        if self.mode == EvaluationMode.MANUAL:
            if self.scores is None:
                raise ValueError("manual mode requires `scores`")
            if self.model_result_id is None:
                raise ValueError("manual mode applies to a single model_result_id")
        if self.mode == EvaluationMode.DISABLED:
            raise ValueError("cannot evaluate with mode 'disabled'")
        return self


class EvaluateResponse(BaseModel):
    evaluated: int
    failed: int
    evaluations: list[EvaluationOut]
    errors: list[str] = Field(default_factory=list)
