import { useCallback, useEffect, useRef, useState } from 'react';
import type { RollBootstrapResponse } from '../types/rollBootstrap';
import { rollBootstrapApi } from '../services/rollBootstrapApi';
import { useToast } from '../contexts/useToast';
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from './rollMutationReconciliation';

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id';

export function useRollBootstrap() {
  const [data, setData] = useState<RollBootstrapResponse | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { showToast } = useToast();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);
  const justReconciledRef = useRef<RollBootstrapResponse | null>(null);
  const reconciliationExpiryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const refetchBootstrap = useCallback(async () => {
    const reconciled = justReconciledRef.current;
    if (reconciled) {
      justReconciledRef.current = null;
      if (reconciliationExpiryRef.current) {
        clearTimeout(reconciliationExpiryRef.current);
        reconciliationExpiryRef.current = null;
      }
      return reconciled;
    }

    return fetchBootstrap();
  }, [fetchBootstrap]);

  useEffect(() => {
    // Defer the request by one microtask so consumers can reliably observe the
    // initial loading state before even an already-resolved test or cache value settles.
    void Promise.resolve().then(fetchBootstrap).catch(() => undefined);
  }, [fetchBootstrap]);

  useEffect(() => {
    const handleReconciledBootstrap = (event: Event) => {
      const reconciled = (event as CustomEvent<RollBootstrapResponse>).detail;
      if (!reconciled) return;

      justReconciledRef.current = reconciled;
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current);
      reconciliationExpiryRef.current = setTimeout(() => {
        if (justReconciledRef.current === reconciled) justReconciledRef.current = null;
        reconciliationExpiryRef.current = null;
      }, 0);

      setData(reconciled);
      setIsPending(false);
      setIsError(false);
      setError(null);
    };

    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap);
    return () => {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap);
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current);
    };
  }, []);

  return { data, isPending, isError, error, refetch: refetchBootstrap };
}
