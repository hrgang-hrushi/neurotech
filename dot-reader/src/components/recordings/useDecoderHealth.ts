'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchHealth } from '@/lib/recordingApi';

export type DecoderStatus = 'checking' | 'online' | 'offline';

const HEALTH_POLL_MS = 10_000;
/** One slow health check (e.g. while a big file decodes) must not flip the UI to offline. */
const FAILURES_BEFORE_OFFLINE = 2;

/**
 * Poll the decoder's health. Pauses while `paused` (a decode is running) or the
 * tab is hidden, and aborts the in-flight request on cleanup.
 */
export function useDecoderHealth(paused: boolean): {
  status: DecoderStatus;
  models: string[];
  retry: () => void;
} {
  const [status, setStatus] = useState<DecoderStatus>('checking');
  const [models, setModels] = useState<string[]>([]);
  const failures = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  const check = useCallback(async () => {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    try {
      const health = await fetchHealth(undefined, controller.signal);
      if (controller.signal.aborted) return;
      failures.current = 0;
      setStatus('online');
      setModels(health.models);
    } catch {
      if (controller.signal.aborted) return;
      failures.current += 1;
      if (failures.current >= FAILURES_BEFORE_OFFLINE) setStatus('offline');
    }
  }, []);

  useEffect(() => {
    if (paused) return undefined;
    const tick = () => {
      if (!document.hidden) void check();
    };
    tick();
    const id = setInterval(tick, HEALTH_POLL_MS);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', tick);
      inflight.current?.abort();
    };
  }, [paused, check]);

  const retry = useCallback(() => {
    failures.current = FAILURES_BEFORE_OFFLINE - 1;
    setStatus('checking');
    void check();
  }, [check]);

  return { status, models, retry };
}
