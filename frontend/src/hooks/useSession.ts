import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { sessionApi } from '../services/api';
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
} from '../types';
import { useToast } from '../contexts/useToast';
import { useCache } from '../contexts/useCache';

const EMPTY_PARAMS = Object.freeze({});
const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id';

export function useSession() {
  const { showToast } = useToast();
  const lastNotifiedSessionIdRef = useRef<number | null>(null);

  const query = useQuery({
    queryKey: ['session', 'current'],
    queryFn: async () => {
      const result = await sessionApi.getCurrent();
      const currentSessionId = result.id;
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
    retry: false,
    staleTime: 30_000,
  });

  return {
    data: query.data as SessionCurrent | null | undefined,
    setData: () => {},
    isPending: query.isPending,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : (query.error ? new Error(String(query.error)) : null),
    refetch: query.refetch,
  };
}

export function useSessions(params = EMPTY_PARAMS) {
  const query = useQuery({
    queryKey: ['session', 'pages', params],
    queryFn: () => sessionApi.list(params ?? EMPTY_PARAMS, null),
    retry: false,
  });

  const sessionsData = (query.data as import('../types').SessionListResponse | undefined)?.sessions ?? [];
  const nextPageToken = (query.data as import('../types').SessionListResponse | undefined)?.next_page_token ?? null;

  return {
    data: sessionsData as SessionSummary[],
    isPending: query.isPending,
    isLoadingMore: false,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : (query.error ? new Error(String(query.error)) : null),
    hasMore: !!nextPageToken && sessionsData.length > 0,
    loadMore: async () => {},
    refetch: query.refetch,
  };
}

export function useSessionDetails(id: number | string | null | undefined) {
  const query = useQuery({
    queryKey: ['session', 'detail', id],
    queryFn: () => (id ? sessionApi.getDetails(id) : Promise.resolve(null)),
    enabled: !!id,
    retry: false,
  });

  return {
    data: query.data as SessionDetails | null,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : (query.error ? new Error(String(query.error)) : null),
    refetch: query.refetch,
  };
}

export function useSessionSnapshots(id: number | string | null | undefined) {
  const query = useQuery({
    queryKey: ['session', 'snapshots', id],
    queryFn: () => (id ? sessionApi.getSnapshots(id) : Promise.resolve(null)),
    enabled: !!id,
    retry: false,
  });

  return {
    data: query.data as SessionSnapshotsResponse | null,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : (query.error ? new Error(String(query.error)) : null),
    refetch: query.refetch,
  };
}

export function useRestoreSessionStart() {
  const mutation = useMutation({
    mutationFn: async (sessionId: number | string) => {
      const result = await sessionApi.restoreSessionStart(sessionId);
      return result;
    },
    retry: false,
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error instanceof Error ? mutation.error : (mutation.error ? new Error(String(mutation.error)) : null),
  };
}
