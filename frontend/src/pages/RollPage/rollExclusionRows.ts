import type { BlockingDependency } from '../../types'
import type { RollBootstrapThread, ThreadExclusionReason } from '../../types/rollBootstrap'

/**
 * Map one loaded blocked-exclusion row onto the pool row shape `ThreadPool` renders.
 *
 * A missing Thread id becomes `0`, the sentinel `ThreadPool` treats as
 * non-actionable, so a blocked row never renders a speculative link.
 */
export function toBlockedPoolRow(item: ThreadExclusionReason): RollBootstrapThread {
  return {
    id: item.thread_id ?? 0,
    title: item.title,
    format: item.format,
    blocking_reasons: item.blocking_reasons ?? [],
    last_activity_at: item.last_activity_at ?? null,
  }
}

/**
 * Merge loaded blocked-exclusion dependency details into the bootstrap map.
 *
 * Only rows with a resolvable Thread id contribute, so `undefined` can never
 * become a map key and leak dependency details onto another series.
 */
export function mergeBlockingDependencies(
  base: Record<number, BlockingDependency[]>,
  items: ThreadExclusionReason[],
) {
  const merged = { ...base }
  for (const item of items) {
    if (item.thread_id && item.blocking_dependencies && item.blocking_dependencies.length > 0) {
      merged[item.thread_id] = item.blocking_dependencies
    }
  }
  return merged
}
