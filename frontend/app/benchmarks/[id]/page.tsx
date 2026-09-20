'use client';

import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ComparisonTable } from '@/components/benchmark/comparison-table';
import { ManualScoreDialog } from '@/components/benchmark/manual-score-dialog';
import { ResponseCard } from '@/components/benchmark/response-card';
import { RunProgressPanel } from '@/components/benchmark/run-progress';
import { VariantMatrix } from '@/components/benchmark/variant-matrix';
import { ChartFrame, CategoryBars, GroupedBars } from '@/components/charts/chart-kit';
import { PageHeader } from '@/components/layout/page-header';
import { Badge, StatusBadge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState, InlineNote, LoadingPanel } from '@/components/ui/feedback';
import { Collapsible, ConfirmButton, CopyButton, Tabs } from '@/components/ui/misc';
import { Select } from '@/components/ui/input';
import { useToast } from '@/components/ui/toast';
import { useAction, useAsync } from '@/hooks/use-async';
import { useRunProgress } from '@/hooks/use-run-progress';
import { api, downloadFile } from '@/lib/api';
import {
  evaluationModeLabel,
  formatCost,
  formatDate,
  formatLatency,
  formatScore,
  formatTokens,
  providerLabel,
} from '@/lib/format';
import type { BenchmarkRun, EvaluationMode, ModelResult } from '@/types';

type ExportFormat = 'json' | 'csv' | 'markdown' | 'html';

