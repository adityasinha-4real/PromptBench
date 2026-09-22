"""Run-to-run comparison: metric movement, classification and the API wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.models.benchmark import BenchmarkRun, Evaluation, ModelResult, ResultStatus, RunStatus
from app.services.comparison_service import build_comparison
from tests.conftest import benchmark_payload

STARTED = datetime(2026, 1, 1, tzinfo=UTC)


def make_result(
    *,
    provider: str = "ollama",
    model: str = "m1",
    variant: str = "Default",
    status: str = ResultStatus.SUCCESS,
    quality: float | None = 8.0,
    latency: int | None = 1000,
    cost: float | None = 0.002,
    tokens: int | None = 100,
    mode: str = "heuristic",
) -> ModelResult:
    result = ModelResult(
        provider=provider,
        model=model,
        variant_name=variant,
        status=status,
        latency_ms=latency,
        estimated_cost=cost,
        total_tokens=tokens,
    )
    if quality is not None:
        result.evaluation = Evaluation(
            relevance=quality,
            correctness=quality,
            conciseness=quality,
            clarity=quality,
            overall=quality,
            mode=mode,
        )
    return result


def make_run(results: list[ModelResult], run_id: int = 1) -> BenchmarkRun:
    run = BenchmarkRun(benchmark_id=7, status=RunStatus.COMPLETED)
    run.id = run_id
    run.started_at = STARTED + timedelta(hours=run_id)
    run.completed_at = run.started_at + timedelta(minutes=1)
    run.results = results
    return run


def only_entry(base: list[ModelResult], target: list[ModelResult]) -> Any:
    comparison = build_comparison(make_run(base, 1), make_run(target, 2))
    assert len(comparison.entries) == 1
    return comparison.entries[0]


# ----------------------------------------------------------------------
# Metric movement
# ----------------------------------------------------------------------
def test_quality_up_and_latency_down_is_an_improvement() -> None:
    entry = only_entry(
        [make_result(quality=6.0, latency=2000)], [make_result(quality=8.0, latency=1000)]
    )
    assert entry.quality.delta == 2.0
    assert entry.quality.direction == "better"
    assert entry.latency_ms.delta == -1000
    assert entry.latency_ms.direction == "better"
    assert entry.latency_ms.percent_change == -50.0
    assert entry.change == "improved"


def test_cheaper_but_worse_is_reported_as_mixed_not_averaged_away() -> None:
    entry = only_entry(
        [make_result(quality=9.0, cost=0.01)], [make_result(quality=6.0, cost=0.001)]
    )
    assert entry.quality.direction == "worse"
    assert entry.estimated_cost.direction == "better"
    assert entry.change == "mixed"


def test_movement_within_the_epsilon_is_unchanged() -> None:
    entry = only_entry(
        [make_result(quality=8.0, latency=1000)], [make_result(quality=8.02, latency=1005)]
    )
    assert entry.quality.direction == "unchanged"
    assert entry.latency_ms.direction == "unchanged"
    assert entry.change == "unchanged"


def test_a_missing_price_is_unknown_rather_than_zero() -> None:
    entry = only_entry([make_result(cost=None)], [make_result(cost=0.004)])
    assert entry.estimated_cost.direction == "unknown"
    assert entry.estimated_cost.delta is None
    assert entry.estimated_cost.base is None


def test_percent_change_is_omitted_when_the_base_is_zero() -> None:
    entry = only_entry([make_result(cost=0.0)], [make_result(cost=0.004)])
    assert entry.estimated_cost.delta == 0.004
    assert entry.estimated_cost.percent_change is None


def test_a_failed_result_contributes_no_metrics() -> None:
    """A failure's latency is time spent failing, not a faster answer."""
    entry = only_entry(
        [make_result(latency=3000)],
        [make_result(status=ResultStatus.FAILED, quality=None, latency=5)],
    )
    assert entry.latency_ms.target is None
    assert entry.latency_ms.direction == "unknown"
    assert entry.change == "regressed"
    assert entry.note is not None and "failed" in entry.note.lower()


def test_a_fixed_failure_counts_as_improved() -> None:
    entry = only_entry(
        [make_result(status=ResultStatus.FAILED, quality=None)], [make_result(quality=7.0)]
    )
    assert entry.change == "improved"


# ----------------------------------------------------------------------
# Line-up and summary
# ----------------------------------------------------------------------
def test_models_added_and_removed_between_runs_are_both_listed() -> None:
    comparison = build_comparison(
        make_run([make_result(model="gone"), make_result(model="kept")], 1),
        make_run([make_result(model="kept"), make_result(model="new")], 2),
    )
    by_model = {e.model: e for e in comparison.entries}
    assert by_model["new"].change == "added"
    assert by_model["gone"].change == "removed"
    assert by_model["kept"].change == "unchanged"
    assert comparison.summary.added == 1
    assert comparison.summary.removed == 1


