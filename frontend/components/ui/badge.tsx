import { cn } from '@/lib/utils';
import type { ResultStatus, RunStatus } from '@/types';

type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'muted';

const TONES: Record<Tone, string> = {
  neutral: 'bg-elevated text-fg-muted border-line',
  accent: 'bg-accent-soft text-[#7db0f5] border-[#1f3c63]',
  ok: 'bg-[#0f2418] text-[#5fd08a] border-[#1c4029]',
  warn: 'bg-[#2c2410] text-[#e0b04a] border-[#4a3a15]',
  danger: 'bg-[#2c1618] text-[#f18e8e] border-[#4a2327]',
  muted: 'bg-transparent text-fg-subtle border-line',
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = 'neutral', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium leading-none whitespace-nowrap',
        TONES[tone],
        className
      )}
      {...props}
    />
  );
}

const STATUS_TONE: Record<string, Tone> = {
  success: 'ok',
  completed: 'ok',
  running: 'accent',
  pending: 'neutral',
  queued: 'muted',
  failed: 'danger',
  cancelled: 'warn',
};

const STATUS_LABEL: Record<string, string> = {
  success: 'Success',
  completed: 'Completed',
  running: 'Running',
  pending: 'Pending',
  queued: 'Queued',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

/** Status chip carrying a glyph as well as colour, so state is never colour-alone. */
export function StatusBadge({
  status,
  className,
}: {
  status: RunStatus | ResultStatus | string;
  className?: string;
}) {
  const glyph: Record<string, string> = {
    success: '✓',
    completed: '✓',
    running: '⟳',
    pending: '○',
    queued: '○',
    failed: '✕',
    cancelled: '⊘',
  };
  return (
    <Badge tone={STATUS_TONE[status] ?? 'neutral'} className={className}>
      <span aria-hidden="true">{glyph[status] ?? '•'}</span>
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}
