import { useQuery, useMutation } from '@tanstack/react-query';
import { threadsApi } from '../services/api-threads';
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadUpdatePayload } from '../types';
import {
  applyEditedThreadToQueuePages,
  invalidateAfterCreatorCreditChange,
  invalidateAfterQueueMutation,
  invalidatePotentialDuplicates,
} from '../query/cacheEffects';
import { queryClient } from '../query/queryClient';
import { queryKeys } from '../query/queryKeys';

export function useThread(id?: number | null) {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: id ? queryKeys.thread.detail(id) : [],
    queryFn: () => threadsApi.get(id!),
    enabled: !!id,
    // SAFETY: null is the intentional initialData placeholder while the thread
    // query is loading; `initialDataUpdatedAt: 0` forces the initial fetch even
    // under the app's 30s staleTime so a fresh thread always loads on mount.
    initialData: null as Thread | null,
    initialDataUpdatedAt: 0,
  });

  return { data, isPending, isError, error, refetch };
}

export function useStaleThreads(days?: number) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.thread.summaries(),
    queryFn: () => threadsApi.listStale(days),
    // Note: if 'days' needs to be part of the key, update queryKeys.thread.summaries
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
    onSuccess: async (result, variables) => {
      applyEditedThreadToQueuePages(queryClient, result);
      // A rename or format change rewrites which existing editions the Add
      // Series and Edit/Rename forms should warn about (#3612). The queue rows
      // are patched in place above, so only the advisory duplicate answers
      // need to stop serving their pre-edit observation.
      await invalidatePotentialDuplicates(queryClient);
      // Creator analytics are derived server-side from the series' manual
      // creator credits, so only a credits edit needs those refreshed. Leave
      // other thread edits out of the creator cache (#3461).
      if (variables.data.manual_creator_credits !== undefined) {
        await invalidateAfterCreatorCreditChange(queryClient);
      }
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

/**
 * Removes a series from the active queue without deleting it (#3807).
 *
 * The mutation owns the write, so the queue and excluded-library cache effects
 * live with it instead of in the caller's dialog handler.
 */
export function useExcludeThread() {
  const mutation = useMutation({
    mutationFn: (id: number) => threadsApi.exclude(id),
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
