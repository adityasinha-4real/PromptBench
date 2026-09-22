/**
 * Page-level tests.
 *
 * The API client is mocked at the module boundary, so these exercise the real
 * page components, their loading/error/empty states and their filter wiring.
 */

import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import {
  makeBenchmark,
  makeComparison,
  makeComparisonEntry,
  makeDelta,
  makeProviders,
  makeResult,
  makeRun,
  makeRunSummary,
} from './fixtures';

// vi.mock factories are hoisted, so the doubles they close over must be too.
const { push, apiMock } = vi.hoisted(() => ({
  push: vi.fn(),
  apiMock: {
    health: vi.fn(),
    settings: vi.fn(),
    models: vi.fn(),
    dashboard: vi.fn(),
    listBenchmarks: vi.fn(),
    getBenchmark: vi.fn(),
    getRun: vi.fn(),
    runBenchmark: vi.fn(),
    rerunBenchmark: vi.fn(),
    deleteBenchmark: vi.fn(),
    deleteResult: vi.fn(),
    cancelRun: vi.fn(),
    evaluateRun: vi.fn(),
    evaluateResult: vi.fn(),
    evaluationModes: vi.fn(),
    compareRuns: vi.fn(),
    analytics: vi.fn(),
    leaderboard: vi.fn(),
    leaderboardMetrics: vi.fn(),
    testConnection: vi.fn(),
    exportBenchmark: vi.fn(),
    reloadPricing: vi.fn(),
    getRunProgress: vi.fn(),
    runStreamUrl: vi.fn(() => 'http://localhost:8000/api/runs/10/stream'),
  },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, back: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/history',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: '1' }),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, api: apiMock, downloadFile: vi.fn() };
});

const HistoryPage = (await import('@/app/history/page')).default;
const BenchmarkPage = (await import('@/app/benchmarks/[id]/page')).default;
const ModelsPage = (await import('@/app/models/page')).default;
const NewBenchmarkPage = (await import('@/app/benchmarks/new/page')).default;
const { RunComparison } = await import('@/components/benchmark/run-comparison');

function emptyPage() {
  return { items: [], total: 0, limit: 20, offset: 0 };
}

const EVALUATION_MODES = [
  { id: 'disabled', label: 'Disabled', available: true, requires_credentials: false },
  { id: 'heuristic', label: 'Heuristic (offline)', available: true, requires_credentials: false },
  { id: 'llm_judge', label: 'LLM as a judge', available: true, requires_credentials: true },
  { id: 'manual', label: 'Manual', available: true, requires_credentials: false },
].map((mode) => ({ ...mode, description: `${mode.label} description` }));

function settingsWith(evaluation: {
  default_mode: string;
  judge_provider?: string | null;
  judge_model?: string | null;
}) {
  // Only the parts the new-benchmark form reads.
  return {
    evaluation: { modes: EVALUATION_MODES, judge_provider: null, judge_model: null, ...evaluation },
    limits: {},
  };
}

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    if (typeof fn === 'function' && 'mockReset' in fn) (fn as ReturnType<typeof vi.fn>).mockReset();
  }
  apiMock.runStreamUrl.mockReturnValue('http://localhost:8000/api/runs/10/stream');
  apiMock.models.mockResolvedValue({
    providers: makeProviders(),
    models: [],
    pricing: {
      as_of: '2025-06-01',
      currency: 'USD',
      unit: 'per_1m_tokens',
      sources: { ollama: 'local execution - no API billing' },
      estimated: true,
      disclaimer: 'Costs are estimates.',
    },
  });
  push.mockReset();
});

/* -------------------------------------------------------------------------- */
/* History                                                                     */
/* -------------------------------------------------------------------------- */

