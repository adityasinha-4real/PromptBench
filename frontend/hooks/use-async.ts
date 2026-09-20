'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '@/lib/api';

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (value: T | null) => void;
}

/**
 * Fetch-on-mount hook with reload, cancellation on unmount, and a message-only
 * error surface (components never handle raw exceptions).
 *
 * `deps` controls refetching; pass the values the request depends on.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let stale = false;
    setLoading(true);

    loaderRef
      .current()
      .then((value) => {
        if (!stale && mounted.current) {
          setData(value);
          setError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!stale && mounted.current) setError(errorMessage(cause));
      })
      .finally(() => {
        if (!stale && mounted.current) setLoading(false);
      });

    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, error, loading, reload, setData };
}

/**
 * Wrap a one-shot action (submit, delete, run) with pending/error state.
 */
export function useAction<Args extends unknown[], R>(
  action: (...args: Args) => Promise<R>
): {
  run: (...args: Args) => Promise<R | undefined>;
  pending: boolean;
  error: string | null;
  clearError: () => void;
} {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const actionRef = useRef(action);
  actionRef.current = action;

  const run = useCallback(async (...args: Args) => {
    setPending(true);
    setError(null);
    try {
      return await actionRef.current(...args);
    } catch (cause) {
      setError(errorMessage(cause));
      return undefined;
    } finally {
      setPending(false);
    }
  }, []);

  return { run, pending, error, clearError: useCallback(() => setError(null), []) };
}
