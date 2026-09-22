# PromptBench API reference

Base URL: `http://localhost:8000` · All endpoints are prefixed with `/api`.

An interactive OpenAPI UI is served at `/docs` (and ReDoc at `/redoc`) whenever
the backend is running; the machine-readable schema is at `/openapi.json`.

There is **no authentication** — PromptBench is designed to run locally. See the
security section of the README before exposing it to a network.

---

## Conventions

### Error envelope

Every non-2xx response uses one shape:

```json
{
  "error": {
    "code": "authentication",
    "message": "Gemini request failed: API key is missing.",
    "hint": "Check that the provider's API key environment variable is set and valid.",
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "retryable": false,
    "upstream_status": 401
  }
}
```

`provider`, `model`, `retryable` and `upstream_status` appear only on provider
failures. Validation failures add a `details` array of `{field, message}`.

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `timeout` | 504 | The provider did not respond in time. |
| `rate_limit` | 429 | The provider is throttling this key. |
| `authentication` | 401 | Missing or rejected credential. |
| `provider_unavailable` | 503 | Could not reach the provider. |
| `invalid_request` | 400 | Rejected request — often an unknown model id. |
| `content_filter` | 422 | Blocked by the provider's safety policy. |
| `cancelled` | 499 | The run was cancelled before this model finished. |
| `not_found` | 404 | No such benchmark, run or result. |
| `conflict` | 409 | Action conflicts with an in-flight run. |
| `unknown` | 500 | Unclassified failure. |

`timeout`, `rate_limit` and `provider_unavailable` are the retryable set.

### Status codes

`200` OK · `201` created · `202` run accepted · `204` deleted ·
`400/404/409/422` client errors · `429/500/503/504` as above.

---

## Health

### `GET /api/health`

Liveness, database reachability and provider **configuration** (not connectivity
— it makes no outbound calls, so it stays fast and works offline).

```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "development",
  "database": "ok",
  "providers": { "ollama": true, "openai": true, "anthropic": false, "gemini": false },
  "details": {
    "local_providers": ["ollama"],
    "any_provider_configured": true,
    "pricing": { "as_of": "2025-06-01", "estimated": true, "...": "..." },
    "limits": { "max_prompt_chars": 32000, "max_concurrency": 8, "...": "..." }
  }
}
```

---

## Providers and models

### `GET /api/models`

| Query | Default | Purpose |
|---|---|---|
| `probe` | `true` | Check reachability. `false` returns configuration only (fast). |

```json
{
  "providers": [
    {
      "id": "ollama",
      "label": "Ollama (local)",
      "is_local": true,
      "configured": true,
      "available": true,
      "status_detail": "Ollama is running with 2 local model(s).",
      "api_key_env": null,
      "error_code": null,
      "latency_ms": 4,
      "models": [
        {
          "provider": "ollama",
          "id": "llama3.2:latest",
          "label": "Llama3.2",
          "context_window": null,
          "description": "3.2B · Q4_K_M · 2.02 GB",
          "local": true,
          "pricing": { "input_per_1m": 0.0, "output_per_1m": 0.0, "note": "Runs locally - no API billing." },
          "available": true
        }
      ]
    }
  ],
  "models": ["… flattened list of every model …"],
  "pricing": { "as_of": "2025-06-01", "currency": "USD", "estimated": true, "disclaimer": "…" }
}
```

`pricing: null` on a model means **no configured price** — render "Pricing
unavailable", never `$0.00`.

`api_key_env` names the environment variable to set. The **value** is never
returned by this or any other endpoint.

### `POST /api/models/test`

```json
{ "provider": "openai", "model": "gpt-4o-mini" }
```

Omit `model` to check credentials and reachability only. Supply it to also run a
5-token probe generation, proving that specific model id works.

