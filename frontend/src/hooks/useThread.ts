import { useMutation, useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { threadsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import { applyEditedThreadToQueuePages, invalidateAfterQueueMutation } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadUpdatePayload } from '../types'

export function useThread(id?: number | null) {
  const query = useQuery({
    queryKey: id ? queryKeys.thread.detail(id) : ['thread', 'detail', null],
    queryFn: () => (id ? threadsApi.get(id) : Promise.resolve(null)),
    enabled: Boolean(id),
    retry: false,
  })

  return {
    data: query.data ?? null,
    // A disabled query (no id) must report "not pending", matching the old
    // hook contract where an empty id resolved immediately with no data.
    isPending: Boolean(id) && query.isPending,
    isError: query.isError,
  }
}

export function useStaleThreads(days?: number) {
  const query = useQuery({
    queryKey: ['thread', 'stale', days === undefined ? null : days],
    queryFn: () => threadsApi.listStale(days),
    retry: false,
  })

  const refetch = (): Promise<void> => query.refetch().then(() => undefined)

  return {
    data: query.data ?? null,
    isPending: query.isPending,
    isError: query.isError,
    refetch,
  }
}

export function useCreateThread() {
  const mutation = useMutation({
    mutationFn: async (data: ThreadCreatePayload) => {
      const result = await threadsApi.create(data)
      await invalidateAfterQueueMutation(queryClient)
      return result
    },
    retry: false,
  })

  const mutate = async (data: ThreadCreatePayload): Promise<Thread> => {
    try {
      return await mutation.mutateAsync(data)
    } catch (error: unknown) {
      console.error('Failed to create thread:', getApiErrorDetail(error))
      throw error
    }
  }

  return { mutate, isPending: mutation.isPending, isError: mutation.isError }
}

export function useUpdateThread() {
  const mutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: ThreadUpdatePayload }) => {
      const result = await threadsApi.update(id, data)
      applyEditedThreadToQueuePages(queryClient, result)
      return result
    },
    retry: false,
  })

  const mutate = async (input: { id: number; data: ThreadUpdatePayload }): Promise<Thread> => {
    try {
      return await mutation.mutateAsync(input)
    } catch (error: unknown) {
      console.error('Failed to update thread:', getApiErrorDetail(error))
      throw error
    }
  }

  return { mutate, isPending: mutation.isPending, isError: mutation.isError }
}

export function useDeleteThread() {
  const mutation = useMutation({
    mutationFn: async (id: number) => {
      await threadsApi.delete(id)
      await invalidateAfterQueueMutation(queryClient)
      return undefined
    },
    retry: false,
  })

  const mutate = async (id: number): Promise<void> => {
    try {
      await mutation.mutateAsync(id)
    } catch (error: unknown) {
      console.error('Failed to delete thread:', getApiErrorDetail(error))
      throw error
    }
  }

  return { mutate, isPending: mutation.isPending, isError: mutation.isError }
}

export function useReactivateThread() {
  const mutation = useMutation({
    mutationFn: async (data: ReactivateThreadPayload) => {
      const result = await threadsApi.reactivate(data)
      await invalidateAfterQueueMutation(queryClient)
      return result
    },
    retry: false,
  })

  const mutate = async (data: ReactivateThreadPayload): Promise<Thread> => {
    try {
      return await mutation.mutateAsync(data)
    } catch (error: unknown) {
      console.error('Failed to reactivate thread:', getApiErrorDetail(error))
      throw error
    }
  }

  return { mutate, isPending: mutation.isPending, isError: mutation.isError }
}
