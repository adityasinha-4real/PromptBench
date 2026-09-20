import type {
  BenchmarkDetail,
  BenchmarkRun,
  ModelResult,
  ProviderInfo,
  RunProgress,
} from '@/types';

export function makeResult(overrides: Partial<ModelResult> = {}): ModelResult {
  return {
    id: 1,
    variant_id: null,
    variant_name: 'Default',
    provider: 'ollama',
    model: 'llama3.2',
    status: 'success',
    response: 'TCP uses a three-way handshake to agree on sequence numbers.',
    input_tokens: 40,
    output_tokens: 60,
    total_tokens: 100,
    latency_ms: 820,
    tokens_per_second: 73.2,
    estimated_cost: 0,
    cost_per_1k_tokens: 0,
    finish_reason: 'stop',
    token_source: 'provider',
    error_code: null,
    error_message: null,
    attempts: 1,
    request_params: { temperature: 0.2, max_tokens: 256 },
    metadata: { request_id: 'req-1' },
    evaluation: {
      id: 1,
      relevance: 8,
      correctness: 9,
      conciseness: 7,
      clarity: 9,
      overall: 8.4,
      reasoning: 'Accurate and well structured.',
      mode: 'heuristic',
      evaluator_model: 'builtin:heuristic-v1',
      created_at: '2026-01-01T00:00:00Z',
    },
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

export function makeFailedResult(overrides: Partial<ModelResult> = {}): ModelResult {
  return makeResult({
    id: 2,
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    status: 'failed',
    response: null,
    input_tokens: null,
    output_tokens: null,
    total_tokens: null,
    latency_ms: null,
    tokens_per_second: null,
    estimated_cost: null,
    cost_per_1k_tokens: null,
    finish_reason: null,
    error_code: 'timeout',
    error_message: 'Gemini request failed: request timed out after 120s.',
    attempts: 3,
    evaluation: null,
    ...overrides,
  });
}

export function makeRun(results: ModelResult[] = [makeResult()]): BenchmarkRun {
  return {
    id: 10,
    benchmark_id: 1,
    status: 'completed',
    started_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:03Z',
    duration_ms: 3000,
    error_message: null,
    params_snapshot: { temperature: 0.2, max_tokens: 256 },
    results,
  };
}

export function makeBenchmark(overrides: Partial<BenchmarkDetail> = {}): BenchmarkDetail {
  return {
    id: 1,
    name: 'TCP handshake',
    description: null,
    prompt: 'Explain why TCP uses a three-way handshake.',
    system_prompt: null,
    temperature: 0.2,
    max_tokens: 256,
    top_p: null,
    evaluation_enabled: true,
    evaluation_mode: 'heuristic',
    judge_provider: null,
    judge_model: null,
    models: [
      { provider: 'ollama', model: 'llama3.2' },
      { provider: 'openai', model: 'gpt-4o-mini' },
    ],
    tags: ['networking'],
    variants: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    runs: [
      {
        id: 10,
        status: 'completed',
        started_at: '2026-01-01T00:00:00Z',
        completed_at: '2026-01-01T00:00:03Z',
        result_count: 2,
        success_count: 2,
        failure_count: 0,
        avg_latency_ms: 820,
        total_cost: 0,
        avg_quality: 8.4,
      },
    ],
    latest_run: null,
    ...overrides,
  };
}

export function makeProviders(): ProviderInfo[] {
  return [
    {
      id: 'ollama',
      label: 'Ollama (local)',
      is_local: true,
      configured: true,
      available: true,
      status_detail: 'Ollama is running with 2 local model(s).',
      api_key_env: null,
      error_code: null,
      latency_ms: 4,
      models: [
        {
          provider: 'ollama',
          id: 'llama3.2',
          label: 'Llama3.2',
          context_window: 131072,
          description: '3B · Q4_0',
          local: true,
          pricing: { input_per_1m: 0, output_per_1m: 0, note: 'Runs locally - no API billing.' },
          available: true,
        },
      ],
    },
    {
      id: 'openai',
      label: 'OpenAI',
      is_local: false,
      configured: false,
      available: false,
      status_detail: 'OPENAI_API_KEY is not set.',
      api_key_env: 'OPENAI_API_KEY',
      error_code: 'authentication',
      latency_ms: null,
      models: [
        {
          provider: 'openai',
          id: 'gpt-4o-mini',
          label: 'GPT-4o mini',
          context_window: 128000,
          description: null,
          local: false,
          pricing: { input_per_1m: 0.15, output_per_1m: 0.6, note: null },
          available: false,
        },
      ],
    },
  ];
}

export function makeProgress(overrides: Partial<RunProgress> = {}): RunProgress {
  return {
    run_id: 10,
    benchmark_id: 1,
    status: 'running',
    total: 3,
    completed: 1,
    succeeded: 1,
    failed: 0,
    tasks: [
      {
        key: 'Default::ollama:llama3.2',
        provider: 'ollama',
        model: 'llama3.2',
        variant_name: 'Default',
        status: 'success',
        latency_ms: 820,
        attempts: 1,
        error_code: null,
        error_message: null,
        result_id: 1,
      },
      {
        key: 'Default::openai:gpt-4o-mini',
        provider: 'openai',
        model: 'gpt-4o-mini',
        variant_name: 'Default',
        status: 'running',
        latency_ms: null,
        attempts: 1,
        error_code: null,
        error_message: null,
        result_id: 2,
      },
      {
        key: 'Default::gemini:gemini-2.5-flash',
        provider: 'gemini',
        model: 'gemini-2.5-flash',
        variant_name: 'Default',
        status: 'queued',
        latency_ms: null,
        attempts: 0,
        error_code: null,
        error_message: null,
        result_id: 3,
      },
    ],
    started_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    ...overrides,
  };
}
