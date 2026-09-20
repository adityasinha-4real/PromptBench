'use client';

import { useState } from 'react';
import { Badge, StatusBadge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/feedback';
import { Collapsible, ConfirmButton, CopyButton } from '@/components/ui/misc';
import { cn } from '@/lib/utils';
import {
  errorLabel,
  formatCost,
  formatLatency,
  formatScore,
  formatThroughput,
  formatTokens,
  providerLabel,
} from '@/lib/format';
import type { ModelResult } from '@/types';

const COLLAPSED_HEIGHT = 280;

function Metric({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="label-caps">{label}</p>
      <p className={cn('mt-0.5 text-sm text-fg', mono && 'tabular')}>{value}</p>
    </div>
  );
}

export interface ResponseCardProps {
  result: ModelResult;
  onRetry?: (result: ModelResult) => void;
  onRemove?: (result: ModelResult) => void;
  onScore?: (result: ModelResult) => void;
  retrying?: boolean;
}

/**
 * One model's answer, with its metrics, evaluation and raw provider metadata.
 */
export function ResponseCard({ result, onRetry, onRemove, onScore, retrying }: ResponseCardProps) {
  const [expanded, setExpanded] = useState(false);
  const failed = result.status !== 'success';
  const response = result.response ?? '';
  const long = response.length > 900;

  return (
    <article className="panel flex flex-col">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-mono text-sm font-medium text-fg">{result.model}</h3>
            <StatusBadge status={result.status} />
            {result.variant_name !== 'Default' && (
              <Badge tone="neutral">{result.variant_name}</Badge>
            )}
          </div>
          <p className="mt-0.5 text-xs text-fg-subtle">
            {providerLabel(result.provider)}
            {result.finish_reason && ` · finish: ${result.finish_reason}`}
            {result.attempts > 1 && ` · ${result.attempts} attempts`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1">
          {!failed && <CopyButton value={response} label="Copy" />}
          {onRetry && (
            <Button size="sm" variant="ghost" loading={retrying} onClick={() => onRetry(result)}>
              <span aria-hidden="true">↻</span> Retry
            </Button>
          )}
          {onScore && !failed && (
            <Button size="sm" variant="ghost" onClick={() => onScore(result)}>
              <span aria-hidden="true">☆</span> Score
            </Button>
          )}
          {onRemove && (
            <ConfirmButton
              variant="ghost"
              onConfirm={() => onRemove(result)}
              confirmLabel="Remove?"
            >
              <span aria-hidden="true">✕</span> Remove
            </ConfirmButton>
          )}
        </div>
      </header>

      {failed ? (
        <div className="p-4">
          <ErrorState
            title={`${providerLabel(result.provider)} — ${errorLabel(result.error_code)}`}
            message={result.error_message ?? 'The provider returned an error.'}
            hint={
              result.attempts > 1
                ? `Retried ${result.attempts - 1} time${result.attempts === 2 ? '' : 's'} before giving up.`
                : undefined
            }
            onRetry={onRetry ? () => onRetry(result) : undefined}
          />
        </div>
      ) : (
        <>
          <div className="relative">
            <div
              className="overflow-y-auto px-4 py-3"
              style={{ maxHeight: expanded ? 'none' : COLLAPSED_HEIGHT }}
            >
              <pre className="whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-fg">
                {response || <span className="text-fg-subtle">(empty response)</span>}
              </pre>
            </div>
            {long && !expanded && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-surface to-transparent" />
            )}
          </div>

          {long && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
              className="border-t border-line px-4 py-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
            >
              {expanded
                ? 'Collapse'
                : `Expand full response (${response.length.toLocaleString()} chars)`}
            </button>
          )}

          <div className="grid grid-cols-2 gap-3 border-t border-line px-4 py-3 sm:grid-cols-4">
            <Metric label="Latency" value={formatLatency(result.latency_ms)} />
            <Metric label="Tokens" value={formatTokens(result.total_tokens)} />
            <Metric label="Throughput" value={formatThroughput(result.tokens_per_second)} />
            <Metric label="Est. cost" value={formatCost(result.estimated_cost)} />
          </div>

          {result.evaluation ? (
            <div className="border-t border-line px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <p className="label-caps">Evaluation</p>
                <span className="text-xs text-fg-subtle">
                  {result.evaluation.mode}
                  {result.evaluation.evaluator_model && ` · ${result.evaluation.evaluator_model}`}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {(
                  [
                    ['Relevance', result.evaluation.relevance],
                    ['Correctness', result.evaluation.correctness],
                    ['Conciseness', result.evaluation.conciseness],
                    ['Clarity', result.evaluation.clarity],
                    ['Overall', result.evaluation.overall],
                  ] as const
                ).map(([label, value], index) => (
                  <div
                    key={label}
                    className={cn(
                      'rounded border border-line px-2 py-1.5',
                      index === 4 && 'border-accent bg-accent-soft'
                    )}
                  >
                    <p className="label-caps">{label}</p>
                    <p className="tabular mt-0.5 text-sm font-medium text-fg">
                      {formatScore(value)}
                      <span className="text-[11px] font-normal text-fg-subtle"> /10</span>
                    </p>
                  </div>
                ))}
              </div>
              {result.evaluation.reasoning && (
                <p className="mt-2 border-l-2 border-line pl-2.5 text-xs leading-relaxed text-fg-subtle">
                  {result.evaluation.reasoning}
                </p>
              )}
            </div>
          ) : (
            <div className="border-t border-line px-4 py-2">
              <p className="text-xs text-fg-subtle">
                Not scored.
                {typeof result.metadata?.evaluation_error === 'string' &&
                  ` Evaluation failed: ${result.metadata.evaluation_error}`}
              </p>
            </div>
          )}

          <div className="border-t border-line p-3">
            <TechnicalDetails result={result} />
          </div>
        </>
      )}
    </article>
  );
}

