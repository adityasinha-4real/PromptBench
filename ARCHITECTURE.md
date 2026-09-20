# Architecture

This document explains how PromptBench is put together and **why** each
significant decision was made. Where a decision has a cost, the cost is stated.

---

## 1. Layering

```
frontend (Next.js)
      │  REST + Server-Sent Events
      ▼
api/          FastAPI routers — HTTP concerns only
      │
schemas/      Pydantic request/response contracts (the public API surface)
      │
services/     Benchmark engine, analytics, export, evaluation orchestration
      │
providers/    LLMProvider interface + one adapter per provider
evaluation/   Evaluator interface + one class per evaluation mode
      │
models/ db/   SQLAlchemy ORM and async session management
```

The rule that keeps this honest: **a layer may only depend downward.** Routers
never touch the ORM directly, services never build HTTP responses, and adapters
never know a benchmark exists.

### ORM models are never returned

Every endpoint returns a Pydantic schema. This costs a mapping step but means
the wire format is a deliberate contract rather than an accident of the table
layout — renaming a column does not silently break a client, and the ORM's
`metadata` column can be exposed under a clean name.

---

## 2. Provider adapter architecture

### The interface

```python
class LLMProvider(ABC):
    id: str
    label: str
    is_local: bool
    api_key_env: str | None

    def is_configured(self) -> bool: ...
    async def get_models(self) -> list[ModelInfo]: ...
    async def test_connection(self) -> ProviderStatus: ...
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
```

`GenerationResult` is identical for every provider. Nothing above
`providers/` branches on provider identity — the engine, the services, the API
and the UI all operate on the normalised shape.

**Adding a provider** is one new module plus one line in
`providers/registry.py`. The engine is untouched. This is the property the
architecture is built to protect.

### Why raw `httpx` instead of vendor SDKs

Four SDKs would mean four retry policies, four timeout models, four exception
hierarchies and four dependency trees to keep in step. The provider APIs used
here are small, stable, well-documented JSON endpoints.

Going direct buys:

- **one** timeout/retry/error-classification path, in `LLMProvider._post_json`;
- one connection-pooling strategy;
- a dependency list short enough to audit;
- tests that drive the real request-construction code through
  `httpx.MockTransport`, rather than mocking an SDK's surface.

The cost is real: new provider features (structured outputs, tool use, streaming
shapes) must be implemented by hand rather than inherited from an SDK. For a
benchmarking tool, whose need is a single non-streaming completion plus accurate
usage numbers, that cost is small and the uniformity is worth more.

### Derived metrics live in one place

`LLMProvider.build_result` computes latency, tokens/sec and cost for **every**
provider. An adapter's only job is to parse its provider's response and hand
over the text, the usage numbers and the finish reason. This is why throughput
is comparable across providers at all.

Tokens/sec is derived from the raw elapsed float, not the rounded millisecond
value — dividing by a rounded 0 ms would report 0 tokens/sec for a fast response.

### Token accounting is honest about its source

When a provider reports usage, it is used verbatim and tagged
`token_source="provider"`. When it does not, a `len/4` estimate is used and
tagged `token_source="estimated"`, which the UI surfaces in the technical panel.
Estimated counts feed cost estimates, so the provenance has to be visible.

### Curated model lists

Hosted providers' `/models` endpoints return hundreds of entries including
embeddings, moderation and retired snapshots — useless for a picker. Each hosted
adapter therefore ships a short curated list in `providers/catalog.py`. Adapters
**do not validate against it**: any model id can be typed in and will be sent.
The list is a convenience, not a gate.

Ollama is the exception — it lists live from `/api/tags`, because the available
set is whatever the user has pulled. Its results are cached for 15 seconds so
the model page and picker do not hammer the daemon.

---

## 3. Execution engine

`services/engine.py` owns the whole run lifecycle.

### Concurrency

A run expands into `models × prompt variants` tasks, gathered under an
`asyncio.Semaphore(MAX_CONCURRENCY)`. Independent models never wait for each
other. The bound exists because an unbounded gather would open as many sockets
as the cross-product, which a local Ollama daemon will not thank you for.

### Failure isolation

`asyncio.gather(..., return_exceptions=True)` plus a per-task try/except means a
failing provider produces a failed **row**, not a failed run. GPT succeeds,
Claude succeeds, Gemini times out, Ollama succeeds → the run completes and
Gemini's row carries its error code and message. A run is only marked `failed`
when *every* task failed.

Even a bug inside an adapter is contained: an unexpected exception is caught,
logged, and recorded as an `unknown` error against that one result.

### Retries

