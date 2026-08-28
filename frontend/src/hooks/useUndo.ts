import { useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  undoApi,
  type SessionSnapshotsResponse,
} from '../services/api';
import { getApiErrorDetail } from '../utils/apiError';
import type { UndoPayload } from '../types/index.ts';
import { queryKeys } from '../query/queryKeys';

export function useSnapshots(sessionId: number | string | null | undefined) {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.undo.snapshots(sessionId),
    queryFn: async () => {
      if (!sessionId) {
        return null;
      }
      return undoApi.listSnapshots(sessionId);
    },
    enabled: sessionId != null,
  });

  return {
    data: data ?? null,
    isLoading: isPending,
    isError,
    error: error ?? null,
    refetch,
  };
}

export function useUndo() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ sessionId, snapshotId }: UndoPayload) => {
    setIsPending(true)
    setIsError(false)

    try {
      await undoApi.undo(sessionId, snapshotId)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to undo action:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
