import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import {
  continuityPlansApi,
  type ReadingPlanReleaseSourceStatus,
} from '../services/api-continuity-plans'

/**
 * List the reader's release sources for one plan.
 *
 * The plan reader view already embeds release source status, so this hook is
 * only needed for surfaces that mutate sources without reloading the plan
 * reader, or that need the status outside of the reader view.
 */
export function useReleaseSources(planId: number | null) {
  return useQuery({
    queryKey: planId ? queryKeys.readingPlans.releaseSources(planId) : [],
    queryFn: () => continuityPlansApi.listReleaseSources(planId!),
    enabled: planId != null,
  })
}

/**
 * Enable or disable one release source.
 *
 * The mutation flips the enable flag in every cached plan reader view and
 * release-source list so the toggle feels instant, then invalidates the
 * sync status so the last-synced timestamp reflects reality.
 */
export function useEnableReleaseSource(deps: EnableReleaseSourceDeps = {}) {
  const { api = continuityPlansApi } = deps
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      sourceId,
      enabled,
    }: {
      sourceId: number
      enabled: boolean
    }) => api.updateReleaseSourceEnabled(sourceId, enabled),
    onMutate: async ({ sourceId, enabled }) => {
      const rollbacks: Array<() => void> = []
      // Update every cached plan reader view that already contains this source.
      // The prefix `['readingPlans', 'reader']` matches every plan's reader
      // query regardless of plan id, so a toggle on any plan re-renders the
      // cached view without needing the plan id at mutation time.
      const readerPrefix = queryKeys.readingPlans.reader(0).slice(0, 2)
      for (const [key, data] of client.getQueriesData({
        queryKey: readerPrefix,
      })) {
        if (!data || typeof data !== 'object') continue
        const record = data as {
          release_sources?: ReadingPlanReleaseSourceStatus[]
        }
        if (!Array.isArray(record.release_sources)) continue
        const previous = record.release_sources
        if (!previous.some((source) => source.source_id === sourceId)) continue
        const next = previous.map((source) =>
          source.source_id === sourceId ? { ...source, enabled } : source,
        )
        client.setQueryData(key, { ...record, release_sources: next })
        rollbacks.push(() =>
          client.setQueryData(key, { ...record, release_sources: previous }),
        )
      }
      return { rollbacks }
    },
    onError: (_err, _vars, ctx) => {
      for (const rollback of ctx?.rollbacks ?? []) {
        rollback()
      }
    },
    onSuccess: async () => {
      // Re-fetch every plan reader view that cached this source so the server
      // truth (enable flag and last_synced_at) replaces the optimistic value.
      const readerPrefix = queryKeys.readingPlans.reader(0).slice(0, 2)
      await client.invalidateQueries({ queryKey: readerPrefix })
      await client.invalidateQueries({
        queryKey: queryKeys.readingPlans.releaseSources(0).slice(0, 2),
      })
    },
  })
}