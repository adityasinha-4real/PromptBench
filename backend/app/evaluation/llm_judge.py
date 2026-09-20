"""LLM-as-a-judge evaluator.

A second model scores the response against the four criteria and returns JSON,
which is validated with Pydantic before it reaches the database. The judge is
addressed through the same :class:`~app.providers.base.LLMProvider` interface as
any benchmarked model, so any configured provider can judge — including a local
Ollama model, which keeps LLM-judge mode free.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import ProviderError
from app.evaluation.base import EvaluationError, EvaluationScores, Evaluator, parse_scores
from app.providers.base import GenerationRequest, LLMProvider

JUDGE_SYSTEM_PROMPT = """You are a strict, impartial evaluator of language model output.

You will be given a PROMPT and a RESPONSE. Score the RESPONSE on four criteria,
each an integer or one-decimal number from 0 to 10:

- relevance:   Does it address what the prompt actually asked?
- correctness: Is it factually and logically sound? Penalise confident errors heavily.
- conciseness: Is it as short as it can be while still complete? Penalise padding.
- clarity:     Is it well organised and easy to follow?

Also give `overall` (0-10), your holistic judgement, and `reasoning`: two or three
sentences citing specific evidence from the response.

Reply with ONE JSON object and nothing else:

{"relevance": 0, "correctness": 0, "conciseness": 0, "clarity": 0, "overall": 0, "reasoning": ""}

Do not wrap it in a code fence. Do not add commentary before or after."""

_MAX_EXCERPT_CHARS = 12_000


def _truncate(text: str, limit: int = _MAX_EXCERPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated, {len(text) - limit} more characters]"


def build_judge_prompt(prompt: str, response: str, system_prompt: str | None = None) -> str:
    parts = ["<prompt>", _truncate(prompt, 8000), "</prompt>"]
    if system_prompt:
        parts += ["", "<system_prompt>", _truncate(system_prompt, 4000), "</system_prompt>"]
    parts += ["", "<response>", _truncate(response), "</response>", "", "Score the response now."]
    return "\n".join(parts)


class LLMJudgeEvaluator(Evaluator):
    """Scores a response using another model."""

    mode = "llm_judge"

    #: Deterministic judging; sampling noise would make scores unrepeatable.
    temperature = 0.0
    max_tokens = 700

    def __init__(self, provider: LLMProvider, model: str, *, timeout: float | None = None) -> None:
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.evaluator_model = f"{provider.id}:{model}"

    async def evaluate(
        self,
        *,
        prompt: str,
        response: str,
        system_prompt: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> EvaluationScores:
        if not (response or "").strip():
            return EvaluationScores(
                relevance=0,
                correctness=0,
                conciseness=0,
                clarity=0,
                overall=0,
                reasoning="Empty response; not sent to the judge.",
            )

        request = GenerationRequest(
            model=self.model,
            prompt=build_judge_prompt(prompt, response, system_prompt),
            system_prompt=JUDGE_SYSTEM_PROMPT,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

        try:
            result = await self.provider.generate(request)
        except ProviderError as exc:
            raise EvaluationError(f"Judge {self.evaluator_model} failed: {exc.message}") from exc

        scores = parse_scores(result.response)
        if scores.reasoning is None:
            scores = scores.model_copy(update={"reasoning": "Judge returned no reasoning."})
        return scores
