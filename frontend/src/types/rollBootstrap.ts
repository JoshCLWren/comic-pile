import type { SessionThread } from './index'

/** Lightweight thread summary returned by the Roll bootstrap endpoint. */
export interface RollBootstrapThread {
  id: number
  title: string
  format: string
  last_activity_at?: string | null
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
  roll_pool: RollBootstrapThread[]
  snoozed_threads: RollBootstrapThread[]
  snoozed_count: number
  blocked_count: number
  blocked_threads: RollBootstrapThread[]
  stale_thread_count: number
  stale_thread: RollBootstrapThread | null
}
