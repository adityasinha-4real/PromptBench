'use client';

import { useMemo, useState } from 'react';
import { CategoryBars, ChartFrame, TrendLine } from '@/components/charts/chart-kit';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState, InlineNote, LoadingPanel } from '@/components/ui/feedback';
import { Input, Select } from '@/components/ui/input';
import { StatTile, Tabs } from '@/components/ui/misc';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';
import {
  formatCost,
  formatLatency,
  formatNumber,
  formatPercent,
  formatScore,
  formatThroughput,
  formatTokens,
  providerLabel,
} from '@/lib/format';

export default function AnalyticsPage() {
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [metric, setMetric] = useState('quality');
  const [minExecutions, setMinExecutions] = useState(1);
  const [tab, setTab] = useState('overview');

  const filters = useMemo(
    () => ({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      provider: provider || undefined,
      model: model || undefined,
    }),
    [dateFrom, dateTo, provider, model]
  );

  const analytics = useAsync(() => api.analytics(filters), [dateFrom, dateTo, provider, model]);
  const metrics = useAsync(() => api.leaderboardMetrics(), []);
  const leaderboard = useAsync(
    () => api.leaderboard(metric, minExecutions, filters),
    [metric, minExecutions, dateFrom, dateTo, provider, model]
  );
  const providers = useAsync(() => api.models(false), []);

  const data = analytics.data;
  const byModel = data?.by_model ?? [];
  const label = (stat: { provider: string; model: string }) => stat.model;

  const unpriced = data?.totals.unpriced_executions ?? 0;
  const hasData = (data?.totals.total_executions ?? 0) > 0;

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Aggregate latency, cost, token usage and quality across every recorded run."
      />

      <section className="flex flex-wrap items-end gap-2" aria-label="Filters">
        <div>
          <label htmlFor="from" className="label-caps mb-1 block">
            From
          </label>
          <Input
            id="from"
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            className="w-40"
          />
        </div>
        <div>
          <label htmlFor="to" className="label-caps mb-1 block">
            To
          </label>
          <Input
            id="to"
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            className="w-40"
          />
        </div>
        <div>
          <label htmlFor="provider-filter" className="label-caps mb-1 block">
            Provider
          </label>
          <Select
            id="provider-filter"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            className="w-40"
          >
            <option value="">All</option>
            {providers.data?.providers.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="model-filter" className="label-caps mb-1 block">
            Model
          </label>
          <Select
            id="model-filter"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="w-48"
          >
            <option value="">All</option>
            {byModel.map((stat) => (
              <option key={`${stat.provider}:${stat.model}`} value={stat.model}>
                {stat.model}
              </option>
            ))}
          </Select>
        </div>
        {(dateFrom || dateTo || provider || model) && (
          <button
            type="button"
            className="h-9 px-2 text-xs text-fg-muted hover:text-fg"
            onClick={() => {
              setDateFrom('');
              setDateTo('');
              setProvider('');
              setModel('');
            }}
          >
            Clear filters
          </button>
        )}
      </section>

      {analytics.error && <ErrorState message={analytics.error} onRetry={analytics.reload} />}

      {analytics.loading && !data ? (
        <LoadingPanel rows={6} />
      ) : !hasData ? (
        <EmptyState
          title="No executions recorded for this range"
          description="Run a benchmark, or widen the date filter."
        />
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
            <StatTile label="Benchmarks" value={data!.totals.total_benchmarks} />
            <StatTile
              label="Executions"
              value={data!.totals.total_executions}
              sub={`${data!.totals.failed_executions} failed`}
            />
            <StatTile label="Avg latency" value={formatLatency(data!.totals.avg_latency_ms)} />
            <StatTile
              label="Avg cost"
              value={formatCost(data!.totals.avg_cost)}
              sub={`total ${formatCost(data!.totals.total_cost)}`}
            />
            <StatTile
              label="Avg quality"
              value={formatScore(data!.totals.avg_quality)}
              sub="/ 10"
            />
            <StatTile
              label="Total tokens"
              value={formatTokens(data!.totals.total_tokens)}
              sub={`${formatTokens(data!.totals.total_output_tokens)} out`}
            />
          </section>

          {unpriced > 0 && (
            <InlineNote>
              {unpriced} execution{unpriced === 1 ? '' : 's'} ran on a model with no configured
              price and {unpriced === 1 ? 'is' : 'are'} excluded from cost figures rather than
              counted as free.
            </InlineNote>
          )}

          <Tabs
            items={[
              { id: 'overview', label: 'Charts' },
              { id: 'leaderboard', label: 'Leaderboard' },
              { id: 'table', label: 'Model table', count: byModel.length },
            ]}
            active={tab}
            onChange={setTab}
          />

          {tab === 'overview' && (
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartFrame title="Average latency by model" subtitle="Lower is better">
                <CategoryBars
                  data={byModel.map((stat) => ({
                    label: label(stat),
                    value: stat.avg_latency_ms,
                  }))}
                  format={(value) => formatLatency(value)}
                />
              </ChartFrame>

              <ChartFrame
                title="Total estimated cost by model"
                subtitle="Lower is better"
                footnote="Unpriced models are omitted, not plotted as zero."
              >
                <CategoryBars
                  data={byModel.map((stat) => ({ label: label(stat), value: stat.total_cost }))}
                  format={(value) => formatCost(value)}
                />
              </ChartFrame>

              <ChartFrame
                title="Average quality by model"
                subtitle="Overall score, higher is better"
              >
                <CategoryBars
                  data={byModel.map((stat) => ({ label: label(stat), value: stat.avg_quality }))}
                  format={(value) => formatScore(value)}
                />
              </ChartFrame>

              <ChartFrame title="Total token usage by model">
                <CategoryBars
                  data={byModel.map((stat) => ({ label: label(stat), value: stat.total_tokens }))}
                  format={(value) => formatTokens(value)}
                />
              </ChartFrame>

              <ChartFrame title="Executions over time" subtitle="Model calls recorded per day">
                <TrendLine
                  data={data!.timeline}
                  dataKey="executions"
                  label="Executions"
                  format={(value) => formatNumber(value)}
                />
              </ChartFrame>

              <ChartFrame title="Average latency over time" subtitle="Per day, across all models">
                <TrendLine
                  data={data!.timeline}
                  dataKey="avg_latency_ms"
                  label="Avg latency"
                  format={(value) => formatLatency(value)}
                  colorIndex={1}
                />
              </ChartFrame>

              {data!.errors.length > 0 && (
                <Card className="xl:col-span-2">
                  <CardHeader>
                    <CardTitle>Failures by cause</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    {data!.errors.map((error) => (
                      <Badge key={error.code} tone="danger">
                        {error.code.replace(/_/g, ' ')} · {error.count}
                      </Badge>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {tab === 'leaderboard' && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-end gap-2">
                <div>
                  <label htmlFor="metric" className="label-caps mb-1 block">
                    Rank by
                  </label>
                  <Select
                    id="metric"
                    value={metric}
                    onChange={(event) => setMetric(event.target.value)}
                    className="w-56"
                  >
                    {(metrics.data?.metrics ?? []).map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id.replace(/_/g, ' ')} (
                        {item.direction === 'desc' ? 'higher is better' : 'lower is better'})
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <label htmlFor="min-exec" className="label-caps mb-1 block">
                    Min executions
                  </label>
                  <Input
                    id="min-exec"
                    type="number"
                    min={1}
                    value={minExecutions}
                    onChange={(event) => setMinExecutions(Math.max(1, Number(event.target.value)))}
                    className="w-28"
                  />
                </div>
              </div>

              {leaderboard.error && <ErrorState message={leaderboard.error} />}

              <div className="panel">
                <Table>
                  <THead>
                    <TR>
                      <TH numeric>#</TH>
                      <TH>Model</TH>
                      <TH numeric>Executions</TH>
                      <TH numeric>Success</TH>
                      <TH numeric>Quality</TH>
                      <TH numeric>Latency</TH>
                      <TH numeric>p95</TH>
                      <TH numeric>Tok/s</TH>
                      <TH numeric>Avg cost</TH>
                      <TH numeric>Cost / 1K</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {(leaderboard.data?.entries ?? []).map((entry) => (
                      <TR key={`${entry.provider}:${entry.model}`}>
                        <TD numeric className="text-fg-subtle">
                          {entry.rank}
                        </TD>
                        <TD>
                          <span className="font-mono text-xs text-fg">{entry.model}</span>
                          <span className="ml-1.5 text-[11px] text-fg-subtle">
                            {providerLabel(entry.provider)}
                          </span>
                        </TD>
                        <TD numeric>{entry.executions}</TD>
                        <TD numeric>{formatPercent(entry.success_rate)}</TD>
                        <TD numeric>{formatScore(entry.avg_quality)}</TD>
                        <TD numeric>{formatLatency(entry.avg_latency_ms)}</TD>
                        <TD numeric>{formatLatency(entry.p95_latency_ms)}</TD>
                        <TD numeric>{formatThroughput(entry.avg_tokens_per_second)}</TD>
                        <TD numeric className={entry.priced ? '' : 'text-xs text-fg-subtle'}>
                          {formatCost(entry.avg_cost)}
                        </TD>
                        <TD numeric className={entry.priced ? '' : 'text-xs text-fg-subtle'}>
                          {formatCost(entry.cost_per_1k_tokens)}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>

              {leaderboard.data && (
                <Card>
                  <CardHeader>
                    <CardTitle>Methodology</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="whitespace-pre-line text-xs leading-relaxed text-fg-muted">
                      {leaderboard.data.methodology}
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {tab === 'table' && (
            <div className="panel">
              <Table>
                <THead>
                  <TR>
                    <TH>Model</TH>
                    <TH>Provider</TH>
                    <TH numeric>Runs</TH>
                    <TH numeric>Failures</TH>
                    <TH numeric>Avg in</TH>
                    <TH numeric>Avg out</TH>
                    <TH numeric>Total tokens</TH>
                    <TH numeric>Relevance</TH>
                    <TH numeric>Correctness</TH>
                    <TH numeric>Conciseness</TH>
                    <TH numeric>Clarity</TH>
                    <TH numeric>Overall</TH>
                  </TR>
                </THead>
                <TBody>
                  {byModel.map((stat) => (
                    <TR key={`${stat.provider}:${stat.model}`}>
                      <TD className="font-mono text-xs">{stat.model}</TD>
                      <TD className="text-xs text-fg-muted">{providerLabel(stat.provider)}</TD>
                      <TD numeric>{stat.executions}</TD>
                      <TD numeric>{stat.failures}</TD>
                      <TD numeric>{formatNumber(stat.avg_input_tokens)}</TD>
                      <TD numeric>{formatNumber(stat.avg_output_tokens)}</TD>
                      <TD numeric>{formatTokens(stat.total_tokens)}</TD>
                      <TD numeric>{formatScore(stat.avg_relevance)}</TD>
                      <TD numeric>{formatScore(stat.avg_correctness)}</TD>
                      <TD numeric>{formatScore(stat.avg_conciseness)}</TD>
                      <TD numeric>{formatScore(stat.avg_clarity)}</TD>
                      <TD numeric className="font-medium text-fg">
                        {formatScore(stat.avg_quality)}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </>
      )}
    </>
  );
}
