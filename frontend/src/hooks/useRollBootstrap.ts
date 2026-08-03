import { useCallback, useEffect, useRef, useState } from 'react';
import type { RollBootstrapResponse } from '../types/rollBootstrap';
import { rollBootstrapApi } from '../services/rollBootstrapApi';
import { useToast } from '../contexts/useToast';

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id';

export function useRollBootstrap() {
  const [data, setData] = useState<RollBootstrapResponse | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { showToast } = useToast();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);

  const fetchBootstrap = useCallback(async () => {
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      const result = await rollBootstrapApi.get();

      const currentSessionId = result.session_id;
      const currentUserId = result.user_id ?? 'anonymous';
      const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`;
      let storedSessionId: string | null = null;
      try {
        storedSessionId = localStorage.getItem(storageKey);
      } catch {
        // Session loading should still succeed when browser storage is unavailable.
      }
      let previousSessionId: number | null = null;
      if (storedSessionId) {
        const parsed = parseInt(storedSessionId, 10);
        previousSessionId = Number.isFinite(parsed) ? parsed : null;
      }

      if (
        previousSessionId !== null &&
        currentSessionId !== previousSessionId &&
        currentSessionId !== lastNotifiedSessionIdRef.current
      ) {
        showToast('Session started. Happy reading!', 'info');
        lastNotifiedSessionIdRef.current = currentSessionId;
      }

      try {
        localStorage.setItem(storageKey, currentSessionId.toString());
      } catch {
        // Persisting the session ID is best effort and must not hide the API result.
      }

      setData(result);
      return result;
    } catch (err: unknown) {
      const normalized = err instanceof Error ? err : new Error('Failed to fetch roll bootstrap');
      setIsError(true);
      setError(normalized);
      throw normalized;
    } finally {
      setIsPending(false);
    }
  }, [showToast]);

  useEffect(() => {
    // Defer the request by one microtask so consumers can reliably observe the
    // initial loading state before even an already-resolved test or cache value settles.
    void Promise.resolve().then(fetchBootstrap).catch(() => undefined);
  }, [fetchBootstrap]);

  return { data, isPending, isError, error, refetch: fetchBootstrap };
}
