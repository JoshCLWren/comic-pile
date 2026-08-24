import { useCallback, useEffect, useState } from 'react'
import { api } from '../services/api'
import type { TasteDiscovery } from '../components/TasteDiscoveryCard'

interface UseTasteDiscoveryOptions {
  enabled?: boolean
  pollIntervalMs?: number
}

export function useTasteDiscovery(options: UseTasteDiscoveryOptions = {}) {
  const { enabled = true, pollIntervalMs } = options
  const [discoveries, setDiscoveries] = useState<TasteDiscovery[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const fetchDiscoveries = useCallback(async () => {
    if (!enabled) return
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.get<TasteDiscovery[]>('/v1/taste/discoveries')
      setDiscoveries(res)
    } catch (err) {
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    fetchDiscoveries()
    if (pollIntervalMs && enabled) {
      const id = setInterval(fetchDiscoveries, pollIntervalMs)
      return () => clearInterval(id)
    }
  }, [fetchDiscoveries, pollIntervalMs, enabled])

  const submitVerdict = useCallback(
    async (signalId: number, verdict: 'confirmed' | 'sometimes' | 'rejected') => {
      await api.post(`/v1/taste/signals/${signalId}/verdict`, { verdict })
      setDiscoveries((prev) => prev.filter((d) => d.signal.id !== signalId))
    },
    [],
  )

  const dismiss = useCallback((signalId: number) => {
    // Dismissal does not count as verdict — just hide locally, cooldown handles re-prompt suppression via backend last_prompted_at only on verdict.
    // For UX, we hide this session without recording verdict.
    setDiscoveries((prev) => prev.filter((d) => d.signal.id !== signalId))
  }, [])

  return { discoveries, isLoading, error, refetch: fetchDiscoveries, submitVerdict, dismiss }
}
