import { describe, expect, it } from 'vitest'
import type { Issue, Thread } from '../types'
import { applyIssueReadStatus } from '../pages/thread-detail/issueMutationState'

const thread: Thread = {
  id: 7,
  title: 'Test Thread',
  format: 'single issues',
  issues_remaining: 2,
  total_issues: 3,
  next_unread_issue_id: 11,
  next_unread_issue_number: '2',
  queue_position: 1,
  status: 'active',
  reading_progress: 'in_progress',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  notes: null,
  is_test: false,
  created_at: '2026-08-03T00:00:00Z',
}

const issues: Issue[] = [
  { id: 10, thread_id: 7, issue_number: '1', status: 'read', read_at: '2026-08-01T00:00:00Z', created_at: '2026-07-01T00:00:00Z' },
  { id: 11, thread_id: 7, issue_number: '2', status: 'unread', read_at: null, created_at: '2026-07-02T00:00:00Z' },
  { id: 12, thread_id: 7, issue_number: '3', status: 'unread', read_at: null, created_at: '2026-07-03T00:00:00Z' },
]

const readIssue: Issue = {
  id: 10,
  thread_id: 7,
  issue_number: '1',
  status: 'read',
  read_at: '2026-08-01T00:00:00Z',
  created_at: '2026-07-01T00:00:00Z',
}

describe('applyIssueReadStatus', () => {
  it('uses authoritative thread metadata when marking a visible issue read', () => {
    const result = applyIssueReadStatus({ issues, thread }, 11, {
      status: 'read',
      read_at: '2026-08-03T17:30:00Z',
      issues_remaining: 1,
      next_unread_issue_id: 99,
      next_unread_issue_number: '25',
      thread_status: 'active',
      thread_reading_progress: 'in_progress',
    })

    expect(result.issues[1]).toMatchObject({ status: 'read', read_at: '2026-08-03T17:30:00Z' })
    expect(result.thread).toMatchObject({
      issues_remaining: 1,
      next_unread_issue_id: 99,
      next_unread_issue_number: '25',
      status: 'active',
      reading_progress: 'in_progress',
    })
  })

  it('clears read_at when marking a visible issue unread', () => {
    const result = applyIssueReadStatus({ issues, thread }, 10, {
      status: 'unread',
      read_at: null,
      issues_remaining: 3,
      next_unread_issue_id: 10,
      next_unread_issue_number: '1',
      thread_status: 'active',
      thread_reading_progress: 'in_progress',
    })

    expect(result.issues[0]).toMatchObject({ status: 'unread', read_at: null })
    expect(result.thread.issues_remaining).toBe(3)
  })

  it('returns the original snapshot when the authoritative result is already applied', () => {
    const snapshot = { issues, thread }
    expect(applyIssueReadStatus(snapshot, 11, {
      status: 'unread',
      read_at: null,
      issues_remaining: 2,
      next_unread_issue_id: 11,
      next_unread_issue_number: '2',
      thread_status: 'active',
      thread_reading_progress: 'in_progress',
    })).toBe(snapshot)
  })

  it('returns the original snapshot when the issue is not visible', () => {
    const snapshot = { issues, thread }
    expect(applyIssueReadStatus(snapshot, 999, {
      status: 'read',
      read_at: '2026-08-03T17:30:00Z',
      issues_remaining: 1,
      next_unread_issue_id: 12,
      next_unread_issue_number: '3',
      thread_status: 'active',
      thread_reading_progress: 'in_progress',
    })).toBe(snapshot)
  })

  // Regression coverage for #3113: only the unread counters were projected onto
  // the cached thread, so a status flip never reached the thread query and the
  // thread detail STATUS panel kept rendering the pre-toggle value.
  it('reactivates a completed thread when the server reports the status flip', () => {
    const completedThread: Thread = {
      ...thread,
      issues_remaining: 0,
      next_unread_issue_id: null,
      next_unread_issue_number: null,
      status: 'completed',
      reading_progress: 'completed',
    }

    const result = applyIssueReadStatus({ issues: [readIssue], thread: completedThread }, 10, {
      status: 'unread',
      read_at: null,
      issues_remaining: 1,
      next_unread_issue_id: 10,
      next_unread_issue_number: '1',
      thread_status: 'active',
      thread_reading_progress: 'in_progress',
    })

    expect(result.thread).toMatchObject({
      status: 'active',
      reading_progress: 'in_progress',
      issues_remaining: 1,
    })
  })

  it('completes an active thread when the server reports the status flip', () => {
    const result = applyIssueReadStatus({ issues, thread }, 12, {
      status: 'read',
      read_at: '2026-08-03T17:35:00Z',
      issues_remaining: 0,
      next_unread_issue_id: null,
      next_unread_issue_number: null,
      thread_status: 'completed',
      thread_reading_progress: 'completed',
    })

    expect(result.thread).toMatchObject({
      status: 'completed',
      reading_progress: 'completed',
      issues_remaining: 0,
      next_unread_issue_id: null,
    })
  })

  it('emits a new snapshot when only the thread status changed', () => {
    const snapshot = { issues, thread }

    const result = applyIssueReadStatus(snapshot, 11, {
      status: 'unread',
      read_at: null,
      issues_remaining: 2,
      next_unread_issue_id: 11,
      next_unread_issue_number: '2',
      thread_status: 'blocked',
      thread_reading_progress: 'in_progress',
    })

    expect(result).not.toBe(snapshot)
    expect(result.thread.status).toBe('blocked')
  })

  it('treats an absent cached reading_progress as equal to a null result', () => {
    const threadWithoutProgress: Thread = { ...thread, reading_progress: undefined }
    const snapshot = { issues, thread: threadWithoutProgress }

    // `undefined` (older cached row) and `null` (server value) describe the
    // same state, so the projection must not churn the snapshot for it.
    expect(applyIssueReadStatus(snapshot, 11, {
      status: 'unread',
      read_at: null,
      issues_remaining: 2,
      next_unread_issue_id: 11,
      next_unread_issue_number: '2',
      thread_status: 'active',
      thread_reading_progress: null,
    })).toBe(snapshot)
  })

  it('emits a null reading_progress when the server clears one the cache held', () => {
    const result = applyIssueReadStatus({ issues, thread }, 11, {
      status: 'unread',
      read_at: null,
      issues_remaining: 2,
      next_unread_issue_id: 11,
      next_unread_issue_number: '2',
      thread_status: 'active',
      thread_reading_progress: null,
    })

    expect(result.thread.reading_progress).toBeNull()
  })
})