Always returns `200` — an unavailable provider is a valid answer, not a server
error.

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "available": true,
  "detail": "OpenAI responded with 'gpt-4o-mini' in 412 ms.",
  "error_code": null,
  "latency_ms": 412,
  "model_count": 2,
  "generation_ok": true
}
```

---

## Benchmarks

### `POST /api/benchmarks` → `201`

```json
{
  "name": "TCP handshake explanation",
  "description": "Optional.",
  "prompt": "Explain why TCP uses a three-way handshake.",
  "system_prompt": "Be concise.",
  "temperature": 0.2,
  "max_tokens": 512,
  "top_p": null,
  "evaluation_enabled": true,
  "evaluation_mode": "heuristic",
  "judge_provider": null,
  "judge_model": null,
  "models": [
    { "provider": "ollama", "model": "llama3.2" },
    { "provider": "openai", "model": "gpt-4o-mini" }
  ],
  "variants": [
    { "name": "Plain",   "prompt": "Explain TCP." },
    { "name": "Analogy", "prompt": "Explain TCP to a beginner using an analogy." }
  ],
  "tags": ["networking"],
  "run_immediately": false
}
```

| Field | Rules |
|---|---|
| `name` | 1–200 chars, whitespace collapsed. |
| `prompt` | Non-blank, ≤ `MAX_PROMPT_CHARS` (32,000). |
| `system_prompt` | ≤ `MAX_SYSTEM_PROMPT_CHARS` (8,000). |
| `temperature` | 0.0–2.0. |
| `max_tokens` | 1 – `MAX_OUTPUT_TOKENS_LIMIT` (8,192). |
| `models` | 1 – `MAX_MODELS_PER_BENCHMARK` (12), no duplicates. |
| `variants` | 0 – `MAX_VARIANTS_PER_BENCHMARK` (10), unique names. |
| `evaluation_mode` | `disabled` \| `heuristic` \| `llm_judge` \| `manual`. `llm_judge` requires a judge provider+model, here or via env. |
| `tags` | ≤ 20, lower-cased, de-duplicated. |

Returns the full benchmark including generated variant ids.

### `GET /api/benchmarks`

| Query | Default | Purpose |
|---|---|---|
| `search` | — | Substring of name, prompt or description. |
| `tag` | — | Exact tag. |
| `provider` / `model` | — | Benchmarks targeting that provider/model. |
| `status` | — | Has a run with this status. |
| `date_from` / `date_to` | — | ISO-8601 bounds on creation. |
| `sort` | `created_at` | `created_at` \| `updated_at` \| `name`. |
| `order` | `desc` | `asc` \| `desc`. |
| `limit` / `offset` | `25` / `0` | Pagination (limit ≤ 100). |

```json
{
  "items": [
    {
      "id": 1,
      "name": "TCP handshake explanation",
      "prompt_excerpt": "Explain why TCP uses a three-way handshake.",
      "tags": ["networking"],
      "model_count": 2,
      "variant_count": 0,
      "run_count": 3,
      "evaluation_mode": "heuristic",
      "created_at": "2026-01-01T10:00:00Z",
      "last_run_at": "2026-01-02T09:00:00Z",
      "last_run_status": "completed",
      "avg_quality": 8.4,
      "total_cost": 0.000046
    }
  ],
  "total": 1, "limit": 25, "offset": 0
}
```

### `GET /api/benchmarks/{id}`

The benchmark, its variants, a summary of every run, and the full `latest_run`
with results.

### `PATCH /api/benchmarks/{id}`

Accepts `name`, `description`, `tags` only. Prompt and model configuration are
immutable once results exist, so stored runs remain a truthful record.

### `DELETE /api/benchmarks/{id}` → `204`

Cascades to runs, results and evaluations. Returns `409` if a run is in flight;
cancel it first.

---

## Execution

### `POST /api/benchmarks/{id}/run` → `202`

Optional per-run overrides, applied **without** modifying the benchmark:

```json
{
  "models": [{ "provider": "ollama", "model": "llama3.2" }],
  "temperature": 0.9,
  "max_tokens": 256,
  "evaluation_mode": "disabled",
  "variant_ids": [3]
}
```

| Query | Default | Purpose |
|---|---|---|
| `wait` | `false` | Block until the run finishes. Useful for scripts and CI. |

Returns the initial progress snapshot; models execute concurrently.

### `POST /api/benchmarks/{id}/rerun` → `202`

Re-runs with the saved configuration, producing a new run to compare against.

### `GET /api/runs/{id}`

The run with every result:

```json
{
  "id": 1,
  "benchmark_id": 1,
  "status": "completed",
  "started_at": "2026-01-01T10:00:00Z",
  "completed_at": "2026-01-01T10:00:03Z",
  "duration_ms": 2541,
  "error_message": "1 of 3 model calls failed.",
  "params_snapshot": { "temperature": 0.2, "max_tokens": 300, "...": "..." },
  "results": [
    {
      "id": 1,
      "variant_id": null,
      "variant_name": "Default",
      "provider": "openai",
      "model": "gpt-4o-mini",
      "status": "success",
      "response": "TCP uses a three-way handshake because …",
      "input_tokens": 23,
      "output_tokens": 71,
      "total_tokens": 94,
      "latency_ms": 138,
      "tokens_per_second": 513.79,
      "estimated_cost": 0.00004605,
      "cost_per_1k_tokens": 0.00048989,
      "finish_reason": "stop",
      "token_source": "provider",
      "error_code": null,
      "error_message": null,
      "attempts": 1,
      "request_params": { "temperature": 0.2, "max_tokens": 300, "top_p": null },
      "metadata": { "request_id": "req_…", "usage": { "...": "..." } },
      "evaluation": {
        "id": 1, "relevance": 10.0, "correctness": 7.5, "conciseness": 8.87,
        "clarity": 9.0, "overall": 8.83, "reasoning": "…",
        "mode": "heuristic", "evaluator_model": "builtin:heuristic-v1",
        "created_at": "2026-01-01T10:00:03Z"
      },
      "created_at": "2026-01-01T10:00:00Z"
    }
  ]
}
```

`estimated_cost: null` means **pricing unavailable**, not free.
`token_source: "estimated"` means the provider reported no usage and the counts
were derived.

### `GET /api/runs/{id}/progress`

Live snapshot while running; reconstructed from the database afterwards, so it
works after a refresh or a backend restart.

```json
{
  "run_id": 1, "benchmark_id": 1, "status": "running",
  "total": 3, "completed": 1, "succeeded": 1, "failed": 0,
  "tasks": [
    { "key": "Default::ollama:llama3.2", "provider": "ollama", "model": "llama3.2",
      "variant_name": "Default", "status": "success", "latency_ms": 820,
      "attempts": 1, "error_code": null, "error_message": null, "result_id": 1 }
  ],
  "started_at": "2026-01-01T10:00:00Z", "completed_at": null
}
```

Task statuses: `queued` → `running` → `success` | `failed` | `cancelled`.

### `GET /api/runs/{id}/stream`

`text/event-stream`. Emits a `progress` event on every state change, a
`: heartbeat` comment every 15 s, and a final `done` event.

```javascript
const source = new EventSource(`${API}/api/runs/${runId}/stream`);
source.addEventListener('progress', (e) => update(JSON.parse(e.data)));
source.addEventListener('done', (e) => { finish(JSON.parse(e.data)); source.close(); });
```

Clients that cannot use SSE should poll `/progress` instead.

### `POST /api/runs/{id}/cancel`

Aborts in-flight provider requests. Results already stored are kept.

```json
{ "run_id": 1, "cancelled": true, "detail": "Cancellation signalled." }
```

Returns `cancelled: false` with an explanation if the run has already finished.

### `GET /api/runs/{id}/matrix`

```json
{
  "variants": ["Plain", "Analogy"],
  "targets": ["ollama:llama3.2", "openai:gpt-4o-mini"],
  "cells": { "Plain": { "ollama:llama3.2": 1, "openai:gpt-4o-mini": 2 } }
}
```

Cell values are `model_result` ids.

### `GET /api/benchmarks/{id}/compare`

Movement between two runs of the same benchmark, matched on
provider + model + prompt variant.

| Parameter | Default |
|---|---|
| `base_run_id` | the second-newest run |
| `target_run_id` | the newest run |

```json
{
  "benchmark_id": 1,
  "base": { "id": 10, "status": "completed", "evaluation_modes": ["heuristic"] },
  "target": { "id": 11, "status": "completed", "evaluation_modes": ["heuristic"] },
  "entries": [
    {
      "key": "Default::ollama:llama3.2",
      "provider": "ollama",
      "model": "llama3.2",
      "variant_name": "Default",
      "base_status": "success",
      "target_status": "success",
      "quality": {
        "base": 6.0,
        "target": 8.0,
        "delta": 2.0,
        "percent_change": 33.33,
        "direction": "better"
      },
      "latency_ms": { "base": 1000, "target": 1500, "delta": 500, "direction": "worse" },
      "change": "mixed",
      "note": null
    }
  ],
  "summary": { "improved": 0, "regressed": 0, "mixed": 1, "new_failures": 0 },
  "quality_comparable": true,
  "notes": []
}
```

- The ids are normalised to oldest-first, so `delta` always reads as what the
  re-run changed, whichever order you pass them in.
- `direction` is per metric — higher quality is better, lower latency, cost and
  token counts are better. There is no composite score.
- A missing value gives `"direction": "unknown"` with a `null` delta, and is
  excluded from the summary averages. It is never counted as zero.
- Metrics come only from successful results: a failure's latency is time spent
  failing, not a faster answer.
- `quality_comparable` is `false` when the two runs were scored in different
  evaluation modes; quality deltas are then withheld and the reason is in
  `notes`.
- `400 invalid_request` when the benchmark has fewer than two runs, the two ids
  are the same, or a run belongs to another benchmark.

### Other run endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/benchmarks/{id}/runs` | Run summaries for a benchmark. |
| `DELETE /api/runs/{id}` → `204` | Delete a run and its results. |
| `DELETE /api/results/{id}` → `204` | Remove one result from a comparison. |

