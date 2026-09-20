"""Export formats, standalone evaluation, settings and error handling."""

from __future__ import annotations

import csv
import io
import json

import pytest
from httpx import AsyncClient

from tests.conftest import benchmark_payload


async def seeded(client: AsyncClient, **overrides) -> tuple[int, int]:
    created = (await client.post("/api/benchmarks", json=benchmark_payload(**overrides))).json()
    progress = (await client.post(f"/api/benchmarks/{created['id']}/run?wait=true")).json()
    return created["id"], progress["run_id"]


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
async def test_export_json_contains_every_required_field(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client)
    response = await client.get(f"/api/export/{benchmark_id}?format=json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = json.loads(response.text)

    assert payload["benchmark"]["prompt"]
    assert payload["pricing"]["estimated"] is True
    assert len(payload["results"]) == 2
    row = payload["results"][0]
    for field in (
        "prompt",
        "model",
        "provider",
        "response",
        "latency_ms",
        "total_tokens",
        "estimated_cost_usd",
        "overall",
        "timestamp",
    ):
        assert field in row, f"missing {field}"


async def test_export_csv_is_parseable(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client)
    response = await client.get(f"/api/export/{benchmark_id}?format=csv")

    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 2
    assert rows[0]["provider"] in ("ollama", "openai")
    assert rows[0]["response"]


async def test_export_csv_neutralises_spreadsheet_formulas(client: AsyncClient) -> None:
    """A benchmark name is user input and lands in a CSV cell.

    Without an escape, ``=cmd|'/c calc'!A1`` is a live DDE formula the moment the
    export is opened in Excel.
    """
    benchmark_id, _ = await seeded(client, name="=cmd|'/c calc'!A1")
    response = await client.get(f"/api/export/{benchmark_id}?format=csv")

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows, "export produced no rows"
    for row in rows:
        assert row["benchmark_name"] == "'=cmd|'/c calc'!A1"
        for value in row.values():
            assert not value.startswith(("=", "+", "@", "\t", "\r")), value


async def test_export_csv_leaves_ordinary_values_untouched(client: AsyncClient) -> None:
    """The escape must not corrupt normal text or negative numbers."""
    benchmark_id, _ = await seeded(client)
    response = await client.get(f"/api/export/{benchmark_id}?format=csv")

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["benchmark_name"] == "TCP handshake"
    assert not rows[0]["response"].startswith("'")


async def test_export_markdown_escapes_pipes_in_a_variant_name(client: AsyncClient) -> None:
    """A pipe in a variant name would otherwise invent a column and skew the table."""
    benchmark_id, _ = await seeded(
        client,
        variants=[{"name": "a|b", "prompt": "Explain TCP."}],
    )
    response = await client.get(f"/api/export/{benchmark_id}?format=markdown")

    body = response.text
    header = next(line for line in body.splitlines() if line.startswith("| Variant |"))
    expected_columns = header.count("|")
    data_rows = [
        line
        for line in body.splitlines()
        if line.startswith("| ") and not line.startswith(("| Variant |", "| --- |"))
    ]
    assert data_rows, "no summary rows rendered"
    for line in data_rows:
        assert "a\\|b" in line or "a|b" not in line
        # An unescaped pipe would raise the count above the header's.
        assert line.count("|") - line.count("\\|") == expected_columns


async def test_export_markdown_has_a_summary_table_and_responses(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client)
    text = (await client.get(f"/api/export/{benchmark_id}?format=markdown")).text

    assert text.startswith("# TCP handshake")
    assert "| Variant | Provider | Model |" in text
    assert "## Responses" in text
    assert "ESTIMATED" in text


async def test_export_markdown_accepts_the_md_alias(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client)
    assert (await client.get(f"/api/export/{benchmark_id}?format=md")).status_code == 200


async def test_export_html_is_self_contained(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client)
    text = (await client.get(f"/api/export/{benchmark_id}?format=html")).text

    assert text.startswith("<!doctype html>")
    assert "<style>" in text
    assert "http://" not in text.split("<style>")[0], "no external assets"
    assert "ESTIMATED" in text


async def test_export_escapes_html_in_model_output(client: AsyncClient, registry) -> None:
    registry.get("ollama").text = "<script>alert('xss')</script>"
    benchmark_id, _ = await seeded(client)
    text = (await client.get(f"/api/export/{benchmark_id}?format=html")).text
    assert "<script>alert" not in text
    assert "&lt;script&gt;" in text


async def test_export_filename_is_sanitised(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client, name='../../etc/passwd "; rm -rf /')
    response = await client.get(f"/api/export/{benchmark_id}?format=json")
    disposition = response.headers["content-disposition"]
    assert ".." not in disposition
    assert "/" not in disposition.split("filename=")[1]
    assert ";" not in disposition.split('filename="')[1].rstrip('"')


async def test_export_failed_results_are_included_with_their_error(
    client: AsyncClient, registry
) -> None:
    from app.core.errors import ErrorCode, ProviderError

    registry.get("openai").fail_with = ProviderError(
        "quota exceeded.", code=ErrorCode.RATE_LIMIT, provider="openai"
    )
    benchmark_id, _ = await seeded(client)
    payload = json.loads((await client.get(f"/api/export/{benchmark_id}?format=json")).text)

    failed = next(r for r in payload["results"] if r["provider"] == "openai")
    assert failed["status"] == "failed"
    assert failed["error_code"] == "rate_limit"
    assert "quota exceeded" in failed["error_message"]


async def test_export_specific_run(client: AsyncClient) -> None:
    benchmark_id, first_run = await seeded(client)
    await client.post(f"/api/benchmarks/{benchmark_id}/rerun?wait=true")

    payload = json.loads(
        (await client.get(f"/api/export/{benchmark_id}?format=json&run_id={first_run}")).text
    )
    assert payload["run"]["id"] == first_run


async def test_export_rejects_an_unsupported_format(client: AsyncClient) -> None:
    benchmark_id, _ = await seeded(client)
    response = await client.get(f"/api/export/{benchmark_id}?format=pdf")
    assert response.status_code == 400
    assert "Unsupported export format" in response.json()["error"]["message"]


async def test_export_of_a_benchmark_with_no_runs_is_404(client: AsyncClient) -> None:
    created = (await client.post("/api/benchmarks", json=benchmark_payload())).json()
    response = await client.get(f"/api/export/{created['id']}?format=json")
    assert response.status_code == 404
    assert "no runs" in response.json()["error"]["message"]


async def test_export_of_a_run_from_another_benchmark_is_404(client: AsyncClient) -> None:
    _first, run_id = await seeded(client)
    second, _ = await seeded(client, name="other")
    response = await client.get(f"/api/export/{second}?format=json&run_id={run_id}")
    assert response.status_code == 404


# ----------------------------------------------------------------------
# Evaluation endpoint
# ----------------------------------------------------------------------
async def test_evaluate_a_whole_run_with_the_heuristic(client: AsyncClient) -> None:
    _, run_id = await seeded(client, evaluation_enabled=False, evaluation_mode="disabled")

    response = await client.post("/api/evaluate", json={"run_id": run_id, "mode": "heuristic"})
    assert response.status_code == 200
    body = response.json()
    assert body["evaluated"] == 2
    assert body["failed"] == 0
    assert all(e["mode"] == "heuristic" for e in body["evaluations"])

    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert all(r["evaluation"] is not None for r in run["results"])


async def test_manual_scoring_of_one_result(client: AsyncClient) -> None:
    _, run_id = await seeded(client, evaluation_enabled=False, evaluation_mode="disabled")
    run = (await client.get(f"/api/runs/{run_id}")).json()
    result_id = run["results"][0]["id"]

    response = await client.post(
        "/api/evaluate",
        json={
            "model_result_id": result_id,
            "mode": "manual",
            "reviewer": "ada",
            "scores": {
                "relevance": 9,
                "correctness": 8,
                "conciseness": 6,
                "clarity": 9,
                "reasoning": "Accurate but a little long.",
            },
        },
    )
    assert response.status_code == 200
    evaluation = response.json()["evaluations"][0]
    assert evaluation["mode"] == "manual"
    assert evaluation["evaluator_model"] == "human:ada"
    assert evaluation["relevance"] == 9
    assert evaluation["overall"] > 0


async def test_re_evaluating_replaces_the_previous_score(client: AsyncClient) -> None:
    _, run_id = await seeded(client)
    run = (await client.get(f"/api/runs/{run_id}")).json()
    result_id = run["results"][0]["id"]

    await client.post(
        "/api/evaluate",
        json={
            "model_result_id": result_id,
            "mode": "manual",
            "scores": {"relevance": 1, "correctness": 1, "conciseness": 1, "clarity": 1},
        },
    )
    refreshed = (await client.get(f"/api/runs/{run_id}")).json()
    scored = next(r for r in refreshed["results"] if r["id"] == result_id)
    assert scored["evaluation"]["relevance"] == 1
    assert scored["evaluation"]["mode"] == "manual"


async def test_overwrite_false_keeps_the_existing_score(client: AsyncClient) -> None:
    _, run_id = await seeded(client)
    response = await client.post(
        "/api/evaluate", json={"run_id": run_id, "mode": "heuristic", "overwrite": False}
    )
    body = response.json()
    assert body["evaluated"] == 0
    assert all("already scored" in e for e in body["errors"])


async def test_evaluating_a_failed_result_is_reported_not_fatal(
    client: AsyncClient, registry
) -> None:
    from app.core.errors import ErrorCode, ProviderError

    registry.get("openai").fail_with = ProviderError(
        "down.", code=ErrorCode.PROVIDER_UNAVAILABLE, provider="openai"
    )
    _, run_id = await seeded(client, evaluation_enabled=False, evaluation_mode="disabled")

    body = (await client.post("/api/evaluate", json={"run_id": run_id, "mode": "heuristic"})).json()
    assert body["evaluated"] == 1
    assert body["failed"] == 1
    assert any("no successful response" in e for e in body["errors"])


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "heuristic"},  # neither target
        {"run_id": 1, "model_result_id": 1, "mode": "heuristic"},  # both targets
        {"run_id": 1, "mode": "disabled"},
        {"model_result_id": 1, "mode": "manual"},  # manual without scores
        {
            "model_result_id": 1,
            "mode": "manual",
            "scores": {"relevance": 50, "correctness": 1, "conciseness": 1, "clarity": 1},
        },
    ],
)
async def test_evaluate_rejects_invalid_requests(client: AsyncClient, payload: dict) -> None:
    assert (await client.post("/api/evaluate", json=payload)).status_code == 422


