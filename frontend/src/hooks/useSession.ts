import { useCallback, useRef } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { sessionApi } from '../services/api';
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
} from '../types';
import { useToast } from '../contexts/useToast';

const EMPTY_PARAMS = Object.freeze({});
const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id';

function normalizeQueryError(err: unknown, fallbackMessage: string): Error {
  return err instanceof Error ? err : new Error(fallbackMessage);
}

export function useSession() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);

  const query = useQuery({
    queryKey: ['session', 'current'],
    queryFn: async () => {
      let result: SessionCurrent;
      try {
        result = await sessionApi.getCurrent();
      } catch (err: unknown) {
        throw normalizeQueryError(err, 'Failed to fetch current session');
      }

      const currentSessionId = result.id;
      const currentUserId = result.user_id ?? 'anonymous';
      const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`;
      let storedSessionId: string | null = null;
      try {
        storedSessionId = localStorage.getItem(storageKey);
      } catch {
        // Storage can be unavailable (private mode); treat as "no previous".
      }
      let previousSessionId: number | null = null;
      if (storedSessionId !== null) {
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
    retry: false,
    staleTime: 30_000,
  });

  const setData = useCallback(
    (
      value:
        | SessionCurrent
        | null
        | ((prev: SessionCurrent | null) => SessionCurrent | null),
    ) => {
      queryClient.setQueryData<SessionCurrent | null>(['session', 'current'], (prev) =>
        typeof value === 'function' ? value(prev ?? null) : value,
      );
    },
    [queryClient],
  );

  return {
    data: query.data ?? null,
    setData,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
  };
}

export function useSessions(params: Record<string, unknown> | null = EMPTY_PARAMS) {
  const query = useInfiniteQuery({
    queryKey: ['session', 'pages', params ?? EMPTY_PARAMS],
    queryFn: async ({ pageParam }: { pageParam: string | null }) => {
      try {
        return await sessionApi.list(params ?? EMPTY_PARAMS, pageParam);
      } catch (err: unknown) {
        throw normalizeQueryError(
          err,
          pageParam === null ? 'Failed to fetch sessions' : 'Failed to load more sessions',
        );
      }
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: SessionListResponse) => lastPage.next_page_token ?? undefined,
    retry: false,
  });

  const sessionsData: SessionSummary[] = (() => {
    const pages = query.data?.pages ?? [];
    const seenIds = new Set<unknown>();
    const combined: SessionSummary[] = [];
    for (const page of pages) {
      for (const session of page.sessions) {
        if (!seenIds.has(session.id)) {
          seenIds.add(session.id);
          combined.push(session);
        }
      }
    }
    return combined;
  })();
  const isLoadingMore = query.isFetchingNextPage;

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve();
    }
    return query.fetchNextPage().then(() => undefined);
  }, [query]);

  return {
    data: sessionsData,
    isPending: query.isPending,
    isLoadingMore,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
    hasMore: Boolean(query.hasNextPage) && sessionsData.length > 0,
    loadMore,
    refetch: (): Promise<void> => query.refetch().then(() => undefined),
  };
}

export function useSessionDetails(id: number | string | null | undefined) {
  const query = useQuery({
    queryKey: ['session', 'detail', id ?? null],
    queryFn: async () => {
      try {
        return await sessionApi.getDetails(id as number | string);
      } catch (err: unknown) {
        throw normalizeQueryError(err, 'Failed to fetch session details');
      }
    },
    enabled: Boolean(id),
    retry: false,
  });

  return {
    data: query.data ?? null,
    // A disabled query (no id) must report "not pending", matching the old
    // hook contract where an empty id resolved immediately with no data.
    isPending: Boolean(id) && query.isPending,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
  };
}

export function useSessionSnapshots(id: number | string | null | undefined) {
  const query = useQuery({
    queryKey: ['session', 'snapshots', id ?? null],
    queryFn: async () => {
      try {
        return await sessionApi.getSnapshots(id as number | string);
      } catch (err: unknown) {
        throw normalizeQueryError(err, 'Failed to fetch session snapshots');
      }
    },
    enabled: Boolean(id),
    retry: false,
  });

  return {
    data: query.data ?? null,
    isPending: Boolean(id) && query.isPending,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
  };
}

export function useRestoreSessionStart() {
  const mutation = useMutation({
    mutationFn: async (sessionId: number | string) => sessionApi.restoreSessionStart(sessionId),
    retry: false,
  });

  // The raw rejection propagates to callers while the exposed `error` stays a
  // normalized Error instance (identity-preserving for real Errors), matching
  // the previous hand-rolled contract consumed by tests and UI.
  const mutate = useCallback(
    async (sessionId: number | string) => {
      return await mutation.mutateAsync(sessionId);
    },
    [mutation],
  );

  const error =
    mutation.error === null || mutation.error === undefined
      ? null
      : normalizeQueryError(mutation.error, 'Failed to restore session');

  return {
    mutate,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error,
  };
}
