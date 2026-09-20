"""Cost calculation and the pricing table."""

from __future__ import annotations

import json

import pytest

from app.core import pricing
from app.core.pricing import (
    ModelPrice,
    PricingTable,
    cost_per_1k_tokens,
    estimate_cost,
    get_price,
    get_pricing_table,
    pricing_metadata,
    reload_pricing_table,
)


def test_cost_formula_matches_specification() -> None:
    price = ModelPrice(input_per_1m=2.5, output_per_1m=10.0)
    # (1000/1e6 * 2.5) + (2000/1e6 * 10) = 0.0025 + 0.02
    assert price.cost_for(1000, 2000) == pytest.approx(0.0225)


def test_estimate_cost_for_known_model() -> None:
    cost = estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
    price = get_price("openai", "gpt-4o")
    assert price is not None
    assert cost == pytest.approx(price.input_per_1m + price.output_per_1m)


def test_unknown_model_returns_none_not_zero() -> None:
    """Pricing must never be invented; None drives 'Pricing unavailable' in the UI."""
    assert estimate_cost("openai", "totally-made-up-model", 1000, 1000) is None
    assert get_price("openai", "totally-made-up-model") is None


def test_unknown_provider_returns_none() -> None:
    assert estimate_cost("no-such-provider", "whatever", 100, 100) is None


def test_ollama_wildcard_is_free_because_it_is_local() -> None:
    assert estimate_cost("ollama", "llama3.2", 5_000, 9_000) == 0.0
    assert estimate_cost("ollama", "any-model-at-all:7b", 1, 1) == 0.0


def test_dated_model_alias_falls_back_to_base_model() -> None:
    base = get_price("openai", "gpt-4o")
    alias = get_price("openai", "gpt-4o-2024-08-06")
    assert base is not None and alias is not None
    assert alias.input_per_1m == base.input_per_1m


def test_cost_per_1k_tokens_is_blended() -> None:
    value = cost_per_1k_tokens("openai", "gpt-4o", 1000, 1000)
    total_cost = estimate_cost("openai", "gpt-4o", 1000, 1000)
    assert total_cost is not None and value is not None
    assert value == pytest.approx(total_cost / 2000 * 1000)


def test_cost_per_1k_with_zero_tokens_is_none() -> None:
    assert cost_per_1k_tokens("openai", "gpt-4o", 0, 0) is None


def test_negative_tokens_are_clamped() -> None:
    assert estimate_cost("openai", "gpt-4o", -500, -500) == 0.0


def test_pricing_metadata_declares_estimates() -> None:
    meta = pricing_metadata()
    assert meta["estimated"] is True
    assert "estimate" in meta["disclaimer"].lower()
    assert meta["currency"] == "USD"


def test_table_lookup_prefers_exact_match_over_wildcard() -> None:
    table = PricingTable(
        as_of="test",
        currency="USD",
        unit="per_1m_tokens",
        sources={},
        providers={
            "x": {"*": ModelPrice(1.0, 1.0), "special": ModelPrice(9.0, 9.0)},
        },
    )
    assert table.lookup("x", "special").input_per_1m == 9.0
    assert table.lookup("x", "other").input_per_1m == 1.0


def test_malformed_entries_are_skipped_not_fatal(tmp_path, monkeypatch) -> None:
    path = tmp_path / "pricing.json"
    path.write_text(
        json.dumps(
            {
                "as_of": "2025-01-01",
                "providers": {
                    "demo": {
                        "good": {"input": 1.0, "output": 2.0},
                        "bad": {"input": "not-a-number", "output": 2.0},
                        "missing": {"input": 1.0},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pricing.settings, "pricing_file", str(path))
    table = reload_pricing_table()
    try:
        assert "good" in table.providers["demo"]
        assert "bad" not in table.providers["demo"]
        assert "missing" not in table.providers["demo"]
    finally:
        monkeypatch.setattr(pricing.settings, "pricing_file", None)
        reload_pricing_table()


def test_missing_pricing_file_falls_back_without_crashing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pricing.settings, "pricing_file", str(tmp_path / "nope.json"))
    table = reload_pricing_table()
    try:
        assert table.as_of == "unknown"
        assert estimate_cost("ollama", "llama3.2", 10, 10) == 0.0
        assert estimate_cost("openai", "gpt-4o", 10, 10) is None
    finally:
        monkeypatch.setattr(pricing.settings, "pricing_file", None)
        reload_pricing_table()


def test_shipped_table_is_loadable_and_populated() -> None:
    table = get_pricing_table()
    assert table.providers
    assert table.as_of != "unknown"
    for provider, models in table.providers.items():
        for model, price in models.items():
            assert price.input_per_1m >= 0, f"{provider}/{model}"
            assert price.output_per_1m >= 0, f"{provider}/{model}"
