"""Builds the evaluator for a run from its configured mode."""

from __future__ import annotations

from app.core.config import settings
from app.core.errors import ProviderError
from app.evaluation.base import EvaluationError, Evaluator
from app.evaluation.heuristic import HeuristicEvaluator
from app.evaluation.llm_judge import LLMJudgeEvaluator
from app.evaluation.manual import ManualEvaluator
from app.models.benchmark import EvaluationMode
from app.providers.registry import ProviderRegistry


def build_evaluator(
    mode: str,
    *,
    registry: ProviderRegistry,
    judge_provider: str | None = None,
    judge_model: str | None = None,
) -> Evaluator | None:
    """Return an evaluator for ``mode``, or ``None`` when evaluation is off.

    Raises:
        EvaluationError: when LLM-judge mode is requested but not configured.
    """
    normalised = (mode or "").strip().lower()

    if normalised in ("", EvaluationMode.DISABLED):
        return None

    if normalised == EvaluationMode.HEURISTIC:
        return HeuristicEvaluator()

    if normalised == EvaluationMode.MANUAL:
        # Scores arrive later via the API; nothing runs during the benchmark.
        return None

    if normalised == EvaluationMode.LLM_JUDGE:
        provider_id = judge_provider or settings.judge_provider
        model_id = judge_model or settings.judge_model
        if not provider_id or not model_id:
            raise EvaluationError(
                "LLM-judge mode needs a judge provider and model. Set them on the "
                "benchmark, or set JUDGE_PROVIDER and JUDGE_MODEL."
            )
        try:
            provider = registry.get(provider_id)
        except ProviderError as exc:
            raise EvaluationError(exc.message) from exc
        if not provider.is_configured():
            raise EvaluationError(
                f"Judge provider '{provider_id}' is unavailable: {provider.unavailable_reason()}"
            )
        return LLMJudgeEvaluator(provider, model_id)

    raise EvaluationError(f"Unknown evaluation mode '{mode}'.")


def build_manual_evaluator(
    scores: dict[str, float], reviewer: str | None = None
) -> ManualEvaluator:
    return ManualEvaluator(scores, reviewer=reviewer)


def available_modes() -> list[dict[str, object]]:
    """Evaluation modes with their availability, for the settings UI."""
    judge_ready = bool(settings.judge_provider and settings.judge_model)
    return [
        {
            "id": EvaluationMode.DISABLED.value,
            "label": "Disabled",
            "available": True,
            "requires_credentials": False,
            "description": "Skip scoring entirely; only measure latency, tokens and cost.",
        },
        {
            "id": EvaluationMode.HEURISTIC.value,
            "label": "Heuristic (offline)",
            "available": True,
            "requires_credentials": False,
            "description": (
                "Deterministic lexical and structural scoring. No network calls. "
                "Correctness is a completeness proxy, not a fact check."
            ),
        },
        {
            "id": EvaluationMode.LLM_JUDGE.value,
            "label": "LLM as a judge",
            "available": True,
            "requires_credentials": True,
            "configured_default": judge_ready,
            "description": (
                "A second model scores each response. Works with a local Ollama "
                "model, so it does not require a paid provider."
            ),
        },
        {
            "id": EvaluationMode.MANUAL.value,
            "label": "Manual",
            "available": True,
            "requires_credentials": False,
            "description": "You score each response yourself after the run.",
        },
    ]


__all__ = ["available_modes", "build_evaluator", "build_manual_evaluator"]