async def test_evaluate_unknown_result_is_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/evaluate", json={"model_result_id": 9999, "mode": "heuristic"}
    )
    assert response.status_code == 404


async def test_evaluation_modes_endpoint(client: AsyncClient) -> None:
    body = (await client.get("/api/evaluation/modes")).json()
    assert body["criteria"] == ["relevance", "correctness", "conciseness", "clarity"]
    assert {m["id"] for m in body["modes"]} == {"disabled", "heuristic", "llm_judge", "manual"}


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
async def test_settings_reports_presence_not_secrets(client: AsyncClient) -> None:
    body = (await client.get("/api/settings")).json()
    for provider in body["providers"]:
        assert isinstance(provider["credential_present"], bool)
        assert "api_key" not in {k for k in provider if k != "api_key_env"}
    assert body["pricing"]["estimated"] is True
    assert body["limits"]["max_prompt_chars"] > 0
    assert body["application"]["database_backend"] == "sqlite+aiosqlite"


async def test_pricing_can_be_reloaded_without_a_restart(client: AsyncClient) -> None:
    body = (await client.post("/api/settings/pricing/reload")).json()
    assert body["reloaded"] is True
    assert body["models_priced"] > 0


# ----------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------
async def test_404_has_the_standard_error_envelope(client: AsyncClient) -> None:
    body = (await client.get("/api/benchmarks/123456")).json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"


async def test_validation_errors_name_the_offending_field(client: AsyncClient) -> None:
    response = await client.post("/api/benchmarks", json=benchmark_payload(temperature=99))
    body = response.json()["error"]
    assert body["code"] == "invalid_request"
    assert "temperature" in body["message"]
    assert any(d["field"].endswith("temperature") for d in body["details"])


async def test_unknown_route_returns_json_not_html(client: AsyncClient) -> None:
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_root_endpoint_advertises_the_api(client: AsyncClient) -> None:
    body = (await client.get("/")).json()
    assert body["api"] == "/api"
    assert body["docs"] == "/docs"


async def test_openapi_schema_is_generated(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert "/api/benchmarks" in schema["paths"]
    assert "/api/export/{benchmark_id}" in schema["paths"]
