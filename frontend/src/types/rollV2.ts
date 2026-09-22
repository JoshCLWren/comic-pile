import type { SessionMode, SessionThread } from './index'
import type { RollRecoveryInfo } from './rollBootstrap'

export type { RollBootstrapResponse, RollBootstrapThread } from './rollBootstrap'

/** Frozen v2 identity derived-state enum. */
export type RollV2IdentityState =
  | 'confirmed'
  | 'candidate'
  | 'unresolved'
  | 'ambiguous'
  | 'conflicting'

/** Frozen v2 route kind. No subtype is inferred from the group name. */
export type RollV2RouteKind = 'group'

/** Frozen v2 progress scope. Canonical run length is the denominator. */
export type RollV2ProgressScope = 'canonical_series_run' | 'thread'

/** Frozen v2 identity source. Unavailable means null canonical id/stats. */
export type RollV2IdentitySource = 'comicvine' | 'unavailable'

/** Thread row inside a v2 rollable item. */
export interface RollV2Thread {
  id: number
  title: string
  format: string
  last_activity_at?: string | null
}

/** Required next-unread issue row. V2 never returns `issue: null`. */
export interface RollV2Issue {
  id: number
  number: string
  canonical_series_title?: string | null
  /** Same-origin `/api/v1/images/optimize?...` URL only, else null. */
  cover_url?: string | null
}

/** Canonical identity row reusing #1401 semantics. */
export interface RollV2Identity {
  source: RollV2IdentitySource
  canonical_series_id: string | null
  state: RollV2IdentityState
  series_mapping_state: RollV2IdentityState
}

/** Reader context row with explicit nullability. */
export interface RollV2Reader {
  latest_rating: number | null
  average_rating: number | null
  rating_count: number | null
  read_count: number | null
  issue_count: number | null
  progress_scope: RollV2ProgressScope
}

/** One route. At most 3 per item; extras count toward overflow. */
export interface RollV2Route {
  kind: RollV2RouteKind
  name: string
}

/** One rollable candidate row. */
export interface RollV2Item {
  thread: RollV2Thread
  issue: RollV2Issue
  identity: RollV2Identity
  reader: RollV2Reader
  routes: RollV2Route[]
  overflow_routes_count: number
}

/** Nullable session-scoped last-read object shared with rate responses. */
export interface RollV2LastRead {
  issue_id?: number | null
  issue_number?: string | null
  thread_id?: number | null
  thread_title?: string | null
  read_at?: string | null
}

/** Session bandwidth state carried by bootstrap responses. */
export interface RollV2BandwidthState {
  predicted_bandwidth: string | null
  active_bandwidth: string | null
  confidence: number | null
  source: string | null
  mode_version: string | null
}

/**
 * V2 bootstrap superset. Every v1 session/recovery/partition field keeps its
 * semantics; `roll_pool` is replaced by `rollable` and `last_read` is added.
 */
export interface RollV2BootstrapResponse {
  session_id: number
  user_id: number
  current_die: number
  manual_die: number | null
  pending_thread_id: number | null
  last_rolled_result: number | null
  session_mode: SessionMode
  active_thread: SessionThread | null
  roll_recovery?: RollRecoveryInfo | null
  bandwidth: RollV2BandwidthState
  rollable: RollV2Item[]
  last_read: RollV2LastRead | null
  snoozed_threads: RollV2Thread[]
  snoozed_count: number
  skipped_thread_ids: number[]
  skipped_threads: RollV2Thread[]
  blocked_count: number
  blocked_threads: RollV2Thread[]
  stale_thread_count: number
  stale_thread: RollV2Thread | null
  timezone?: string | null
}

/** Additive rate response: ThreadResponse fields plus roll reconciliation. */
export interface RollV2RateResponse {
  id: number
  title: string
  format: string
  issues_remaining: number
  queue_position: number
  status: string
  last_rating: number | null
  last_activity_at: string | null
  notes: string | null
  is_test: boolean
  is_blocked: boolean
  blocking_reasons: string[]
  created_at: string
  total_issues: number | null
  reading_progress: string | null
  next_unread_issue_id: number | null
  next_unread_issue_number: string | null
  roll_reconciliation: { last_read: RollV2LastRead } | null
}