describe('History page', () => {
  it('lists benchmarks with their run summaries', async () => {
    apiMock.listBenchmarks.mockResolvedValue({
      items: [
        {
          id: 1,
          name: 'TCP handshake',
          description: null,
          prompt_excerpt: 'Explain why TCP uses a three-way handshake.',
          tags: ['networking'],
          model_count: 2,
          variant_count: 0,
          run_count: 1,
          evaluation_mode: 'heuristic',
          created_at: '2026-01-01T00:00:00Z',
          last_run_at: '2026-01-01T00:00:00Z',
          last_run_status: 'completed',
          avg_quality: 8.4,
          total_cost: 0.0021,
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    });

    render(<HistoryPage />);

    expect(await screen.findByText('TCP handshake')).toBeInTheDocument();
    expect(screen.getByText('networking')).toBeInTheDocument();
    expect(screen.getByText('8.4')).toBeInTheDocument();
    expect(screen.getByText('$0.0021')).toBeInTheDocument();
    // The status appears in the filter dropdown as well as on the row.
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0);
  });

  it('shows an empty state when nothing has been created yet', async () => {
    apiMock.listBenchmarks.mockResolvedValue(emptyPage());
    render(<HistoryPage />);
    expect(await screen.findByText('No benchmarks yet')).toBeInTheDocument();
  });

  it('passes the search term to the API and reports when filters match nothing', async () => {
    const user = userEvent.setup();
    apiMock.listBenchmarks.mockResolvedValue(emptyPage());
    render(<HistoryPage />);

    await user.type(screen.getByLabelText('Search'), 'quicksort');

    await waitFor(
      () =>
        expect(apiMock.listBenchmarks).toHaveBeenCalledWith(
          expect.objectContaining({ search: 'quicksort' })
        ),
      { timeout: 2000 }
    );
    expect(await screen.findByText('No benchmarks match those filters')).toBeInTheDocument();
  });

  it('passes provider and status filters to the API', async () => {
    const user = userEvent.setup();
    apiMock.listBenchmarks.mockResolvedValue(emptyPage());
    render(<HistoryPage />);
    await screen.findByLabelText('Provider');

    await user.selectOptions(screen.getByLabelText('Provider'), 'ollama');
    await waitFor(() =>
      expect(apiMock.listBenchmarks).toHaveBeenCalledWith(
        expect.objectContaining({ provider: 'ollama' })
      )
    );

    await user.selectOptions(screen.getByLabelText('Run status'), 'failed');
    await waitFor(() =>
      expect(apiMock.listBenchmarks).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'failed' })
      )
    );
  });

  it('surfaces a backend failure with a retry action', async () => {
    apiMock.listBenchmarks.mockRejectedValue(
      new ApiError(503, { code: 'provider_unavailable', message: 'Database is unavailable.' })
    );
    render(<HistoryPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Database is unavailable.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Benchmark results                                                           */
/* -------------------------------------------------------------------------- */

describe('Benchmark results page', () => {
  it('renders the prompt, the comparison and each response', async () => {
    apiMock.getBenchmark.mockResolvedValue(makeBenchmark());
    apiMock.getRun.mockResolvedValue(
      makeRun([
        makeResult({ id: 1, model: 'llama3.2' }),
        makeResult({ id: 2, provider: 'openai', model: 'gpt-4o-mini', latency_ms: 1400 }),
      ])
    );

    render(<BenchmarkPage />);

    expect(await screen.findByRole('heading', { name: 'TCP handshake' })).toBeInTheDocument();
    expect(
      screen.getAllByText('Explain why TCP uses a three-way handshake.').length
    ).toBeGreaterThan(0);
    expect(await screen.findByText('Quality')).toBeInTheDocument();
    expect(screen.getAllByText('llama3.2').length).toBeGreaterThan(0);
    expect(screen.getAllByText('gpt-4o-mini').length).toBeGreaterThan(0);
  });

  it('prompts the user to run a benchmark that has never been executed', async () => {
    apiMock.getBenchmark.mockResolvedValue(makeBenchmark({ runs: [] }));
    render(<BenchmarkPage />);

    expect(await screen.findByText('This benchmark has not been run yet')).toBeInTheDocument();
    expect(apiMock.getRun).not.toHaveBeenCalled();
  });

  it('starts a run and follows it', async () => {
    const user = userEvent.setup();
    apiMock.getBenchmark.mockResolvedValue(makeBenchmark({ runs: [] }));
    apiMock.runBenchmark.mockResolvedValue({
      run_id: 11,
      benchmark_id: 1,
      status: 'running',
      total: 2,
      completed: 0,
      succeeded: 0,
      failed: 0,
      tasks: [],
      started_at: '2026-01-01T00:00:00Z',
      completed_at: null,
    });
    apiMock.getRunProgress.mockResolvedValue({
      run_id: 11,
      benchmark_id: 1,
      status: 'running',
      total: 2,
      completed: 0,
      succeeded: 0,
      failed: 0,
      tasks: [],
      started_at: '2026-01-01T00:00:00Z',
      completed_at: null,
    });
    apiMock.getRun.mockResolvedValue(makeRun([]));

    render(<BenchmarkPage />);
    // Both the header action and the empty state offer to run it.
    const runButtons = await screen.findAllByRole('button', { name: /Run benchmark/ });
    await user.click(runButtons[0]!);

    await waitFor(() => expect(apiMock.runBenchmark).toHaveBeenCalledWith(1));
  });

  it('reports a failed model with its reason while keeping the successful one', async () => {
    apiMock.getBenchmark.mockResolvedValue(makeBenchmark());
    apiMock.getRun.mockResolvedValue(
      makeRun([
        makeResult({ id: 1, model: 'llama3.2' }),
        makeResult({
          id: 2,
          provider: 'gemini',
          model: 'gemini-2.5-flash',
          status: 'failed',
          response: null,
          latency_ms: null,
          estimated_cost: null,
          error_code: 'authentication',
          error_message: 'Gemini request failed: API key is missing.',
          evaluation: null,
        }),
      ])
    );

    render(<BenchmarkPage />);

    expect(await screen.findByText(/API key is missing/)).toBeInTheDocument();
    expect(screen.getByText(/three-way handshake to agree/)).toBeInTheDocument();
  });

  it('surfaces a load failure rather than rendering a blank page', async () => {
    apiMock.getBenchmark.mockRejectedValue(
      new ApiError(404, { code: 'not_found', message: 'Benchmark 1 was not found.' })
    );
    render(<BenchmarkPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Benchmark 1 was not found.');
  });
});

/* -------------------------------------------------------------------------- */
/* Run comparison                                                              */
/* -------------------------------------------------------------------------- */

describe('Run comparison', () => {
  const twoRuns = [makeRunSummary({ id: 11 }), makeRunSummary({ id: 10 })];

  it('compares the two most recent runs and shows each metric separately', async () => {
    apiMock.compareRuns.mockResolvedValue(makeComparison());
    render(<RunComparison benchmarkId={1} runs={twoRuns} />);

    // Newest against the one before it, oldest first.
    await waitFor(() => expect(apiMock.compareRuns).toHaveBeenCalledWith(1, 10, 11));
    expect(await screen.findByText('llama3.2')).toBeInTheDocument();
    expect(screen.getByText('1 mixed')).toBeInTheDocument();
    expect(screen.getByText('Mixed')).toBeInTheDocument();
  });

  it('shows direction with an arrow and a sign, not by colour alone', async () => {
    apiMock.compareRuns.mockResolvedValue(makeComparison());
    render(<RunComparison benchmarkId={1} runs={twoRuns} />);

    // Quality rose by 2.0, latency worsened by 500ms; both are readable as text.
    expect(await screen.findByText(/▲ \+2\.0/)).toBeInTheDocument();
    expect(screen.getByText(/▲ \+500 ms/)).toBeInTheDocument();
  });

  it('never renders a missing value as zero', async () => {
    apiMock.compareRuns.mockResolvedValue(
      makeComparison({
        entries: [
          makeComparisonEntry({
            estimated_cost: makeDelta({ base: null, target: null, direction: 'unknown' }),
          }),
        ],
      })
    );
    render(<RunComparison benchmarkId={1} runs={twoRuns} />);

    expect(await screen.findByText('n/a')).toBeInTheDocument();
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
  });

  it('surfaces the backend note when the evaluation mode changed', async () => {
    apiMock.compareRuns.mockResolvedValue(
      makeComparison({
        quality_comparable: false,
        notes: ['Quality is not compared: these runs were scored in different evaluation modes.'],
      })
    );
    render(<RunComparison benchmarkId={1} runs={twoRuns} />);

    expect(await screen.findByText(/different evaluation modes/)).toBeInTheDocument();
  });

  it('refetches when a different run is picked', async () => {
    const user = userEvent.setup();
    apiMock.compareRuns.mockResolvedValue(makeComparison());
    render(
      <RunComparison
        benchmarkId={1}
        runs={[makeRunSummary({ id: 12 }), makeRunSummary({ id: 11 }), makeRunSummary({ id: 10 })]}
      />
    );
    await screen.findByText('llama3.2');

    await user.selectOptions(screen.getByLabelText('Older run'), '10');

    await waitFor(() => expect(apiMock.compareRuns).toHaveBeenCalledWith(1, 10, 12));
  });

  it('asks for a second run instead of comparing a run with itself', () => {
    render(<RunComparison benchmarkId={1} runs={[makeRunSummary({ id: 11 })]} />);

    expect(screen.getByText('Only one run so far')).toBeInTheDocument();
    expect(apiMock.compareRuns).not.toHaveBeenCalled();
  });

  it('is offered on the results page once a benchmark has two runs', async () => {
    const user = userEvent.setup();
    apiMock.getBenchmark.mockResolvedValue(
      makeBenchmark({ runs: [makeRunSummary({ id: 11 }), makeRunSummary({ id: 10 })] })
    );
    apiMock.getRun.mockResolvedValue(makeRun([makeResult({ id: 1, model: 'llama3.2' })]));
    apiMock.compareRuns.mockResolvedValue(makeComparison());

    render(<BenchmarkPage />);
    await user.click(await screen.findByRole('tab', { name: /Compare runs/ }));

    expect(await screen.findByText('What changed between runs')).toBeInTheDocument();
  });

  it('is not offered when there is only one run', async () => {
    apiMock.getBenchmark.mockResolvedValue(makeBenchmark());
    apiMock.getRun.mockResolvedValue(makeRun([makeResult({ id: 1, model: 'llama3.2' })]));

    render(<BenchmarkPage />);
    await screen.findByRole('heading', { name: 'TCP handshake' });

    expect(screen.queryByRole('tab', { name: /Compare runs/ })).not.toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* New benchmark                                                               */
/* -------------------------------------------------------------------------- */

describe('New benchmark page', () => {
  beforeEach(() => {
    apiMock.evaluationModes.mockResolvedValue({ modes: EVALUATION_MODES });
  });

  it('preselects the evaluation mode configured on the server', async () => {
    apiMock.settings.mockResolvedValue(settingsWith({ default_mode: 'manual' }));
    render(<NewBenchmarkPage />);
    expect(await screen.findByDisplayValue('Manual')).toBeInTheDocument();
  });

  it('prefills the configured judge when the default mode is LLM judge', async () => {
    apiMock.settings.mockResolvedValue(
      settingsWith({ default_mode: 'llm_judge', judge_provider: 'ollama', judge_model: 'llama3.2' })
    );
    render(<NewBenchmarkPage />);
    expect(await screen.findByDisplayValue('LLM as a judge')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Ollama (local)')).toBeInTheDocument();
    expect(screen.getByDisplayValue('llama3.2')).toBeInTheDocument();
  });

  it('shows a configured judge that is currently unavailable instead of hiding it', async () => {
    apiMock.settings.mockResolvedValue(
      settingsWith({ default_mode: 'llm_judge', judge_provider: 'openai', judge_model: 'gpt-4o' })
    );
    render(<NewBenchmarkPage />);
    expect(await screen.findByDisplayValue('openai (unavailable)')).toBeInTheDocument();
    expect(screen.getByDisplayValue('gpt-4o')).toBeInTheDocument();
  });

  it('does not overwrite a mode the user picked before settings arrived', async () => {
    const user = userEvent.setup();
    let resolveSettings!: (value: unknown) => void;
    apiMock.settings.mockReturnValue(new Promise((resolve) => (resolveSettings = resolve)));
    render(<NewBenchmarkPage />);

    const modeSelect = await screen.findByDisplayValue('Heuristic (offline)');
    await user.selectOptions(modeSelect, 'disabled');
    // Flush the settings response and the effect it triggers.
    await act(async () => resolveSettings(settingsWith({ default_mode: 'manual' })));

    expect(screen.getByDisplayValue('Disabled')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Manual')).not.toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Models                                                                      */
/* -------------------------------------------------------------------------- */

describe('Models page', () => {
  it('shows availability per provider and names the missing env var', async () => {
    render(<ModelsPage />);

    expect(await screen.findByText('Ollama (local)')).toBeInTheDocument();
    expect(screen.getAllByText('Available').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Set OPENAI_API_KEY in your \.env to enable this provider/)
    ).toBeInTheDocument();
  });

  it('never renders a credential value', async () => {
    render(<ModelsPage />);
    await screen.findByText('Ollama (local)');
    expect(document.body.textContent).not.toMatch(/sk-[A-Za-z0-9]/);
  });

  it('runs a connection test and reports the outcome', async () => {
    const user = userEvent.setup();
    apiMock.testConnection.mockResolvedValue({
      provider: 'ollama',
      model: null,
      available: true,
      detail: 'Ollama is running with 2 local model(s).',
      error_code: null,
      latency_ms: 4,
      model_count: 2,
      generation_ok: null,
    });

    render(<ModelsPage />);
    await screen.findByText('Ollama (local)');
    await user.click(screen.getAllByRole('button', { name: 'Test connection' })[0]!);

    await waitFor(() => expect(apiMock.testConnection).toHaveBeenCalledWith('ollama', undefined));
  });
});
