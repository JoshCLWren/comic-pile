import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { createToastSpy } from './toastSpy'
import { ToastContextSpy } from './toastTestHarness'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
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

describe('ComicIdentity creator status (issue #4149)', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    importIssue.mockReset()
    refreshMetadata.mockReset()
  })

  function renderIdentity(issueId = 1) {
    return renderWithToast(<ComicIdentity issueId={issueId} />)
  }

  function waitForLoaded() {
    return waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())
  }

  function intelligenceResponse(overrides: Partial<ComicVineIssueIntelligence> = {}) {
    return {
      comicvine_issue_id: '100',
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
      ...overrides,
    }
  }

  // Server contract (app/services/comicvine_metadata_repair.py): pending/running
  // repairs return refresh_retry_after_seconds: null; only deferred/failed carry
  // a declared delay. Tests for active repairs must use those responses.
  const FALLBACK_REFRESH_MS = 10_000 // METADATA_REFRESH_FALLBACK_SECONDS * 1000 (component constant)
  const MAX_REFRESH_POLLS = 30 // METADATA_REFRESH_MAX_POLLS (component constant)

  function flushInitialLoad() {
    return act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
  }

  // TanStack Query batches observer notifications onto `setTimeout(..., 0)`.
  // Advancing by exactly 0 does not run a timer scheduled during that same
  // tick, so a refetch triggered at the end of an advance needs one extra
  // millisecond before its hydrated data is rendered.
  function flushQueryNotification() {
    return act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
  }

  afterEach(() => {
    vi.useRealTimers()
  })


  it('says credits are not fetched without claiming a running repair', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '100',
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
      metadata_status: 'not_deep_fetched',
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-not-fetched')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-not-fetched')).toHaveTextContent('Creator credits not yet fetched')
  })

  it('says credits are queued when metadata_status is refresh_pending', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '200',
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
      metadata_status: 'refresh_pending',
      // Server returns null for pending/running repairs
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-fetching')).toHaveTextContent('Creator credits queued for fetch…')
  })

  it('shows "Creator credits being fetched" when metadata_status is refresh_running', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '300',
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
      metadata_status: 'refresh_running',
      // Server returns null for pending/running repairs
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-fetching')).toHaveTextContent('Creator credits being fetched…')
  })

  it('shows "Refresh deferred — retry in Ns" when metadata_status is refresh_deferred with retry_after', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '400',
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
      metadata_status: 'refresh_deferred',
      refresh_retry_after_seconds: 60,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-deferred')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-deferred')).toHaveTextContent('Refresh deferred — retry in 60s')
  })

  it('shows "Refresh deferred" when metadata_status is refresh_deferred without retry_after', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '500',
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
      metadata_status: 'refresh_deferred',
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-deferred')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-deferred')).toHaveTextContent('Refresh deferred')
  })

  it('shows "Refresh failed" when metadata_status is refresh_failed', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '600',
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
      metadata_status: 'refresh_failed',
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-failed')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-failed')).toHaveTextContent('Refresh failed')
  })

  it('offers manual refresh recovery for failed creator metadata (#5695)', async () => {
    getIntelligence
      .mockResolvedValueOnce(
        intelligenceResponse({
          comicvine_issue_id: '601',
          metadata_status: 'refresh_failed',
          refresh_retry_after_seconds: null,
        }),
      )
      .mockResolvedValueOnce(
        intelligenceResponse({
          comicvine_issue_id: '601',
          metadata_status: 'complete',
          creators: [{ name: 'Recovered Writer', roles: ['writer'] }],
        }),
      )
    // SAFETY: the mocked route returns exactly the three response fields consumed by this test.
    refreshMetadata.mockResolvedValue({ issue_id: 1, refreshed: true, comicvine_issue_id: '601' } as never)

    renderIdentity()
    await waitForLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))

    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.getByText('Recovered Writer')).toBeInTheDocument())
  })

  it('reports a failed manual recovery request and leaves retry available (#5695)', async () => {
    getIntelligence.mockResolvedValue(
      intelligenceResponse({
        comicvine_issue_id: '602',
        metadata_status: 'refresh_failed',
        refresh_retry_after_seconds: null,
      }),
    )
    refreshMetadata.mockRejectedValue(new Error('network unavailable'))

    renderIdentity()
    await waitForLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))

    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not request a creator refresh. Try again.',
    )
    expect(screen.getByTestId('creator-status-failed')).toHaveTextContent('Refresh failed')
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
  })

  it('shows "ComicVine currently has no creator credits" when metadata_status is deep_fetched_no_credits', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '700',
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
      metadata_status: 'deep_fetched_no_credits',
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-no-credits')).toBeInTheDocument()
    expect(screen.getByTestId('creator-status-no-credits')).toHaveTextContent('ComicVine currently has no creator credits')
  })

  it('does not show status when creators array is not empty', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '800',
      comicvine_url: null,
      series_name: 'Test Series',
      series_id: 1,
      issue_number: '1',
      name: 'Test Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [{ name: 'Test Creator', roles: ['writer'] }],
      story_arcs: [],
      metadata_status: 'not_deep_fetched',
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-deferred')).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-failed')).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-no-credits')).not.toBeInTheDocument()
  })

  it('does not show status when metadata_status is not provided', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '900',
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
      // metadata_status not provided (defaults to 'not_deep_fetched' in schema but we test undefined)
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
  })

  it('shows no status for an unrecognized metadata status instead of guessing', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '950',
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
      metadata_status: 'some_future_status',
      refresh_retry_after_seconds: null,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-no-credits')).not.toBeInTheDocument()
  })

  it('shows plain deferred copy when the server delay has already elapsed', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '975',
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
      metadata_status: 'refresh_deferred',
      refresh_retry_after_seconds: 0,
    })

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-deferred')).toHaveTextContent('Refresh deferred')
    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
  })

  it('refetches after the bounded fallback when a pending repair returns no retry delay', async () => {
    getIntelligence
      .mockResolvedValueOnce(
        intelligenceResponse({
          comicvine_issue_id: '1000',
          metadata_status: 'refresh_pending',
          refresh_retry_after_seconds: null,
        }),
      )
      .mockResolvedValue(
        intelligenceResponse({
          comicvine_issue_id: '1000',
          metadata_status: 'complete',
          creators: [{ name: 'Fetched Writer', roles: ['writer'] }],
        }),
      )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    // Just before the bounded fallback delay expires: no refetch yet
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS - 1)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    // Beyond the bounded fallback delay: exactly one bounded refetch fired
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })
    await flushQueryNotification()
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    // Hydrated credits replace the fetching message without a manual reload
    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.getByText('Fetched Writer')).toBeInTheDocument()

    unmount()
  })

  it('refetches after the bounded fallback when a running repair returns no retry delay, then shows hydrated credits', async () => {
    getIntelligence
      .mockResolvedValueOnce(
        intelligenceResponse({
          comicvine_issue_id: '1100',
          metadata_status: 'refresh_running',
          refresh_retry_after_seconds: null,
        }),
      )
      .mockResolvedValue(
        intelligenceResponse({
          comicvine_issue_id: '1100',
          metadata_status: 'complete',
          creators: [{ name: 'Hydrated Artist', roles: ['penciler'] }],
        }),
      )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })
    await flushQueryNotification()
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.getByText('Hydrated Artist')).toBeInTheDocument()

    unmount()
  })

  it('honors a declared retry delay when the server provides one', async () => {
    getIntelligence
      .mockResolvedValueOnce(
        intelligenceResponse({
          comicvine_issue_id: '1150',
          metadata_status: 'refresh_pending',
          refresh_retry_after_seconds: 60,
        }),
      )
      .mockResolvedValue(
        intelligenceResponse({
          comicvine_issue_id: '1150',
          metadata_status: 'complete',
          creators: [{ name: 'Deferred Writer', roles: ['writer'] }],
        }),
      )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    // 60 seconds is longer than the 10s fallback: do not refetch early
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(45_000)
    })
    await flushQueryNotification()
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.getByText('Deferred Writer')).toBeInTheDocument()

    unmount()
  })

  it('does not refetch when status is refresh_deferred', async () => {
    getIntelligence.mockResolvedValue(
      intelligenceResponse({
        comicvine_issue_id: '1200',
        metadata_status: 'refresh_deferred',
        refresh_retry_after_seconds: 1,
      }),
    )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    unmount()
  })

  it('does not refetch when status is deep_fetched_no_credits', async () => {
    getIntelligence.mockResolvedValue(
      intelligenceResponse({
        comicvine_issue_id: '1300',
        metadata_status: 'deep_fetched_no_credits',
        refresh_retry_after_seconds: 1,
      }),
    )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    unmount()
  })

  it('clears the refetch timeout on unmount so no late refetch fires', async () => {
    getIntelligence.mockResolvedValue(
      intelligenceResponse({
        comicvine_issue_id: '1400',
        metadata_status: 'refresh_pending',
        refresh_retry_after_seconds: null,
      }),
    )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    // Unmount before the timeout, then advance well beyond the full fallback delay
    unmount()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })

    // Should not have refetched because the component was unmounted
    expect(getIntelligence).toHaveBeenCalledTimes(1)
  })

  it('does not double-fire the refetch across repeated mounts', async () => {
    getIntelligence.mockResolvedValue(
      intelligenceResponse({
        comicvine_issue_id: '1600',
        metadata_status: 'refresh_pending',
        refresh_retry_after_seconds: null,
      }),
    )

    vi.useFakeTimers()
    const first = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)
    first.unmount()

    // Remounting with the same issueId serves the cached entry; no provider
    // request is made merely by remounting, and a fresh bounded timer is armed.
    const second = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()
    second.unmount()

    // Both timers must have been cleared with their mounts
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })

    expect(getIntelligence).toHaveBeenCalledTimes(1)
  })

  it('shows correct status when issueId changes', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '1500',
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
      metadata_status: 'refresh_pending',
      // Server returns null for pending/running repairs
      refresh_retry_after_seconds: null,
    })

    const { rerender } = renderIdentity(1)
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()

    // Change to deep_fetched_no_credits
    getIntelligence.mockResolvedValueOnce({
      comicvine_issue_id: '1501',
      comicvine_url: null,
      series_name: 'Test Series',
      series_id: 1,
      issue_number: '2',
      name: 'Test Issue 2',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
      metadata_status: 'deep_fetched_no_credits',
      refresh_retry_after_seconds: null,
    })

    rerender(<ComicIdentity issueId={2} />)
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-no-credits')).toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
  })

  it('re-arms and refetches when a pending repair returns unchanged metadata, then shows credits', async () => {
    const pending = intelligenceResponse({
      comicvine_issue_id: '2000',
      metadata_status: 'refresh_pending',
      refresh_retry_after_seconds: null,
      creators: [],
    })
    getIntelligence
      .mockResolvedValueOnce(pending) // initial load
      .mockResolvedValueOnce(pending) // first refresh returns unchanged metadata
      .mockResolvedValue(
        intelligenceResponse({
          comicvine_issue_id: '2000',
          metadata_status: 'complete',
          creators: [{ name: 'Finally Writer', roles: ['writer'] }],
        }),
      )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    // First bounded refetch fires but returns unchanged metadata. Without a
    // re-arm the timer would stop here and credits would stay hidden.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS)
    })
    await flushInitialLoad()
    expect(getIntelligence).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()

    // Second bounded refetch fires after the re-arm and now returns credits.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS)
    })
    await flushQueryNotification()
    expect(getIntelligence).toHaveBeenCalledTimes(3)

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.getByText('Finally Writer')).toBeInTheDocument()

    unmount()
  })

  it('stops an unchanged active repair at the poll budget and offers manual recovery (#5695)', async () => {
    const pending = intelligenceResponse({
      comicvine_issue_id: '2050',
      metadata_status: 'refresh_pending',
      refresh_retry_after_seconds: null,
    })
    getIntelligence.mockResolvedValue(pending)

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * (MAX_REFRESH_POLLS + 1))
    })
    await flushQueryNotification()

    expect(getIntelligence).toHaveBeenCalledTimes(MAX_REFRESH_POLLS + 1)
    expect(screen.getByTestId('creator-status-delayed')).toHaveTextContent(
      'Creator credits are still waiting for ComicVine. Retry refresh or check again later.',
    )
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 3)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(MAX_REFRESH_POLLS + 1)

    unmount()
  })

  it('does not overlap refetches while a slow repair response is still in flight', async () => {
    const pending = intelligenceResponse({
      comicvine_issue_id: '2100',
      metadata_status: 'refresh_pending',
      refresh_retry_after_seconds: null,
    })
    let resolveSecond: ((value: ComicVineIssueIntelligence) => void) | null = null
    const secondFetch = new Promise<ComicVineIssueIntelligence>((resolve) => {
      resolveSecond = resolve
    })

    getIntelligence
      .mockResolvedValueOnce(pending)
      .mockReturnValueOnce(secondFetch)
      .mockResolvedValue(
        intelligenceResponse({
          comicvine_issue_id: '2100',
          metadata_status: 'complete',
          creators: [{ name: 'Settled Writer', roles: ['writer'] }],
        }),
      )

    vi.useFakeTimers()
    const { unmount } = renderIdentity()
    await flushInitialLoad()

    expect(getIntelligence).toHaveBeenCalledTimes(1)

    // The first bounded refetch starts and stays in flight longer than the delay.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    // Further delays pass while that request is unresolved: no overlap, and
    // therefore no cancellation of the in-flight repair response.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    // Once it settles, the next bounded refetch is armed a full delay later.
    await act(async () => {
      resolveSecond?.(pending)
      await vi.advanceTimersByTimeAsync(0)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS)
    })
    await flushQueryNotification()
    expect(getIntelligence).toHaveBeenCalledTimes(3)

    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()
    expect(screen.getByText('Settled Writer')).toBeInTheDocument()

    unmount()
  })

  it('stops polling once a remapped intelligence response completes', async () => {
    const intelligence = (overrides: Partial<ComicVineIssueIntelligence> = {}) => ({
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
      metadata_status: 'complete',
      refresh_retry_after_seconds: null,
      ...overrides,
    })

    const a = intelligence({
      comicvine_issue_id: 'A',
      metadata_status: 'refresh_pending',
      refresh_retry_after_seconds: null,
      creators: [],
    })
    const b = intelligence({
      comicvine_issue_id: 'B',
      metadata_status: 'complete',
      creators: [{ name: 'Writer B', roles: ['penciler'] }],
    })

    vi.useFakeTimers()
    getIntelligence.mockResolvedValueOnce(a).mockResolvedValue(b)

    renderWithToast(<ComicIdentity issueId={1} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(getIntelligence).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('creator-status-fetching')).toBeInTheDocument()

    // The next intelligence response represents the remapped issue B.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS)
    })
    await flushQueryNotification()
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    // B's credits replace the pending state; the fetching message is gone.
    expect(screen.getByText('Writer B')).toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-fetching')).not.toBeInTheDocument()

    // Once complete, the bounded poller is disarmed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_REFRESH_MS * 2)
    })
    expect(getIntelligence).toHaveBeenCalledTimes(2)

    vi.useRealTimers()
  })

})
