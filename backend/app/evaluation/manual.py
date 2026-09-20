"""Manual evaluator — scores supplied by a human through the UI."""

from __future__ import annotations

from typing import Any

from app.evaluation.base import EvaluationError, EvaluationScores, Evaluator


class ManualEvaluator(Evaluator):
    """Validates and returns human-entered scores.

    In manual mode the benchmark engine records no evaluation at run time; the
    user submits scores afterwards via ``POST /api/evaluate``, which routes here
    so manual scores pass through exactly the same validation as automatic ones.
    """

    mode = "manual"
    evaluator_model = None

    def __init__(
        self, scores: dict[str, Any] | None = None, *, reviewer: str | None = None
    ) -> None:
        self._scores = scores or {}
        self.reviewer = reviewer
        if reviewer:
            self.evaluator_model = f"human:{reviewer}"

    async def evaluate(
        self,
        *,
        prompt: str,
        response: str,
        system_prompt: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> EvaluationScores:
        payload = {**self._scores, **(context or {})}
        if not payload:
            raise EvaluationError("Manual evaluation requires scores to be supplied.")
        try:
            return EvaluationScores.model_validate(payload)
        except Exception as exc:
            raise EvaluationError(f"Manual scores failed validation: {exc}") from exc
