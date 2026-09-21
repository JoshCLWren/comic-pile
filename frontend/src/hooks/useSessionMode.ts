import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import type { CacheEffectsApi, SessionModeApi } from '../services/apiTypes'
import { invalidateAfterSessionModeUpdate } from '../query/cacheEffects'
import { queryClient as fallbackQueryClient } from '../query/queryClient'
import type { SessionModeUpdateRequest, SessionModeResponse } from '../types'

export interface SessionModeMutationDeps {
  sessionApi?: SessionModeApi
  cacheEffects?: CacheEffectsApi
  queryClientInstance?: QueryClient
}

export function useSessionMode(deps: SessionModeMutationDeps = {}) {
  const sessionInstance = deps.sessionApi
  const invalidateSessionCache =
    deps.cacheEffects?.invalidateAfterSessionModeUpdate ?? invalidateAfterSessionModeUpdate
  const queryClientFromHook = useQueryClient()
  const client = deps.queryClientInstance ?? queryClientFromHook ?? fallbackQueryClient

  const mutation = useMutation<SessionModeResponse, Error, SessionModeUpdateRequest>({
    mutationFn: async (data: SessionModeUpdateRequest) => {
        const apiSession = sessionInstance ?? (await import('../services/api')).sessionApi;
        return apiSession.updateMode(data);
      },
    onSuccess: async () => {
      await invalidateSessionCache(client)
    },
  })

  return {
    mutate: mutation.mutateAsync,
    mutateAsync: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error,
  }
}
