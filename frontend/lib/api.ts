/**
 * Typed client for the PromptBench API.
 *
 * All backend errors arrive as `{ "error": { code, message, hint? } }`; this
 * module turns them into an {@link ApiError} carrying the readable message the
 * UI shows, so no component ever renders a bare "HTTP 500".
 */

import type {
  AnalyticsResponse,
  ApiErrorDetail,
  BenchmarkCreatePayload,
  BenchmarkDetail,
  BenchmarkListItem,
  BenchmarkRun,
  DashboardSummary,
  EvaluateResponse,
  EvaluationMode,
  EvaluationModeInfo,
  HealthResponse,
  LeaderboardMetric,
  LeaderboardResponse,
  ManualScores,
  ModelSelection,
  ModelsResponse,
  Page,
  ResultMatrix,
  RunComparison,
  RunProgress,
  SettingsResponse,
  TestConnectionResponse,
} from '@/types';

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  ''
);

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }

  get code(): string {
    return this.detail.code;
  }

  get hint(): string | undefined {
    return this.detail.hint ?? undefined;
  }

  /** True when the failure is worth offering a retry button for. */
  get retryable(): boolean {
    return (
      this.detail.retryable === true ||
      ['timeout', 'rate_limit', 'provider_unavailable'].includes(this.detail.code)
    );
  }
}

/** Raised when the API cannot be reached at all (backend down, CORS, offline). */
export class NetworkError extends ApiError {
  constructor(message: string) {
    super(0, {
      code: 'provider_unavailable',
      message,
      hint: `Is the API running at ${API_BASE_URL}?`,
    });
    this.name = 'NetworkError';
  }
}

type QueryValue = string | number | boolean | null | undefined;

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(
  path: string,
  options: RequestInit & { query?: Record<string, QueryValue> } = {}
): Promise<T> {
  const { query, ...init } = options;
  let response: Response;

  try {
    response = await fetch(buildUrl(path, query), {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    });
  } catch (cause) {
    throw new NetworkError(
      cause instanceof Error && cause.name === 'AbortError'
        ? 'Request cancelled.'
        : 'Could not reach the PromptBench API.'
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const envelope = (payload as { error?: ApiErrorDetail } | null)?.error;
    throw new ApiError(
      response.status,
      envelope ?? {
        code: 'unknown',
        message: text.slice(0, 300) || `Request failed with status ${response.status}.`,
      }
    );
  }

  return payload as T;
}

/** Non-JSON responses (exports) come back as raw text. */
async function requestText(
  path: string,
  query?: Record<string, QueryValue>
): Promise<{ body: string; filename: string; contentType: string }> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, query));
  } catch {
    throw new NetworkError('Could not reach the PromptBench API.');
  }
  const body = await response.text();
  if (!response.ok) {
    let detail: ApiErrorDetail = { code: 'unknown', message: 'Export failed.' };
    try {
      detail = (JSON.parse(body) as { error: ApiErrorDetail }).error ?? detail;
    } catch {
      /* keep the fallback */
    }
    throw new ApiError(response.status, detail);
  }
  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename="([^"]+)"/.exec(disposition);
  return {
    body,
    filename: match?.[1] ?? 'promptbench-export',
    contentType: response.headers.get('content-type') ?? 'text/plain',
  };
}

