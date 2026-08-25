import { dependenciesApi } from '../../services/api'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollDependenciesParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
}

/**
 * Owns dependency recovery on the Roll page: expanding the hidden blocked
 * pool loads every blocked thread's named blockers with one batched request,
 * and never loads them while the section stays collapsed.
 */
export function useRollDependencies({ state, bootstrap }: UseRollDependenciesParams) {
  const { blockedExpanded, setBlockedExpanded, setBlockingDependencyMap } = state

  async function handleToggleBlocked() {
    if (!blockedExpanded) {
      const blockedThreads = bootstrap?.blocked_threads ?? []
      try {
        const response = await dependenciesApi.getBatchBlockingInfo(
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
