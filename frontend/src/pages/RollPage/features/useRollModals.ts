import { useCallback } from 'react'
import type { RollPageStateSetters } from '../useRollPageState'

export function useRollModals(setters: RollPageStateSetters) {
  const handleThreadClick = useCallback((thread: any) => {
    setters.setSelectedThread(thread)
    setters.setIsActionSheetOpen(true)
  }, [setters])

  const handleToggleBlocked = useCallback(async (bootstrap: any, dependenciesApi: any) => {
    if (!setters.blockedExpanded) {
      const blockedThreads = bootstrap?.blocked_threads ?? []
      const details = await Promise.all(
        blockedThreads.map(async (thread: any): Promise<[number, string[]]> => {
          try {
            const info = await dependenciesApi.getBlockingInfo(thread.id)
            return [thread.id, info.blocking_reasons ?? []]
          } catch {
            return [thread.id, []]
          }
        }),
      )
      setters.setBlockingReasonMap(Object.fromEntries(details))
    }
    setters.setBlockedExpanded(!setters.blockedExpanded)
  }, [setters])

  return {
    handleThreadClick,
    handleToggleBlocked,
  }
}
