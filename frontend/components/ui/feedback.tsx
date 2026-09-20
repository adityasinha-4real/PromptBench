'use client';

import { cn } from '@/lib/utils';
import { Button } from './button';

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded bg-elevated', className)} aria-hidden="true" />;
}

export function LoadingPanel({ rows = 3, label = 'Loading…' }: { rows?: number; label?: string }) {
  return (
    <div className="panel space-y-3 p-4" role="status" aria-label={label}>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-4" />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

export interface ErrorStateProps {
  title?: string;
  message: string;
  hint?: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * Error surface. Always shows what failed and what to do about it — never a
 * bare status code.
 */
export function ErrorState({
  title = 'Something went wrong',
  message,
  hint,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn('rounded-md border border-[#4a2327] bg-[#1d1315] px-4 py-3 text-sm', className)}
    >
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="mt-0.5 text-[#f18e8e]">
          ✕
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-[#f5b3b3]">{title}</p>
          <p className="mt-0.5 break-words text-fg-muted">{message}</p>
          {hint && <p className="mt-1 text-xs text-fg-subtle">{hint}</p>}
        </div>
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('panel flex flex-col items-center gap-2 px-6 py-12 text-center', className)}>
      <p className="text-sm font-medium text-fg">{title}</p>
      {description && <p className="max-w-md text-xs text-fg-subtle">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function InlineNote({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p className={cn('text-xs text-fg-subtle', className)}>
      <span aria-hidden="true" className="mr-1">
        ⓘ
      </span>
      {children}
    </p>
  );
}
