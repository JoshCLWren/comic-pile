import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueRateButton } from '../pages/thread-detail/IssueRateButton'
import type { IssueMutationSnapshot } from '../pages/thread-detail/issueMutationState'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { rateApi } from '../services/api-rate'
import type { Issue, Thread } from '../types'

vi.mock('../services/api-rate', () => ({
  rateApi: { rate: vi.fn() },
}))

vi.mock('../query/cacheEffects', () => ({
  applyRatedThreadCache: vi.fn(),
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
  next_unread_issue_id: 12,
  next_unread_issue_number: '3',
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: '2026-08-03T18:30:00Z',
  last_rating: null,
  notes: null,
  is_test: false,
  created_at: '2026-08-03T00:00:00Z',
}

const snapshot: IssueMutationSnapshot = { issues: [issue], thread }

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('IssueRateButton', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(applyRatedThreadCache).mockResolvedValue()
  })

  it('rates the row directly and reconciles the issue and thread cache', async () => {
    const ratedThread: Thread = {
      ...thread,
      issues_remaining: 1,
      next_unread_issue_id: 12,
      next_unread_issue_number: '3',
      last_rating: 4,
    }
    vi.mocked(rateApi.rate).mockResolvedValue(ratedThread)
    const onSnapshotChange = vi.fn()

    render(
      <IssueRateButton
        issue={issue}
        snapshot={snapshot}
        onSnapshotChange={onSnapshotChange}
      />,
      { wrapper },
    )

    fireEvent.click(screen.getByRole('button', { name: 'Rate' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rate issue #2 4 out of 5' }))

    await waitFor(() => expect(onSnapshotChange).toHaveBeenCalledTimes(1))
    expect(rateApi.rate).toHaveBeenCalledWith({
      thread_id: 7,
      rating: 4,
      direct: true,
      issue_number: '2',
    })
    expect(applyRatedThreadCache).toHaveBeenCalledWith(queryClient, ratedThread)
    expect(onSnapshotChange).toHaveBeenCalledWith({
      issues: [{ ...issue, status: 'read', read_at: '2026-08-03T18:30:00Z' }],
      thread: {
        ...thread,
        issues_remaining: 1,
        next_unread_issue_id: 12,
        next_unread_issue_number: '3',
      },
    })
    expect(screen.getByRole('button', { name: 'Rated 4' })).toBeInTheDocument()
  })

  it('shows an error and keeps the issue unread when the server rejects the rating', async () => {
    vi.mocked(rateApi.rate).mockRejectedValue(new Error('nope'))
    const onSnapshotChange = vi.fn()

    render(
      <IssueRateButton
        issue={issue}
        snapshot={snapshot}
        onSnapshotChange={onSnapshotChange}
      />,
      { wrapper },
    )

    fireEvent.click(screen.getByRole('button', { name: 'Rate' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rate issue #2 3 out of 5' }))

    expect(await screen.findByText('Failed to rate')).toBeInTheDocument()
    expect(onSnapshotChange).not.toHaveBeenCalled()
    expect(applyRatedThreadCache).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Rate' })).toBeInTheDocument()
  })
})
