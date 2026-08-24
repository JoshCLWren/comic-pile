import { useMemo, useRef } from "react";
import { useQuery, useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { sessionApi } from "../services/api";
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
} from "../types";
import { useToast } from "../contexts/useToast";
import { queryKeys } from "../query/queryKeys";

const EMPTY_PARAMS = Object.freeze({});
const STORAGE_KEY_PREFIX = "comic_pile_last_session_id";

function normalizeQueryError(error: unknown, fallbackMessage: string): Error | null {
  if (error == null) return null;
  if (error instanceof Error) return error;
  return new Error(fallbackMessage);
}

export function useSession() {
  const { showToast } = useToast();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.session.current(),
    queryFn: async () => {
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
      return result;
    },
  });

  return useMemo(
    () => ({
      data,
      isPending,
      isError,
      error: normalizeQueryError(error, "Failed to fetch current session"),
      refetch,
    }),
    [data, isPending, isError, error, refetch],
  );
}

export function useSessions(params = EMPTY_PARAMS) {
  const query = useInfiniteQuery({
    queryKey: ['sessions', params],
    queryFn: async ({ pageParam }) => {
      try {
        return await sessionApi.list(params, pageParam as string | null);
      } catch (error: unknown) {
        if (error instanceof Error) throw error;
        throw new Error(
          pageParam === null ? 'Failed to fetch sessions' : 'Failed to load more sessions',
        );
      }
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: SessionListResponse) => lastPage.next_page_token ?? undefined,
  });

  return useMemo(
    () => {
      const seenIds = new Set<number>();
      const sessions =
        query.data?.pages
          .flatMap((page) => page.sessions)
          .filter((session) => {
            if (seenIds.has(session.id)) return false;
            seenIds.add(session.id);
            return true;
          }) ?? [];
      const isPending = query.isPending;
      const isLoadingMore = query.isFetchingNextPage;
      const isError = query.isError;
      const error = normalizeQueryError(query.error, 'Failed to fetch sessions');
      const hasMore = !!query.hasNextPage;
      const loadMore = () => query.fetchNextPage();

      return {
        data: sessions,
        isPending,
        isLoadingMore,
        isError,
        error,
        hasMore,
        loadMore,
        refetch: query.refetch,
      };
    },
    [query],
  );
}

export function useSessionDetails(id: number | string | null | undefined) {
  const { data, isPending, fetchStatus, isError, error, refetch } = useQuery({
    queryKey: id ? queryKeys.session.detail(Number(id)) : [],
    queryFn: () => sessionApi.getDetails(id!),
    enabled: !!id,
  });

  return {
    data,
    isPending: isPending && fetchStatus !== 'idle',
    isError,
    error: normalizeQueryError(error, 'Failed to fetch session details'),
    refetch,
  };
}

export function useSessionSnapshots(id: number | string | null | undefined) {
  const { data, isPending, fetchStatus, isError, error, refetch } = useQuery({
    queryKey: id ? ['session', 'snapshots', id] : [],
    queryFn: () => sessionApi.getSnapshots(id!),
    enabled: !!id,
  });

  return {
    data,
    isPending: isPending && fetchStatus !== 'idle',
    isError,
    error: normalizeQueryError(error, 'Failed to fetch session snapshots'),
    refetch,
  };
}

export function useRestoreSessionStart() {
  const mutation = useMutation({
    mutationFn: (sessionId: number | string) => sessionApi.restoreSessionStart(sessionId),
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: normalizeQueryError(mutation.error, 'Failed to restore session'),
  };
}
