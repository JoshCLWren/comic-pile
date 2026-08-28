import { useCallback, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { RollBootstrapResponse } from '../types/rollBootstrap';
import { rollBootstrapApi } from '../services/rollBootstrapApi';
import { useToast } from '../contexts/useToast';
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from './rollMutationReconciliation';
import { queryKeys } from '../query/queryKeys';

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id';

/** Best-effort browser IANA timezone used to timestamp the reading session. */
export function resolveBrowserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

export function useRollBootstrap() {
  const { showToast } = useToast();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);
  const justReconciledRef = useRef<RollBootstrapResponse | null>(null);
  const reconciliationExpiryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: async () => {
      const result = await rollBootstrapApi.get(resolveBrowserTimezone());

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

      return result;
    },
  });

  // Handle reconciled bootstrap data from mutations
  useEffect(() => {
    const handleReconciledBootstrap = (event: Event) => {
      const reconciled = (event as CustomEvent<RollBootstrapResponse>).detail;
      if (!reconciled) return;

      // Update the query data with the reconciled bootstrap
      // We don't increment request generation here as we're not making a new request
      justReconciledRef.current = reconciled;
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current);
      reconciliationExpiryRef.current = setTimeout(() => {
        if (justReconciledRef.current === reconciled) justReconciledRef.current = null;
        reconciliationExpiryRef.current = null;
      }, 0);
    };

    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap);
    return () => {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap);
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current);
    };
  }, []);

  // Custom refetch function that returns reconciled data if available
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

    // Otherwise, refetch the query
    return refetch();
  }, [refetch]);

  return { data, isPending, isError, error, refetch: refetchBootstrap };
}
