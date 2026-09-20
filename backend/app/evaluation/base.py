"""Evaluator abstraction and the validated score schema.

The benchmark engine depends on :class:`Evaluator` only, so evaluators are
swappable. Malformed evaluator output can never break a benchmark: parsing is
Pydantic-validated and failures surface as :class:`EvaluationError`, which the
engine records against the result while leaving the generation intact.
"""

from __future__ import annotations

import abc
import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.errors import ErrorCode, PromptBenchError

#: Criteria scored by every evaluator, in display order.
CRITERIA: tuple[str, ...] = ("relevance", "correctness", "conciseness", "clarity")

#: Weights used to derive `overall` when an evaluator does not supply one.
DEFAULT_WEIGHTS: dict[str, float] = {
    "relevance": 0.3,
    "correctness": 0.3,
    "conciseness": 0.15,
    "clarity": 0.25,
}


class EvaluationError(PromptBenchError):
    """Raised when an evaluator cannot produce valid scores."""

    code = ErrorCode.UNKNOWN


class EvaluationScores(BaseModel):
    """Validated 0-10 scores for one response."""

    relevance: float = Field(ge=0, le=10)
    correctness: float = Field(ge=0, le=10)
    conciseness: float = Field(ge=0, le=10)
    clarity: float = Field(ge=0, le=10)
    overall: float = Field(default=0.0, ge=0, le=10)
    reasoning: str | None = None

    @field_validator("relevance", "correctness", "conciseness", "clarity", "overall", mode="before")
    @classmethod
    def _coerce_number(cls, value: Any) -> Any:
        """Accept ``"8"``, ``"8/10"`` and ``8.5`` alike, and clamp to range."""
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if not match:
                raise ValueError(f"not a number: {value!r}")
            value = float(match.group())
        if isinstance(value, bool):
            raise ValueError("boolean is not a valid score")
        if isinstance(value, (int, float)):
            return round(min(10.0, max(0.0, float(value))), 2)
        raise ValueError(f"not a number: {value!r}")

    @field_validator("reasoning", mode="before")
    @classmethod
    def _trim_reasoning(cls, value: Any) -> Any:
        if value is None:
            return None
        text = value if isinstance(value, str) else json.dumps(value)
        text = text.strip()
        return text[:4000] or None

    @model_validator(mode="after")
    def _fill_overall(self) -> EvaluationScores:
        if self.overall == 0.0 and any(getattr(self, c) > 0 for c in CRITERIA):
            weighted = sum(getattr(self, c) * DEFAULT_WEIGHTS[c] for c in CRITERIA)
            object.__setattr__(self, "overall", round(weighted, 2))
        return self


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of free-form model output.

    Handles fenced blocks and leading/trailing prose, which judges emit routinely.

    Raises:
        EvaluationError: when no parseable object is present.
    """
    if not text or not text.strip():
        raise EvaluationError("Evaluator returned an empty response.")

    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.IGNORECASE)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Scan for the first balanced {...} span, ignoring braces inside strings.
    depth = 0
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(cleaned):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    candidate = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError:
                    start = -1
                    continue
                if isinstance(candidate, dict):
                    return candidate
                start = -1

    raise EvaluationError("Evaluator output did not contain a JSON object.")


def parse_scores(text: str) -> EvaluationScores:
    """Parse and validate evaluator output into :class:`EvaluationScores`."""
    payload = extract_json_object(text)
    # Judges occasionally nest the scores one level down.
    for key in ("scores", "evaluation", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict) and any(c in nested for c in CRITERIA):
            reasoning = payload.get("reasoning") or nested.get("reasoning")
            payload = {**nested, "reasoning": reasoning}
            break

    missing = [c for c in CRITERIA if c not in payload]
    if missing:
        raise EvaluationError(f"Evaluator output is missing: {', '.join(missing)}.")

    try:
        return EvaluationScores.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise EvaluationError(f"Evaluator output failed validation: {exc}") from exc


class Evaluator(abc.ABC):
    """Scores a single response. Implementations must be stateless per call."""

    #: Matches ``EvaluationMode`` in the ORM layer.
    mode: str = "base"
    #: Identifier recorded as ``evaluator_model`` (may be ``None`` for offline modes).
    evaluator_model: str | None = None

    @abc.abstractmethod
    async def evaluate(
        self,
        *,
        prompt: str,
        response: str,
        system_prompt: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> EvaluationScores:
        """Return validated scores, or raise :class:`EvaluationError`."""
