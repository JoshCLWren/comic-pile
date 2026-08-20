import { dependenciesApi } from '../../services/api'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollDependenciesParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse
}

/**
 * Owns dependency recovery on the Roll page: expanding the hidden blocked
 * pool lazily loads each blocked thread's blocking reasons exactly once, and
 * never loads them while the section stays collapsed.
 */
export function useRollDependencies({ state, bootstrap }: UseRollDependenciesParams) {
  const { blockedExpanded, setBlockedExpanded, setBlockingReasonMap } = state

  async function handleToggleBlocked() {
    if (!blockedExpanded) {
      const blockedThreads = bootstrap?.blocked_threads ?? []
      const details = await Promise.all(
        blockedThreads.map(async (thread): Promise<[number, string[]]> => {
          try {
            const info = await dependenciesApi.getBlockingInfo(thread.id)
            return [thread.id, info.blocking_reasons ?? []]
          } catch {
            return [thread.id, []]
          }
        }),
      )
      setBlockingReasonMap(Object.fromEntries(details))
    }
    setBlockedExpanded(!blockedExpanded)
  }

  return { handleToggleBlocked }
}