'use client';

import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import { errorLabel, formatCost, formatLatency, formatScore, providerLabel } from '@/lib/format';
import type { ModelResult } from '@/types';

/**
 * Model × prompt-variant matrix.
 *
 * Only rendered when a benchmark actually has variants — with a single prompt
 * the comparison table already says everything a 1-row matrix would.
 */
export function VariantMatrix({
  results,
  onSelect,
  selectedId,
}: {
  results: ModelResult[];
  onSelect?: (result: ModelResult) => void;
  selectedId?: number | null;
}) {
  const { variants, targets, cells } = useMemo(() => {
    const variantNames: string[] = [];
    const targetKeys: string[] = [];
    const grid = new Map<string, ModelResult>();

    for (const result of results) {
      if (!variantNames.includes(result.variant_name)) variantNames.push(result.variant_name);
      const target = `${result.provider}:${result.model}`;
      if (!targetKeys.includes(target)) targetKeys.push(target);
      grid.set(`${result.variant_name}|${target}`, result);
    }
    return { variants: variantNames, targets: targetKeys, cells: grid };
  }, [results]);

  if (variants.length < 2) return null;

  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">Results by prompt variant and model</caption>
        <thead>
          <tr className="border-b border-line">
            <th
              scope="col"
              className="label-caps sticky left-0 z-10 bg-surface px-4 py-3 text-left"
            >
              Variant
            </th>
            {targets.map((target) => {
              const [provider, ...rest] = target.split(':');
              return (
                <th key={target} scope="col" className="px-3 py-3 text-left">
                  <p className="truncate font-mono text-xs text-fg">{rest.join(':')}</p>
                  <p className="text-[11px] font-normal text-fg-subtle">
                    {providerLabel(provider ?? '')}
                  </p>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {variants.map((variant) => (
            <tr key={variant}>
              <th
                scope="row"
                className="sticky left-0 z-10 bg-surface px-4 py-2.5 text-left align-top text-xs font-medium text-fg-muted"
              >
                {variant}
              </th>
              {targets.map((target) => {
                const result = cells.get(`${variant}|${target}`);
                if (!result) {
                  return (
                    <td key={target} className="px-3 py-2.5 text-xs text-fg-subtle">
                      —
                    </td>
                  );
                }
                const failed = result.status !== 'success';
                return (
                  <td key={target} className="p-1.5 align-top">
                    <button
                      type="button"
                      onClick={() => onSelect?.(result)}
                      className={cn(
                        'w-full rounded border px-2.5 py-2 text-left transition-colors',
                        selectedId === result.id
                          ? 'border-accent bg-accent-soft'
                          : 'border-line hover:border-line-strong hover:bg-surface-2',
                        failed && 'border-[#4a2327] bg-[#1d1315]'
                      )}
                    >
                      {failed ? (
                        <span className="text-xs text-[#f18e8e]">
                          ✕ {errorLabel(result.error_code)}
                        </span>
                      ) : (
                        <>
                          <span className="tabular block text-sm font-medium text-fg">
                            {formatScore(result.evaluation?.overall)}
                            <span className="text-[11px] font-normal text-fg-subtle"> /10</span>
                          </span>
                          <span className="tabular mt-0.5 block text-[11px] text-fg-subtle">
                            {formatLatency(result.latency_ms)} · {formatCost(result.estimated_cost)}
                          </span>
                        </>
                      )}
                    </button>
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
