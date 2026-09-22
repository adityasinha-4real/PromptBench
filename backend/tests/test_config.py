"""Settings validation: bad configuration must fail at startup, not later."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**values: object) -> Settings:
    # Ignore any developer .env so the test sees only what it passes.
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_default_evaluation_mode_is_heuristic() -> None:
    assert make().evaluation_default_mode == "heuristic"


@pytest.mark.parametrize("raw", ["Manual", "  manual ", "MANUAL"])
def test_default_evaluation_mode_is_normalised(raw: str) -> None:
    assert make(evaluation_default_mode=raw).evaluation_default_mode == "manual"


def test_unknown_default_evaluation_mode_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        make(evaluation_default_mode="heursitic")
    assert "evaluation_default_mode" in str(exc.value)


def test_blank_judge_values_mean_unset() -> None:
    settings = make(judge_provider="", judge_model="   ")
    assert settings.judge_provider is None
    assert settings.judge_model is None


def test_llm_judge_default_requires_a_configured_judge() -> None:
    with pytest.raises(ValidationError) as exc:
        make(evaluation_default_mode="llm_judge", judge_provider="ollama")
    assert "JUDGE_MODEL" in str(exc.value)


def test_llm_judge_default_is_accepted_with_a_judge() -> None:
    settings = make(
        evaluation_default_mode="llm_judge", judge_provider="ollama", judge_model="llama3.2"
    )
    assert settings.evaluation_default_mode == "llm_judge"
