import { useCallback, useState } from 'react';
import axios from 'axios';
import { useQuery } from '@tanstack/react-query';
import { threadsApi } from '../services/api';
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadUpdatePayload } from '../types';
import { applyEditedThreadToQueuePages, invalidateAfterQueueMutation } from '../query/cacheEffects';
import { queryClient } from '../query/queryClient';
import { queryKeys } from '../query/queryKeys';

export function useThread(id?: number | null) {
  const query = useQuery({
    queryKey: queryKeys.thread.detail(id ?? -1),
    queryFn: async () => {
      if (id == null) {
        throw new Error('No thread ID')
      }
      return threadsApi.get(id)
    },
    enabled: id != null,
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
  }
}

export function useStaleThreads(days?: number) {
  const query = useQuery({
    queryKey: queryKeys.thread.stale({ days }),
    queryFn: async () => {
      return threadsApi.listStale(days)
    },
    enabled: true,
    staleTime: 30_000,
    retry: false,
  })

  const refetch = useCallback(async () => {
    return query.refetch()
  }, [query])

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    refetch,
  }
}

export function useCreateThread() {
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async (data: ThreadCreatePayload) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.create(data);
        await invalidateAfterQueueMutation(queryClient);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to create thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    []
  );

  return { mutate, isPending, isError };
}

export function useUpdateThread() {
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async ({ id, data }: { id: number; data: ThreadUpdatePayload }) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.update(id, data);
        applyEditedThreadToQueuePages(queryClient, result);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to update thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    []
  );

  return { mutate, isPending, isError };
}

export function useDeleteThread() {
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async (id: number) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.delete(id);
        await invalidateAfterQueueMutation(queryClient);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to delete thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    []
  );

  return { mutate, isPending, isError };
}

export function useReactivateThread() {
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async (data: ReactivateThreadPayload) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.reactivate(data);
        await invalidateAfterQueueMutation(queryClient);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to reactivate thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    []
  );

  return { mutate, isPending, isError };
}