Only failures in `RETRYABLE_CODES` — timeout, rate limit, provider unavailable —
are retried, with exponential backoff plus jitter, at most `MAX_RETRIES` times.
Authentication failures and invalid requests are **never** retried; retrying a
missing API key just wastes the user's time. The attempt count is persisted so
the UI can say "retried 2 times before giving up".

### Cancellation

The naive approach — checking a flag between tasks — cannot stop a request
already in flight, which is exactly the case that matters when a model is
hanging. Instead each generation races against the run's cancel event:

```python
done, _ = await asyncio.wait({gen_task, cancel_task}, return_when=FIRST_COMPLETED)
if cancel_task in done:
    gen_task.cancel()
```

Cancelling a run therefore aborts open HTTP requests within milliseconds.
Results already stored are kept; unstarted tasks are recorded as cancelled.

### Database access from background tasks

Concurrent tasks must not share one `AsyncSession` — it is not thread- or
task-safe. Each task opens its own short-lived session via `session_scope()`
purely to write its own row. SQLite runs in WAL mode so these concurrent writes
do not block readers.

### Progress

An in-memory `RunTracker` holds live per-task state, the cancel event and a set
of subscriber queues. The SSE endpoint subscribes and yields snapshots; the
queues are bounded, and a stalled client has its oldest frame dropped rather
than being allowed to grow memory without limit.

Finished runs are retained in memory for five minutes so a client that connects
late still sees the terminal event, then evicted. The durable record is the
database — `/runs/{id}/progress` reconstructs a snapshot from stored rows once a
run has left memory, which is why the UI works after a page refresh or a
backend restart.

---

## 4. Evaluation architecture

```python
class Evaluator(ABC):
    mode: str
    evaluator_model: str | None
    async def evaluate(self, *, prompt, response, system_prompt=None, context=None)
        -> EvaluationScores: ...
```

The engine depends on this interface only; `evaluation/factory.py` decides which
implementation a run gets. Adding a scorer means adding a class and a branch in
the factory.

### The heuristic evaluator exists for a specific reason

LLM-as-a-judge requires a configured provider. If that were the only automatic
mode, PromptBench's headline claim — that it works with no credentials — would
be false the moment you enabled evaluation. The heuristic evaluator is
deterministic, offline, and documented precisely (including that its
`correctness` is a completeness **proxy**, not a fact check) so it is not
mistaken for something it is not.

Determinism has a second benefit: identical input scores identically, so the
mode is usable for regression comparison across runs.

### Malformed evaluator output cannot break a benchmark

Judges emit code fences, prose preambles, nested objects and `"8/10"` strings.
`evaluation/base.py` handles all of those: strip fences, scan for the first
balanced `{...}` span (string-aware, so braces inside strings do not confuse
it), unwrap a `scores`/`evaluation`/`result` wrapper, coerce numeric strings,
clamp to 0–10, then validate with Pydantic.

If it still cannot parse, an `EvaluationError` is raised — and the engine
catches it, keeps the generation, and records `evaluation_error` in the result's
metadata. **A bad judge costs you a score, never a response.**

Manual scores go through the same `EvaluationScores` validation, so human and
automatic scores are stored identically.

---

## 5. Pricing

Cost is computed in exactly one function, `core/pricing.estimate_cost`. No other
module multiplies tokens by a rate.

The table is data (`core/pricing.json`), not code, so it can be overridden with
`PRICING_FILE` and reloaded at runtime without a restart.

The design decision that matters: **an unknown model returns `None`, not `0`.**
`None` propagates all the way to the UI as "Pricing unavailable", is excluded
from cost aggregates, and sorts last on the cost leaderboard. Defaulting to zero
would silently claim that an unpriced model is free — the single most damaging
thing a cost tool can do.

Ollama is priced at `0` through a `"*"` wildcard because local execution
genuinely incurs no API charge. That is a fact, not a fallback.

Analytics means are rounded to 10 decimal places rather than a display
precision. Rounding to 4 dp collapsed any per-request cost below `1e-4` to
`0.0`, making paid models look free on the leaderboard — a bug caught in
end-to-end testing and now covered by a regression test. **Formatting is the
UI's job, not the aggregator's.**

---

## 6. Data model

```
benchmarks ──1:N──► prompt_variants
     └─────1:N──► benchmark_runs ──1:N──► model_results ──1:1──► evaluations
```

Two decisions worth calling out:

**Runs snapshot their parameters.** `benchmark_runs.params_snapshot` records the
temperature, max tokens, evaluation mode and model list actually used. Without
it, editing a benchmark would retroactively falsify its history. For the same
reason the `PATCH` endpoint only accepts name, description and tags — prompt and
model configuration are immutable once results exist.

**Every benchmark has at least one conceptual variant.** Benchmarks without
explicit variants run the base prompt once under the name `"Default"`, so the
model × variant matrix is the single code path rather than a special case.

