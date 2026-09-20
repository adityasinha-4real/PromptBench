# Contributing to PromptBench

Thanks for helping out. This document covers the local setup, the quality bar
a change has to clear, and step-by-step recipes for the two extensions the
architecture is explicitly designed for: adding a provider and adding an
evaluator.

Please read [ARCHITECTURE.md](ARCHITECTURE.md) first — it explains why the code
is shaped the way it is, which makes most review comments unnecessary.

---

## Setup

```bash
git clone <your-fork> promptbench && cd promptbench
cp .env.example .env          # nothing is required; the app runs with none set

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Install Ollama and `ollama pull llama3.2` if you want to develop against a real
model without spending anything.

---

## Quality bar

A change is ready when all of this passes:

```bash
# Backend
cd backend
pytest -q
ruff check .
ruff format --check .

# Frontend
cd frontend
npm test
npm run lint
npm run typecheck
npm run build
```

Do not open a pull request with any of these failing. If a test is wrong, fix
the test and say why in the commit message.

> `mypy` is configured in `pyproject.toml` and is the intended type checker for
> the backend. It could not be executed in the environment this project was
> built in (a Windows Application Control policy blocks it from loading a DLL),
> so the backend's type annotations are currently enforced by review and by
> Ruff rather than by a checker run. If it runs on your machine, please run
> `mypy app` and fix what it finds.

### House style

**Backend.** Ruff with a 100-character line length; `ruff format` is
authoritative. Type-annotate public functions. Docstrings explain *why*, not
*what* — the code already says what.

**Frontend.** Prettier is authoritative (single quotes, 100 columns).
TypeScript `strict`; `any` is an error. Components are function components with
named exports; `cn()` combines class names.

**Both.** Comments earn their place by explaining a non-obvious decision. Delete
commented-out code rather than shipping it.

### Testing expectations

| Change | Expected tests |
|---|---|
| New provider | Success normalisation, auth failure, a classified HTTP error, and token/cost handling, all via `httpx.MockTransport`. |
| Engine behaviour | Its concurrency, isolation, retry or cancellation property. |
| New endpoint | Happy path, a validation failure, and a not-found. |
| New evaluator | Valid output, malformed output, and empty input. |
| UI component | Rendering, the interaction, and the error state. |

Assert on **behaviour**, not implementation. Test names should read as
sentences: `test_one_provider_failure_does_not_fail_the_run`.

### Commit messages

Conventional-commit prefixes: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`,
`chore:`. Subject in the imperative, under ~72 characters. The body explains why
the change is needed and any trade-off taken.

---

## Adding a provider

The whole point of the adapter layer is that this touches two files.

### 1. Write the adapter

`backend/app/providers/cohere_provider.py`:

```python
"""Cohere adapter."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ErrorCode
from app.providers.base import (
    GenerationRequest, GenerationResult, LLMProvider, ModelInfo, ProviderStatus,
)


class CohereProvider(LLMProvider):
    id = "cohere"
    label = "Cohere"
    api_key_env = "COHERE_API_KEY"

    def is_configured(self) -> bool:
        return bool(settings.cohere_api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.cohere_api_key}",
            "Content-Type": "application/json",
        }

    async def get_models(self) -> list[ModelInfo]:
        return [ModelInfo(self.id, "command-r-plus", "Command R+", 128_000)]

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(self.id, False, self.unavailable_reason(),
                                  ErrorCode.AUTHENTICATION)
        started = time.perf_counter()
        try:
            response = await self.client.get(
                f"{settings.cohere_base_url}/models", headers=self._headers(),
                timeout=self._timeout(settings.connect_timeout_seconds * 2),
            )
        except httpx.HTTPError as exc:
            return ProviderStatus(self.id, False,
                                  f"Could not reach Cohere: {exc.__class__.__name__}",
                                  ErrorCode.PROVIDER_UNAVAILABLE)
        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            err = self._http_error(response, model=None)
            return ProviderStatus(self.id, False, err.message, err.code, latency)
        return ProviderStatus(self.id, True, "Authenticated.", None, latency)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.ensure_configured(request.model)

        payload: dict[str, Any] = {
            "model": request.model,
            "message": request.prompt,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.system_prompt:
            payload["preamble"] = request.system_prompt

        started = time.perf_counter()
        data, response = await self._post_json(
            f"{settings.cohere_base_url}/chat",
            json=payload, headers=self._headers(),
            model=request.model, timeout=request.timeout,
        )

        usage = (data.get("meta") or {}).get("tokens") or {}
        return self.build_result(
            request=request,
            text=data.get("text") or "",
            started=started,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            finish_reason=data.get("finish_reason"),
            metadata={"response_id": data.get("generation_id"), "usage": usage},
        )
```

