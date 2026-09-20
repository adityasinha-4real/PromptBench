'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';

type ToastTone = 'info' | 'success' | 'error';

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  toast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_CLASS: Record<ToastTone, string> = {
  info: 'border-line bg-elevated text-fg',
  success: 'border-[#1c4029] bg-[#0f2418] text-[#8ee0ad]',
  error: 'border-[#4a2327] bg-[#1d1315] text-[#f5b3b3]',
};

const GLYPH: Record<ToastTone, string> = { info: 'ⓘ', success: '✓', error: '✕' };

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((message: string, tone: ToastTone = 'info') => {
    setToasts((current) => [...current, { id: Date.now() + Math.random(), tone, message }]);
  }, []);

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map((item) => (
          <ToastItem
            key={item.id}
            toast={item}
            onDismiss={() => setToasts((current) => current.filter((t) => t.id !== item.id))}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, toast.tone === 'error' ? 8000 : 4000);
    return () => clearTimeout(timer);
  }, [onDismiss, toast.tone]);

  return (
    <div
      role="status"
      className={cn(
        'pointer-events-auto flex items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-lg',
        TONE_CLASS[toast.tone]
      )}
    >
      <span aria-hidden="true">{GLYPH[toast.tone]}</span>
      <span className="min-w-0 flex-1 break-words">{toast.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-fg-subtle hover:text-fg"
        aria-label="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  // Falling back to a no-op keeps components renderable in isolation (tests,
  // storybook-style harnesses) without wrapping every one in a provider.
  return context ?? { toast: () => undefined };
}