def test_variants_of_the_same_model_are_compared_separately() -> None:
    comparison = build_comparison(
        make_run([make_result(variant="A", quality=5.0), make_result(variant="B", quality=5.0)], 1),
        make_run([make_result(variant="A", quality=9.0), make_result(variant="B", quality=5.0)], 2),
    )
    by_variant = {e.variant_name: e.change for e in comparison.entries}
    assert by_variant == {"A": "improved", "B": "unchanged"}


def test_summary_totals_and_averages_skip_missing_values() -> None:
    comparison = build_comparison(
        make_run([make_result(model="a", quality=6.0), make_result(model="b", cost=None)], 1),
        make_run([make_result(model="a", quality=8.0), make_result(model="b", cost=None)], 2),
    )
    assert comparison.summary.improved == 1
    assert comparison.summary.avg_quality_delta == 1.0  # (+2.0 and 0.0) / 2
    # Model b has no price on either side, so it is absent from the cost total.
    assert comparison.summary.total_cost_delta == 0.0


def test_new_and_fixed_failures_are_counted() -> None:
    comparison = build_comparison(
        make_run([make_result(model="a"), make_result(model="b", status=ResultStatus.FAILED)], 1),
        make_run([make_result(model="a", status=ResultStatus.FAILED), make_result(model="b")], 2),
    )
    assert comparison.summary.new_failures == 1
    assert comparison.summary.fixed_failures == 1


def test_quality_is_withheld_when_the_evaluation_mode_changed() -> None:
    comparison = build_comparison(
        make_run([make_result(quality=5.0, mode="heuristic")], 1),
        make_run([make_result(quality=9.0, mode="llm_judge")], 2),
    )
    assert comparison.quality_comparable is False
    assert comparison.entries[0].quality.delta is None
    assert any("evaluation mode" in note for note in comparison.notes)


def test_an_unfinished_run_is_flagged() -> None:
    base = make_run([make_result()], 1)
    target = make_run([make_result()], 2)
    target.status = RunStatus.CANCELLED
    comparison = build_comparison(base, target)
    assert any("cancelled" in note for note in comparison.notes)


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
async def create_with_runs(client: AsyncClient, runs: int = 2) -> dict[str, Any]:
    created = (await client.post("/api/benchmarks", json=benchmark_payload())).json()
    for _ in range(runs):
        response = await client.post(f"/api/benchmarks/{created['id']}/run?wait=true")
        assert response.status_code == 202, response.text
    return (await client.get(f"/api/benchmarks/{created['id']}")).json()


async def test_compare_defaults_to_the_two_most_recent_runs(client: AsyncClient) -> None:
    benchmark = await create_with_runs(client, runs=3)
    run_ids = sorted(r["id"] for r in benchmark["runs"])

    body = (await client.get(f"/api/benchmarks/{benchmark['id']}/compare")).json()

    assert body["base"]["id"] == run_ids[-2]
    assert body["target"]["id"] == run_ids[-1]
    assert len(body["entries"]) == 2  # two models in the default payload
    assert body["quality_comparable"] is True


async def test_compare_accepts_explicit_runs_in_either_order(client: AsyncClient) -> None:
    benchmark = await create_with_runs(client, runs=2)
    oldest, newest = sorted(r["id"] for r in benchmark["runs"])

    swapped = (
        await client.get(
            f"/api/benchmarks/{benchmark['id']}/compare",
            params={"base_run_id": newest, "target_run_id": oldest},
        )
    ).json()

    # Normalised to oldest-first, so a delta always means "what the re-run did".
    assert swapped["base"]["id"] == oldest
    assert swapped["target"]["id"] == newest


@pytest.mark.parametrize("params", [{}, {"base_run_id": 1, "target_run_id": 1}])
async def test_compare_rejects_impossible_requests(
    client: AsyncClient, params: dict[str, int]
) -> None:
    created = (await client.post("/api/benchmarks", json=benchmark_payload())).json()
    await client.post(f"/api/benchmarks/{created['id']}/run?wait=true")

    response = await client.get(f"/api/benchmarks/{created['id']}/compare", params=params)

    # 400 for a request the app understands but cannot satisfy; 422 is reserved
    # for a malformed one.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_compare_rejects_a_run_from_another_benchmark(client: AsyncClient) -> None:
    first = await create_with_runs(client, runs=2)
    second = await create_with_runs(client, runs=2)
    foreign_run = second["runs"][0]["id"]

    response = await client.get(
        f"/api/benchmarks/{first['id']}/compare",
        params={"base_run_id": first["runs"][0]["id"], "target_run_id": foreign_run},
    )

    assert response.status_code == 400
    assert str(second["id"]) in response.json()["error"]["message"]


async def test_compare_on_a_missing_benchmark_is_a_404(client: AsyncClient) -> None:
    response = await client.get("/api/benchmarks/9999/compare")
    assert response.status_code == 404
