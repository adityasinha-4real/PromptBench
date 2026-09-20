'use client';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { errorLabel, formatLatency, providerLabel } from '@/lib/format';
import type { RunProgress, RunTaskState } from '@/types';

const GLYPH: Record<string, string> = {
  queued: '○',
  running: '⟳',
  success: '✓',
  failed: '✕',
  cancelled: '⊘',
};

const TONE: Record<string, string> = {
  queued: 'text-fg-subtle',
  running: 'text-accent',
  success: 'text-[#5fd08a]',
  failed: 'text-[#f18e8e]',
  cancelled: 'text-[#e0b04a]',
};

function TaskRow({ task }: { task: RunTaskState }) {
  return (
    <li className="flex items-center gap-2.5 py-1.5 text-sm">
      <span
        aria-hidden="true"
        className={cn(
          'w-4 shrink-0 text-center',
          TONE[task.status],
          task.status === 'running' && 'animate-spin'
        )}
      >
        {GLYPH[task.status] ?? '•'}
      </span>
      <span className="truncate font-mono text-xs text-fg">{task.model}</span>
      <span className="shrink-0 text-[11px] text-fg-subtle">{providerLabel(task.provider)}</span>
      {task.variant_name !== 'Default' && (
        <span className="shrink-0 rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-subtle">
          {task.variant_name}
        </span>
      )}
      <span className="ml-auto shrink-0 text-right text-xs">
        {task.status === 'success' ? (
          <span className="tabular text-fg-muted">{formatLatency(task.latency_ms)}</span>
        ) : task.status === 'failed' ? (
          <span className="text-[#f18e8e]">{errorLabel(task.error_code)}</span>
        ) : task.status === 'running' ? (
          <span className="text-accent">
            running{task.attempts > 1 ? ` · retry ${task.attempts - 1}` : ''}…
          </span>
        ) : (
          <span className="text-fg-subtle">{task.status}</span>
        )}
      </span>
    </li>
  );
}

export interface RunProgressPanelProps {
  progress: RunProgress;
  onCancel?: () => void;
  cancelling?: boolean;
  transport?: 'idle' | 'sse' | 'poll';
}

/**
 * Live per-model execution state.
 *
 * Nothing here blocks the rest of the page: the panel updates in place as each
 * model finishes, and completed results render underneath while others run.
 */
export function RunProgressPanel({
  progress,
  onCancel,
  cancelling,
  transport,
}: RunProgressPanelProps) {
  const active = progress.status === 'running' || progress.status === 'pending';
  const percent = progress.total === 0 ? 0 : (progress.completed / progress.total) * 100;

  const failedTasks = progress.tasks.filter((task) => task.status === 'failed');

  return (
    <section className="panel p-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {active && <Spinner className="text-accent" />}
          <h2 className="text-sm font-medium text-fg">
            {active
              ? 'Running benchmark…'
              : progress.status === 'cancelled'
                ? 'Run cancelled'
                : progress.status === 'failed'
                  ? 'Run failed'
                  : 'Run complete'}
          </h2>
          <span className="tabular text-xs text-fg-subtle">
            {progress.completed} / {progress.total} · {progress.succeeded} succeeded
            {progress.failed > 0 && ` · ${progress.failed} failed`}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {transport === 'poll' && active && (
            <span className="text-[11px] text-fg-subtle">polling</span>
          )}
          {active && onCancel && (
            <Button size="sm" variant="outline" onClick={onCancel} loading={cancelling}>
              Cancel run
            </Button>
          )}
        </div>
      </div>

      <div
        className="mt-3 h-1 w-full overflow-hidden rounded-full bg-line"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={progress.total}
        aria-valuenow={progress.completed}
        aria-label="Benchmark progress"
      >
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-300',
            progress.failed > 0 && !active ? 'bg-[#e0b04a]' : 'bg-accent'
          )}
          style={{ width: `${percent}%` }}
        />
      </div>

      <ul className="mt-2 divide-y divide-line">
        {progress.tasks.map((task) => (
          <TaskRow key={task.key} task={task} />
        ))}
      </ul>

      {failedTasks.length > 0 && (
        <div className="mt-3 space-y-1 rounded-md border border-[#4a2327] bg-[#1d1315] p-3">
          {failedTasks.map((task) => (
            <p key={task.key} className="text-xs text-fg-muted">
              <span className="font-mono text-[#f5b3b3]">{task.model}</span> —{' '}
              {task.error_message ?? errorLabel(task.error_code)}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
