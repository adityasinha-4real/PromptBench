'use client';

import { useMemo } from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  PRICING_UNAVAILABLE,
  errorLabel,
  formatCost,
  formatLatency,
  formatScore,
  formatThroughput,
  formatTokens,
  providerLabel,
} from '@/lib/format';
import type { ModelResult } from '@/types';

type Direction = 'higher' | 'lower';

interface MetricRow {
  label: string;
  hint?: string;
  direction: Direction | null;
  value: (result: ModelResult) => number | null;
  render: (result: ModelResult) => string;
}

const ROWS: MetricRow[] = [
  {
    label: 'Quality',
    hint: 'Overall evaluation score, 0–10',
    direction: 'higher',
    value: (r) => r.evaluation?.overall ?? null,
    render: (r) => formatScore(r.evaluation?.overall),
  },
  {
    label: 'Latency',
    hint: 'Wall-clock time for the request',
    direction: 'lower',
    value: (r) => r.latency_ms,
    render: (r) => formatLatency(r.latency_ms),
  },
  {
    label: 'Tokens',
    hint: 'Input + output',
    direction: null,
    value: (r) => r.total_tokens,
    render: (r) => formatTokens(r.total_tokens),
  },
  {
    label: 'Output tokens',
    direction: null,
    value: (r) => r.output_tokens,
    render: (r) => formatTokens(r.output_tokens),
  },
  {
    label: 'Throughput',
    hint: 'Output tokens per second',
    direction: 'higher',
    value: (r) => r.tokens_per_second,
    render: (r) => formatThroughput(r.tokens_per_second),
  },
  {
    label: 'Est. cost',
    hint: 'Estimated from the configured price table',
    direction: 'lower',
    value: (r) => r.estimated_cost,
    render: (r) => formatCost(r.estimated_cost),
  },
  {
    label: 'Est. cost / 1K',
    hint: 'Blended cost per 1,000 tokens',
    direction: 'lower',
    value: (r) => r.cost_per_1k_tokens,
    render: (r) => formatCost(r.cost_per_1k_tokens),
  },
];

/**
 * The headline comparison: metrics down the side, models across the top.
 *
 * The best value in each row is marked with a glyph as well as weight, so the
 * signal is never carried by styling alone. Rows where "best" is meaningless
 * (raw token counts) are not marked at all.
 */
export function ComparisonTable({ results }: { results: ModelResult[] }) {
  const successes = useMemo(() => results.filter((r) => r.status === 'success'), [results]);

  const best = useMemo(() => {
    const map = new Map<string, number | null>();
    for (const row of ROWS) {
      if (!row.direction) {
        map.set(row.label, null);
        continue;
      }
      const values = successes
        .map(row.value)
        .filter((value): value is number => value !== null && value !== undefined);
      if (values.length < 2) {
        map.set(row.label, null);
        continue;
      }
      map.set(row.label, row.direction === 'higher' ? Math.max(...values) : Math.min(...values));
    }
    return map;
  }, [successes]);

  if (results.length === 0) return null;

  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">Metric comparison across models</caption>
        <thead>
          <tr className="border-b border-line">
            <th
              scope="col"
              className="label-caps sticky left-0 z-10 bg-surface px-4 py-3 text-left"
            >
              Metric
            </th>
            {results.map((result) => (
              <th key={result.id} scope="col" className="px-4 py-3 text-left align-top">
                <p className="truncate font-mono text-xs font-medium text-fg">{result.model}</p>
                <p className="mt-0.5 text-[11px] font-normal text-fg-subtle">
                  {providerLabel(result.provider)}
                  {result.variant_name !== 'Default' && ` · ${result.variant_name}`}
                </p>
                {result.status !== 'success' && (
                  <Badge tone="danger" className="mt-1">
                    {errorLabel(result.error_code)}
                  </Badge>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {ROWS.map((row) => (
            <tr key={row.label} className="hover:bg-surface-2">
              <th
                scope="row"
                className="sticky left-0 z-10 bg-surface px-4 py-2.5 text-left align-top font-normal"
              >
                <span className="text-fg-muted">{row.label}</span>
                {row.hint && <span className="block text-[11px] text-fg-subtle">{row.hint}</span>}
              </th>
              {results.map((result) => {
                const value = row.value(result);
                const target = best.get(row.label);
                const isBest = target !== null && target !== undefined && value === target;
                const rendered = result.status === 'success' ? row.render(result) : '—';
                return (
                  <td key={result.id} className="px-4 py-2.5 align-top">
                    <span
                      className={cn(
                        'tabular inline-flex items-center gap-1.5',
                        isBest ? 'font-semibold text-fg' : 'text-fg-muted',
                        rendered === PRICING_UNAVAILABLE && 'text-[11px] text-fg-subtle'
                      )}
                    >
                      {isBest && (
                        <span
                          aria-label="best in row"
                          title="Best in row"
                          className="text-[#5fd08a]"
                        >
                          ★
                        </span>
                      )}
                      {rendered}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
