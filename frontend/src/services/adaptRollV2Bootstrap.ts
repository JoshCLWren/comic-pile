import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'

/**
 * Keep the Roll page's established state contract while routing its only
 * bootstrap read through Rust's native v2 endpoint.
 *
 * V2 intentionally replaces roll_pool with rollable: issue identity and
 * reading-list route labels live on each candidate rather than the thread.
 * Keep the remaining authoritative v2 fields intact, including last_read,
 * instead of issuing a second Python v1 request for enrichment.
 */
export function adaptRollV2Bootstrap(state: RollV2BootstrapResponse): RollBootstrapResponse {
  return {
    ...state,
    roll_pool: state.rollable.map(({ thread, issue, routes }) => ({
      ...thread,
      issue_id: issue.id,
      issue_number: issue.number,
      route_labels: routes.map((route) => route.name),
    })),
  }
}
