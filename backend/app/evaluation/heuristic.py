"""Deterministic, offline evaluator.

This is the default evaluation mode because it is the only one that works with
no API credentials at all, which keeps PromptBench useful out of the box.

What it actually measures — stated plainly, because an evaluation metric that
overstates itself is worse than none:

* **relevance**  — lexical coverage of the prompt's content words, plus a bonus
  for answering the prompt's question words. A genuine signal.
* **correctness** — a *proxy*. It cannot check facts. It scores whether the
  response looks like a delivered answer: non-empty, not a refusal, not
  truncated mid-sentence, not hedged into uselessness. Use LLM-judge mode or
  manual scoring when factual accuracy matters.
* **conciseness** — length against a prompt-scaled target band, penalised for
  repeated sentences and filler openers.
* **clarity**    — sentence-length distribution and the presence of structure
  (paragraphs, lists, headings).

Identical input always produces an identical score, which makes this mode
useful for regression comparisons across runs.
"""

from __future__ import annotations

import re
from typing import Any

from app.evaluation.base import EvaluationScores, Evaluator

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "here",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "me",
        "might",
        "more",
        "most",
        "must",
        "my",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "on",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "via",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_REFUSAL_PATTERNS = (
    r"\bi (?:can(?:no|')t|cannot|am unable to|won'?t) (?:help|assist|answer|provide|comply)",
    r"\bas an ai (?:language )?model\b",
    r"\bi (?:don'?t|do not) have (?:enough )?(?:information|knowledge|access)\b",
    r"\bi'?m (?:sorry|afraid)[, ].{0,40}(?:can(?:no|')t|cannot|unable)",
)

