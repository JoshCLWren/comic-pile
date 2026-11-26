import { act, render, screen } from '@testing-library/react'
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

const FALLBACK_REFRESH_MS = 10_000 // METADATA_REFRESH_FALLBACK_SECONDS * 1000 (component constant)

// TanStack Query batches observer notifications onto setTimeout(..., 0); a refetch
// triggered at the end of an advance needs one extra millisecond to render.
function flushQueryNotification() {
  return act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
}

describe('ComicIdentity remapped issue polling (#5695)', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    importIssue.mockReset()
    refreshMetadata.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
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
