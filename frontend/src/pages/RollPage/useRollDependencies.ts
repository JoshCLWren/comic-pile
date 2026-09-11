import { dependenciesApi } from '../../services/api'
import type { RollDependenciesApi } from '../../services/apiTypes'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollDependenciesParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
  dependencies?: RollDependenciesApi
}

/**
 * Owns dependency recovery on the Roll page: expanding the hidden blocked
 * pool loads every blocked thread's named blockers with one batched request,
 * and never loads them while the section stays collapsed.
 */
export function useRollDependencies({ state, bootstrap, dependencies }: UseRollDependenciesParams) {
  const { blockedExpanded, setBlockedExpanded, setBlockingDependencyMap } = state
  const batchApi = dependencies ?? dependenciesApi

  async function handleToggleBlocked() {
    if (!blockedExpanded) {
      const blockedThreads = bootstrap?.blocked_threads ?? []
      try {
        const response = await batchApi.getBatchBlockingInfo(
          blockedThreads.map((thread) => thread.id),
        )
        const map: typeof state.blockingDependencyMap = {}
        for (const [threadId, info] of Object.entries(response.threads)) {
          map[Number(threadId)] = info.blocking_dependencies ?? []
        }
        setBlockingDependencyMap(map)
      } catch {
        setBlockingDependencyMap({})
      }
    }
    setBlockedExpanded(!blockedExpanded)
  }

  return { handleToggleBlocked }
}
