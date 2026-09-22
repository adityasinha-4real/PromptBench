'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState, InlineNote, LoadingPanel } from '@/components/ui/feedback';
import { Select } from '@/components/ui/input';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';
import {
  formatCost,
  formatDate,
  formatLatency,
  formatScore,
  formatTokens,
  providerLabel,
} from '@/lib/format';
import type { EntryChange, MetricDelta, RunSummary } from '@/types';

const CHANGE_TONE: Record<EntryChange, 'ok' | 'danger' | 'warn' | 'accent' | 'muted' | 'neutral'> =
  {
    improved: 'ok',
    regressed: 'danger',
    mixed: 'warn',
    added: 'accent',
    removed: 'muted',
    unchanged: 'neutral',
  };

const CHANGE_LABEL: Record<EntryChange, string> = {
  improved: 'Improved',
  regressed: 'Regressed',
  mixed: 'Mixed',
  added: 'New',
  removed: 'Gone',
  unchanged: 'Unchanged',
};

/**
 * One metric: the newer value, then how it moved.
 *
 * Direction is never carried by colour alone — every delta has an arrow and a
 * sign — and a missing value reads as "no comparison", never as zero.
 */
function DeltaCell({
  metric,
  format,
  label,
}: {
  metric: MetricDelta;
  format: (value: number | null) => string;
  label: string;
}) {
  const { delta, direction, target, percent_change: percent } = metric;

  if (delta === null) {
    const reason =
      target === null && metric.base === null
        ? `No ${label} recorded in either run.`
        : `Recorded in only one of the two runs, so ${label} is not compared.`;
    return (
      <TD numeric>
        <span className="text-fg">{format(target)}</span>
        <span className="ml-2 text-fg-subtle" title={reason}>
          n/a
        </span>
      </TD>
    );
  }

  const tone =
    direction === 'better'
      ? 'text-[#5fd08a]'
      : direction === 'worse'
        ? 'text-[#f18e8e]'
        : 'text-fg-subtle';
  const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '=';
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';

  return (
    <TD numeric>
      <span className="text-fg">{format(target)}</span>{' '}
      <span
        className={tone}
        title={`${label}: ${format(metric.base)} → ${format(target)} (${direction})`}
      >
        {arrow} {sign}
        {format(Math.abs(delta))}
        {percent !== null && ` (${sign}${Math.abs(percent).toFixed(1)}%)`}
      </span>
    </TD>
  );
}

export interface RunComparisonProps {
  benchmarkId: number;
  runs: RunSummary[];
}

