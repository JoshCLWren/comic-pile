/**
 * Single source of truth for when a snooze control may be used.
 *
 * `POST /v1/snooze/` snoozes the reading session's **pending** thread, so
 * "snooze this series" is only meaningful for the series the reader currently
 * has rolled. Every snooze entry point (Queue row menu, Roll pool action sheet)
 * derives its enabled state and its disabled explanation from this module, so
 * the rule and its wording cannot drift between the two surfaces.
 *
 * Before this rule existed the Roll pool action sheet ignored the selected
 * series entirely and fired the pending-thread snooze anyway, which either
 * snoozed a different series or failed with a 400 the sheet swallowed into the
 * console. The reader saw the sheet close and nothing recorded — the exact
 * symptom reported in issue #3260.
 */

/** Explains why a snooze control is unavailable for a series. */
export const SNOOZE_REQUIRES_PENDING_SERIES_REASON =
  'Only the series you rolled this session can be snoozed'

interface SnoozeAvailabilityInput {
  /** Series the control was opened for. */
  threadId: number
  /** Whether that series is already snoozed in the current session. */
  isSnoozed: boolean
  /** The reading session's pending thread, or `null` when nothing is rolled. */
  pendingThreadId: number | null | undefined
}

/**
 * Resolve whether a snooze control may be used for a series.
 *
 * Unsnoozing is always available for a series the session already snoozed.
 * Snoozing requires the control's series to be the session's pending thread.
 *
 * @param input - The control's series plus its snoozed and pending context.
 * @returns True when the control may be used.
 */
export function canSnoozeSeries({
  threadId,
  isSnoozed,
  pendingThreadId,
}: SnoozeAvailabilityInput): boolean {
  if (isSnoozed) return true
  return pendingThreadId != null && pendingThreadId === threadId
}