---

## Evaluation

### `POST /api/evaluate`

Score one stored result or every result in a run. Supply **exactly one** of
`model_result_id` or `run_id`.

```json
{ "run_id": 1, "mode": "heuristic", "overwrite": true }
```

Manual scoring targets a single result:

```json
{
  "model_result_id": 1,
  "mode": "manual",
  "reviewer": "ada",
  "scores": {
    "relevance": 9, "correctness": 8, "conciseness": 6, "clarity": 9,
    "reasoning": "Accurate but buries the answer."
  }
}
```

LLM-judge mode may override the judge per call with `judge_provider` and
`judge_model`.

```json
{
  "evaluated": 2,
  "failed": 1,
  "evaluations": [{ "id": 1, "relevance": 8.0, "...": "..." }],
  "errors": ["gemini:gemini-2.5-flash (Default): skipped — no successful response to score."]
}
```

Per-result failures are reported in `errors` rather than failing the request, so
one unparseable judge verdict never discards the rest of the scores.

### `GET /api/evaluation/modes`

Available modes with their descriptions and whether they need credentials, plus
the criteria list.

---

## Analytics

### `GET /api/analytics`

Filters: `date_from`, `date_to`, `provider`, `model`, `benchmark_id`. An
unparseable date is ignored rather than rejected.