export function RunComparison({ benchmarkId, runs }: RunComparisonProps) {
  // `runs` arrives newest first.
  const [targetRunId, setTargetRunId] = useState<number>(runs[0]?.id ?? 0);
  const [baseRunId, setBaseRunId] = useState<number>(runs[1]?.id ?? 0);

  // With fewer than two runs there is nothing to ask the backend for, and
  // asking anyway would send a run id of 0.
  const comparable = runs.length > 1 && baseRunId > 0 && targetRunId > 0;
  const comparison = useAsync(
    () =>
      comparable ? api.compareRuns(benchmarkId, baseRunId, targetRunId) : Promise.resolve(null),
    [benchmarkId, baseRunId, targetRunId, comparable]
  );

  const data = comparison.data;
  const summary = data?.summary;
  const counts = useMemo(
    () =>
      summary
        ? ([
            ['improved', summary.improved, 'ok'],
            ['regressed', summary.regressed, 'danger'],
            ['mixed', summary.mixed, 'warn'],
            ['unchanged', summary.unchanged, 'neutral'],
            ['added', summary.added, 'accent'],
            ['removed', summary.removed, 'muted'],
          ] as const)
        : [],
    [summary]
  );

  if (runs.length < 2) {
    return (
      <EmptyState
        title="Only one run so far"
        description="Re-run this benchmark to compare the two against each other."
      />
    );
  }

  const runOption = (summary: RunSummary) =>
    `#${summary.id} · ${formatDate(summary.started_at)} · ${summary.success_count}/${summary.result_count} ok`;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>What changed between runs</CardTitle>
          <p className="mt-0.5 text-xs text-fg-subtle">
            Every metric is judged on its own — higher quality, lower latency and cost are better.
            There is no combined score.
          </p>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label htmlFor="compare-base" className="label-caps block">
              Older run
            </label>
            <Select
              id="compare-base"
              className="h-8 w-auto min-w-[240px] text-xs"
              value={baseRunId}
              onChange={(event) => setBaseRunId(Number(event.target.value))}
            >
              {runs.map((summary) => (
                <option key={summary.id} value={summary.id} disabled={summary.id === targetRunId}>
                  {runOption(summary)}
                </option>
              ))}
            </Select>
          </div>
          <span aria-hidden className="pb-1.5 text-fg-subtle">
            →
          </span>
          <div className="space-y-1">
            <label htmlFor="compare-target" className="label-caps block">
              Newer run
            </label>
            <Select
              id="compare-target"
              className="h-8 w-auto min-w-[240px] text-xs"
              value={targetRunId}
              onChange={(event) => setTargetRunId(Number(event.target.value))}
            >
              {runs.map((summary) => (
                <option key={summary.id} value={summary.id} disabled={summary.id === baseRunId}>
                  {runOption(summary)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {comparison.loading && !data ? (
          <LoadingPanel rows={4} />
        ) : comparison.error ? (
          <ErrorState message={comparison.error} onRetry={comparison.reload} />
        ) : data && summary ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              {counts
                .filter(([, count]) => count > 0)
                .map(([name, count, tone]) => (
                  <Badge key={name} tone={tone}>
                    {count} {name}
                  </Badge>
                ))}
              {summary.new_failures > 0 && (
                <Badge tone="danger">
                  {summary.new_failures} new failure{summary.new_failures === 1 ? '' : 's'}
                </Badge>
              )}
              {summary.fixed_failures > 0 && (
                <Badge tone="ok">
                  {summary.fixed_failures} failure{summary.fixed_failures === 1 ? '' : 's'} fixed
                </Badge>
              )}
            </div>

            {data.notes.map((note) => (
              <InlineNote key={note}>{note}</InlineNote>
            ))}

            <Table>
              <THead>
                <TR>
                  <TH>Model</TH>
                  <TH numeric>Quality</TH>
                  <TH numeric>Latency</TH>
                  <TH numeric>Est. cost</TH>
                  <TH numeric>Tokens</TH>
                  <TH>Verdict</TH>
                </TR>
              </THead>
              <TBody>
                {data.entries.map((entry) => (
                  <TR key={entry.key}>
                    <TD>
                      <span className="text-fg">{entry.model}</span>
                      <span className="ml-1.5 text-xs text-fg-subtle">
                        {providerLabel(entry.provider)}
                      </span>
                      {entry.variant_name !== 'Default' && (
                        <span className="ml-1.5 text-xs text-fg-muted">{entry.variant_name}</span>
                      )}
                    </TD>
                    <DeltaCell metric={entry.quality} format={formatScore} label="quality" />
                    <DeltaCell metric={entry.latency_ms} format={formatLatency} label="latency" />
                    <DeltaCell
                      metric={entry.estimated_cost}
                      format={formatCost}
                      label="estimated cost"
                    />
                    <DeltaCell metric={entry.total_tokens} format={formatTokens} label="tokens" />
                    <TD>
                      <Badge tone={CHANGE_TONE[entry.change]}>{CHANGE_LABEL[entry.change]}</Badge>
                      {entry.note && (
                        <span className="ml-1.5 text-xs text-fg-subtle">{entry.note}</span>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>

            <InlineNote>
              Costs are <strong>estimated</strong> from the price table, so a cost delta moves with
              token counts, not with a vendor invoice.
            </InlineNote>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