### Why no migration tool

The schema is created from declarative metadata at startup. For a single-user
local tool with no existing installed base, a migration runner is ceremony. The
upgrade path is explicit: add Alembic, generate an initial revision matching the
current metadata, and switch `init_db` to `alembic upgrade head`. This is listed
in the README's future improvements rather than pretended away.

### SQLite now, Postgres by configuration

`UTCDateTime` normalises timezones on write and re-attaches UTC on read, because
SQLite discards `tzinfo`. On Postgres it behaves as `TIMESTAMPTZ`. JSON columns
use SQLAlchemy's portable `JSON` type. No query uses a SQLite-specific feature,
so `DATABASE_URL=postgresql+asyncpg://…` is the only change required.

The one place this shows is history filtering by tag or provider, which does a
`LIKE` against the serialised JSON rather than using a JSON operator. That is
portable and fine at this scale; on Postgres at scale it would become a `jsonb`
containment query.

### Analytics aggregates in Python

Filters are pushed into SQL; the reduction happens in Python. For a local tool
the row counts are thousands, not millions, and keeping the arithmetic in one
readable place beats four dialect-specific aggregate queries. If this ever needs
to scale, only the reduction step moves.

---

## 7. Error architecture

A single `ErrorCode` enum spans the whole system: `timeout`, `rate_limit`,
`authentication`, `provider_unavailable`, `invalid_request`, `content_filter`,
`cancelled`, `not_found`, `conflict`, `unknown`.

`classify_http_status` maps upstream statuses onto it, so a 429 from any
provider becomes the same `rate_limit` — which is what lets the engine decide
retryability without knowing which provider it is talking to.

Every error reaches the client in one envelope with a `code`, a human `message`
and, where useful, a `hint`. Provider errors render as
`"Gemini request failed: API key is missing."` rather than `HTTP 401`. The
frontend's `ApiError` carries `code`, `hint` and `retryable`, which is how error
states can offer a retry button only when retrying could help.

In production, unhandled exceptions return an opaque message plus an incident id
that correlates with the full server-side log. Outside production the redacted
detail is included, because debugging matters more than opacity on a laptop.

---

## 8. Frontend

**Client components throughout.** Every page is interactive and reads from a
separate API origin; server components would add a proxy hop for no benefit and
break the SSE progress stream's directness.

**A hand-written API client, not a data-fetching library.** `lib/api.ts` is the
only module that knows about HTTP. It unwraps the error envelope into `ApiError`
so no component ever handles a raw `Response`. `useAsync` and `useAction` supply
loading/error/reload state; the surface a component sees is
`{ data, error, loading, reload }`.

**SSE with a polling fallback.** `useRunProgress` prefers `EventSource` and
falls back to polling `/progress` when it is unavailable or the stream drops
mid-run. The stream closing at the end of a run is normal and does not trigger
the fallback.

**Charts follow explicit rules**, enforced in `lib/chart-theme.ts` and
`components/charts/chart-kit.tsx`:

- Categorical colours are assigned in fixed order and never cycled, so a model
  keeps its colour across charts and filter changes.
- **No chart has two y-axes.** Measures of different scale get separate charts.
- Multi-series charts are only used where the series share a scale (the four
  0–10 evaluation criteria).
- Rows with `null` are dropped, never plotted as zero; the count of omissions is
  stated in the footnote. Models that never succeeded are excluded entirely — a
  zero-height bar reads as "free and instant", not "never ran".
- The palette was validated against the actual dark chart surface for lightness
  band, chroma floor, colour-vision-deficiency separation and contrast.

**Status is never colour alone.** Badges carry a glyph, and the best value in a
comparison row is marked with `★` plus a label, not just weight and hue.

---

## 9. Security posture

| Concern | Approach |
|---|---|
| Credential exposure | Keys live in backend env vars only. No endpoint returns one; `/api/settings` reports a boolean. Tests assert a sentinel key never appears in any response. |
| Log leakage | A `RedactingFilter` on every handler, including uvicorn's, scrubs key-shaped strings. |
| Key in URLs | Gemini's key goes in `x-goog-api-key`, not a query parameter. |
| Input validation | Pydantic bounds prompt size, system prompt size, output tokens, model count, variant count, tags, temperature. |
| SSRF | Provider base URLs come from the environment, never from request bodies. |
| Export filenames | Sanitised to `[A-Za-z0-9._-]`, length-capped, timestamped. |
| Stack traces | Suppressed in production behind an incident id. |
| CORS | Explicit origin allow-list from the environment. |

**Not implemented: authentication.** PromptBench is a local-first single-user
tool. Deploying it to a shared network requires an authenticating proxy in
front. Saying so plainly is better than shipping a token check that implies more
safety than it provides.
