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
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-08-03T00:00:00Z',
}

const issues: Issue[] = [
  { id: 10, thread_id: 7, issue_number: '1', status: 'read', read_at: '2026-08-01T00:00:00Z', created_at: '2026-07-01T00:00:00Z' },
  { id: 11, thread_id: 7, issue_number: '2', status: 'unread', read_at: null, created_at: '2026-07-02T00:00:00Z' },
  { id: 12, thread_id: 7, issue_number: '3', status: 'unread', read_at: null, created_at: '2026-07-03T00:00:00Z' },
]

describe('applyIssueReadStatus', () => {
  it('uses authoritative thread metadata when marking a visible issue read', () => {
    const result = applyIssueReadStatus({ issues, thread }, 11, {
      status: 'read',
      read_at: '2026-08-03T17:30:00Z',
      issues_remaining: 1,
      next_unread_issue_id: 99,
      next_unread_issue_number: '25',
    })

    expect(result.issues[1]).toMatchObject({ status: 'read', read_at: '2026-08-03T17:30:00Z' })
    expect(result.thread).toMatchObject({
      issues_remaining: 1,
      next_unread_issue_id: 99,
      next_unread_issue_number: '25',
    })
  })

  it('clears read_at when marking a visible issue unread', () => {
    const result = applyIssueReadStatus({ issues, thread }, 10, {
      status: 'unread',
      read_at: null,
      issues_remaining: 3,
      next_unread_issue_id: 10,
      next_unread_issue_number: '1',
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
    })).toBe(snapshot)
  })
})
