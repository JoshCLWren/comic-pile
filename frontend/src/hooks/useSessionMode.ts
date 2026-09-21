import { useMutation } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import type { CacheEffectsApi, SessionModeApi } from '../services/apiTypes'
import { invalidateAfterSessionModeUpdate } from '../query/cacheEffects'
import { sessionApi } from '../services/api'
import { queryClient } from '../query/queryClient'
import type { SessionModeUpdateRequest, SessionModeResponse } from '../types'

export interface SessionModeMutationDeps {
  sessionApi?: SessionModeApi
  cacheEffects?: CacheEffectsApi
  queryClientInstance?: QueryClient
}

export function useSessionMode(deps: SessionModeMutationDeps = {}) {
  const sessionInstance = deps.sessionApi ?? sessionApi
  const invalidateSessionCache =
    deps.cacheEffects?.invalidateAfterSessionModeUpdate ?? invalidateAfterSessionModeUpdate
  const client = deps.queryClientInstance ?? queryClient

  const mutation = useMutation<SessionModeResponse, Error, SessionModeUpdateRequest>({
    mutationFn: (data: SessionModeUpdateRequest) => sessionInstance.updateMode(data),
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
