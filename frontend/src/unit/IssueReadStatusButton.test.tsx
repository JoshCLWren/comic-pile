import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueReadStatusButton } from '../pages/thread-detail/IssueReadStatusButton'
import type { IssueMutationSnapshot } from '../pages/thread-detail/issueMutationState'
import { threadsApi } from '../services/api-threads'
import { issuesApi } from '../services/api-issues'
import type { Issue, Thread } from '../types'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    markRead: vi.fn(),
    markUnread: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../services/api-threads', () => ({
  threadsApi: {
    get: vi.fn(),
  },
}))

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })

  return { promise, resolve, reject }
}

interface ControlledIssueButtonsProps {
  initialSnapshot: IssueMutationSnapshot
  onSnapshotChange: (snapshot: IssueMutationSnapshot) => void
}

function ControlledIssueButtons({
  initialSnapshot,
  onSnapshotChange,
}: ControlledIssueButtonsProps) {
  const [snapshot, setSnapshot] = useState(initialSnapshot)

  function handleSnapshotChange(nextSnapshot: IssueMutationSnapshot) {
    setSnapshot(nextSnapshot)
    onSnapshotChange(nextSnapshot)
  }

  return snapshot.issues.map((currentIssue) => (
    <IssueReadStatusButton
      key={currentIssue.id}
      issue={currentIssue}
      snapshot={snapshot}
      onSnapshotChange={handleSnapshotChange}
    />
  ))
}

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
  reading_progress: 'in_progress',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  notes: null,
  is_test: false,
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
        status: 'active',
        reading_progress: 'in_progress',
      },
    })
  })

  // Regression coverage for #3113: the thread read that already happens after a
  // successful toggle must project `status`/`reading_progress` into the
  // snapshot, otherwise the thread detail STATUS panel keeps the old value.
  it('projects the server thread status when a toggle completes the thread', async () => {
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
      status: 'completed',
      reading_progress: 'completed',
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
    expect(vi.mocked(onSnapshotChange).mock.calls[0]?.[0].thread).toMatchObject({
      status: 'completed',
      reading_progress: 'completed',
      issues_remaining: 0,
    })
  })

  it('projects the server thread status when a toggle reactivates a completed thread', async () => {
    const readIssue: Issue = {
      ...issue,
      status: 'read',
      read_at: '2026-08-01T00:00:00Z',
    }
    const completedThread: Thread = {
      ...thread,
      issues_remaining: 0,
      next_unread_issue_id: null,
      next_unread_issue_number: null,
      status: 'completed',
      reading_progress: 'completed',
    }
    vi.mocked(issuesApi.markUnread).mockResolvedValue()
    vi.mocked(issuesApi.get).mockResolvedValue({
      ...readIssue,
      status: 'unread',
      read_at: null,
    })
    vi.mocked(threadsApi.get).mockResolvedValue({
      ...completedThread,
      issues_remaining: 1,
      next_unread_issue_id: readIssue.id,
      next_unread_issue_number: readIssue.issue_number,
      status: 'active',
      reading_progress: 'in_progress',
    })
    const onSnapshotChange = vi.fn()

    render(
      <IssueReadStatusButton
        issue={readIssue}
        snapshot={{ issues: [readIssue], thread: completedThread }}
        onSnapshotChange={onSnapshotChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Mark unread' }))

    await waitFor(() => expect(onSnapshotChange).toHaveBeenCalledTimes(1))
    expect(vi.mocked(onSnapshotChange).mock.calls[0]?.[0].thread).toMatchObject({
      status: 'active',
      reading_progress: 'in_progress',
      issues_remaining: 1,
    })
  })

  it('preserves a newer row transition when an older request finishes later', async () => {
    const secondIssue: Issue = {
      ...issue,
      id: 12,
      issue_number: '3',
    }
    const firstIssueRequest = createDeferred<Issue>()
    const secondIssueRequest = createDeferred<Issue>()
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
      <ControlledIssueButtons
        initialSnapshot={snapshot}
        onSnapshotChange={onSnapshotChange}
      />,
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
