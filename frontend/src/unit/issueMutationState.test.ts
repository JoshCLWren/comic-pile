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
  {
    id: 10,
    thread_id: 7,
    issue_number: '1',
    status: 'read',
    read_at: '2026-08-01T00:00:00Z',
    created_at: '2026-07-01T00:00:00Z',
  },
  {
    id: 11,
    thread_id: 7,
    issue_number: '2',
    status: 'unread',
    read_at: null,
    created_at: '2026-07-02T00:00:00Z',
  },
  {
    id: 12,
    thread_id: 7,
    issue_number: '3',
    status: 'unread',
    read_at: null,
    created_at: '2026-07-03T00:00:00Z',
  },
]

describe('applyIssueReadStatus', () => {
  it('marks a visible issue read and advances the thread summary', () => {
    const result = applyIssueReadStatus({ issues, thread }, 11, 'read')

    expect(result.issues.map((issue) => issue.status)).toEqual(['read', 'read', 'unread'])
    expect(result.thread.issues_remaining).toBe(1)
    expect(result.thread.next_unread_issue_id).toBe(12)
    expect(result.thread.next_unread_issue_number).toBe('3')
  })

  it('marks a visible issue unread and restores it as next unread', () => {
    const result = applyIssueReadStatus({ issues, thread }, 10, 'unread')

    expect(result.issues[0]?.status).toBe('unread')
    expect(result.thread.issues_remaining).toBe(3)
    expect(result.thread.next_unread_issue_id).toBe(10)
    expect(result.thread.next_unread_issue_number).toBe('1')
  })

  it('returns the original snapshot when the requested status is already applied', () => {
    const snapshot = { issues, thread }

    expect(applyIssueReadStatus(snapshot, 11, 'unread')).toBe(snapshot)
  })
})
