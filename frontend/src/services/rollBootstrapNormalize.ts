import type { RollBootstrapResponse, RollPoolRow } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse, RollV2Item } from '../types/rollV2'

/**
 * Convert one v2 rollable item into the idle Roll pool row the UI renders.
 *
 * Every value is copied from the single v2 response. Nullable provider fields
 * stay null so the row can render honest fallbacks instead of inventing a
 * cover, canonical title, rating, or run length.
 *
 * @param item - One rollable item from `GET /api/v2/roll/bootstrap`.
 * @returns The pool row carrying legacy identity plus v2 enrichment.
 */
function toPoolRow(item: RollV2Item): RollPoolRow {
  return {
    id: item.thread.id,
    title: item.thread.title,
    format: item.thread.format,
    issue_id: item.issue.id,
    issue_number: item.issue.number,
    last_activity_at: item.thread.last_activity_at ?? null,
    cover_url: item.issue.cover_url ?? null,
    canonical_series_title: item.issue.canonical_series_title ?? null,
    identity_state: item.identity.state,
    series_mapping_state: item.identity.series_mapping_state,
    latest_rating: item.reader.latest_rating,
    average_rating: item.reader.average_rating,
    rating_count: item.reader.rating_count,
    read_count: item.reader.read_count,
    issue_count: item.reader.issue_count,
    progress_scope: item.reader.progress_scope,
    routes: item.routes.map((route) => ({ kind: route.kind, name: route.name })),
    overflow_routes_count: item.overflow_routes_count,
  }
}

/**
 * Normalize the v2 bootstrap response into the Roll page's existing shape.
 *
 * Session chrome (die, pending roll, recovery, snoozed/skipped/blocked/stale
 * summaries) keeps v1 semantics from the same v2 payload. Only `roll_pool` is
 * derived, from `rollable`, so the idle screen never joins a second bootstrap
 * source.
 *
 * @param response - The authoritative v2 bootstrap response.
 * @returns The bounded view consumed by the idle Roll page.
 */
export function normalizeRollV2Bootstrap(
  response: RollV2BootstrapResponse,
): RollBootstrapResponse {
  return {
    session_id: response.session_id,
    user_id: response.user_id,
    current_die: response.current_die,
    manual_die: response.manual_die,
    pending_thread_id: response.pending_thread_id,
    last_rolled_result: response.last_rolled_result,
    session_mode: response.session_mode,
    active_thread: response.active_thread,
    roll_recovery: response.roll_recovery ?? null,
    roll_pool: response.rollable.map(toPoolRow),
    snoozed_threads: response.snoozed_threads,
    snoozed_count: response.snoozed_count,
    skipped_thread_ids: response.skipped_thread_ids,
    skipped_threads: response.skipped_threads,
    blocked_count: response.blocked_count,
    blocked_threads: response.blocked_threads,
    stale_thread_count: response.stale_thread_count,
    stale_thread: response.stale_thread,
    timezone: response.timezone ?? null,
  }
}
