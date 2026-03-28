import { useCallback, useEffect, useState, useMemo, useRef } from 'react';
import axios from 'axios';
import { sessionApi } from '../services/api';
import type { SessionCurrent, SessionDetails, SessionListResponse, SessionSnapshotsResponse, SessionSummary } from '../types';
import { useToast } from '../contexts/ToastContext';
import { useCache } from '../contexts/CacheContext';

const EMPTY_PARAMS = Object.freeze({});
const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id';

export function useSession() {
  const [data, setData] = useState<SessionCurrent | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { showToast } = useToast();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);

  const fetchSession = useCallback(async () => {
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      const result = await sessionApi.getCurrent();

      const currentSessionId = result.id;
      const currentUserId = result.user_id ?? 'anonymous';
      const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`;
      const storedSessionId = localStorage.getItem(storageKey);
      const previousSessionId = storedSessionId ? parseInt(storedSessionId, 10) : null;

      if (previousSessionId !== null &&
        currentSessionId !== previousSessionId &&
        currentSessionId !== lastNotifiedSessionIdRef.current) {
        showToast('Session expired. A new session has started.', 'info');
        lastNotifiedSessionIdRef.current = currentSessionId;
      }

      localStorage.setItem(storageKey, currentSessionId.toString());
      setData(result);
      return result;
    } catch (err: unknown) {
      setIsError(true);
      setError(err instanceof Error ? err : new Error('Failed to fetch current session'));
    } finally {
      setIsPending(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  const value = useMemo(() => ({
    data,
    setData,
    isPending,
    isError,
    error,
    refetch: fetchSession,
  }), [data, isPending, isError, error, fetchSession]);

  return value;
}

export function useSessions(params = EMPTY_PARAMS) {
  const { invalidateQueries } = useCache();
  const [data, setData] = useState<SessionSummary[] | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const effectiveParams = params ?? EMPTY_PARAMS;

  const fetchSessions = useCallback(async () => {
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      // Fetch all pages with large page_size
      const baseParams = { ...effectiveParams, page_size: 200 };
      let allSessions: SessionSummary[] = [];
      let nextToken: string | null = null;
      let currentToken: string | undefined = undefined;
      do {
        const params = { ...baseParams };
        if (currentToken) {
          params.page_token = currentToken;
        }
        const result: SessionListResponse = await sessionApi.list(params, currentToken);
        allSessions = allSessions.concat(result.sessions);
        nextToken = result.next_page_token;
        currentToken = nextToken ?? undefined;
      } while (nextToken);
      
      setData(allSessions);
      // Invalidate any cached session queries after fetching fresh data
      invalidateQueries(['sessions']);
    } catch (err: unknown) {
      setIsError(true);
      setError(err instanceof Error ? err : new Error('Failed to fetch sessions'));
    } finally {
      setIsPending(false);
    }
  }, [effectiveParams, invalidateQueries]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  return { data, isPending, isError, error, refetch: fetchSessions };
}

export function useSessionDetails(id: number | string | null | undefined) {
  const [data, setData] = useState<SessionDetails | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchDetails = useCallback(async () => {
    if (!id) {
      setData(null);
      setIsError(false);
      setError(null);
      setIsPending(false);
      return;
    }
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      const result = await sessionApi.getDetails(id);
      setData(result);
    } catch (err: unknown) {
      setIsError(true);
      setError(err instanceof Error ? err : new Error('Failed to fetch session details'));
    } finally {
      setIsPending(false);
    }
  }, [id]);

  useEffect(() => {
    fetchDetails();
  }, [fetchDetails]);

  return { data, isPending, isError, error, refetch: fetchDetails };
}

export function useSessionSnapshots(id: number | string | null | undefined) {
  const [data, setData] = useState<SessionSnapshotsResponse | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchSnapshots = useCallback(async () => {
    if (!id) {
      setData(null);
      setIsError(false);
      setError(null);
      setIsPending(false);
      return;
    }
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      const result = await sessionApi.getSnapshots(id);
      setData(result);
    } catch (err: unknown) {
      setIsError(true);
      setError(err instanceof Error ? err : new Error('Failed to fetch session snapshots'));
    } finally {
      setIsPending(false);
    }
  }, [id]);

  useEffect(() => {
    fetchSnapshots();
  }, [fetchSnapshots]);

  return { data, isPending, isError, error, refetch: fetchSnapshots };
}

export function useRestoreSessionStart() {
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutate = useCallback(async (sessionId: number | string) => {
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      const result = await sessionApi.restoreSessionStart(sessionId);
      return result;
    } catch (err: unknown) {
      setIsError(true);
      const normalizedError = err instanceof Error ? err : new Error('Failed to restore session');
      setError(normalizedError);
      if (axios.isAxiosError(err)) {
        console.error('Failed to restore session:', err.response?.data?.detail || err.message);
      } else {
        console.error('Failed to restore session:', normalizedError.message);
      }
      throw err;
    } finally {
      setIsPending(false);
    }
  }, []);

  return { mutate, isPending, isError, error };
}
