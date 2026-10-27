import type {
  BlockingDependency,
  ReadingBandwidth,
  ReadingIntent,
  SessionMode,
  SessionThread,
} from './index'
import type { Tag } from '../services/api-tags'

export type { ReadingBandwidth, ReadingIntent, SessionMode, SessionModeCorrectionGuidance } from './index'

/** Lightweight thread summary returned by the Roll bootstrap endpoint. */
export interface RollBootstrapThread {
  id: number
  title: string
  format: string
  issue_id?: number | null
  issue_number?: string | null
  blocking_reasons?: string[]
  route_labels?: string[]
  last_activity_at?: string | null
  /** Visible direct tags, so a die face shows tag context before rolling (#3425). */
  tags?: Tag[]
}

/** One series excluded from the roll pool, with the reason the user can understand. */
export interface ThreadExclusionReason {
  /**
   * Stable Thread id for the row.
   *
   * The server always sends it, but the UI treats it as optional so a
   * contract-violating row renders honest plain text instead of linking to a
   * speculative `/thread/undefined` route.
   */
  thread_id?: number
  title: string
  format: string
  /** Truthful identity context for disambiguating same-named out-of-pool series. */
  year?: number | string | null
  volume?: string | null
  publisher?: string | null
  reason: "blocked" | "snoozed" | "skipped" | "completed" | "not_in_queue"
  detail?: string | null
  /** Live eligibility labels for a blocked series, when the server has them. */
  blocking_reasons?: string[]
  /** Navigable dependency details for a blocked series, when the server has them. */
  blocking_dependencies?: BlockingDependency[]
  last_activity_at?: string | null
}

/** Categories the Roll exclusion drill-down can page through (issue #3330). */
export type RollExclusionCategory = 'blocked' | 'inactive'

/**
 * One deterministic page of a Roll exclusion category.
 *
 * `total` is the authoritative category size, computed by the backend from the
 * same predicate as the bootstrap category count, so a heading can never show
 * the loaded preview size as if it were the total.
 */
export interface RollExclusionPageResponse {
  category: RollExclusionCategory
  items: ThreadExclusionReason[]
  total: number
  limit: number
  offset: number
  next_cursor: string | null
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
  /** Specific issue identity/number for the restored pending roll, when known. */
  original_thread_issue_number?: string | null
  /** Honest rating representation; null means no rating was recorded. */
  original_thread_rating?: number | null
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

/**
 * Canonical session reading-mode snapshot returned by Roll bootstrap.
 * Raw confidence is metadata for other surfaces and must not render in compact controls.
 */
export interface SessionModeState {
  bandwidth: ReadingBandwidth | string | null
  intent: ReadingIntent | string | null
  source?: string | null
  confidence?: number | null
  version?: string | number | null
}

/** Human-readable label for a bandwidth or intent value; falls back to the raw value. */
export function readingModeLabel(value: string | null | undefined): string {
  if (!value) return ''
  const normalized = value.trim().toLowerCase()
  if (normalized === 'balanced') return 'Balanced'
  if (normalized === 'light') return 'Light'
  if (normalized === 'deep') return 'Deep'
  if (normalized === 'momentum') return 'Momentum'
  if (normalized === 'familiar') return 'Familiar'
  if (normalized === 'explore') return 'Explore'
  if (normalized === 'random') return 'Random'
  return value.trim()
}

/** Compact `Bandwidth · Intent` summary for header-scale mode controls. */
export function formatSessionMode(mode: SessionModeState | null | undefined): string {
  if (!mode) return ''
  const parts = [readingModeLabel(mode.bandwidth), readingModeLabel(mode.intent)].filter(Boolean)
  return parts.join(' · ')
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
  skipped_thread_ids: number[]
  skipped_threads: RollBootstrapThread[]
  blocked_count: number
  blocked_threads: RollBootstrapThread[]
  stale_thread_count: number
  stale_thread: RollBootstrapThread | null
  timezone?: string | null

  // Issue #3125: exclusion transparency — every series not in the pool is
  // explained so the user can see why options vanish.
  total_threads?: number
  available_threads?: number
  excluded_count?: number
  excluded_threads?: ThreadExclusionReason[]
  inactive_count?: number
  inactive_threads?: ThreadExclusionReason[]
}