export interface BenchmarkQuery {
  search?: string;
  tag?: string;
  provider?: string;
  model?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  sort?: 'created_at' | 'updated_at' | 'name';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export interface AnalyticsQuery {
  date_from?: string;
  date_to?: string;
  provider?: string;
  model?: string;
  benchmark_id?: number;
}

export interface RunOverrides {
  models?: ModelSelection[];
  temperature?: number;
  max_tokens?: number;
  evaluation_mode?: EvaluationMode;
  variant_ids?: number[];
}

export const api = {
  /* ---- health & configuration ---- */
  health: () => request<HealthResponse>('/api/health'),
  settings: () => request<SettingsResponse>('/api/settings'),
  reloadPricing: () =>
    request<{ reloaded: boolean; as_of: string; models_priced: number }>(
      '/api/settings/pricing/reload',
      { method: 'POST' }
    ),

  /* ---- providers & models ---- */
  models: (probe = true) => request<ModelsResponse>('/api/models', { query: { probe } }),
  testConnection: (provider: string, model?: string) =>
    request<TestConnectionResponse>('/api/models/test', {
      method: 'POST',
      body: JSON.stringify({ provider, model: model ?? null }),
    }),

  /* ---- benchmarks ---- */
  createBenchmark: (payload: BenchmarkCreatePayload) =>
    request<BenchmarkDetail>('/api/benchmarks', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listBenchmarks: (query: BenchmarkQuery = {}) =>
    request<Page<BenchmarkListItem>>('/api/benchmarks', {
      query: query as Record<string, QueryValue>,
    }),
  getBenchmark: (id: number) => request<BenchmarkDetail>(`/api/benchmarks/${id}`),
  updateBenchmark: (id: number, patch: { name?: string; description?: string; tags?: string[] }) =>
    request<BenchmarkDetail>(`/api/benchmarks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteBenchmark: (id: number) => request<void>(`/api/benchmarks/${id}`, { method: 'DELETE' }),

  /* ---- execution ---- */
  runBenchmark: (id: number, overrides: RunOverrides = {}, wait = false) =>
    request<RunProgress>(`/api/benchmarks/${id}/run`, {
      method: 'POST',
      query: { wait },
      body: JSON.stringify(overrides),
    }),
  rerunBenchmark: (id: number, wait = false) =>
    request<RunProgress>(`/api/benchmarks/${id}/rerun`, { method: 'POST', query: { wait } }),
  listRuns: (benchmarkId: number) => request<RunProgress[]>(`/api/benchmarks/${benchmarkId}/runs`),
  /** Compare two runs; omit both ids for the two most recent. */
  compareRuns: (benchmarkId: number, baseRunId?: number, targetRunId?: number) =>
    request<RunComparison>(`/api/benchmarks/${benchmarkId}/compare`, {
      query: { base_run_id: baseRunId, target_run_id: targetRunId },
    }),
  getRun: (runId: number) => request<BenchmarkRun>(`/api/runs/${runId}`),
  getRunProgress: (runId: number) => request<RunProgress>(`/api/runs/${runId}/progress`),
  getMatrix: (runId: number) => request<ResultMatrix>(`/api/runs/${runId}/matrix`),
  cancelRun: (runId: number) =>
    request<{ run_id: number; cancelled: boolean; detail: string }>(`/api/runs/${runId}/cancel`, {
      method: 'POST',
    }),
  deleteRun: (runId: number) => request<void>(`/api/runs/${runId}`, { method: 'DELETE' }),
  deleteResult: (resultId: number) =>
    request<void>(`/api/results/${resultId}`, { method: 'DELETE' }),

  /** URL for the SSE progress stream (consumed with `EventSource`). */
  runStreamUrl: (runId: number) => `${API_BASE_URL}/api/runs/${runId}/stream`,

  /* ---- evaluation ---- */
  evaluationModes: () =>
    request<{ modes: EvaluationModeInfo[]; criteria: string[] }>('/api/evaluation/modes'),
  evaluateRun: (runId: number, mode: EvaluationMode, overwrite = true) =>
    request<EvaluateResponse>('/api/evaluate', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, mode, overwrite }),
    }),
  evaluateResult: (
    modelResultId: number,
    mode: EvaluationMode,
    extra: {
      scores?: ManualScores;
      reviewer?: string;
      judge_provider?: string;
      judge_model?: string;
    } = {}
  ) =>
    request<EvaluateResponse>('/api/evaluate', {
      method: 'POST',
      body: JSON.stringify({ model_result_id: modelResultId, mode, ...extra }),
    }),

  /* ---- analytics ---- */
  analytics: (query: AnalyticsQuery = {}) =>
    request<AnalyticsResponse>('/api/analytics', { query: query as Record<string, QueryValue> }),
  leaderboard: (metric: string, minExecutions = 1, query: AnalyticsQuery = {}) =>
    request<LeaderboardResponse>('/api/leaderboard', {
      query: { metric, min_executions: minExecutions, ...(query as Record<string, QueryValue>) },
    }),
  leaderboardMetrics: () =>
    request<{ metrics: LeaderboardMetric[]; methodology: string }>('/api/leaderboard/metrics'),
  dashboard: () => request<DashboardSummary>('/api/dashboard'),

  /* ---- export ---- */
  exportBenchmark: (id: number, format: 'json' | 'csv' | 'markdown' | 'html', runId?: number) =>
    requestText(`/api/export/${id}`, { format, run_id: runId }),
};

/** Trigger a browser download for exported content. */
export function downloadFile(filename: string, content: string, contentType: string): void {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

/** Normalise any thrown value into a message safe to show a user. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}
