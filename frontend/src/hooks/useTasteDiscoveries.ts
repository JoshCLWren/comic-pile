import { useCallback, useEffect, useRef, useState } from 'react'
import {
  tasteApi,
  type TasteDiscovery,
  type TasteVerdict,
} from '../services/api-taste'

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
  const [state, setState] = useState<TasteDiscoveriesState>({
    discoveries: [],
    isLoading: true,
  })
  const pendingIdsRef = useRef(new Set<number>())

  useEffect(() => {
    let isCurrent = true

    setState({ discoveries: [], isLoading: true })
    tasteApi
      .getDiscoveries()
      .then((response) => {
        if (isCurrent) {
          setState({ discoveries: response.discoveries, isLoading: false })
        }
      })
      .catch(() => {
        if (isCurrent) {
          setState({ discoveries: [], isLoading: false })
        }
      })

    return () => {
      isCurrent = false
    }
  }, [])

  const removeCurrent = useCallback((signalId: number) => {
    setState((previous) => ({
      ...previous,
      discoveries: previous.discoveries.filter((item) => item.id !== signalId),
    }))
  }, [])

  const respond = useCallback(
    async (verdict: TasteVerdict): Promise<boolean> => {
      const current = state.discoveries[0]
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
    [state.discoveries, removeCurrent],
  )

  const dismiss = useCallback(async (): Promise<boolean> => {
    const current = state.discoveries[0]
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
  }, [state.discoveries, removeCurrent])

  return {
    current: state.discoveries.length > 0 ? state.discoveries[0] : null,
    isLoading: state.isLoading,
    respond,
    dismiss,
  }
}
