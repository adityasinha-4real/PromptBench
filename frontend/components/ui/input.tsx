'use client';

import { forwardRef, useId } from 'react';
import { cn } from '@/lib/utils';

const FIELD = cn(
  'w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-fg',
  'placeholder:text-fg-subtle',
  'transition-colors focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent',
  'disabled:cursor-not-allowed disabled:opacity-50',
  'aria-[invalid=true]:border-[#7a2c30] aria-[invalid=true]:focus:ring-[#d03b3b]'
);

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(FIELD, 'h-9 py-0', className)} {...props} />;
  }
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(FIELD, 'resize-y font-mono text-[13px] leading-relaxed', className)}
      {...props}
    />
  );
});

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...props }, ref) {
    return (
      <select ref={ref} className={cn(FIELD, 'h-9 cursor-pointer py-0 pr-8', className)} {...props}>
        {children}
      </select>
    );
  }
);

export interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
  className?: string;
}

/** Label + control + hint/error, wired up for screen readers. */
export function Field({ label, hint, error, required, htmlFor, children, className }: FieldProps) {
  const generated = useId();
  const id = htmlFor ?? generated;
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={id} className="block text-xs font-medium text-fg-muted">
        {label}
        {required && <span className="ml-1 text-[#d03b3b]">*</span>}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-[#f18e8e]" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-fg-subtle">{hint}</p>
      ) : null}
    </div>
  );
}

export interface SliderProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  value: number;
  displayValue?: string;
}

export function Slider({ className, value, displayValue, ...props }: SliderProps) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        value={value}
        className={cn(
          'h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-line accent-accent',
          className
        )}
        {...props}
      />
      <span className="tabular w-12 text-right text-xs text-fg-muted">{displayValue ?? value}</span>
    </div>
  );
}

export function Checkbox({
  label,
  description,
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; description?: string }) {
  const id = useId();
  return (
    <div className={cn('flex items-start gap-2.5', className)}>
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-line bg-surface-2 accent-accent"
        {...props}
      />
      <label htmlFor={id} className="cursor-pointer select-none">
        <span className="block text-sm text-fg">{label}</span>
        {description && <span className="block text-xs text-fg-subtle">{description}</span>}
      </label>
    </div>
  );
}
