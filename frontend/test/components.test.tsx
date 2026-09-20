import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ComparisonTable } from '@/components/benchmark/comparison-table';
import { ModelPicker } from '@/components/benchmark/model-picker';
import { ResponseCard } from '@/components/benchmark/response-card';
import { RunProgressPanel } from '@/components/benchmark/run-progress';
import { VariantMatrix } from '@/components/benchmark/variant-matrix';
import { ErrorState } from '@/components/ui/feedback';
import { makeFailedResult, makeProgress, makeProviders, makeResult } from './fixtures';

/* -------------------------------------------------------------------------- */
/* Model selection                                                             */
/* -------------------------------------------------------------------------- */

describe('ModelPicker', () => {
  it('selects and deselects a model', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ModelPicker providers={makeProviders()} selected={[]} onChange={onChange} max={12} />);

    await user.click(screen.getByRole('button', { name: /llama3\.2/ }));
    expect(onChange).toHaveBeenCalledWith([{ provider: 'ollama', model: 'llama3.2' }]);
  });

  it('keeps unavailable providers visible but disabled, with the reason', () => {
    render(<ModelPicker providers={makeProviders()} selected={[]} onChange={vi.fn()} max={12} />);

    expect(screen.getByText('OPENAI_API_KEY is not set.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /gpt-4o-mini/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /llama3\.2/ })).toBeEnabled();
  });

  it('shows "Pricing unavailable" rather than a zero for unpriced models', () => {
    const providers = makeProviders();
    providers[0]!.models[0]!.pricing = null;
    render(<ModelPicker providers={providers} selected={[]} onChange={vi.fn()} max={12} />);
    expect(screen.getByText('Pricing unavailable')).toBeInTheDocument();
  });

  it('stops selection at the configured limit', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelPicker
        providers={makeProviders()}
        selected={[{ provider: 'ollama', model: 'llama3.2' }]}
        onChange={onChange}
        max={1}
      />
    );
    expect(screen.getByText('1 of 1 selected')).toBeInTheDocument();

    // Deselecting the already-chosen model is still allowed at the limit.
    // (The chosen model appears twice: in the grid and as a removable chip.)
    await user.click(screen.getAllByRole('button', { name: /llama3\.2/ })[0]!);
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('accepts a custom model id that is not in the catalogue', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ModelPicker providers={makeProviders()} selected={[]} onChange={onChange} max={12} />);

    const input = screen.getByLabelText(/Add a custom Ollama \(local\) model/i);
    await user.type(input, 'mistral:7b');
    await user.click(screen.getAllByRole('button', { name: 'Add' })[0]!);

    expect(onChange).toHaveBeenCalledWith([{ provider: 'ollama', model: 'mistral:7b' }]);
  });
});

/* -------------------------------------------------------------------------- */
/* Comparison table                                                            */
/* -------------------------------------------------------------------------- */

