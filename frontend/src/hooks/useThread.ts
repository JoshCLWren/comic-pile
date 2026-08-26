import { useMutation } from '@tanstack/react-query';
import { threadsApi } from '../services/api';
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadUpdatePayload } from '../types';
import { applyEditedThreadToQueuePages, invalidateAfterQueueMutation } from '../query/cacheEffects';
import { queryClient } from '../query/queryClient';
import { queryKeys } from '../query/queryKeys';

export function useThread(id?: number | null) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: id ? queryKeys.thread.detail(id) : [],
    queryFn: () => threadsApi.get(id!),
    enabled: !!id,
    initialData: null as Thread | null,
  });

  return { data, isPending, isError, refetch };
}

export function useStaleThreads(days?: number) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.thread.summaries(),
    queryFn: () => threadsApi.listStale(days),
  });

  return {
    data: data ?? null,
    isPending,
    isError,
    // Preserve the historical void-returning refetch contract for callers.
    refetch: async () => {
      await refetch();
    },
  };
}

export function useCreateThread() {
  const mutation = useMutation({
    mutationFn: (data: ThreadCreatePayload) => threadsApi.create(data),
    onSuccess: async () => {
      await invalidateAfterQueueMutation(queryClient);
    },
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}

export function useUpdateThread() {
  const mutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: ThreadUpdatePayload }) =>
      threadsApi.update(id, data),
    onSuccess: (result) => {
      applyEditedThreadToQueuePages(queryClient, result);
    },
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}

export function useDeleteThread() {
  const mutation = useMutation({
    mutationFn: (id: number) => threadsApi.delete(id),
    onSuccess: async () => {
      await invalidateAfterQueueMutation(queryClient);
    },
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}

export function useReactivateThread() {
  const mutation = useMutation({
    mutationFn: (data: ReactivateThreadPayload) => threadsApi.reactivate(data),
    onSuccess: async () => {
      await invalidateAfterQueueMutation(queryClient);
    },
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}