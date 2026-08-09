import type { SessionThread } from './index'

/** Lightweight thread summary returned by the Roll bootstrap endpoint. */
export interface RollBootstrapThread {
  id: number
  title: string
  format: string
  last_activity_at?: string | null
}

/** One direct continuity blocker for a pending roll. */
export interface RollRecoveryBlocker {
  rule_id: number
  source_type: 'issue' | 'crossover'
  source_id: number
  source_label: string
  satisfaction_type: 'complete' | 'reach_issue'
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

/** Recovery context that keeps the original pending roll visible while blocked. */
export interface RollRecoveryInfo {
  original_thread_id: number
  original_thread_title: string
  direct_blockers: RollRecoveryBlocker[]
  readable_prerequisites: RollRecoveryPrerequisite[]
}

/** Bounded bootstrap payload for the Roll initial render. */
export interface RollBootstrapResponse {
  session_id: number
  user_id: number
  current_die: number
  manual_die: number | null
  pending_thread_id: number | null
  last_rolled_result: number | null
  active_thread: SessionThread | null
  roll_recovery: RollRecoveryInfo | null
  roll_pool: RollBootstrapThread[]
  snoozed_threads: RollBootstrapThread[]
  snoozed_count: number
  blocked_count: number
  blocked_threads: RollBootstrapThread[]
  stale_thread_count: number
  stale_thread: RollBootstrapThread | null
}

declare module './index' {
  interface RollBootstrapThread {
    id: number
    title: string
    format: string
    last_activity_at?: string | null
  }
}
