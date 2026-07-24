import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { sessionApi } from "../services/api";
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
} from "../types";
import { useToast } from "../contexts/useToast";
import { useCache } from "../contexts/useCache";

const EMPTY_PARAMS = Object.freeze({});
const STORAGE_KEY_PREFIX = "comic_pile_last_session_id";

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
      const currentUserId = result.user_id ?? "anonymous";
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
        showToast("Session started. Happy reading!", "info");
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
      setIsError(true);
      setError(
        err instanceof Error
          ? err
          : new Error("Failed to fetch current session"),
      );
    } finally {
      setIsPending(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  const value = useMemo(
    () => ({
      data,
      setData,
      isPending,
      isError,
      error,
      refetch: fetchSession,
    }),
    [data, isPending, isError, error, fetchSession],
  );

  return value;
}

export function useSessions(params = EMPTY_PARAMS) {
  const { invalidateQueries } = useCache();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isPending, setIsPending] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const isLoadingMoreRef = useRef(false);
  const paramsRef = useRef(params ?? EMPTY_PARAMS);
  // Keep the ref current without causing re-renders
  paramsRef.current = params ?? EMPTY_PARAMS;

  const fetchFirstPage = useCallback(async () => {
    setIsPending(true);
    setIsError(false);
    setError(null);
    setSessions([]);
    setNextPageToken(null);
    setHasMore(false);
    try {
      const result: SessionListResponse = await sessionApi.list(
        paramsRef.current,
        null,
      );
      setSessions(result.sessions);
      setNextPageToken(result.next_page_token);
      setHasMore(result.next_page_token !== null && result.sessions.length > 0);
      invalidateQueries(["sessions"]);
    } catch (err: unknown) {
      setIsError(true);
      setError(
        err instanceof Error ? err : new Error("Failed to fetch sessions"),
      );
    } finally {
      setIsPending(false);
    }
  }, [invalidateQueries]);

  const loadMore = useCallback(async () => {
    if (!nextPageToken || isLoadingMoreRef.current) return;
    isLoadingMoreRef.current = true;
    setIsLoadingMore(true);
    setError(null);
    try {
      const result: SessionListResponse = await sessionApi.list(
        paramsRef.current,
        nextPageToken,
      );
      setSessions((prev) => {
        const existingIds = new Set(prev.map((s) => s.id));
        const newSessions = result.sessions.filter(
          (s) => !existingIds.has(s.id),
        );
        return [...prev, ...newSessions];
      });
      setNextPageToken(result.next_page_token);
      setHasMore(result.next_page_token !== null && result.sessions.length > 0);
    } catch (err: unknown) {
      setIsError(true);
      setError(
        err instanceof Error
          ? err
          : new Error("Failed to load more sessions"),
      );
    } finally {
      setIsLoadingMore(false);
      isLoadingMoreRef.current = false;
    }
  }, [nextPageToken]);

  useEffect(() => {
    fetchFirstPage();
  }, [fetchFirstPage]);

  const value = useMemo(
    () => ({
      data: sessions,
      isPending,
      isLoadingMore,
      isError,
      error,
      hasMore,
      loadMore,
      refetch: fetchFirstPage,
    }),
    [sessions, isPending, isLoadingMore, isError, error, hasMore, loadMore, fetchFirstPage],
  );

  return value;
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
      setError(
        err instanceof Error
          ? err
          : new Error("Failed to fetch session details"),
      );
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
      setError(
        err instanceof Error
          ? err
          : new Error("Failed to fetch session snapshots"),
      );
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
      const normalizedError =
        err instanceof Error ? err : new Error("Failed to restore session");
      setError(normalizedError);
      if (axios.isAxiosError(err)) {
        console.error(
          "Failed to restore session:",
          err.response?.data?.detail || err.message,
        );
      } else {
        console.error("Failed to restore session:", normalizedError.message);
      }
      throw err;
    } finally {
      setIsPending(false);
    }
  }, []);

  return { mutate, isPending, isError, error };
}
