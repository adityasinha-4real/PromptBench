'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { RunProgress } from '@/types';

const TERMINAL: string[] = ['completed', 'failed', 'cancelled'];
const POLL_INTERVAL_MS = 1200;

export interface RunProgressState {
  progress: RunProgress | null;
  finished: boolean;
  /** 'sse' while streaming, 'poll' after a fallback, 'idle' before start. */
  transport: 'idle' | 'sse' | 'poll';
  error: string | null;
}

/**
 * Follows a run's progress, preferring server-sent events and falling back to
 * polling when EventSource is unavailable or the stream drops.
 *
 * The UI stays responsive either way: per-model state updates as each model
 * finishes rather than waiting for the whole run.
 */
export function useRunProgress(runId: number | null, onFinished?: () => void): RunProgressState {
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [transport, setTransport] = useState<RunProgressState['transport']>('idle');
  const [error, setError] = useState<string | null>(null);

  const finishedRef = useRef(false);
  const finishedCallback = useRef(onFinished);
  finishedCallback.current = onFinished;

  const markFinished = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    finishedCallback.current?.();
  }, []);

  useEffect(() => {
    if (runId === null) {
      setProgress(null);
      setTransport('idle');
      finishedRef.current = false;
      return;
    }

    finishedRef.current = false;
    let cancelled = false;
    let source: EventSource | null = null;
    let poller: ReturnType<typeof setInterval> | null = null;

    const apply = (next: RunProgress) => {
      if (cancelled) return;
      setProgress(next);
      if (TERMINAL.includes(next.status)) {
        markFinished();
        stop();
      }
    };

    const stop = () => {
      source?.close();
      source = null;
      if (poller) {
        clearInterval(poller);
        poller = null;
      }
    };

    const startPolling = () => {
      if (cancelled || poller) return;
      setTransport('poll');
      const tick = () =>
        api
          .getRunProgress(runId)
          .then(apply)
          .catch(() => {
            /* transient; the next tick retries */
          });
      void tick();
      poller = setInterval(tick, POLL_INTERVAL_MS);
    };

    if (typeof EventSource === 'undefined') {
      startPolling();
    } else {
      setTransport('sse');
      source = new EventSource(api.runStreamUrl(runId));

      source.addEventListener('progress', (event) => {
        try {
          apply(JSON.parse((event as MessageEvent<string>).data) as RunProgress);
        } catch {
          setError('Received a malformed progress event.');
        }
      });

      source.addEventListener('done', (event) => {
        try {
          apply(JSON.parse((event as MessageEvent<string>).data) as RunProgress);
        } catch {
          /* the terminal state still arrives from the final progress frame */
        }
        markFinished();
        stop();
      });

      source.onerror = () => {
        // The stream closes normally at the end of a run; only fall back while
        // the run is still open.
        source?.close();
        source = null;
        if (!cancelled && !finishedRef.current) startPolling();
      };
    }

    return () => {
      cancelled = true;
      stop();
    };
  }, [runId, markFinished]);

  return {
    progress,
    finished: progress ? TERMINAL.includes(progress.status) : false,
    transport,
    error,
  };
}