/**
 * Raw provider metadata. Shows only what the adapter recorded — API keys are
 * never part of the metadata the backend stores or returns.
 */
export function TechnicalDetails({ result }: { result: ModelResult }) {
  const params = result.request_params ?? {};
  const metadata = result.metadata ?? {};

  return (
    <Collapsible title="Technical details">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
        <Detail label="Provider" value={result.provider} />
        <Detail label="Model" value={result.model} />
        <Detail label="Result id" value={String(result.id)} />
        <Detail label="Request id" value={(metadata.request_id as string) ?? '—'} />
        <Detail label="Finish reason" value={result.finish_reason ?? '—'} />
        <Detail label="Attempts" value={String(result.attempts)} />
        <Detail label="Input tokens" value={formatTokens(result.input_tokens)} />
        <Detail label="Output tokens" value={formatTokens(result.output_tokens)} />
        <Detail
          label="Token source"
          value={
            result.token_source === 'estimated'
              ? 'estimated (provider reported none)'
              : (result.token_source ?? '—')
          }
        />
        <Detail label="Temperature" value={String(params.temperature ?? '—')} />
        <Detail label="Max tokens" value={String(params.max_tokens ?? '—')} />
        <Detail label="Top P" value={String(params.top_p ?? '—')} />
      </dl>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between">
          <p className="label-caps">Raw provider metadata</p>
          <CopyButton value={JSON.stringify(metadata, null, 2)} label="Copy JSON" />
        </div>
        <pre className="max-h-64 overflow-auto rounded border border-line bg-bg p-2.5 font-mono text-[11px] leading-relaxed text-fg-muted">
          {JSON.stringify(metadata, null, 2)}
        </pre>
      </div>
    </Collapsible>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="label-caps">{label}</dt>
      <dd className="truncate font-mono text-fg-muted" title={value}>
        {value}
      </dd>
    </div>
  );
}
