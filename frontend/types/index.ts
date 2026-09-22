/**
 * TypeScript mirror of the backend Pydantic schemas.
 *
 * Kept hand-written rather than generated so the shapes stay readable; the
 * source of truth is the OpenAPI document at `${API_URL}/openapi.json`.
 */

export type EvaluationMode = 'disabled' | 'heuristic' | 'llm_judge' | 'manual';

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type ResultStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled';

export type ErrorCode =
  | 'timeout'
  | 'rate_limit'
  | 'authentication'
  | 'provider_unavailable'
  | 'invalid_request'
  | 'content_filter'
  | 'cancelled'
  | 'not_found'
  | 'conflict'
  | 'unknown';

export interface ApiErrorDetail {
  code: ErrorCode | string;
  message: string;
  hint?: string | null;
  provider?: string | null;
  model?: string | null;
  retryable?: boolean | null;
  upstream_status?: number | null;
  details?: { field: string; message: string }[];
  incident_id?: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/* -------------------------------------------------------------------------- */
/* Providers & models                                                          */
/* -------------------------------------------------------------------------- */

export interface Pricing {
  input_per_1m: number;
  output_per_1m: number;
  note?: string | null;
}

export interface ModelInfo {
  provider: string;
  id: string;
  label: string;
  context_window?: number | null;
  description?: string | null;
  local: boolean;
  /** `null` means the model has no configured price — render "Pricing unavailable". */
  pricing: Pricing | null;
  available: boolean;
}

export interface ProviderInfo {
  id: string;
  label: string;
  is_local: boolean;
  configured: boolean;
  available: boolean;
  status_detail: string;
  api_key_env?: string | null;
  error_code?: string | null;
  latency_ms?: number | null;
  models: ModelInfo[];
}

export interface PricingMeta {
  as_of: string;
  currency: string;
  unit: string;
  sources: Record<string, string>;
  estimated: boolean;
  disclaimer: string;
}

export interface ModelsResponse {
  providers: ProviderInfo[];
  models: ModelInfo[];
  pricing: PricingMeta;
}

export interface TestConnectionResponse {
  provider: string;
  model?: string | null;
  available: boolean;
  detail: string;
  error_code?: string | null;
  latency_ms?: number | null;
  model_count?: number | null;
  generation_ok?: boolean | null;
}

/* -------------------------------------------------------------------------- */
/* Benchmarks                                                                  */
/* -------------------------------------------------------------------------- */

export interface ModelSelection {
  provider: string;
  model: string;
}

export interface PromptVariant {
  id: number;
  name: string;
  prompt: string;
  position: number;
}

export interface Evaluation {
  id: number;
  relevance: number;
  correctness: number;
  conciseness: number;
  clarity: number;
  overall: number;
  reasoning: string | null;
  mode: string;
  evaluator_model: string | null;
  created_at: string;
}

export interface ModelResult {
  id: number;
  variant_id: number | null;
  variant_name: string;
  provider: string;
  model: string;
  status: ResultStatus;
  response: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  tokens_per_second: number | null;
  /** `null` means pricing is unavailable for this model — never treat it as 0. */
  estimated_cost: number | null;
  cost_per_1k_tokens: number | null;
  finish_reason: string | null;
  token_source: string | null;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  request_params: Record<string, unknown>;
  metadata: Record<string, unknown>;
  evaluation: Evaluation | null;
  created_at: string;
}

export interface BenchmarkRun {
  id: number;
  benchmark_id: number;
  status: RunStatus;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  params_snapshot: Record<string, unknown>;
  results: ModelResult[];
}

export interface RunSummary {
  id: number;
  status: RunStatus;
  started_at: string;
  completed_at: string | null;
  result_count: number;
  success_count: number;
  failure_count: number;
  avg_latency_ms: number | null;
  total_cost: number | null;
  avg_quality: number | null;
}

export interface Benchmark {
  id: number;
  name: string;
  description: string | null;
  prompt: string;
  system_prompt: string | null;
  temperature: number;
  max_tokens: number;
  top_p: number | null;
  evaluation_enabled: boolean;
  evaluation_mode: EvaluationMode;
  judge_provider: string | null;
  judge_model: string | null;
  models: ModelSelection[];
  tags: string[];
  variants: PromptVariant[];
  created_at: string;
  updated_at: string;
}

export interface BenchmarkDetail extends Benchmark {
  runs: RunSummary[];
  latest_run: BenchmarkRun | null;
}

export interface BenchmarkListItem {
  id: number;
  name: string;
  description: string | null;
  prompt_excerpt: string;
  tags: string[];
  model_count: number;
  variant_count: number;
  run_count: number;
  evaluation_mode: string;
  created_at: string;
  last_run_at: string | null;
  last_run_status: RunStatus | null;
  avg_quality: number | null;
  total_cost: number | null;
}

export interface BenchmarkCreatePayload {
  name: string;
  description?: string | null;
  prompt: string;
  system_prompt?: string | null;
  temperature: number;
  max_tokens: number;
  top_p?: number | null;
  evaluation_enabled: boolean;
  evaluation_mode: EvaluationMode;
  judge_provider?: string | null;
  judge_model?: string | null;
  models: ModelSelection[];
  variants: { name: string; prompt: string }[];
  tags: string[];
  run_immediately?: boolean;
}

export interface RunTaskState {
  key: string;
  provider: string;
  model: string;
  variant_name: string;
  status: ResultStatus;
  latency_ms: number | null;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  result_id: number | null;
}

export interface RunProgress {
  run_id: number;
  benchmark_id: number;
  status: RunStatus;
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  tasks: RunTaskState[];
  started_at: string | null;
  completed_at: string | null;
}

export interface ResultMatrix {
  variants: string[];
  targets: string[];
  cells: Record<string, Record<string, number>>;
}

/* -------------------------------------------------------------------------- */
/* Analytics                                                                   */
/* -------------------------------------------------------------------------- */

export interface AnalyticsTotals {
  total_benchmarks: number;
  total_runs: number;
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  avg_latency_ms: number | null;
  avg_cost: number | null;
  total_cost: number | null;
  avg_quality: number | null;
  unpriced_executions: number;
}

export interface ModelStat {
  provider: string;
  model: string;
  executions: number;
  successes: number;
  failures: number;
  success_rate: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_tokens_per_second: number | null;
  avg_input_tokens: number | null;
  avg_output_tokens: number | null;
  total_tokens: number;
  avg_cost: number | null;
  total_cost: number | null;
  cost_per_1k_tokens: number | null;
  avg_quality: number | null;
  avg_relevance: number | null;
  avg_correctness: number | null;
  avg_conciseness: number | null;
  avg_clarity: number | null;
  priced: boolean;
}

export interface ProviderStat {
  provider: string;
  executions: number;
  successes: number;
  failures: number;
  avg_latency_ms: number | null;
  total_cost: number | null;
  avg_quality: number | null;
}

export interface TimelinePoint {
  date: string;
  runs: number;
  executions: number;
  avg_latency_ms: number | null;
  total_cost: number | null;
  avg_quality: number | null;
}

export interface AnalyticsResponse {
  totals: AnalyticsTotals;
  by_model: ModelStat[];
  by_provider: ProviderStat[];
  timeline: TimelinePoint[];
  errors: { code: string; count: number }[];
  filters_applied: Record<string, string | null>;
  generated_at: string;
}

export interface LeaderboardEntry extends ModelStat {
  rank: number;
}

export interface LeaderboardResponse {
  metric: string;
  direction: 'asc' | 'desc';
  min_executions: number;
  entries: LeaderboardEntry[];
  methodology: string;
}

export interface LeaderboardMetric {
  id: string;
  direction: 'asc' | 'desc';
  description: string;
}

export interface DashboardSummary {
  totals: AnalyticsTotals;
  top_models: ModelStat[];
  evaluations_recorded: number;
  recent_benchmark_ids: number[];
}

/* -------------------------------------------------------------------------- */
/* Evaluation & settings                                                       */
/* -------------------------------------------------------------------------- */

export interface ManualScores {
  relevance: number;
  correctness: number;
  conciseness: number;
  clarity: number;
  overall?: number | null;
  reasoning?: string | null;
}

export interface EvaluateResponse {
  evaluated: number;
  failed: number;
  evaluations: Evaluation[];
  errors: string[];
}

export interface EvaluationModeInfo {
  id: EvaluationMode;
  label: string;
  available: boolean;
  requires_credentials: boolean;
  configured_default?: boolean;
  description: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
  database: string;
  providers: Record<string, boolean>;
  details: Record<string, unknown>;
}

export interface SettingsResponse {
  application: {
    name: string;
    environment: string;
    debug: boolean;
    database_backend: string;
    cors_origins: string[];
  };
  providers: {
    id: string;
    label: string;
    is_local: boolean;
    api_key_env: string | null;
    credential_present: boolean;
    base_url: string | null;
  }[];
  evaluation: {
    modes: EvaluationModeInfo[];
    default_mode: EvaluationMode;
    judge_provider: string | null;
    judge_model: string | null;
  };
  pricing: PricingMeta & {
    file: string;
    models_priced: number;
    table: Record<string, Record<string, Pricing>>;
  };
  limits: Record<string, number>;
}