```json
{
  "totals": {
    "total_benchmarks": 2, "total_runs": 2, "total_executions": 5,
    "successful_executions": 4, "failed_executions": 1,
    "total_tokens": 188, "total_input_tokens": 46, "total_output_tokens": 142,
    "avg_latency_ms": 140.5, "avg_cost": 0.000023025,
    "total_cost": 0.00004605, "avg_quality": 8.83,
    "unpriced_executions": 0
  },
  "by_model": [
    {
      "provider": "openai", "model": "gpt-4o-mini",
      "executions": 1, "successes": 1, "failures": 0, "success_rate": 1.0,
      "avg_latency_ms": 138.0, "p95_latency_ms": 138.0,
      "avg_tokens_per_second": 513.79,
      "avg_input_tokens": 23.0, "avg_output_tokens": 71.0, "total_tokens": 94,
      "avg_cost": 0.00004605, "total_cost": 0.00004605,
      "cost_per_1k_tokens": 0.00048989,
      "avg_quality": 8.83, "avg_relevance": 10.0, "avg_correctness": 7.5,
      "avg_conciseness": 8.87, "avg_clarity": 9.0,
      "priced": true
    }
  ],
  "by_provider": [{ "provider": "openai", "executions": 1, "...": "..." }],
  "timeline": [{ "date": "2026-01-01", "runs": 1, "executions": 3, "...": "..." }],
  "errors": [{ "code": "provider_unavailable", "count": 1 }],
  "filters_applied": { "provider": null, "...": "..." },
  "generated_at": "2026-01-01T10:05:00Z"
}
```

