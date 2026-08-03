import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueReadStatusButton } from '../pages/thread-detail/IssueReadStatusButton'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import type { Issue, Thread } from '../types'
import type { IssueMutationSnapshot } from '../pages/thread-detail/issueMutationState'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    markRead: vi.fn(),
    markUnread: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../services/api', () => ({
  threadsApi: {
    get: vi.fn(),
  },
}))

const issue: Issue = {
  id: 11,
  thread_id: 7,
  issue_number: '2',
  status: 'unread',
  read_at: null,
  created_at: '2026-07-02T00:00:00Z',
}

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

describe('IssueReadStatusButton', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('marks an unread issue read and reconciles the latest visible snapshot', async () => {
    vi.mocked(issuesApi.markRead).mockResolvedValue()
    vi.mocked(issuesApi.get).mockResolvedValue({
      ...issue,
      status: 'read',
      read_at: '2026-08-03T18:30:00Z',
    })
    vi.mocked(threadsApi.get).mockResolvedValue({
      ...thread,
      issues_remaining: 1,
      next_unread_issue_id: 99,
      next_unread_issue_number: '25',
    })
    let snapshot: IssueMutationSnapshot = { issues: [issue], thread }
    const onSnapshotChange = vi.fn(
      (update: (current: IssueMutationSnapshot) => IssueMutationSnapshot) => {
        snapshot = update(snapshot)
      },
    )

    render(<IssueReadStatusButton issue={issue} onSnapshotChange={onSnapshotChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))

    await waitFor(() => expect(onSnapshotChange).toHaveBeenCalledTimes(1))
    expect(issuesApi.markRead).toHaveBeenCalledWith(11)
    expect(issuesApi.get).toHaveBeenCalledWith(11)
    expect(threadsApi.get).toHaveBeenCalledWith(7)
    expect(snapshot).toEqual({
      issues: [{ ...issue, status: 'read', read_at: '2026-08-03T18:30:00Z' }],
      thread: {
        ...thread,
        issues_remaining: 1,
        next_unread_issue_id: 99,
        next_unread_issue_number: '25',
      },
    })
  })

  it('applies a delayed result without overwriting a newer row transition', async () => {
    vi.mocked(issuesApi.markRead).mockResolvedValue()
    vi.mocked(issuesApi.get).mockResolvedValue({
      ...issue,
      status: 'read',
      read_at: '2026-08-03T18:30:00Z',
    })
    vi.mocked(threadsApi.get).mockResolvedValue({
      ...thread,
      issues_remaining: 0,
      next_unread_issue_id: null,
      next_unread_issue_number: null,
    })
    const otherIssue: Issue = {
      ...issue,
      id: 12,
      issue_number: '3',
      status: 'read',
      read_at: '2026-08-03T18:29:00Z',
    }
    let snapshot: IssueMutationSnapshot = {
      issues: [issue, { ...otherIssue, status: 'unread', read_at: null }],
      thread,
    }
    const onSnapshotChange = (
      update: (current: IssueMutationSnapshot) => IssueMutationSnapshot,
    ) => {
      snapshot = {
        ...snapshot,
        issues: snapshot.issues.map((item) => (item.id === 12 ? otherIssue : item)),
      }
      snapshot = update(snapshot)
    }

    render(<IssueReadStatusButton issue={issue} onSnapshotChange={onSnapshotChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))

    await waitFor(() => expect(snapshot.issues[0].status).toBe('read'))
    expect(snapshot.issues[1]).toEqual(otherIssue)
  })

  it('keeps the current snapshot and shows a retryable error when the mutation fails', async () => {
    vi.mocked(issuesApi.markRead).mockRejectedValue(new Error('network'))
    const onSnapshotChange = vi.fn()

    render(<IssueReadStatusButton issue={issue} onSnapshotChange={onSnapshotChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))

    expect(await screen.findByText('Failed to update issue')).toBeInTheDocument()
    expect(onSnapshotChange).not.toHaveBeenCalled()
  })
})
