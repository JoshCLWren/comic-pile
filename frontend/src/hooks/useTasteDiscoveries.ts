import { useCallback, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  tasteApi,
  type TasteDiscovery,
  type TasteVerdict,
} from '../services/api-taste'
import { queryKeys } from '../query/queryKeys'

interface TasteDiscoveriesState {
  discoveries: TasteDiscovery[]
  isLoading: boolean
}

/**
 * Load prompt-eligible Taste Bank discoveries once per Roll visit and manage
 * the local response queue. Verdicts are submitted through the canonical
 * Taste Bank signal API; dismissal only suppresses the discovery card.
 * Discovery failures never surface as page errors: the card simply stays
 * hidden so rolling and rating are never interrupted.
 */
export function useTasteDiscoveries() {
  const { data, isPending } = useQuery({
    queryKey: queryKeys.taste.discoveries(),
    queryFn: () => tasteApi.getDiscoveries(),
    initialData: { discoveries: [] } as { discoveries: TasteDiscovery[] },
  })

  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  const pendingIdsRef = useRef(new Set<number>())

  const discoveries = (data?.discoveries ?? []).filter((item) => !dismissed.has(item.id))

  const removeCurrent = useCallback((signalId: number) => {
    setDismissed((previous) => {
      const next = new Set(previous)
      next.add(signalId)
      return next
    })
  }, [])

  const respond = useCallback(
    async (verdict: TasteVerdict): Promise<boolean> => {
      const current = discoveries[0]
      if (!current || pendingIdsRef.current.has(current.id)) return false

      pendingIdsRef.current.add(current.id)
      try {
        await tasteApi.submitVerdict(current.signal_type, current.external_key, verdict)
        removeCurrent(current.id)
        return true
      } catch {
        // Keep the card visible on failure so the reader can retry later.
        return false
      } finally {
        pendingIdsRef.current.delete(current.id)
      }
    },
    [discoveries, removeCurrent],
  )

  const dismiss = useCallback(
    async (): Promise<boolean> => {
      const current = discoveries[0]
      if (!current || pendingIdsRef.current.has(current.id)) return false

      pendingIdsRef.current.add(current.id)
      try {
        await tasteApi.dismiss(current.id)
        removeCurrent(current.id)
        return true
      } catch {
        return false
      } finally {
        pendingIdsRef.current.delete(current.id)
      }
    },
    [discoveries, removeCurrent],
  )

  return {
    current: discoveries.length > 0 ? discoveries[0] : null,
    isLoading: isPending,
    respond,
    dismiss,
  }
}