_FILLER_PATTERNS = (
    r"\bcertainly[!,]",
    r"\bof course[!,]",
    r"\bgreat question\b",
    r"\bi'?d be happy to\b",
    r"\bin today'?s world\b",
    r"\bit'?s important to note that\b",
    r"\bin conclusion,",
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _content_words(text: str) -> set[str]:
    return {w for w in _words(text) if w not in _STOPWORDS and len(w) > 2}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def _scale(value: float, low: float, high: float) -> float:
    """Map ``value`` from the ``[low, high]`` band onto ``[0, 10]``."""
    if high <= low:
        return 0.0
    return round(min(10.0, max(0.0, (value - low) / (high - low) * 10)), 2)


class HeuristicEvaluator(Evaluator):
    """Offline scorer. Requires no provider and no network."""

    mode = "heuristic"
    evaluator_model = "builtin:heuristic-v1"

    async def evaluate(
        self,
        *,
        prompt: str,
        response: str,
        system_prompt: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> EvaluationScores:
        text = (response or "").strip()
        if not text:
            return EvaluationScores(
                relevance=0,
                correctness=0,
                conciseness=0,
                clarity=0,
                overall=0,
                reasoning="Empty response.",
            )

        notes: list[str] = []
        relevance = self._relevance(prompt, text, notes)
        correctness = self._correctness_proxy(text, notes)
        conciseness = self._conciseness(prompt, text, notes)
        clarity = self._clarity(text, notes)

        return EvaluationScores(
            relevance=relevance,
            correctness=correctness,
            conciseness=conciseness,
            clarity=clarity,
            reasoning="Heuristic (offline, deterministic). " + " ".join(notes),
        )

    # -- individual criteria ------------------------------------------------
    def _relevance(self, prompt: str, text: str, notes: list[str]) -> float:
        prompt_terms = _content_words(prompt)
        if not prompt_terms:
            notes.append("Prompt had no scorable content words; relevance defaulted to 5.0.")
            return 5.0

        response_terms = _content_words(text)
        # Stem-insensitive match so "handshake"/"handshakes" both count.
        hits = sum(
            1
            for term in prompt_terms
            if term in response_terms or any(r.startswith(term[:6]) for r in response_terms)
        )
        coverage = hits / len(prompt_terms)
        score = _scale(coverage, 0.1, 0.75)

        # Explanatory prompts should produce explanatory answers.
        if re.search(r"\b(why|how|explain|describe|compare)\b", prompt, re.IGNORECASE):
            connectives = r"\b(because|since|therefore|so that|which means|due to)\b"
            if re.search(connectives, text, re.IGNORECASE):
                score = min(10.0, score + 1.0)
            else:
                notes.append("No explanatory connectives for an explanation-style prompt.")
        notes.append(f"Covers {coverage:.0%} of prompt terms.")
        return round(score, 2)

    def _correctness_proxy(self, text: str, notes: list[str]) -> float:
        score = 7.5  # neutral prior: a delivered, well-formed answer
        lowered = text.lower()

        if any(re.search(p, lowered) for p in _REFUSAL_PATTERNS):
            score -= 4.0
            notes.append("Contains refusal or capability-disclaimer language.")

        words = _words(text)
        if len(words) < 15:
            score -= 2.0
            notes.append("Very short answer.")

        # Truncated mid-sentence is a strong negative signal.
        if text and text[-1] not in ".!?\"')]`" and not text.endswith("```"):
            score -= 1.5
            notes.append("Appears truncated mid-sentence.")

        hedges = len(re.findall(r"\b(maybe|perhaps|possibly|might be|i think|not sure)\b", lowered))
        if hedges >= 3:
            score -= 1.0
            notes.append(f"Heavily hedged ({hedges} hedge phrases).")

        # Concrete detail correlates with substantive answers.
        if re.search(r"\d", text) or re.search(r"`[^`]+`", text):
            score += 0.5

        return round(min(10.0, max(0.0, score)), 2)

    def _conciseness(self, prompt: str, text: str, notes: list[str]) -> float:
        words = _words(text)
        count = len(words)
        # Target band scales with prompt complexity.
        prompt_words = max(len(_words(prompt)), 5)
        target = min(400, max(60, prompt_words * 12))

        if count <= target:
            score = _scale(count, target * 0.12, target * 0.85)
            score = min(10.0, score + 1.0)
        else:
            overshoot = count / target
            score = max(0.0, 10.0 - (overshoot - 1.0) * 5.0)
            notes.append(f"{overshoot:.1f}x longer than the target length.")

        sentences = _sentences(text)
        if len(sentences) > 2:
            unique_ratio = len({s.lower() for s in sentences}) / len(sentences)
            if unique_ratio < 0.9:
                score *= unique_ratio
                notes.append("Contains repeated sentences.")

        fillers = sum(1 for p in _FILLER_PATTERNS if re.search(p, text, re.IGNORECASE))
        if fillers:
            score = max(0.0, score - fillers * 0.75)
            notes.append(f"{fillers} filler phrase(s).")

        return round(min(10.0, max(0.0, score)), 2)

    def _clarity(self, text: str, notes: list[str]) -> float:
        sentences = _sentences(text)
        if not sentences:
            return 0.0

        lengths = [len(_words(s)) for s in sentences if _words(s)]
        if not lengths:
            return 0.0
        mean_len = sum(lengths) / len(lengths)

        # 8-24 words per sentence reads well; penalise linearly outside that band.
        if 8 <= mean_len <= 24:
            score = 9.0
        elif mean_len < 8:
            score = 9.0 - (8 - mean_len) * 0.6
        else:
            score = 9.0 - (mean_len - 24) * 0.25

        runaway = sum(1 for length in lengths if length > 45)
        if runaway:
            score -= runaway * 0.75
            notes.append(f"{runaway} sentence(s) over 45 words.")

        if re.search(r"^\s*(?:[-*•]|\d+\.)\s+", text, re.MULTILINE) or "\n\n" in text:
            score += 1.0
        if re.search(r"^#{1,6}\s+", text, re.MULTILINE):
            score += 0.5

        notes.append(f"Mean sentence length {mean_len:.0f} words.")
        return round(min(10.0, max(0.0, score)), 2)
