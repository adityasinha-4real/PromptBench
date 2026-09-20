"""Evaluation engine: parsing robustness, heuristic scoring, judge, manual mode."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.errors import ErrorCode, ProviderError
from app.evaluation.base import (
    EvaluationError,
    EvaluationScores,
    extract_json_object,
    parse_scores,
)
from app.evaluation.factory import available_modes, build_evaluator
from app.evaluation.heuristic import HeuristicEvaluator
from app.evaluation.llm_judge import LLMJudgeEvaluator, build_judge_prompt
from app.evaluation.manual import ManualEvaluator
from app.providers.registry import ProviderRegistry
from tests.conftest import FakeProvider, JudgeProvider

GOOD = '{"relevance": 8, "correctness": 9, "conciseness": 7, "clarity": 9, "overall": 8.2, "reasoning": "Solid."}'


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------
def test_parses_plain_json() -> None:
    scores = parse_scores(GOOD)
    assert (scores.relevance, scores.correctness, scores.overall) == (8, 9, 8.2)
    assert scores.reasoning == "Solid."


def test_parses_json_inside_a_code_fence() -> None:
    assert parse_scores(f"```json\n{GOOD}\n```").overall == 8.2


def test_parses_json_surrounded_by_prose() -> None:
    text = f"Here is my assessment.\n\n{GOOD}\n\nHope that helps!"
    assert parse_scores(text).clarity == 9


def test_ignores_braces_inside_strings() -> None:
    text = '{"relevance": 5, "correctness": 5, "conciseness": 5, "clarity": 5, "reasoning": "uses {curly} braces"}'
    assert parse_scores(text).reasoning == "uses {curly} braces"


def test_coerces_string_and_fraction_scores() -> None:
    text = '{"relevance": "8", "correctness": "7/10", "conciseness": 6.5, "clarity": " 9 "}'
    scores = parse_scores(text)
    assert scores.relevance == 8
    assert scores.correctness == 7
    assert scores.clarity == 9


def test_clamps_out_of_range_scores() -> None:
    text = '{"relevance": 42, "correctness": -5, "conciseness": 5, "clarity": 5}'
    scores = parse_scores(text)
    assert scores.relevance == 10
    assert scores.correctness == 0


def test_computes_overall_when_the_judge_omits_it() -> None:
    text = '{"relevance": 10, "correctness": 10, "conciseness": 10, "clarity": 10}'
    assert parse_scores(text).overall == 10.0


def test_accepts_scores_nested_under_a_wrapper_key() -> None:
    text = '{"scores": {"relevance": 6, "correctness": 6, "conciseness": 6, "clarity": 6}, "reasoning": "meh"}'
    scores = parse_scores(text)
    assert scores.relevance == 6
    assert scores.reasoning == "meh"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "I refuse to score this.",
        "{not json at all",
        '{"relevance": 8}',  # missing criteria
        '{"relevance": "high", "correctness": 5, "conciseness": 5, "clarity": 5}',
        '["relevance", 8]',
    ],
)
def test_malformed_output_raises_a_contained_error(bad: str) -> None:
    """Bad evaluator output must never propagate as an unhandled exception."""
    with pytest.raises(EvaluationError):
        parse_scores(bad)


def test_extract_json_object_rejects_non_objects() -> None:
    with pytest.raises(EvaluationError):
        extract_json_object("[1, 2, 3]")


def test_reasoning_is_truncated() -> None:
    scores = EvaluationScores(
        relevance=5, correctness=5, conciseness=5, clarity=5, reasoning="x" * 9000
    )
    assert scores.reasoning is not None
    assert len(scores.reasoning) == 4000


def test_boolean_is_not_a_valid_score() -> None:
    with pytest.raises(EvaluationError):
        parse_scores('{"relevance": true, "correctness": 5, "conciseness": 5, "clarity": 5}')


# ----------------------------------------------------------------------
# Heuristic evaluator
# ----------------------------------------------------------------------
PROMPT = "Explain why TCP uses a three-way handshake."
GOOD_ANSWER = (
    "TCP uses a three-way handshake because both endpoints must agree on initial "
    "sequence numbers before any data is exchanged. The client sends a SYN, the server "
    "replies with SYN-ACK, and the client answers with ACK. This confirms that both "
    "directions of the connection work and prevents stale duplicate connections."
)


async def test_heuristic_is_deterministic() -> None:
    evaluator = HeuristicEvaluator()
    first = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    second = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert first.model_dump() == second.model_dump()


async def test_heuristic_scores_a_relevant_answer_above_an_irrelevant_one() -> None:
    evaluator = HeuristicEvaluator()
    good = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    bad = await evaluator.evaluate(
        prompt=PROMPT, response="I enjoy baking sourdough bread on weekends in my kitchen."
    )
    assert good.relevance > bad.relevance
    assert good.overall > bad.overall


async def test_heuristic_penalises_refusals() -> None:
    evaluator = HeuristicEvaluator()
    refusal = await evaluator.evaluate(
        prompt=PROMPT, response="I'm sorry, I can't help with that request."
    )
    good = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert refusal.correctness < good.correctness


async def test_heuristic_penalises_padding() -> None:
    evaluator = HeuristicEvaluator()
    padded = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER + (" " + GOOD_ANSWER) * 6)
    tight = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert padded.conciseness < tight.conciseness


async def test_heuristic_handles_empty_response() -> None:
    scores = await HeuristicEvaluator().evaluate(prompt=PROMPT, response="")
    assert scores.overall == 0
    assert scores.reasoning == "Empty response."


async def test_heuristic_never_leaves_the_valid_range() -> None:
    evaluator = HeuristicEvaluator()
    for response in ["a", "!" * 5000, GOOD_ANSWER, "word " * 3000, "\n\n\n", "12345"]:
        scores = await evaluator.evaluate(prompt=PROMPT, response=response)
        for field in ("relevance", "correctness", "conciseness", "clarity", "overall"):
            value = getattr(scores, field)
            assert 0 <= value <= 10, f"{field}={value} for {response[:20]!r}"


async def test_heuristic_needs_no_network_or_credentials() -> None:
    """The offline evaluator is what makes zero-credential operation viable."""
    evaluator = HeuristicEvaluator()
    scores = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert scores.overall > 0
    assert evaluator.evaluator_model == "builtin:heuristic-v1"


# ----------------------------------------------------------------------
# LLM judge
# ----------------------------------------------------------------------
async def test_llm_judge_parses_a_well_formed_verdict() -> None:
    judge = LLMJudgeEvaluator(JudgeProvider(), "judge-model")
    scores = await judge.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert scores.overall == 8.3
    assert judge.evaluator_model == "judge:judge-model"


async def test_llm_judge_uses_temperature_zero() -> None:
    provider = JudgeProvider()
    judge = LLMJudgeEvaluator(provider, "judge-model")
    await judge.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert provider.calls[0].temperature == 0.0


async def test_llm_judge_surfaces_malformed_output_as_evaluation_error() -> None:
    judge = LLMJudgeEvaluator(JudgeProvider(payload="I think it was pretty good."), "m")
    with pytest.raises(EvaluationError):
        await judge.evaluate(prompt=PROMPT, response=GOOD_ANSWER)


async def test_llm_judge_wraps_provider_failures() -> None:
    provider = JudgeProvider()
    provider.fail_with = ProviderError("rate limited.", code=ErrorCode.RATE_LIMIT, provider="judge")
    judge = LLMJudgeEvaluator(provider, "m")
    with pytest.raises(EvaluationError) as exc:
        await judge.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert "rate limited" in exc.value.message


async def test_llm_judge_short_circuits_on_empty_response() -> None:
    provider = JudgeProvider()
    judge = LLMJudgeEvaluator(provider, "m")
    scores = await judge.evaluate(prompt=PROMPT, response="   ")
    assert scores.overall == 0
    assert provider.calls == [], "no judge call for an empty response"


def test_judge_prompt_truncates_enormous_responses() -> None:
    prompt = build_judge_prompt("p", "x" * 50_000)
    assert "truncated" in prompt
    assert len(prompt) < 20_000


# ----------------------------------------------------------------------
# Manual evaluator
# ----------------------------------------------------------------------
async def test_manual_evaluator_validates_supplied_scores() -> None:
    evaluator = ManualEvaluator(
        {"relevance": 9, "correctness": 8, "conciseness": 7, "clarity": 9}, reviewer="ada"
    )
    scores = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert scores.overall > 0
    assert evaluator.evaluator_model == "human:ada"


async def test_manual_evaluator_rejects_missing_scores() -> None:
    with pytest.raises(EvaluationError):
        await ManualEvaluator().evaluate(prompt=PROMPT, response=GOOD_ANSWER)


async def test_manual_evaluator_clamps_rather_than_crashing() -> None:
    """EvaluationScores is forgiving by design, so a sloppy judge cannot break a run."""
    evaluator = ManualEvaluator({"relevance": 99, "correctness": 8, "conciseness": 7, "clarity": 9})
    scores = await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)
    assert scores.relevance == 10


def test_api_schema_rejects_out_of_range_manual_scores() -> None:
    """Human-submitted scores are hard-validated at the HTTP boundary instead."""
    from pydantic import ValidationError as PydanticValidationError

    from app.schemas.evaluation import ManualScores

    with pytest.raises(PydanticValidationError):
        ManualScores(relevance=99, correctness=8, conciseness=7, clarity=9)


async def test_manual_evaluator_rejects_non_numeric_input() -> None:
    evaluator = ManualEvaluator(
        {"relevance": "excellent", "correctness": 8, "conciseness": 7, "clarity": 9}
    )
    with pytest.raises(EvaluationError):
        await evaluator.evaluate(prompt=PROMPT, response=GOOD_ANSWER)


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------
def test_factory_returns_none_for_disabled_and_manual() -> None:
    registry = ProviderRegistry([FakeProvider()])
    assert build_evaluator("disabled", registry=registry) is None
    assert build_evaluator("manual", registry=registry) is None
    assert build_evaluator("", registry=registry) is None


def test_factory_builds_heuristic_without_any_provider() -> None:
    registry = ProviderRegistry([])
    assert isinstance(build_evaluator("heuristic", registry=registry), HeuristicEvaluator)


def test_factory_requires_judge_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "judge_provider", None)
    monkeypatch.setattr(settings, "judge_model", None)
    with pytest.raises(EvaluationError) as exc:
        build_evaluator("llm_judge", registry=ProviderRegistry([FakeProvider()]))
    assert "JUDGE_PROVIDER" in exc.value.message


def test_factory_rejects_an_unconfigured_judge_provider() -> None:
    registry = ProviderRegistry([FakeProvider("openai", configured=False)])
    with pytest.raises(EvaluationError) as exc:
        build_evaluator(
            "llm_judge", registry=registry, judge_provider="openai", judge_model="gpt-4o"
        )
    assert "unavailable" in exc.value.message


def test_factory_builds_a_judge_when_configured() -> None:
    registry = ProviderRegistry([FakeProvider("openai")])
    evaluator = build_evaluator(
        "llm_judge", registry=registry, judge_provider="openai", judge_model="gpt-4o"
    )
    assert isinstance(evaluator, LLMJudgeEvaluator)


def test_factory_rejects_unknown_mode() -> None:
    with pytest.raises(EvaluationError):
        build_evaluator("telepathy", registry=ProviderRegistry([]))


def test_available_modes_flags_credential_requirements() -> None:
    modes = {m["id"]: m for m in available_modes()}
    assert modes["heuristic"]["requires_credentials"] is False
    assert modes["llm_judge"]["requires_credentials"] is True
    assert set(modes) == {"disabled", "heuristic", "llm_judge", "manual"}