`priced: false` means the model has no configured price; it is excluded from
cost aggregates rather than counted as free, and `unpriced_executions` says how
many.

### `GET /api/leaderboard`

| Query | Default | Purpose |
|---|---|---|
| `metric` | `quality` | See below. Unknown values fall back to `quality`. |
| `min_executions` | `1` | Exclude models with too little data. |
| `date_from`, `date_to`, `provider`, `benchmark_id` | — | Same filters as analytics. |

| Metric | Direction | Meaning |
|---|---|---|
| `quality` | higher | Mean overall evaluation score. |
| `latency` | lower | Mean wall-clock latency. |
| `cost` | lower | Mean estimated cost per execution. |
| `cost_per_1k` | lower | Blended cost per 1,000 tokens. |
| `throughput` | higher | Mean output tokens per second. |
| `success_rate` | higher | Share of executions without an error. |
| `token_efficiency` | lower | Mean output tokens — read alongside quality, never alone. |

The response carries a `methodology` string explaining the metric and stating
that PromptBench deliberately computes no composite "best model" score. Models
with no data for the chosen metric always rank last.

`GET /api/leaderboard/metrics` lists the metrics and the methodology.

### `GET /api/dashboard`

Compact figures for the landing page: totals, top models by volume, evaluation
count, recent benchmark ids.

---

## Export

### `GET /api/export/{benchmark_id}`

| Query | Default | Purpose |
|---|---|---|
| `format` | `json` | `json` \| `csv` \| `markdown` (or `md`) \| `html`. |
| `run_id` | latest | Export a specific run. |
| `download` | `true` | Send `Content-Disposition: attachment`. |

Every format carries prompt, system prompt, variant, provider, model, status,
response, error code/message, latency, token counts, throughput, estimated cost,
cost per 1K, finish reason, generation parameters, all five evaluation scores,
evaluator mode and model, and timestamps.

- **json** — plus pricing provenance and run metadata.
- **csv** — one row per result, flat.
- **markdown** — summary table plus full responses.
- **html** — self-contained dark-themed report, no external assets, HTML-escaped.

Filenames are sanitised: `promptbench-{id}-{slug}-{timestamp}.{ext}`.

`GET /api/export/{id}/formats` lists the supported formats.

---

## Settings

### `GET /api/settings`

Effective configuration: application settings, providers (with
`credential_present` as a **boolean** — never the value), evaluation modes,
the full pricing table with provenance, and all limits.

### `POST /api/settings/pricing/reload`

Reloads `pricing.json` from disk without restarting.

```json
{ "reloaded": true, "as_of": "2025-06-01", "models_priced": 18 }
```

---

## Example: a complete benchmark from the shell

```bash
API=http://localhost:8000/api

# 1. What can I actually run?
curl -s $API/models | jq '.providers[] | {id, available, models: (.models | length)}'

# 2. Create a benchmark
ID=$(curl -s -X POST $API/benchmarks -H 'Content-Type: application/json' -d '{
  "name": "TCP handshake",
  "prompt": "Explain why TCP uses a three-way handshake.",
  "temperature": 0.2, "max_tokens": 300,
  "evaluation_enabled": true, "evaluation_mode": "heuristic",
  "models": [{"provider":"ollama","model":"llama3.2"}]
}' | jq -r .id)

# 3. Run it and wait
curl -s -X POST "$API/benchmarks/$ID/run?wait=true" -H 'Content-Type: application/json' -d '{}' \
  | jq '{status, succeeded, failed}'

# 4. Read the results
curl -s "$API/benchmarks/$ID" \
  | jq '.latest_run.results[] | {model, latency_ms, total_tokens, estimated_cost, quality: .evaluation.overall}'

# 5. Export a report
curl -s "$API/export/$ID?format=markdown" -o report.md
```