describe('ComparisonTable', () => {
  const fast = makeResult({ id: 1, model: 'fast-model', latency_ms: 400, estimated_cost: 0.001 });
  const slow = makeResult({
    id: 2,
    model: 'slow-model',
    latency_ms: 1600,
    estimated_cost: 0.02,
    evaluation: { ...makeResult().evaluation!, overall: 9.1 },
  });

  it('renders one column per result with every metric row', () => {
    render(<ComparisonTable results={[fast, slow]} />);

    expect(screen.getByText('fast-model')).toBeInTheDocument();
    expect(screen.getByText('slow-model')).toBeInTheDocument();
    for (const metric of ['Quality', 'Latency', 'Tokens', 'Throughput', 'Est. cost']) {
      expect(screen.getByText(metric)).toBeInTheDocument();
    }
  });

  it('marks the best value in a row with a glyph, not colour alone', () => {
    render(<ComparisonTable results={[fast, slow]} />);
    const markers = screen.getAllByLabelText('best in row');
    expect(markers.length).toBeGreaterThan(0);
  });

  it('shows "Pricing unavailable" for an unpriced model', () => {
    const unpriced = makeResult({
      id: 3,
      model: 'unpriced',
      estimated_cost: null,
      cost_per_1k_tokens: null,
    });
    render(<ComparisonTable results={[unpriced]} />);
    expect(screen.getAllByText('Pricing unavailable').length).toBeGreaterThan(0);
  });

  it('renders a failed result as a column with its error, not a blank', () => {
    render(<ComparisonTable results={[fast, makeFailedResult()]} />);
    expect(screen.getByText('Timed out')).toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Response card                                                               */
/* -------------------------------------------------------------------------- */

describe('ResponseCard', () => {
  it('renders the response, its metrics and its evaluation', () => {
    render(<ResponseCard result={makeResult()} />);

    expect(screen.getByText(/three-way handshake to agree/)).toBeInTheDocument();
    expect(screen.getByText('820 ms')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('73.2 tok/s')).toBeInTheDocument();
    expect(screen.getByText('8.4')).toBeInTheDocument();
  });

  it('renders a useful message for a failed result instead of a status code', () => {
    render(<ResponseCard result={makeFailedResult()} />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Gemini request failed: request timed out after 120s.'
    );
    expect(screen.getByText(/Retried 2 times before giving up/)).toBeInTheDocument();
    expect(screen.queryByText('HTTP 500')).not.toBeInTheDocument();
  });

  it('exposes retry and remove actions', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const onRemove = vi.fn();
    render(<ResponseCard result={makeResult()} onRetry={onRetry} onRemove={onRemove} />);

    await user.click(screen.getByRole('button', { name: /Retry/ }));
    expect(onRetry).toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /Remove/ }));
    await user.click(screen.getByRole('button', { name: 'Remove?' }));
    expect(onRemove).toHaveBeenCalled();
  });

  it('hides raw metadata behind a disclosure', async () => {
    const user = userEvent.setup();
    render(<ResponseCard result={makeResult()} />);

    const toggle = screen.getByRole('button', { name: /Technical details/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Raw provider metadata')).toBeInTheDocument();
    expect(screen.getByText('req-1')).toBeInTheDocument();
  });

  it('flags estimated token counts in the technical details', async () => {
    const user = userEvent.setup();
    render(<ResponseCard result={makeResult({ token_source: 'estimated' })} />);
    await user.click(screen.getByRole('button', { name: /Technical details/ }));
    expect(screen.getByText(/estimated \(provider reported none\)/)).toBeInTheDocument();
  });

  it('says why a result is unscored when evaluation failed', () => {
    render(
      <ResponseCard
        result={makeResult({
          evaluation: null,
          metadata: { evaluation_error: 'Judge returned malformed JSON.' },
        })}
      />
    );
    expect(screen.getByText(/Judge returned malformed JSON/)).toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Run progress                                                                */
/* -------------------------------------------------------------------------- */

describe('RunProgressPanel', () => {
  it('shows per-model execution state while running', () => {
    render(<RunProgressPanel progress={makeProgress()} />);

    expect(screen.getByText('Running benchmark…')).toBeInTheDocument();
    expect(screen.getByText(/1 \/ 3 · 1 succeeded/)).toBeInTheDocument();
    expect(screen.getByText('820 ms')).toBeInTheDocument();
    expect(screen.getByText(/running…/)).toBeInTheDocument();
    expect(screen.getByText('queued')).toBeInTheDocument();
  });

  it('reports progress to assistive technology', () => {
    render(<RunProgressPanel progress={makeProgress()} />);
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '1');
    expect(bar).toHaveAttribute('aria-valuemax', '3');
  });

  it('offers cancellation only while the run is in flight', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { rerender } = render(<RunProgressPanel progress={makeProgress()} onCancel={onCancel} />);

    await user.click(screen.getByRole('button', { name: /Cancel run/ }));
    expect(onCancel).toHaveBeenCalled();

    rerender(
      <RunProgressPanel
        progress={makeProgress({ status: 'completed', completed: 3, succeeded: 3 })}
        onCancel={onCancel}
      />
    );
    expect(screen.queryByRole('button', { name: /Cancel run/ })).not.toBeInTheDocument();
    expect(screen.getByText('Run complete')).toBeInTheDocument();
  });

  it('lists the reason for each failed model', () => {
    const progress = makeProgress({
      status: 'completed',
      completed: 3,
      succeeded: 2,
      failed: 1,
    });
    progress.tasks[2] = {
      ...progress.tasks[2]!,
      status: 'failed',
      error_code: 'authentication',
      error_message: 'Gemini request failed: API key is missing.',
    };
    render(<RunProgressPanel progress={progress} />);

    expect(screen.getByText(/API key is missing/)).toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Variant matrix                                                              */
/* -------------------------------------------------------------------------- */

describe('VariantMatrix', () => {
  const plainA = makeResult({ id: 1, variant_name: 'Plain', model: 'model-a' });
  const plainB = makeResult({ id: 2, variant_name: 'Plain', model: 'model-b' });
  const analogyA = makeResult({ id: 3, variant_name: 'Analogy', model: 'model-a' });
  const analogyB = makeResult({ id: 4, variant_name: 'Analogy', model: 'model-b' });

  it('renders a row per variant and a column per model', () => {
    render(<VariantMatrix results={[plainA, plainB, analogyA, analogyB]} />);

    expect(screen.getByRole('rowheader', { name: 'Plain' })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'Analogy' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /model-a/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /model-b/ })).toBeInTheDocument();
  });

  it('is not rendered for a single-variant run', () => {
    const { container } = render(<VariantMatrix results={[plainA, plainB]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('selects a cell', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<VariantMatrix results={[plainA, plainB, analogyA, analogyB]} onSelect={onSelect} />);
    const row = screen.getByRole('row', { name: /Analogy/ });
    await user.click(within(row).getAllByRole('button')[0]!);
    expect(onSelect).toHaveBeenCalledWith(analogyA);
  });
});

/* -------------------------------------------------------------------------- */
/* Error surface                                                               */
/* -------------------------------------------------------------------------- */

describe('ErrorState', () => {
  it('shows the message, the hint and a retry affordance', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <ErrorState
        title="Gemini failed"
        message="API key is missing."
        hint="Set GEMINI_API_KEY."
        onRetry={onRetry}
      />
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Gemini failed');
    expect(alert).toHaveTextContent('API key is missing.');
    expect(alert).toHaveTextContent('Set GEMINI_API_KEY.');

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });
});
