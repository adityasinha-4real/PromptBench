"""Analytics, leaderboard and dashboard endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import benchmark_payload


async def seed(client: AsyncClient, **overrides) -> int:
    created = (await client.post("/api/benchmarks", json=benchmark_payload(**overrides))).json()
    await client.post(f"/api/benchmarks/{created['id']}/run?wait=true")
    return created["id"]


async def test_analytics_on_an_empty_database(client: AsyncClient) -> None:
    body = (await client.get("/api/analytics")).json()
    totals = body["totals"]
    assert totals["total_benchmarks"] == 0
    assert totals["total_executions"] == 0
    assert totals["avg_latency_ms"] is None
    assert totals["avg_cost"] is None
    assert body["by_model"] == []
    assert body["timeline"] == []


async def test_analytics_totals_and_breakdowns(client: AsyncClient) -> None:
    await seed(client)
    await seed(client, name="second")

    body = (await client.get("/api/analytics")).json()
    totals = body["totals"]
    assert totals["total_benchmarks"] == 2
    assert totals["total_runs"] == 2
    assert totals["total_executions"] == 4
    assert totals["successful_executions"] == 4
    assert totals["failed_executions"] == 0
    assert totals["total_input_tokens"] == 160
    assert totals["total_output_tokens"] == 240
    assert totals["total_tokens"] == 400
    assert totals["avg_quality"] is not None

    assert {(m["provider"], m["model"]) for m in body["by_model"]} == {
        ("ollama", "m1"),
        ("openai", "m1"),
    }
    assert {p["provider"] for p in body["by_provider"]} == {"ollama", "openai"}
    assert len(body["timeline"]) == 1
    assert body["timeline"][0]["executions"] == 4


async def test_unpriced_models_are_excluded_from_cost_not_counted_as_free(
    client: AsyncClient,
) -> None:
    """'openai/m1' has no configured price; 'ollama/*' is genuinely $0."""
    await seed(client)
    body = (await client.get("/api/analytics")).json()

    by_key = {(m["provider"], m["model"]): m for m in body["by_model"]}
    assert by_key[("openai", "m1")]["avg_cost"] is None
    assert by_key[("openai", "m1")]["priced"] is False
    assert by_key[("ollama", "m1")]["avg_cost"] == 0.0
    assert by_key[("ollama", "m1")]["priced"] is True
    assert body["totals"]["unpriced_executions"] == 1


async def test_analytics_records_failures_by_error_code(client: AsyncClient, registry) -> None:
    from app.core.errors import ErrorCode, ProviderError

    registry.get("openai").fail_with = ProviderError(
        "timed out.", code=ErrorCode.TIMEOUT, provider="openai"
    )
    await seed(client)
    body = (await client.get("/api/analytics")).json()

    assert body["totals"]["failed_executions"] == 1
    assert body["errors"] == [{"code": "timeout", "count": 1}]
    openai = next(m for m in body["by_model"] if m["provider"] == "openai")
    assert openai["success_rate"] == 0.0


async def test_analytics_filters(client: AsyncClient) -> None:
    benchmark_id = await seed(client)
    await seed(client, name="other")

    by_provider = (await client.get("/api/analytics?provider=ollama")).json()
    assert by_provider["totals"]["total_executions"] == 2
    assert by_provider["filters_applied"]["provider"] == "ollama"

    by_benchmark = (await client.get(f"/api/analytics?benchmark_id={benchmark_id}")).json()
    assert by_benchmark["totals"]["total_executions"] == 2

    future = (await client.get("/api/analytics?date_from=2099-01-01")).json()
    assert future["totals"]["total_executions"] == 0

    past = (await client.get("/api/analytics?date_from=2000-01-01")).json()
    assert past["totals"]["total_executions"] == 4


async def test_malformed_date_filter_is_ignored_not_fatal(client: AsyncClient) -> None:
    await seed(client)
    response = await client.get("/api/analytics?date_from=not-a-date")
    assert response.status_code == 200
    assert response.json()["totals"]["total_executions"] == 2


async def test_leaderboard_sorts_by_the_requested_metric(client: AsyncClient) -> None:
    await seed(client)

    quality = (await client.get("/api/leaderboard?metric=quality")).json()
    assert quality["metric"] == "quality"
    assert quality["direction"] == "desc"
    assert [e["rank"] for e in quality["entries"]] == [1, 2]
    scores = [e["avg_quality"] for e in quality["entries"]]
    assert scores == sorted(scores, reverse=True)

    latency = (await client.get("/api/leaderboard?metric=latency")).json()
    assert latency["direction"] == "asc"
    latencies = [e["avg_latency_ms"] for e in latency["entries"]]
    assert latencies == sorted(latencies)


async def test_leaderboard_publishes_its_methodology(client: AsyncClient) -> None:
    """No opaque composite score: the ranking has to explain itself."""
    await seed(client)
    body = (await client.get("/api/leaderboard?metric=cost")).json()
    assert "composite" in body["methodology"] or "single composite" in body["methodology"]
    assert "estimate" in body["methodology"].lower()


async def test_leaderboard_places_models_without_data_last(client: AsyncClient) -> None:
    await seed(client)
    body = (await client.get("/api/leaderboard?metric=cost")).json()
    costs = [e["avg_cost"] for e in body["entries"]]
    assert costs[-1] is None, "unpriced models rank last rather than as cheapest"


async def test_leaderboard_min_executions_filter(client: AsyncClient) -> None:
    await seed(client)
    assert (await client.get("/api/leaderboard?min_executions=99")).json()["entries"] == []


async def test_leaderboard_unknown_metric_falls_back_to_quality(client: AsyncClient) -> None:
    await seed(client)
    assert (await client.get("/api/leaderboard?metric=vibes")).json()["metric"] == "quality"


async def test_leaderboard_metrics_catalogue(client: AsyncClient) -> None:
    body = (await client.get("/api/leaderboard/metrics")).json()
    ids = {m["id"] for m in body["metrics"]}
    assert {"quality", "latency", "cost", "throughput", "success_rate"} <= ids
    for metric in body["metrics"]:
        assert metric["direction"] in ("asc", "desc")
        assert metric["description"]


async def test_dashboard_summary(client: AsyncClient) -> None:
    await seed(client)
    body = (await client.get("/api/dashboard")).json()
    assert body["totals"]["total_benchmarks"] == 1
    assert len(body["top_models"]) == 2
    assert body["evaluations_recorded"] == 2
    assert len(body["recent_benchmark_ids"]) == 1


async def test_sub_cent_costs_survive_aggregation(client: AsyncClient, registry) -> None:
    """A model costing 4.6e-05 per call must not aggregate to 0.0 and look free."""
    registry.get("openai").input_tokens = 23
    registry.get("openai").output_tokens = 71
    await seed(client, models=[{"provider": "openai", "model": "gpt-4o-mini"}])

    body = (await client.get("/api/analytics")).json()
    stat = next(m for m in body["by_model"] if m["model"] == "gpt-4o-mini")

    expected = 23 / 1_000_000 * 0.15 + 71 / 1_000_000 * 0.60
    assert stat["avg_cost"] == pytest.approx(expected, rel=1e-6)
    assert stat["avg_cost"] > 0
    assert body["totals"]["avg_cost"] == pytest.approx(expected, rel=1e-6)

    leaderboard = (await client.get("/api/leaderboard?metric=cost")).json()
    assert leaderboard["entries"][0]["avg_cost"] == pytest.approx(expected, rel=1e-6)
