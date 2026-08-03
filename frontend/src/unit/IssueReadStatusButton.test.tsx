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

  it('marks an unread issue read and reconciles the visible snapshot from bounded reads', async () => {
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
    const onSnapshotChange = vi.fn()

    render(
      <IssueReadStatusButton
        issue={issue}
        snapshot={{ issues: [issue], thread }}
        onSnapshotChange={onSnapshotChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))

    await waitFor(() => expect(onSnapshotChange).toHaveBeenCalledTimes(1))
    expect(onSnapshotChange).toHaveBeenCalledWith({
      issues: [{ ...issue, status: 'read', read_at: '2026-08-03T18:30:00Z' }],
      thread: {
        ...thread,
        issues_remaining: 1,
        next_unread_issue_id: 99,
        next_unread_issue_number: '25',
      },
    })
  })

  it('preserves a newer row transition when an older request finishes later', async () => {
    const secondIssue: Issue = {
      ...issue,
      id: 12,
      issue_number: '3',
    }
    const firstIssueRequest = Promise.withResolvers<Issue>()
    const secondIssueRequest = Promise.withResolvers<Issue>()
    vi.mocked(issuesApi.markRead).mockResolvedValue()
    vi.mocked(issuesApi.get)
      .mockReturnValueOnce(firstIssueRequest.promise)
      .mockReturnValueOnce(secondIssueRequest.promise)
    vi.mocked(threadsApi.get)
      .mockResolvedValueOnce({
        ...thread,
        issues_remaining: 0,
        next_unread_issue_id: null,
        next_unread_issue_number: null,
      })
      .mockResolvedValueOnce({
        ...thread,
        issues_remaining: 1,
        next_unread_issue_id: 12,
        next_unread_issue_number: '3',
      })

    let snapshot: IssueMutationSnapshot = {
      issues: [issue, secondIssue],
      thread,
    }
    const onSnapshotChange = (nextSnapshot: IssueMutationSnapshot) => {
      snapshot = nextSnapshot
    }

    render(
      <>
        <IssueReadStatusButton
          issue={issue}
          snapshot={snapshot}
          onSnapshotChange={onSnapshotChange}
        />
        <IssueReadStatusButton
          issue={secondIssue}
          snapshot={snapshot}
          onSnapshotChange={onSnapshotChange}
        />
      </>,
    )

    const buttons = screen.getAllByRole('button', { name: 'Mark read' })
    fireEvent.click(buttons[0])
    fireEvent.click(buttons[1])

    secondIssueRequest.resolve({
      ...secondIssue,
      status: 'read',
      read_at: '2026-08-03T18:29:00Z',
    })
    await waitFor(() => expect(snapshot.issues[1].status).toBe('read'))

    firstIssueRequest.resolve({
      ...issue,
      status: 'read',
      read_at: '2026-08-03T18:30:00Z',
    })
    await waitFor(() => expect(snapshot.issues[0].status).toBe('read'))

    expect(snapshot.issues[1]).toMatchObject({
      status: 'read',
      read_at: '2026-08-03T18:29:00Z',
    })
  })

  it('keeps the current snapshot and shows a retryable error when the mutation fails', async () => {
    vi.mocked(issuesApi.markRead).mockRejectedValue(new Error('network'))
    const onSnapshotChange = vi.fn()

    render(
      <IssueReadStatusButton
        issue={issue}
        snapshot={{ issues: [issue], thread }}
        onSnapshotChange={onSnapshotChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))

    expect(await screen.findByText('Failed to update issue')).toBeInTheDocument()
    expect(onSnapshotChange).not.toHaveBeenCalled()
  })
})
