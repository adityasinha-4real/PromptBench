'use client';

import { useCallback, useState } from 'react';
import { cn } from '@/lib/utils';
import { Button } from './button';
import { useToast } from './toast';

/* -------------------------------------------------------------------------- */
/* Copy                                                                        */
/* -------------------------------------------------------------------------- */

export function CopyButton({
  value,
  label = 'Copy',
  className,
  size = 'sm',
}: {
  value: string;
  label?: string;
  className?: string;
  size?: 'sm' | 'md';
}) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast('Clipboard access was blocked by the browser.', 'error');
    }
  }, [value, toast]);

  return (
    <Button variant="ghost" size={size} onClick={copy} className={className} aria-label={label}>
      <span aria-hidden="true">{copied ? '✓' : '⧉'}</span>
      {copied ? 'Copied' : label}
    </Button>
  );
}

/* -------------------------------------------------------------------------- */
/* Collapsible                                                                 */
/* -------------------------------------------------------------------------- */

export function Collapsible({
  title,
  children,
  defaultOpen = false,
  className,
  badge,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  badge?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn('rounded-md border border-line', className)}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-fg-muted transition-colors hover:text-fg"
      >
        <span aria-hidden="true" className={cn('transition-transform', open && 'rotate-90')}>
          ›
        </span>
        <span className="flex-1">{title}</span>
        {badge}
      </button>
      {open && <div className="border-t border-line p-3">{children}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Tabs                                                                        */
/* -------------------------------------------------------------------------- */

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

export function Tabs({
  items,
  active,
  onChange,
  className,
}: {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div role="tablist" className={cn('flex gap-1 border-b border-line', className)}>
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            role="tab"
            type="button"
            aria-selected={selected}
            onClick={() => onChange(item.id)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors',
              selected
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-subtle hover:text-fg-muted'
            )}
          >
            {item.label}
            {item.count !== undefined && (
              <span className="tabular ml-1.5 text-fg-subtle">{item.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Stat tile                                                                   */
/* -------------------------------------------------------------------------- */

export function StatTile({
  label,
  value,
  sub,
  className,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('panel px-4 py-3', className)}>
      <p className="label-caps">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold leading-none text-fg">{value}</p>
      {sub && <p className="mt-1.5 text-xs text-fg-subtle">{sub}</p>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Confirm                                                                     */
/* -------------------------------------------------------------------------- */

export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel = 'Confirm?',
  variant = 'danger',
  size = 'sm',
  className,
}: {
  onConfirm: () => void;
  children: React.ReactNode;
  confirmLabel?: string;
  variant?: 'danger' | 'outline' | 'ghost';
  size?: 'sm' | 'md';
  className?: string;
}) {
  const [armed, setArmed] = useState(false);

  if (!armed) {
    return (
      <Button variant={variant} size={size} className={className} onClick={() => setArmed(true)}>
        {children}
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <Button
        variant="danger"
        size={size}
        className={className}
        onClick={() => {
          setArmed(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button variant="ghost" size={size} onClick={() => setArmed(false)}>
        Cancel
      </Button>
    </span>
  );
}
