import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { invalidateReadingListsAfterCrossTabChange } from '../query/cacheEffects'
import { subscribeToCrossTabChanges } from '../query/crossTabDataSync'

/**
 * Keep an open Reading List in sync with Thread metadata edits made in another
 * tab (#5862).
 *
 * A committed Thread title edit announces itself on the cross-tab data
 * channel, so the receiving tab cancels and refetches its Reading List queries
 * instead of waiting out the 30s `staleTime` or requiring a manual reload.
 * Re-focusing the tab also refreshes, covering browsers without
 * `BroadcastChannel` and tabs that missed a message while suspended.
 */
export function useReadingListsCrossTabSync(): void {
  const client = useQueryClient()

  useEffect(
    () =>
      subscribeToCrossTabChanges((change) => {
        if (change.type === 'thread-metadata-changed') {
          void invalidateReadingListsAfterCrossTabChange(client)
        }
      }),
    [client],
  )

  useEffect(() => {
    function onTabFocus(): void {
      if (document.visibilityState !== 'visible') return
      void invalidateReadingListsAfterCrossTabChange(client)
    }
    document.addEventListener('visibilitychange', onTabFocus)
    window.addEventListener('focus', onTabFocus)
    return () => {
      document.removeEventListener('visibilitychange', onTabFocus)
      window.removeEventListener('focus', onTabFocus)
    }
  }, [client])
}