Rules the adapter must follow:

- **Use `self._post_json`.** It applies the shared timeout, classifies every
  transport and HTTP failure into a `ProviderError`, and redacts credentials
  from messages. Do not hand-roll error handling.
- **Use `self.build_result`.** Latency, tokens/sec and cost are computed there
  for every provider, which is what makes them comparable.
- **Pass `None` for unknown token counts.** `build_result` will estimate and
  mark `token_source="estimated"`. Never guess in the adapter.
- **Never log or interpolate the key** into a message, URL or metadata field.

### 2. Register it

In `backend/app/providers/registry.py`:

```python
_PROVIDER_CLASSES = (OllamaProvider, OpenAIProvider, AnthropicProvider,
                     GeminiProvider, CohereProvider)
```

### 3. Wire up configuration

- `backend/app/core/config.py` — add `cohere_api_key: str | None = None` and
  `cohere_base_url: str = "https://api.cohere.com/v2"`.
- `backend/app/api/routes/settings.py` — add the base URL to `_base_url_for`.
- `.env.example` and the README's environment table — document `COHERE_API_KEY`.

### 4. Pricing

Add an entry to `backend/app/core/pricing.json` under `providers.cohere`, in USD
per 1M tokens, and update `sources` with the pricing page you took it from. If
you do not add one, the model correctly reports "Pricing unavailable" — that is
a valid state, not a bug. **Never invent a price.**

### 5. Test it

`backend/tests/test_providers.py` already has the pattern. At minimum cover:
successful normalisation, a missing key (auth error, and assert no HTTP call was
made), a classified upstream error, and the request body you actually send.

That is the whole change. You should not need to touch the engine, the services,
the API or the frontend — the provider will appear in the picker, the models
page and analytics automatically. **If you find yourself editing the engine to
add a provider, something is wrong; raise it in the PR.**

---

## Adding an evaluator

1. Subclass `Evaluator` in `backend/app/evaluation/`, set `mode` and
   `evaluator_model`, and implement `async def evaluate(...) -> EvaluationScores`.
2. Return validated `EvaluationScores`, or raise `EvaluationError`. Never raise
   anything else — the engine treats an unexpected exception as an adapter bug.
3. Add the mode to `EvaluationMode` in `models/benchmark.py`, to
   `build_evaluator` and `available_modes` in `evaluation/factory.py`.
4. Add it to the `EvaluationMode` union in `frontend/types/index.ts`.
5. Test valid output, malformed output and empty input.

If your evaluator calls a model, go through the `LLMProvider` interface as
`LLMJudgeEvaluator` does, so it works with any configured provider — including a
local Ollama model, which keeps it free.

---

## Adding a frontend page

1. `frontend/app/<route>/page.tsx`, marked `'use client'`.
2. Add it to `NAV` in `components/layout/sidebar.tsx`.
3. Fetch with `useAsync` / `useAction` — never call `fetch` directly; the API
   client is what turns backend errors into readable messages.
4. Handle all four states: loading (`LoadingPanel`), error (`ErrorState` with a
   retry where retrying could help), empty (`EmptyState`), and populated.
5. Charts go through `components/charts/chart-kit.tsx` so they inherit the
   validated palette and the chart rules — no dual axes, nulls dropped rather
   than plotted as zero, fixed categorical colour order.

---

## Things to be careful about

**Never default a missing price to zero.** `estimate_cost` returns `None` for an
unknown model and that `None` must reach the UI as "Pricing unavailable". A cost
tool that quietly claims something is free is worse than one that says it does
not know.

**Never round money in an aggregate.** Per-request costs are routinely below
`1e-4`; rounding to a display precision in the service layer collapses them to
zero. Formatting belongs in the UI.

**Never let an evaluator failure discard a generation.** The response is the
expensive thing. A failed score is recorded on the result and the run continues.

**Never retry a non-retryable error.** Retrying a missing API key three times
just makes the user wait three times as long for the same message.

**Never put a secret anywhere the browser can see it**, including
`NEXT_PUBLIC_*` variables, error messages and result metadata.

---

## Pull requests

- One logical change per PR.
- Describe what changed, why, and any trade-off you took.
- Include test output for the commands in the quality bar above.
- Update the README, API.md or ARCHITECTURE.md if behaviour, the API surface or
  a design decision changed.
- Do not claim support for something that is not implemented and tested.

## Reporting bugs

Include: what you did, what you expected, what happened, your provider and
model, and the relevant backend log lines (they are already credential-redacted,
but check before pasting). For provider failures, the `error.code` and
`incident_id` from the response are the most useful things you can give us.
