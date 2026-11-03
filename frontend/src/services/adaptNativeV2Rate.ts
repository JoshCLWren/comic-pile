import type { RateResponsePayload } from '../types'
import type { IssueReadRateResponse } from '../generated/nativeV2Client'

/**
 * Adapt the native V2 issue read/rate response to the Python RateResponse shape
 * expected by the frontend. The native V2 returns IssueReadRateResponse with
 * issue and thread progress, while the Python v1 returns a flat RateResponse
 * that extends ThreadResponse with roll_reconciliation.
 */
export function adaptNativeV2Rate(native: IssueReadRateResponse): RateResponsePayload {
  const thread = native.thread
  const issue = native.issue

  // Build roll_reconciliation from the native response
  const rollReconciliation = native.read_event_created ? {
    last_read: {
      issue_id: issue.issue_id,
      issue_number: issue.issue_number,
      thread_id: thread.thread_id,
      thread_title: issue.thread_title,
      read_at: issue.read_at ?? new Date().toISOString(),
    },
  } : undefined

  return {
    // ThreadResponse fields from native thread progress
    id: thread.thread_id,
    title: issue.thread_title,
    format: '', // Not in native thread progress, but required by Python shape
    issues_remaining: thread.issues_remaining,
    queue_position: 0, // Not in native thread progress
    status: thread.status,
    last_rating: thread.last_rating ?? null,
    last_activity_at: null, // Not in native thread progress
    notes: null,
    is_test: false,
    is_blocked: false,
    created_at: new Date().toISOString(), // Not in native thread progress
    total_issues: undefined,
    reading_progress: thread.reading_progress ?? undefined,
    next_unread_issue_id: thread.next_unread_issue_id ?? undefined,
    next_unread_issue_number: undefined, // Not in native thread progress
    manual_creator_credits: [],
    blocking_reasons: [],
    roll_reconciliation: rollReconciliation,
  }
}