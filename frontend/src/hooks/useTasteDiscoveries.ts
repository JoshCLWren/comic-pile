import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  tasteApi,
  type TasteDiscovery,
  type TasteVerdict,
} from '../services/api-taste'
import { queryKeys } from '../query/queryKeys'

interface TasteDiscoveriesState {
  discoveries: TasteDiscovery[]
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

/**
 * Load prompt-eligible Taste Bank discoveries once per Roll visit and manage
 * the local response queue. Verdicts are submitted through the canonical
 * Taste Bank signal API; dismissal only suppresses the discovery card.
 * Discovery failures never surface as page errors: the card simply stays
 * hidden so rolling and rating are never interrupted.
 */
export function useTasteDiscoveries(): TasteDiscoveriesState {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.taste.discoveries(),
    queryFn: async () => {
      const response = await tasteApi.getDiscoveries();
      return response.discoveries;
    },
  });

  const pendingIdsRef = useRef(new Set<number>())

  const removeCurrent = useCallback((signalId: number) => {
    setDiscoveries((previous) => ({
      ...previous,
      discoveries: previous.discoveries.filter((item) => item.id !== signalId),
    }))
  }, [setDiscoveries])

  // We need to use useState for the discoveries since we're modifying it based on user actions
  // But we'll derive the initial value from the query data
  const [discoveries, setDiscoveries] = useState<TasteDiscovery[]>([])

  // Synchronize discoveries state with query data
  useEffect(() => {
    setDiscoveries(data ?? [])
  }, [data, setDiscoveries])

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

  const dismiss = useCallback(async (): Promise<boolean> => {
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
  }, [discoveries, removeCurrent])

  return {
    current: discoveries.length > 0 ? discoveries[0] : null,
    isLoading: isPending,
    isError,
    error,
    refetch,
    respond,
    dismiss,
  }
}
