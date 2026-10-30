import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'

/**
 * Preserve the established Roll view state while using v2's canonical
 * issue-level candidate projection. All exclusion and tag information
 * must come from native Rust, never a fabricated fallback.
 */
export function adaptRollV2Bootstrap(state: RollV2BootstrapResponse): RollBootstrapResponse {
  if (
    !Array.isArray(state.rollable)
    || !Number.isInteger(state.total_threads)
    || !Number.isInteger(state.available_threads)
    || !Number.isInteger(state.excluded_count)
    || !Array.isArray(state.excluded_threads)
    || !Number.isInteger(state.inactive_count)
    || !Array.isArray(state.inactive_threads)
  ) {
    throw new Error('Incomplete native Roll v2 bootstrap response')
  }

  return {
    ...state,
    roll_pool: state.rollable.map(({ thread, issue, routes }) => {
      if (!Array.isArray(thread.tags) || !issue || !Array.isArray(routes)) {
        throw new Error('Incomplete native Roll v2 candidate')
      }
      return {
        ...thread,
        issue_id: issue.id,
        issue_number: issue.number,
        route_labels: routes.map((route) => route.name),
      }
    }),
  }
}
