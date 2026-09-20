"""Centralised model pricing and cost estimation.

Cost is *never* computed inline anywhere else in the codebase: call
:func:`estimate_cost`. When a model has no configured price the functions here
return ``None``, which the UI renders as "Pricing unavailable" rather than
inventing a number.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TOKENS_PER_UNIT = 1_000_000


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Price for one model, in USD per 1M tokens."""

    input_per_1m: float
    output_per_1m: float
    note: str | None = None

    def cost_for(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / TOKENS_PER_UNIT) * self.input_per_1m + (
            output_tokens / TOKENS_PER_UNIT
        ) * self.output_per_1m


@dataclass(frozen=True, slots=True)
class PricingTable:
    as_of: str
    currency: str
    unit: str
    sources: dict[str, str]
    providers: dict[str, dict[str, ModelPrice]]

    def lookup(self, provider: str, model: str) -> ModelPrice | None:
        """Resolve a price, honouring an optional ``"*"`` wildcard per provider."""
        by_model = self.providers.get(provider)
        if not by_model:
            return None
        if model in by_model:
            return by_model[model]
        # Providers such as Ollama price every model identically.
        if "*" in by_model:
            return by_model["*"]
        # Tolerate dated model aliases, e.g. "gpt-4o-2024-08-06" -> "gpt-4o".
        for known, price in by_model.items():
            if known != "*" and model.startswith(f"{known}-"):
                return price
        return None


_lock = threading.Lock()
_table: PricingTable | None = None

_FALLBACK: dict[str, Any] = {
    "as_of": "unknown",
    "currency": "USD",
    "unit": "per_1m_tokens",
    "sources": {},
    "providers": {"ollama": {"*": {"input": 0.0, "output": 0.0}}},
}


def _parse(raw: dict[str, Any]) -> PricingTable:
    providers: dict[str, dict[str, ModelPrice]] = {}
    for provider, models in (raw.get("providers") or {}).items():
        parsed: dict[str, ModelPrice] = {}
        for model, price in (models or {}).items():
            try:
                parsed[model] = ModelPrice(
                    input_per_1m=float(price["input"]),
                    output_per_1m=float(price["output"]),
                    note=price.get("note"),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Skipping malformed price entry: %s/%s", provider, model)
        providers[provider] = parsed
    return PricingTable(
        as_of=str(raw.get("as_of", "unknown")),
        currency=str(raw.get("currency", "USD")),
        unit=str(raw.get("unit", "per_1m_tokens")),
        sources=dict(raw.get("sources") or {}),
        providers=providers,
    )


def get_pricing_table() -> PricingTable:
    """Return the process-wide pricing table, loading it on first use."""
    global _table
    if _table is None:
        with _lock:
            if _table is None:
                path = settings.pricing_path
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.error("Could not load pricing file %s: %s", path, exc)
                    raw = _FALLBACK
                _table = _parse(raw)
    return _table


def reload_pricing_table() -> PricingTable:
    """Force a reload — used by tests and by the settings endpoint."""
    global _table
    with _lock:
        _table = None
    return get_pricing_table()


def get_price(provider: str, model: str) -> ModelPrice | None:
    return get_pricing_table().lookup(provider, model)


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated USD cost, or ``None`` when the model has no configured price."""
    price = get_price(provider, model)
    if price is None:
        return None
    return round(price.cost_for(max(input_tokens, 0), max(output_tokens, 0)), 10)


def cost_per_1k_tokens(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> float | None:
    """Blended cost normalised to 1,000 total tokens — comparable across models."""
    total = max(input_tokens, 0) + max(output_tokens, 0)
    if total == 0:
        return None
    cost = estimate_cost(provider, model, input_tokens, output_tokens)
    if cost is None:
        return None
    return round(cost / total * 1000, 10)


def pricing_metadata() -> dict[str, Any]:
    """Provenance shown in the UI next to every estimated cost."""
    table = get_pricing_table()
    return {
        "as_of": table.as_of,
        "currency": table.currency,
        "unit": table.unit,
        "sources": table.sources,
        "estimated": True,
        "disclaimer": (
            "Costs are estimates computed from an operator-maintained price table, "
            "not from provider billing data."
        ),
    }
