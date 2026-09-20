'use client';

import Link from 'next/link';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState, LoadingPanel } from '@/components/ui/feedback';
import { StatTile } from '@/components/ui/misc';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';
import {
  formatCost,
  formatLatency,
  formatRelative,
  formatScore,
  formatTokens,
  providerLabel,
} from '@/lib/format';

export default function DashboardPage() {
  const summary = useAsync(() => api.dashboard(), []);
  const recent = useAsync(() => api.listBenchmarks({ limit: 6, sort: 'created_at' }), []);
  const providers = useAsync(() => api.models(true), []);

  return (
    <>
      <PageHeader
        title="PromptBench"
        description="Benchmark LLMs. Compare quality, speed and cost."
        actions={
          <Link href="/benchmarks/new">
            <Button variant="primary">
              <span aria-hidden="true">＋</span> New Benchmark
            </Button>
          </Link>
        }
      />

      {summary.error && (
        <ErrorState
          title="Could not load dashboard statistics"
          message={summary.error}
          onRetry={summary.reload}
        />
      )}

      {summary.loading && !summary.data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <LoadingPanel key={index} rows={2} />
          ))}
        </div>
      ) : summary.data ? (
        <section aria-label="Overview" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Benchmarks"
            value={summary.data.totals.total_benchmarks}
            sub={`${summary.data.totals.total_runs} run${summary.data.totals.total_runs === 1 ? '' : 's'}`}
          />
          <StatTile
            label="Model executions"
            value={summary.data.totals.total_executions}
            sub={`${summary.data.totals.failed_executions} failed`}
          />
          <StatTile
            label="Average latency"
            value={formatLatency(summary.data.totals.avg_latency_ms)}
            sub={`${formatTokens(summary.data.totals.total_tokens)} tokens total`}
          />
          <StatTile
            label="Estimated spend"
            value={formatCost(summary.data.totals.total_cost)}
            sub={
              summary.data.totals.unpriced_executions > 0
                ? `Excludes ${summary.data.totals.unpriced_executions} unpriced run${summary.data.totals.unpriced_executions === 1 ? '' : 's'}`
                : 'Estimated from the price table'
            }
          />
        </section>
      ) : null}

      <div className="grid items-start gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Recent benchmarks</CardTitle>
            </div>
            <Link href="/history" className="text-xs text-accent hover:underline">
              View all →
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {recent.loading && !recent.data ? (
              <div className="p-4">
                <LoadingPanel rows={4} />
              </div>
            ) : recent.error ? (
              <div className="p-4">
                <ErrorState message={recent.error} onRetry={recent.reload} />
              </div>
            ) : !recent.data || recent.data.items.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title="No benchmarks yet"
                  description="Create one to compare models on the same prompt. Ollama works with no API key."
                  action={
                    <Link href="/benchmarks/new">
                      <Button variant="primary" size="sm">
                        Create your first benchmark
                      </Button>
                    </Link>
                  }
                />
              </div>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Benchmark</TH>
                    <TH>Models</TH>
                    <TH numeric>Quality</TH>
                    <TH numeric>Cost</TH>
                    <TH>Last run</TH>
                  </TR>
                </THead>
                <TBody>
                  {recent.data.items.map((item) => (
                    <TR key={item.id}>
                      <TD>
                        <Link
                          href={`/benchmarks/${item.id}`}
                          className="font-medium text-fg hover:text-accent"
                        >
                          {item.name}
                        </Link>
                        <p className="mt-0.5 line-clamp-1 text-xs text-fg-subtle">
                          {item.prompt_excerpt}
                        </p>
                      </TD>
                      <TD className="text-fg-muted">{item.model_count}</TD>
                      <TD numeric>{formatScore(item.avg_quality)}</TD>
                      <TD numeric>{formatCost(item.total_cost)}</TD>
                      <TD className="whitespace-nowrap text-xs text-fg-subtle">
                        {item.last_run_at ? formatRelative(item.last_run_at) : 'Never run'}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Providers</CardTitle>
              <Link href="/models" className="text-xs text-accent hover:underline">
                Configure →
              </Link>
            </CardHeader>
            <CardContent className="space-y-2 p-3">
              {providers.loading && !providers.data ? (
                <LoadingPanel rows={4} />
              ) : providers.error ? (
                <ErrorState message={providers.error} onRetry={providers.reload} />
              ) : (
                providers.data?.providers.map((provider) => (
                  <div
                    key={provider.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-line px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-fg">{provider.label}</p>
                      <p className="truncate text-xs text-fg-subtle">
                        {provider.models.length} model
                        {provider.models.length === 1 ? '' : 's'}
                      </p>
                    </div>
                    <Badge tone={provider.available ? 'ok' : 'muted'}>
                      <span aria-hidden="true">{provider.available ? '✓' : '○'}</span>
                      {provider.available ? 'Available' : 'Unavailable'}
                    </Badge>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Top models by volume</CardTitle>
              <Link href="/analytics" className="text-xs text-accent hover:underline">
                Analytics →
              </Link>
            </CardHeader>
            <CardContent className="p-0">
              {summary.data && summary.data.top_models.length > 0 ? (
                <Table>
                  <THead>
                    <TR>
                      <TH>Model</TH>
                      <TH numeric>Runs</TH>
                      <TH numeric>Latency</TH>
                      <TH numeric>Quality</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {summary.data.top_models.map((stat) => (
                      <TR key={`${stat.provider}:${stat.model}`}>
                        <TD>
                          <span className="font-mono text-xs text-fg">{stat.model}</span>
                          <span className="ml-1.5 text-[11px] text-fg-subtle">
                            {providerLabel(stat.provider)}
                          </span>
                        </TD>
                        <TD numeric>{stat.executions}</TD>
                        <TD numeric>{formatLatency(stat.avg_latency_ms)}</TD>
                        <TD numeric>{formatScore(stat.avg_quality)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              ) : (
                <p className="p-4 text-xs text-fg-subtle">
                  Run a benchmark to populate model statistics.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
