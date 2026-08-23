import axios from 'axios';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { threadsApi } from '../services/api';
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadUpdatePayload } from '../types';
import { applyEditedThreadToQueuePages, invalidateAfterQueueMutation } from '../query/cacheEffects';
import { queryClient } from '../query/queryClient';
import { queryKeys } from '../query/queryKeys';

export function useThread(id?: number | null) {
  const query = useQuery({
    queryKey: id ? queryKeys.thread.detail(id) : ['thread', 'detail', null],
    queryFn: () => (id ? threadsApi.get(id) : Promise.resolve(null)),
    enabled: !!id && id > 0,
    retry: false,
  });

  return {
    data: query.data as Thread | null,
    isPending: query.isPending,
    isError: query.isError,
  };
}

export function useStaleThreads(days?: number) {
  const query = useQuery({
    queryKey: ['thread', 'stale', days ?? 30],
    queryFn: () => threadsApi.listStale(days),
    retry: false,
  });

  return {
    data: query.data as Thread[] | null,
    isPending: query.isPending,
    isError: query.isError,
    refetch: query.refetch,
  };
}

export function useCreateThread() {
  const mutation = useMutation({
    mutationFn: async (data: ThreadCreatePayload) => {
      const result = await threadsApi.create(data);
      await invalidateAfterQueueMutation(queryClient);
      return result;
    },
    retry: false,
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}

export function useUpdateThread() {
  const mutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: ThreadUpdatePayload }) => {
      const result = await threadsApi.update(id, data);
      applyEditedThreadToQueuePages(queryClient, result);
      return result;
    },
    retry: false,
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}

export function useDeleteThread() {
  const mutation = useMutation({
    mutationFn: async (id: number) => {
      const result = await threadsApi.delete(id);
      await invalidateAfterQueueMutation(queryClient);
      return result;
    },
    retry: false,
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}

export function useReactivateThread() {
  const mutation = useMutation({
    mutationFn: async (data: ReactivateThreadPayload) => {
      const result = await threadsApi.reactivate(data);
      await invalidateAfterQueueMutation(queryClient);
      return result;
    },
    retry: false,
  });

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  };
}
