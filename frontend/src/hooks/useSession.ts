import { useMemo } from "react";
import { useQuery, useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { sessionApi } from "../services/api-sessions";
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
} from "../types";
import { useToast } from "../contexts/useToast";
import { trackSessionGreeting } from "../utils/sessionGreeting";
import { queryKeys, type SessionListParams } from "../query/queryKeys";

const EMPTY_PARAMS: SessionListParams = Object.freeze({});

function normalizeQueryError(error: unknown, fallbackMessage: string): Error | null {
  if (error == null) return null;
  if (error instanceof Error) return error;
  return new Error(fallbackMessage);
}

export function useSession() {
  const { showToast } = useToast();

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.session.current(),
    queryFn: async () => {
      const result = await sessionApi.getCurrent();

      // Greeting persistence and the session-started toast are owned by the
      // shared `sessionGreeting` helper so the roll bootstrap and this query
      // can never race on the same storage key or double-toast.
      trackSessionGreeting({ sessionId: result.id, userId: result.user_id, showToast });
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

export function useSessions(params: SessionListParams = EMPTY_PARAMS) {
  const query = useInfiniteQuery({
    // Canonical `session.pages` space: the cursor lives in `pageParam`, not the
    // key, so invalidation targeting `queryKeys.session.pages()` / `.all`
    // reliably refreshes the Session index.
    queryKey: queryKeys.session.list({ params }),
    queryFn: async ({ pageParam }) => {
      try {
        // SAFETY: useInfiniteQuery starts at the null initialPageParam and only advances with page tokens.
        return await sessionApi.list(params, pageParam as string | null);
      } catch (error: unknown) {
        if (error instanceof Error) throw error;
        throw new Error(
          pageParam === null ? 'Failed to fetch sessions' : 'Failed to load more sessions',
        );
      }
    },
    // SAFETY: null is the intentional first pageParam; later pages always receive page tokens.
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
