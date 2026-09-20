"""Curated model catalogue for the hosted providers.

Listing endpoints for the hosted providers return hundreds of entries including
embeddings, moderation and retired snapshots, which is useless for a model
picker. Instead each provider ships a short curated list here, and users can
still benchmark any other model id by typing it in — the adapters never
validate against this list before calling.
"""

from __future__ import annotations

from app.providers.base import ModelInfo

OPENAI_MODELS: list[ModelInfo] = [
    ModelInfo("openai", "gpt-4.1", "GPT-4.1", 1_047_576, "Flagship general-purpose model."),
    ModelInfo("openai", "gpt-4.1-mini", "GPT-4.1 mini", 1_047_576, "Balanced cost and quality."),
    ModelInfo("openai", "gpt-4.1-nano", "GPT-4.1 nano", 1_047_576, "Fastest, cheapest tier."),
    ModelInfo("openai", "gpt-4o", "GPT-4o", 128_000, "Multimodal flagship."),
    ModelInfo("openai", "gpt-4o-mini", "GPT-4o mini", 128_000, "Small multimodal model."),
    ModelInfo("openai", "o3-mini", "o3-mini", 200_000, "Reasoning-tuned small model."),
]

ANTHROPIC_MODELS: list[ModelInfo] = [
    ModelInfo("anthropic", "claude-sonnet-4-5", "Claude Sonnet 4.5", 200_000, "Balanced flagship."),
    ModelInfo("anthropic", "claude-opus-4-1", "Claude Opus 4.1", 200_000, "Highest capability."),
    ModelInfo("anthropic", "claude-haiku-4-5", "Claude Haiku 4.5", 200_000, "Fast and cheap."),
    ModelInfo(
        "anthropic", "claude-3-5-haiku-latest", "Claude 3.5 Haiku", 200_000, "Previous fast tier."
    ),
]

GEMINI_MODELS: list[ModelInfo] = [
    ModelInfo("gemini", "gemini-2.5-pro", "Gemini 2.5 Pro", 1_048_576, "Highest capability."),
    ModelInfo("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", 1_048_576, "Fast workhorse."),
    ModelInfo("gemini", "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", 1_048_576, "Cheapest."),
    ModelInfo("gemini", "gemini-2.0-flash", "Gemini 2.0 Flash", 1_048_576, "Previous generation."),
]

#: Suggestions shown when Ollama is reachable but has no models pulled yet.
OLLAMA_SUGGESTIONS: list[str] = ["llama3.2", "qwen2.5", "phi3", "mistral", "gemma2"]
