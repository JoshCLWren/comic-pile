import type { RollLastReadPayload } from './index'
import type { Tag } from '../services/api-tags'

/**
 * Why the Roll pool has no in-play faces. One minimal reason derived from the
 * already-loaded Option E inputs; never a list, count or whole-library report.
 */
export type RollPoolReason =
  | 'ready'
  | 'no_series'
  | 'all_blocked'
  | 'all_completed'
  | 'all_out_of_pool'

/** Lightweight owner-scoped thread summary used by the Roll view. */
export interface RollThreadSummary {
  id: number
  title: string
  format: string
  issue_id?: number | null
  issue_number?: string | null
  blocking_reasons?: string[]
  route_labels?: string[]
  overflow_routes_count?: number
  last_activity_at?: string | null
  /** Visible direct tags, so a die face shows tag context before rolling (#3425). */
  tags?: Tag[]
}

export interface RollThreadMetadata extends RollThreadSummary {
  notes?: string | null
  issues_remaining?: number
  queue_position?: number
  total_issues?: number | null
  reading_progress?: string | null
  issue_number_alias?: string | null
  provider_issue_number?: string | null
  next_issue_id?: number | null
  next_issue_number?: string | null
  last_rolled_result?: number | null
  issues_read?: number | null
  last_rating?: number | null
}

/** One direct continuity blocker for a pending roll. */
export interface RollRecoveryBlocker {
  rule_id: number | null
  source_type: 'issue' | 'crossover'
  source_id: number
  source_label: string
  satisfaction_type: 'item_read' | 'all_members_read' | 'checkpoint' | 'selected_members_read'
  satisfied: false
  causing_issue_ids: number[]
  causing_member_issue_ids: number[]
  note: string | null
  crossover_id?: number | null
  sequence_position?: number | null
}

/** One currently readable prerequisite recommended by continuity traversal. */
export interface RollRecoveryPrerequisite {
  node_type: 'issue' | 'crossover'
  node_id: number
  label: string
  is_readable?: boolean
}

/** One labeled step in a continuity prerequisite path. */
export interface RollRecoveryChainNode extends RollRecoveryPrerequisite {
  is_readable: boolean
}

/** A bounded traversal diagnostic that explains malformed or oversized plans. */
export interface RollRecoveryDiagnostic {
  code: 'cycle_detected' | 'depth_limit_exceeded' | 'node_limit_exceeded'
  node_type: 'issue' | 'crossover'
  node_id: number
  limit?: number | null
}

/** Recovery context that keeps the original pending roll visible while blocked. */
export interface RollRecoveryInfo {
  original_thread_id: number
  original_thread_title: string
  direct_blockers: RollRecoveryBlocker[]
  readable_prerequisites: RollRecoveryPrerequisite[]
  chains?: RollRecoveryChainNode[][]
  diagnostics?: RollRecoveryDiagnostic[]
}

/** Request for accepting one concrete issue prerequisite recommendation. */
export interface RollPrerequisiteSwitchRequest {
  node_type: 'issue'
  node_id: number
}

/** Active Roll target after accepting a prerequisite recommendation. */
export interface RollPrerequisiteSwitchResponse {
  original_thread_id: number
  target_thread_id: number
  target_thread_title: string
  target_issue_id: number
  target_issue_number: string
  changed: boolean
}

/** Sessionless local Roll view assembled from scoped resources and browser pending. */
export interface RollState {
  pending_thread_id: number | null
  last_rolled_result: number | null
  active_thread: RollThreadMetadata | null
  roll_recovery?: RollRecoveryInfo | null
  roll_pool: RollThreadSummary[]
  snoozed_threads: RollThreadSummary[]
  snoozed_count: number
  /** Complete browser snooze ids; summaries contain only the bounded display rows. */
  snoozed_thread_ids?: number[]
  /** Minimal empty-pool explanation from the scoped eligible resource. */
  pool_reason?: RollPoolReason
  /** Durable last-read record from the scoped resource, with a rate-cache fallback. */
  last_read?: RollLastReadPayload | null
}
