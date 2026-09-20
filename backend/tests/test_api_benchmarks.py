"""HTTP API: health, models, benchmark CRUD, execution and history."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import benchmark_payload


async def create(client: AsyncClient, **overrides) -> dict:
    response = await client.post("/api/benchmarks", json=benchmark_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def run_to_completion(client: AsyncClient, benchmark_id: int) -> dict:
    response = await client.post(f"/api/benchmarks/{benchmark_id}/run?wait=true")
    assert response.status_code == 202, response.text
    return response.json()


# ----------------------------------------------------------------------
# Health & models
# ----------------------------------------------------------------------
async def test_health_reports_database_and_providers(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert set(body["providers"]) == {"ollama", "openai"}
    assert body["details"]["local_providers"] == ["ollama"]
    assert body["details"]["pricing"]["estimated"] is True


async def test_health_never_leaks_credentials(client: AsyncClient) -> None:
    body = (await client.get("/api/health")).text
    for marker in ("sk-", "api_key", "apiKey", "Bearer"):
        assert marker not in body


async def test_models_endpoint_lists_providers_and_pricing(client: AsyncClient) -> None:
    response = await client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert {p["id"] for p in body["providers"]} == {"ollama", "openai"}
    ollama = next(p for p in body["providers"] if p["id"] == "ollama")
    assert ollama["is_local"] is True
    assert ollama["available"] is True
    assert body["pricing"]["estimated"] is True


async def test_models_endpoint_exposes_env_var_names_not_values(client: AsyncClient) -> None:
    body = (await client.get("/api/models")).json()
    openai = next(p for p in body["providers"] if p["id"] == "openai")
    assert openai["api_key_env"] == "OPENAI_API_KEY"
    assert openai["configured"] is True


@pytest.mark.parametrize("path", ["/api/models", "/api/settings", "/api/health"])
async def test_no_endpoint_ever_returns_a_credential_value(
    client: AsyncClient, monkeypatch, path: str
) -> None:
    """The key value must stay in the backend process — only its presence is reported."""
    from app.core.config import settings

    sentinel = "sk-SENTINEL-must-never-be-returned-0123456789"
    monkeypatch.setattr(settings, "openai_api_key", sentinel)
    monkeypatch.setattr(settings, "anthropic_api_key", sentinel)
    monkeypatch.setattr(settings, "gemini_api_key", sentinel)

    response = await client.get(path)
    assert response.status_code == 200
    assert sentinel not in response.text
    assert "SENTINEL" not in response.text


async def test_unconfigured_provider_reports_unavailable_without_crashing(
    client: AsyncClient, registry
) -> None:
    registry.get("openai")._configured = False
    body = (await client.get("/api/models")).json()
    openai = next(p for p in body["providers"] if p["id"] == "openai")
    assert openai["available"] is False
    assert openai["configured"] is False
    assert "not configured" in openai["status_detail"]


async def test_test_connection_returns_200_even_when_unavailable(
    client: AsyncClient, registry
) -> None:
    registry.get("openai")._configured = False
    response = await client.post("/api/models/test", json={"provider": "openai"})
    assert response.status_code == 200
    assert response.json()["available"] is False


async def test_test_connection_probes_a_specific_model(client: AsyncClient) -> None:
    response = await client.post("/api/models/test", json={"provider": "ollama", "model": "m1"})
    body = response.json()
    assert body["available"] is True
    assert body["generation_ok"] is True


async def test_test_connection_unknown_provider(client: AsyncClient) -> None:
    response = await client.post("/api/models/test", json={"provider": "ghost"})
    assert response.status_code == 200
    assert response.json()["available"] is False


# ----------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------
async def test_create_and_fetch_a_benchmark(client: AsyncClient) -> None:
    created = await create(client)
    assert created["name"] == "TCP handshake"
    assert created["tags"] == ["networking"]
    assert len(created["models"]) == 2

    fetched = (await client.get(f"/api/benchmarks/{created['id']}")).json()
    assert fetched["id"] == created["id"]
    assert fetched["prompt"].startswith("Explain why TCP")


async def test_create_with_run_immediately_produces_results(client: AsyncClient) -> None:
    created = await create(client, run_immediately=True)
    # The run is scheduled in the background; give it a moment, then poll.
    for _ in range(50):
        detail = (await client.get(f"/api/benchmarks/{created['id']}")).json()
        if detail["runs"] and detail["runs"][0]["status"] == "completed":
            break
        await asyncio.sleep(0.05)
    assert detail["runs"], "a run should have been created"


async def test_prompt_variants_are_persisted(client: AsyncClient) -> None:
    created = await create(
        client,
        variants=[
            {"name": "Plain", "prompt": "Explain TCP."},
            {"name": "Analogy", "prompt": "Explain TCP using an analogy."},
        ],
    )
    assert [v["name"] for v in created["variants"]] == ["Plain", "Analogy"]


async def test_update_metadata(client: AsyncClient) -> None:
    created = await create(client)
    response = await client.patch(
        f"/api/benchmarks/{created['id']}",
        json={"name": "  Renamed   benchmark ", "tags": ["TCP", "networking"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed benchmark"
    assert body["tags"] == ["tcp", "networking"]


async def test_delete_benchmark_cascades(client: AsyncClient) -> None:
    created = await create(client)
    await run_to_completion(client, created["id"])

    assert (await client.delete(f"/api/benchmarks/{created['id']}")).status_code == 204
    assert (await client.get(f"/api/benchmarks/{created['id']}")).status_code == 404

    analytics = (await client.get("/api/analytics")).json()
    assert analytics["totals"]["total_executions"] == 0, "results should cascade away"


async def test_missing_benchmark_returns_a_structured_404(client: AsyncClient) -> None:
    response = await client.get("/api/benchmarks/9999")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "9999" in error["message"]


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"prompt": ""}, "prompt"),
        ({"prompt": "   "}, "prompt"),
        ({"name": ""}, "name"),
        ({"models": []}, "models"),
        ({"temperature": 5}, "temperature"),
        ({"temperature": -1}, "temperature"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"max_tokens": 10_000_000}, "max_tokens"),
    ],
)
async def test_invalid_payloads_are_rejected_with_422(
    client: AsyncClient, overrides: dict, fragment: str
) -> None:
    response = await client.post("/api/benchmarks", json=benchmark_payload(**overrides))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_oversized_prompt_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/benchmarks", json=benchmark_payload(prompt="x" * 40_000))
    assert response.status_code == 422
    assert "character limit" in response.text


async def test_duplicate_model_selection_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/benchmarks",
        json=benchmark_payload(
            models=[{"provider": "ollama", "model": "m1"}, {"provider": "ollama", "model": "m1"}]
        ),
    )
    assert response.status_code == 422
    assert "duplicate" in response.text


async def test_llm_judge_without_configuration_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/benchmarks", json=benchmark_payload(evaluation_mode="llm_judge")
    )
    assert response.status_code == 422
    assert "judge" in response.text.lower()


async def test_too_many_models_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/benchmarks",
        json=benchmark_payload(
            models=[{"provider": "ollama", "model": f"m{i}"} for i in range(50)]
        ),
    )
    assert response.status_code == 422


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
async def test_run_returns_normalised_results(client: AsyncClient) -> None:
    created = await create(client)
    progress = await run_to_completion(client, created["id"])
    assert progress["status"] == "completed"
    assert progress["total"] == 2
    assert progress["succeeded"] == 2

    run = (await client.get(f"/api/runs/{progress['run_id']}")).json()
    assert len(run["results"]) == 2
    for result in run["results"]:
        assert result["status"] == "success"
        assert result["response"]
        assert result["total_tokens"] == 100
        assert result["latency_ms"] is not None
        assert result["tokens_per_second"] > 0
        assert result["evaluation"]["overall"] >= 0
        assert "metadata" in result
        assert result["metadata"]["fake"] is True


async def test_run_with_a_failing_provider_reports_a_useful_error(
    client: AsyncClient, registry
) -> None:
    from app.core.errors import ErrorCode, ProviderError

    registry.get("openai").fail_with = ProviderError(
        "API key is missing.",
        code=ErrorCode.AUTHENTICATION,
        provider="openai",
        retryable=False,
    )
    created = await create(client)
    progress = await run_to_completion(client, created["id"])

    run = (await client.get(f"/api/runs/{progress['run_id']}")).json()
    failed = next(r for r in run["results"] if r["provider"] == "openai")
    assert failed["status"] == "failed"
    assert failed["error_code"] == "authentication"
    assert failed["error_message"] == "Openai request failed: API key is missing."
    succeeded = next(r for r in run["results"] if r["provider"] == "ollama")
    assert succeeded["status"] == "success"


async def test_run_overrides_do_not_mutate_the_benchmark(client: AsyncClient) -> None:
    created = await create(client)
    await client.post(
        f"/api/benchmarks/{created['id']}/run?wait=true",
        json={
            "temperature": 1.9,
            "max_tokens": 32,
            "models": [{"provider": "ollama", "model": "m1"}],
        },
    )
    detail = (await client.get(f"/api/benchmarks/{created['id']}")).json()
    assert detail["temperature"] == 0.2
    assert detail["latest_run"]["params_snapshot"]["temperature"] == 1.9
    assert len(detail["latest_run"]["results"]) == 1


async def test_rerun_creates_a_second_run(client: AsyncClient) -> None:
    created = await create(client)
    first = await run_to_completion(client, created["id"])
    second = (await client.post(f"/api/benchmarks/{created['id']}/rerun?wait=true")).json()

    assert second["run_id"] != first["run_id"]
    runs = (await client.get(f"/api/benchmarks/{created['id']}/runs")).json()
    assert len(runs) == 2


async def test_progress_endpoint_works_after_the_run_leaves_memory(client: AsyncClient) -> None:
    from app.services.run_tracker import reset_tracker

    created = await create(client)
    progress = await run_to_completion(client, created["id"])
    reset_tracker()

    response = await client.get(f"/api/runs/{progress['run_id']}/progress")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


async def test_cancel_reports_when_a_run_is_not_in_flight(client: AsyncClient) -> None:
    created = await create(client)
    progress = await run_to_completion(client, created["id"])
    response = await client.post(f"/api/runs/{progress['run_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["cancelled"] is False


async def test_sse_stream_emits_a_terminal_event(client: AsyncClient) -> None:
    created = await create(client)
    progress = await run_to_completion(client, created["id"])
    response = await client.get(f"/api/runs/{progress['run_id']}/stream")
    assert response.status_code == 200
    assert "event: done" in response.text


async def test_matrix_endpoint_maps_variants_to_models(client: AsyncClient) -> None:
    created = await create(
        client,
        variants=[
            {"name": "Plain", "prompt": "Explain TCP."},
            {"name": "Analogy", "prompt": "Explain TCP with an analogy."},
        ],
    )
    progress = await run_to_completion(client, created["id"])
    matrix = (await client.get(f"/api/runs/{progress['run_id']}/matrix")).json()

    assert matrix["variants"] == ["Plain", "Analogy"]
    assert set(matrix["targets"]) == {"ollama:m1", "openai:m1"}
    assert len(matrix["cells"]["Plain"]) == 2


async def test_remove_a_result_from_the_comparison(client: AsyncClient) -> None:
    created = await create(client)
    progress = await run_to_completion(client, created["id"])
    run = (await client.get(f"/api/runs/{progress['run_id']}")).json()
    victim = run["results"][0]["id"]

    assert (await client.delete(f"/api/results/{victim}")).status_code == 204
    remaining = (await client.get(f"/api/runs/{progress['run_id']}")).json()
    assert len(remaining["results"]) == 1


# ----------------------------------------------------------------------
# History: search, filter, sort, paginate
# ----------------------------------------------------------------------
async def test_history_search_and_filters(client: AsyncClient) -> None:
    await create(client, name="TCP handshake", tags=["networking"])
    await create(client, name="CAP theorem", prompt="Explain the CAP theorem.", tags=["distsys"])
    await create(client, name="Sorting", prompt="Explain quicksort.", tags=["algorithms"])

    everything = (await client.get("/api/benchmarks")).json()
    assert everything["total"] == 3

    by_name = (await client.get("/api/benchmarks?search=cap")).json()
    assert [b["name"] for b in by_name["items"]] == ["CAP theorem"]

    by_prompt = (await client.get("/api/benchmarks?search=quicksort")).json()
    assert by_prompt["total"] == 1

    by_tag = (await client.get("/api/benchmarks?tag=networking")).json()
    assert by_tag["total"] == 1

    by_provider = (await client.get("/api/benchmarks?provider=ollama")).json()
    assert by_provider["total"] == 3

    nothing = (await client.get("/api/benchmarks?search=zzzznotfound")).json()
    assert nothing["total"] == 0
    assert nothing["items"] == []


async def test_history_sorting_and_pagination(client: AsyncClient) -> None:
    for name in ("alpha", "bravo", "charlie"):
        await create(client, name=name)

    ascending = (await client.get("/api/benchmarks?sort=name&order=asc")).json()
    assert [b["name"] for b in ascending["items"]] == ["alpha", "bravo", "charlie"]

    descending = (await client.get("/api/benchmarks?sort=name&order=desc")).json()
    assert [b["name"] for b in descending["items"]] == ["charlie", "bravo", "alpha"]

    page = (await client.get("/api/benchmarks?limit=2&offset=1&sort=name&order=asc")).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["name"] == "bravo"


async def test_history_status_filter(client: AsyncClient) -> None:
    ran = await create(client, name="was run")
    await create(client, name="never run")
    await run_to_completion(client, ran["id"])

    completed = (await client.get("/api/benchmarks?status=completed")).json()
    assert [b["name"] for b in completed["items"]] == ["was run"]


async def test_history_rows_include_run_summaries(client: AsyncClient) -> None:
    created = await create(client)
    await run_to_completion(client, created["id"])
    row = (await client.get("/api/benchmarks")).json()["items"][0]
    assert row["run_count"] == 1
    assert row["last_run_status"] == "completed"
    assert row["avg_quality"] is not None
    assert row["model_count"] == 2
    assert row["prompt_excerpt"]


async def test_invalid_sort_field_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/benchmarks?sort=drop_table")).status_code == 422
