import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

/**
 * Regression coverage for #3854: the confirm step must never promise a brand-new
 * series for a volume this user already owns, including one they imported in the
 * same session.
 *
 * Unlike `AddSeriesFromComicVineDialog.test.tsx`, this file deliberately leaves
 * `query/cacheEffects` unmocked so the real invalidation runs against the shared
 * `queryClient` the app uses. That is what makes the assertion behavioral: the
 * confirm step's cached "not imported" answer has to be stale after an import, or
 * the `staleTime` window serves the pre-import answer to the next selection.
 */

const { importSeriesSpy, searchSeriesSpy, importStatusSpy, toastSpy } = vi.hoisted(() => ({
  importSeriesSpy: vi.fn(),
  searchSeriesSpy: vi.fn(),
  importStatusSpy: vi.fn(),
  toastSpy: {
    toasts: [],
    showToast: vi.fn(() => 'toast-id'),
    removeToast: vi.fn(),
  },
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    importSeries: importSeriesSpy,
    getSeriesImportStatus: importStatusSpy,
  },
}))

vi.mock('../contexts/useToast', () => ({
  useToast: () => toastSpy,
}))

vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children, size }: { isOpen: boolean; title: string; children: ReactNode; size?: string }) =>
    isOpen ? <div role="dialog" data-modal-size={size}><h2>{title}</h2>{children}</div> : null,
}))

import AddSeriesFromComicVineDialog from '../components/AddSeriesFromComicVineDialog'

const saga = {
  comicvine_volume_id: 99,
  name: 'Saga',
  publisher: 'Image',
  start_year: 2012,
  issue_count: 3,
  site_detail_url: null,
  image_url: null,
}

const NEW_SERIES_COPY = 'This will create a new series in your queue with all 3 issues from the ComicVine volume.'
const IMPORTED_COPY_FRAGMENT = '"Saga" is already in your queue'

describe('AddSeriesFromComicVineDialog same-session re-add copy (#3854)', () => {
  /**
   * Mirrors the server: the caller owns this volume only once the import has
   * committed, so every status read after the add reports it as imported.
   */
  let queueOwnsVolume = false

  beforeEach(() => {
    vi.clearAllMocks()
    toastSpy.showToast.mockClear()
    toastSpy.showToast.mockImplementation(() => 'toast-id')
    searchSeriesSpy.mockReset()
    importSeriesSpy.mockReset()
    importStatusSpy.mockReset()
    queueOwnsVolume = false
    importStatusSpy.mockImplementation(async () => ({
      comicvine_volume_id: 99,
      imported: queueOwnsVolume,
      thread_id: queueOwnsVolume ? 501 : null,
      series_name: queueOwnsVolume ? 'Saga' : null,
      issue_count: queueOwnsVolume ? 3 : null,
    }))
    searchSeriesSpy.mockResolvedValue({
      query: 'saga',
      results: [saga],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    importSeriesSpy.mockImplementation(async () => {
      queueOwnsVolume = true
      return {
        thread_id: 501,
        series_name: 'Saga',
        comicvine_volume_id: 99,
        total_issues_in_series: 3,
        issues_adopted: 3,
        issues_skipped: 0,
        issues_conflict: 0,
        issue_results: [],
        reading_order_id: null,
        position: null,
        total_items: null,
        thread_created: true,
      }
    })
  })

  async function selectSaga() {
    fireEvent.change(
      screen.getByPlaceholderText('Search series title (e.g., Batman, Saga, One Piece)'),
      { target: { value: 'Saga' } },
    )
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Saga - Image/ }))
    await waitFor(() => expect(screen.getByTestId('add-series-confirm-card')).toBeInTheDocument())
  }

  it('does not promise a new series for a volume imported earlier in the same session', async () => {
    const props = {
      onClose: vi.fn(),
      onAdded: vi.fn(),
    }
    const { rerender } = render(<AddSeriesFromComicVineDialog isOpen {...props} />)

    await selectSaga()
    await waitFor(() => expect(importStatusSpy).toHaveBeenCalledWith(99))
    expect(screen.getByTestId('add-series-confirm-card')).toHaveTextContent(NEW_SERIES_COPY)

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))
    await waitFor(() => expect(props.onAdded).toHaveBeenCalledWith(501))

    // Reopen the dialog and pick the same series again.
    rerender(<AddSeriesFromComicVineDialog isOpen={false} {...props} />)
    rerender(<AddSeriesFromComicVineDialog isOpen {...props} />)
    await selectSaga()

    // The pre-import "not imported" answer is still inside the query's
    // staleTime window, so without an invalidation after the import this read
    // would come straight from cache and promise a duplicate series.
    await waitFor(() =>
      expect(screen.getByTestId('add-series-confirm-card')).toHaveTextContent(IMPORTED_COPY_FRAGMENT),
    )
    expect(
      screen.queryByText(/This will create a new series in your queue/),
    ).not.toBeInTheDocument()
  })
})