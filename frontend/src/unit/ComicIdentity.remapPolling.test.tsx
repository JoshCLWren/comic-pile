import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { createToastSpy } from './toastSpy'
import { ToastContextSpy } from './toastTestHarness'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence, MetadataRefreshResponse } from '../services/api-comicvine'
import { ComicIdentity } from '../pages/RollPage/components/ComicIdentity'

const toast = createToastSpy()

function ToastWrapper({ children }: { children: ReactNode }) {
  return <ToastContextSpy value={toast}>{children}</ToastContextSpy>
}

function renderWithToast(ui: ReactElement) {
  return render(ui, { wrapper: ToastWrapper })
}

vi.mock('../services/api-comicvine', async () => {
  const actual = await vi.importActual<typeof import('../services/api-comicvine')>('../services/api-comicvine')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn(), importIssue: vi.fn(), refreshMetadata: vi.fn() } }
})

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: {
    list: vi.fn().mockResolvedValue({ reading_orders: [] }),
  },
}))

const getIntelligence = vi.mocked(comicVineApi.getIssueIntelligence)
const importIssue = vi.mocked(comicVineApi.importIssue)
const refreshMetadata = vi.mocked(comicVineApi.refreshMetadata)

function intelligence(overrides: Partial<ComicVineIssueIntelligence> = {}) {
  return {
    comicvine_issue_id: '1',
    comicvine_url: null,
    series_name: 'Test Series',
    series_id: 1,
    issue_number: '1',
    name: 'Test Issue',
    description: null,
    image_url: null,
    cover_date: null,
    store_date: null,
    creators: [],
    story_arcs: [],
    metadata_status: 'needs_hydration',
    refresh_retry_after_seconds: null,
    ...overrides,
  }
}

describe('ComicIdentity remapped issue metadata (#5841)', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    importIssue.mockReset()
    refreshMetadata.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('has no poll timer: a stored pending/running state never refetches on its own', async () => {
    vi.useFakeTimers()
    getIntelligence.mockResolvedValue(intelligence({
      metadata_status: 'refresh_pending',
      refresh_retry_after_seconds: null,
    }))
    refreshMetadata.mockResolvedValue({
      issue_id: 1, refreshed: false, comicvine_issue_id: '1',
      outcome: 'provider_unavailable', retry_after_seconds: null,
    })

    const { unmount } = renderWithToast(<ComicIdentity issueId={1} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByTestId('creator-status-not_hydrated')).toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-hydrating')).not.toBeInTheDocument()
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(1)
    expect(refreshMetadata).not.toHaveBeenCalled()

    unmount()
  })

  it('replaces identity A with B without a stale retry or a late refetch', async () => {
    let resolveRetry: ((value: {
      issue_id: number
      refreshed: boolean
      comicvine_issue_id: string
      outcome: 'complete'
    }) => void) | undefined
    refreshMetadata.mockImplementation(() => new Promise((resolve) => {
      resolveRetry = resolve
    }))
    getIntelligence.mockImplementation((issueId: number) => Promise.resolve(
      issueId === 1
        ? intelligence({ comicvine_issue_id: 'A' })
        : intelligence({
          comicvine_issue_id: 'B',
          metadata_status: 'complete',
          creators: [{ name: 'Writer B', roles: ['writer'] }],
        }),
    ))

    const { rerender } = renderWithToast(<ComicIdentity issueId={1} />)
    await waitFor(() => expect(screen.getByTestId('creator-status-not_hydrated')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))
    expect(screen.getByTestId('creator-status-hydrating')).toBeInTheDocument()

    // The reader remaps to B while A's retry is still in flight.
    rerender(<ComicIdentity issueId={2} />)
    await waitFor(() => expect(screen.getByText('Writer B')).toBeInTheDocument())

    await act(async () => {
      resolveRetry?.({ issue_id: 1, refreshed: true, comicvine_issue_id: 'A', outcome: 'complete' })
    })

    // A's late success must not trigger a refetch or repaint B's credits.
    await waitFor(() => expect(screen.queryByTestId('creator-status-hydrating')).not.toBeInTheDocument())
    expect(getIntelligence).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Writer B')).toBeInTheDocument()
    expect(screen.queryByText('Writer A')).not.toBeInTheDocument()
  })

  it('accepts an explicit Retry for B while A is still in flight', async () => {
    let resolveA: ((value: MetadataRefreshResponse) => void) | undefined
    refreshMetadata.mockImplementation((issueId: number) => {
      if (issueId === 1) {
        return new Promise<MetadataRefreshResponse>((resolve) => {
          resolveA = resolve
        })
      }
      return Promise.resolve({
        issue_id: 2,
        refreshed: true,
        comicvine_issue_id: 'B',
        outcome: 'no_credits',
        retry_after_seconds: null,
      })
    })
    getIntelligence.mockImplementation((issueId: number) => Promise.resolve(
      intelligence({
        comicvine_issue_id: issueId === 1 ? 'A' : 'B',
        metadata_status: 'needs_hydration',
      }),
    ))

    const { rerender } = renderWithToast(<ComicIdentity issueId={1} />)
    await waitFor(() => expect(screen.getByTestId('creator-status-not_hydrated')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))

    // Remap to B while A's request is still pending, then retry B immediately.
    // A's stale single-flight flag must not swallow B's explicit click.
    rerender(<ComicIdentity issueId={2} />)
    await waitFor(() => expect(screen.getByTestId('creator-status-not_hydrated')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(2))

    await act(async () => {
      resolveA?.({ issue_id: 1, refreshed: true, comicvine_issue_id: 'A', outcome: 'complete' })
    })

    await waitFor(() => expect(screen.getByTestId('creator-status-no_credits')).toBeInTheDocument())
    expect(refreshMetadata).toHaveBeenCalledTimes(2)
    expect(screen.getByLabelText('Test Issue')).toBeInTheDocument()
  })
})