export default function BenchmarkResultsPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { toast } = useToast();

  const benchmarkId = Number(params.id);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [scoringResult, setScoringResult] = useState<ModelResult | null>(null);
  const [tab, setTab] = useState('responses');

  const benchmark = useAsync(() => api.getBenchmark(benchmarkId), [benchmarkId]);

  // Pick the newest run by default; honour ?run= when arriving from a launch.
  useEffect(() => {
    const fromQuery = searchParams.get('run');
    if (fromQuery) {
      const parsed = Number(fromQuery);
      if (!Number.isNaN(parsed)) {
        setSelectedRunId(parsed);
        setActiveRunId(parsed);
      }
    }
  }, [searchParams]);

  useEffect(() => {
    if (selectedRunId === null && benchmark.data?.runs.length) {
      setSelectedRunId(benchmark.data.runs[0]!.id);
    }
  }, [benchmark.data, selectedRunId]);

  const runDetail = useAsync<BenchmarkRun | null>(
    () => (selectedRunId === null ? Promise.resolve(null) : api.getRun(selectedRunId)),
    [selectedRunId]
  );

  const onRunFinished = useCallback(() => {
    setActiveRunId(null);
    benchmark.reload();
    runDetail.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { progress, transport } = useRunProgress(activeRunId, onRunFinished);

  // While a run is in flight, refresh the stored results as models land so
  // finished responses appear before the whole run completes.
  useEffect(() => {
    if (activeRunId === null || !progress) return;
    runDetail.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress?.completed, activeRunId]);

  const run = runDetail.data;
  const results = useMemo(() => run?.results ?? [], [run]);
  const successes = useMemo(() => results.filter((r) => r.status === 'success'), [results]);
  const hasVariants = (benchmark.data?.variants.length ?? 0) > 1;

  /* ------------------------------ actions ------------------------------ */

  const startRun = useAction(async () => {
    const started = await api.runBenchmark(benchmarkId);
    setActiveRunId(started.run_id);
    setSelectedRunId(started.run_id);
    setTab('responses');
    return started;
  });

  const cancelRun = useAction(async () => {
    if (activeRunId === null) return;
    const response = await api.cancelRun(activeRunId);
    toast(response.detail, response.cancelled ? 'info' : 'error');
  });

  const rescore = useAction(async (mode: EvaluationMode) => {
    if (selectedRunId === null) return;
    const response = await api.evaluateRun(selectedRunId, mode);
    toast(
      `Scored ${response.evaluated} result${response.evaluated === 1 ? '' : 's'}` +
        (response.failed ? `, ${response.failed} skipped.` : '.'),
      response.failed ? 'info' : 'success'
    );
    runDetail.reload();
  });

  const removeResult = useAction(async (result: ModelResult) => {
    await api.deleteResult(result.id);
    toast(`Removed ${result.model} from the comparison.`, 'info');
    runDetail.reload();
  });

  const retryResult = useAction(async (result: ModelResult) => {
    const started = await api.runBenchmark(benchmarkId, {
      models: [{ provider: result.provider, model: result.model }],
    });
    setActiveRunId(started.run_id);
    setSelectedRunId(started.run_id);
    toast(`Re-running ${result.model} in a new run.`, 'info');
  });

  const exportRun = useAction(async (format: ExportFormat) => {
    const file = await api.exportBenchmark(benchmarkId, format, selectedRunId ?? undefined);
    downloadFile(file.filename, file.body, file.contentType);
    toast(`Exported as ${format.toUpperCase()}.`, 'success');
  });

  const removeBenchmark = useAction(async () => {
    await api.deleteBenchmark(benchmarkId);
    toast('Benchmark deleted.', 'info');
    router.push('/history');
  });

  /* ------------------------------ charts ------------------------------ */

  const chartRows = useMemo(
    () =>
      successes.map((result) => ({
        label:
          result.variant_name === 'Default'
            ? result.model
            : `${result.model} · ${result.variant_name}`,
        result,
      })),
    [successes]
  );

  const criteriaData = useMemo(
    () =>
      chartRows
        .filter((row) => row.result.evaluation)
        .map((row) => ({
          label: row.label,
          relevance: row.result.evaluation!.relevance,
          correctness: row.result.evaluation!.correctness,
          conciseness: row.result.evaluation!.conciseness,
          clarity: row.result.evaluation!.clarity,
        })),
    [chartRows]
  );

  const unpriced = successes.filter((r) => r.estimated_cost === null).length;

  /* ------------------------------ render ------------------------------ */

  if (Number.isNaN(benchmarkId)) {
    return <ErrorState message="That benchmark id is not a number." />;
  }

  if (benchmark.loading && !benchmark.data) {
    return (
      <>
        <LoadingPanel rows={3} />
        <LoadingPanel rows={6} />
      </>
    );
  }

  if (benchmark.error || !benchmark.data) {
    return (
      <ErrorState
        title="Could not load this benchmark"
        message={benchmark.error ?? 'Not found.'}
        onRetry={benchmark.reload}
      />
    );
  }

  const data = benchmark.data;

  return (
    <>
      <PageHeader
        breadcrumb={
          <span>
            <Link href="/history" className="hover:text-fg">
              Benchmarks
            </Link>{' '}
            / #{data.id}
          </span>
        }
        title={data.name}
        description={data.description ?? undefined}
        actions={
          <>
            <Select
              aria-label="Export format"
              className="h-9 w-32"
              defaultValue=""
              onChange={(event) => {
                const value = event.target.value as ExportFormat | '';
                if (value) void exportRun.run(value);
                event.target.value = '';
              }}
            >
              <option value="">Export…</option>
              <option value="json">JSON</option>
              <option value="csv">CSV</option>
              <option value="markdown">Markdown</option>
              <option value="html">HTML report</option>
            </Select>
            <Button
              variant="primary"
              loading={startRun.pending}
              disabled={activeRunId !== null}
              onClick={() => void startRun.run()}
            >
              <span aria-hidden="true">▶</span> {data.runs.length ? 'Re-run' : 'Run'} benchmark
            </Button>
            <ConfirmButton onConfirm={() => void removeBenchmark.run()} confirmLabel="Delete?">
              Delete
            </ConfirmButton>
          </>
        }
      />

      {startRun.error && <ErrorState title="Could not start the run" message={startRun.error} />}

      {/* ---------------- Configuration ---------------- */}
      <section className="grid items-start gap-4 xl:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Prompt</CardTitle>
            <CopyButton value={data.prompt} />
          </CardHeader>
          <CardContent className="space-y-3">
            <pre className="whitespace-pre-wrap break-words rounded border border-line bg-bg p-3 font-mono text-[13px] leading-relaxed text-fg">
              {data.prompt}
            </pre>
            {data.system_prompt && (
              <Collapsible title="System prompt">
                <pre className="whitespace-pre-wrap break-words font-mono text-[13px] text-fg-muted">
                  {data.system_prompt}
                </pre>
              </Collapsible>
            )}
            {data.variants.length > 0 && (
              <Collapsible title={`Prompt variants (${data.variants.length})`}>
                <div className="space-y-2">
                  {data.variants.map((variant) => (
                    <div key={variant.id}>
                      <p className="text-xs font-medium text-fg">{variant.name}</p>
                      <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[12px] text-fg-muted">
                        {variant.prompt}
                      </pre>
                    </div>
                  ))}
                </div>
              </Collapsible>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <Row label="Models">
              <div className="flex flex-wrap justify-end gap-1">
                {data.models.map((model) => (
                  <Badge key={`${model.provider}:${model.model}`} tone="neutral">
                    {model.model}
                  </Badge>
                ))}
              </div>
            </Row>
            <Row label="Temperature">{data.temperature}</Row>
            <Row label="Max tokens">{data.max_tokens.toLocaleString()}</Row>
            <Row label="Evaluation">{evaluationModeLabel(data.evaluation_mode)}</Row>
            {data.judge_model && (
              <Row label="Judge">
                {data.judge_provider}:{data.judge_model}
              </Row>
            )}
            <Row label="Created">{formatDate(data.created_at)}</Row>
            {data.tags.length > 0 && (
              <Row label="Tags">
                <div className="flex flex-wrap justify-end gap-1">
                  {data.tags.map((tag) => (
                    <Badge key={tag} tone="muted">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </Row>
            )}
          </CardContent>
        </Card>
      </section>

      {/* ---------------- Live progress ---------------- */}
      {progress && activeRunId !== null && (
        <RunProgressPanel
          progress={progress}
          transport={transport}
          cancelling={cancelRun.pending}
          onCancel={() => void cancelRun.run()}
        />
      )}

      {/* ---------------- Run selector ---------------- */}
      {data.runs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="run-select" className="label-caps">
            Run
          </label>
          <Select
            id="run-select"
            className="h-8 w-auto min-w-[260px] text-xs"
            value={selectedRunId ?? ''}
            onChange={(event) => setSelectedRunId(Number(event.target.value))}
          >
            {data.runs.map((summary) => (
              <option key={summary.id} value={summary.id}>
                #{summary.id} · {formatDate(summary.started_at)} · {summary.status} ·{' '}
                {summary.success_count}/{summary.result_count} ok
              </option>
            ))}
          </Select>
          {run && <StatusBadge status={run.status} />}
          {run?.duration_ms !== null && run?.duration_ms !== undefined && (
            <span className="text-xs text-fg-subtle">
              wall clock {formatLatency(run.duration_ms)}
            </span>
          )}
          {data.runs.length > 1 && (
            <span className="text-xs text-fg-subtle">
              {data.runs.length} runs recorded — compare across time
            </span>
          )}
        </div>
      )}

      {/* ---------------- Results ---------------- */}
      {data.runs.length === 0 ? (
        <EmptyState
          title="This benchmark has not been run yet"
          description="Run it to send the prompt to every selected model and record the comparison."
          action={
            <Button
              variant="primary"
              loading={startRun.pending}
              onClick={() => void startRun.run()}
            >
              Run benchmark
            </Button>
          }
        />
      ) : runDetail.loading && !run ? (
        <LoadingPanel rows={6} />
      ) : runDetail.error ? (
        <ErrorState message={runDetail.error} onRetry={runDetail.reload} />
      ) : results.length === 0 ? (
        <EmptyState title="This run recorded no results." />
      ) : (
        <>
          <ComparisonTable results={results} />
          {unpriced > 0 && (
            <InlineNote>
              Costs are <strong>estimated</strong> from the configured price table. {unpriced} model
              {unpriced === 1 ? ' has' : 's have'} no configured price and show “Pricing
              unavailable” rather than zero.
            </InlineNote>
          )}

          {hasVariants && <VariantMatrix results={results} />}

          <Tabs
            items={[
              { id: 'responses', label: 'Responses', count: results.length },
              { id: 'charts', label: 'Charts' },
              { id: 'evaluation', label: 'Evaluation' },
            ]}
            active={tab}
            onChange={setTab}
          />

          {tab === 'responses' && (
            <div className="grid gap-4 2xl:grid-cols-2">
              {results.map((result) => (
                <ResponseCard
                  key={result.id}
                  result={result}
                  retrying={retryResult.pending}
                  onRetry={(value) => void retryResult.run(value)}
                  onRemove={(value) => void removeResult.run(value)}
                  onScore={setScoringResult}
                />
              ))}
            </div>
          )}

          {tab === 'charts' && (
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartFrame title="Latency by model" subtitle="Lower is better">
                <CategoryBars
                  data={chartRows.map((row) => ({
                    label: row.label,
                    value: row.result.latency_ms,
                  }))}
                  format={(value) => formatLatency(value)}
                />
              </ChartFrame>

              <ChartFrame
                title="Estimated cost by model"
                subtitle="Lower is better"
                footnote={
                  unpriced > 0
                    ? `${unpriced} model${unpriced === 1 ? '' : 's'} omitted: no configured price.`
                    : 'Estimated from the configured price table.'
                }
              >
                <CategoryBars
                  data={chartRows.map((row) => ({
                    label: row.label,
                    value: row.result.estimated_cost,
                  }))}
                  format={(value) => formatCost(value)}
                />
              </ChartFrame>

              <ChartFrame
                title="Quality by model"
                subtitle="Overall evaluation score, higher is better"
              >
                <CategoryBars
                  data={chartRows.map((row) => ({
                    label: row.label,
                    value: row.result.evaluation?.overall ?? null,
                  }))}
                  format={(value) => formatScore(value)}
                />
              </ChartFrame>

              <ChartFrame title="Token usage by model" subtitle="Total input + output tokens">
                <CategoryBars
                  data={chartRows.map((row) => ({
                    label: row.label,
                    value: row.result.total_tokens,
                  }))}
                  format={(value) => formatTokens(value)}
                />
              </ChartFrame>
            </div>
          )}

          {tab === 'evaluation' && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-fg-muted">Re-score this run:</span>
                <Button
                  size="sm"
                  loading={rescore.pending}
                  onClick={() => void rescore.run('heuristic')}
                >
                  Heuristic (offline)
                </Button>
                {data.judge_provider && data.judge_model && (
                  <Button
                    size="sm"
                    loading={rescore.pending}
                    onClick={() => void rescore.run('llm_judge')}
                  >
                    LLM judge ({data.judge_model})
                  </Button>
                )}
                <span className="text-xs text-fg-subtle">
                  or score individual responses by hand from the Responses tab.
                </span>
              </div>
              {rescore.error && <ErrorState message={rescore.error} />}

              <ChartFrame
                title="Evaluation criteria by model"
                subtitle="All four criteria share the 0–10 scale"
                height={300}
                footnote="Scores are only comparable between rows evaluated in the same mode."
              >
                <GroupedBars
                  data={criteriaData}
                  domain={[0, 10]}
                  series={[
                    { key: 'relevance', label: 'Relevance' },
                    { key: 'correctness', label: 'Correctness' },
                    { key: 'conciseness', label: 'Conciseness' },
                    { key: 'clarity', label: 'Clarity' },
                  ]}
                  format={(value) => formatScore(value)}
                  height={300}
                />
              </ChartFrame>

              <Card>
                <CardHeader>
                  <CardTitle>Evaluator notes</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {successes.filter((r) => r.evaluation?.reasoning).length === 0 ? (
                    <p className="text-xs text-fg-subtle">No evaluator notes recorded.</p>
                  ) : (
                    successes
                      .filter((r) => r.evaluation?.reasoning)
                      .map((result) => (
                        <div key={result.id} className="border-l-2 border-line pl-3">
                          <p className="font-mono text-xs text-fg">
                            {result.model}{' '}
                            <span className="font-sans text-fg-subtle">
                              {providerLabel(result.provider)} ·{' '}
                              {formatScore(result.evaluation?.overall)}/10
                            </span>
                          </p>
                          <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">
                            {result.evaluation?.reasoning}
                          </p>
                        </div>
                      ))
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </>
      )}

      <ManualScoreDialog
        result={scoringResult}
        onClose={() => setScoringResult(null)}
        onSaved={() => {
          toast('Score saved.', 'success');
          runDetail.reload();
        }}
      />
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 text-xs text-fg-subtle">{label}</span>
      <span className="text-right text-xs text-fg">{children}</span>
    </div>
  );
}
