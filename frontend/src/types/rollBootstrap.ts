import type { SessionThread } from './index'

/** Lightweight thread summary returned by the Roll bootstrap endpoint. */
export interface RollBootstrapThread {
  id: number
  title: string
  format: string
  issue_id?: number | null
  issue_number?: string | null
  route_labels?: string[]
  last_activity_at?: string | null
}

/** One direct continuity blocker for a pending roll. */
export interface RollRecoveryBlocker {
  rule_id: number
  source_type: 'issue' | 'crossover'
  source_id: number
  source_label: string
  satisfaction_type: 'item_read' | 'all_members_read' | 'checkpoint' | 'selected_members_read'
  satisfied: false
  causing_issue_ids: number[]
  causing_member_issue_ids: number[]
  note: string | null
}

/** One currently readable prerequisite recommended by continuity traversal. */
export interface RollRecoveryPrerequisite {
  node_type: 'issue' | 'crossover'
  node_id: number
  label: string
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

/** Compact band+intent reading mode record exposed at Roll bootstrap. */
export interface SessionMode {
  active_bandwidth: string | null
  predicted_bandwidth: string | null
  bandwidth_confidence: number | null
  bandwidth_source: 'manual' | 'inferred' | null
  bandwidth_version: string | null
  active_intent: string | null
  predicted_intent: string | null
  intent_confidence: number | null
  intent_source: 'manual' | 'inferred' | null
  intent_version: string | null
  session_mode_correction_guidance: Record<string, unknown> | null
}

/** Bounded bootstrap payload for the Roll initial render. */
export interface RollBootstrapResponse {
  session_id: number
  user_id: number
  current_die: number
  manual_die: number | null
  pending_thread_id: number | null
  last_rolled_result: number | null
  session_mode: SessionMode
  active_thread: SessionThread | null
  roll_recovery?: RollRecoveryInfo | null
  roll_pool: RollBootstrapThread[]
  snoozed_threads: RollBootstrapThread[]
  snoozed_count: number
  blocked_count: number
  blocked_threads: RollBootstrapThread[]
  stale_thread_count: number
  stale_thread: RollBootstrapThread | null
}

declare module './index' {
  interface RollBootstrapResponse {
    session_mode: SessionMode
  }
}
