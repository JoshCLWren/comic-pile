import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { listIssuesSpy, searchSeriesSpy, previewSpy, commitSpy } = vi.hoisted(() => ({
  listIssuesSpy: vi.fn(),
  searchSeriesSpy: vi.fn(),
  previewSpy: vi.fn(),
  commitSpy: vi.fn(),
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: { list: listIssuesSpy },
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: { searchSeries: searchSeriesSpy },
}))

vi.mock('../services/api-series-mappings', () => ({
  seriesMappingsApi: { preview: previewSpy, commit: commitSpy },
}))

vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) =>
    isOpen ? <div role="dialog"><h2>{title}</h2>{children}</div> : null,
}))

import MapSeriesDialog from '../pages/QueuePage/MapSeriesDialog'

const thread = {
  id: 7,
  title: 'Saga',
  format: 'Single Issue',
  comicvine_mapping: null,
}
// SAFETY: the dialog only reads id/title off the thread for rendering and anchoring
const threadProp = thread as Parameters<typeof MapSeriesDialog>[0]['thread']

/** Minimal non-axios failure carrying the backend's documented conflict detail. */
function apiError(status: number, detail: string) {
  return { response: { status, data: { detail } } }
}

const series = {
  comicvine_volume_id: 99,
  name: 'Saga',
  publisher: 'Image',
  start_year: 2012,
  issue_count: 70,
  site_detail_url: null,
  image_url: null,
}

const previewResponse = {
  preview_token: 'tok123',
  scope: { status: 'available', scope_key: 'k', origin_issue_id: 11, series_label: 'Saga', basis: 'exact_match_found' },
  provider_series: { id: '99', name: 'Saga', publisher: 'Image', start_year: 2012, count_of_issues: 70, site_detail_url: null, image: null },
  counts: { already_confirmed: 0, safe_exact_match: 1, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 1, excluded_special: 0 },
  rows: [
    { row_id: 'issue:11', issue_id: 11, issue_number: '1', title: 'Chapter One', classification: 'safe_exact_match', thread_id: 7, thread_title: 'Saga', current_mapping_status: null, proposed_mapping: true, default_selected: true, reason: null },
    { row_id: 'issue:12', issue_id: 12, issue_number: '2', title: 'Chapter Two', classification: 'unresolved', thread_id: 7, thread_title: 'Saga', current_mapping_status: null, proposed_mapping: false, default_selected: false, reason: 'no exact match' },
  ],
  issued_at: 1,
  expires_at: null,
}

describe('MapSeriesDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listIssuesSpy.mockResolvedValue({ issues: [{ id: 11 }], total_count: 1, page_size: 1, next_page_token: null })
    searchSeriesSpy.mockResolvedValue({ query: 'Saga', results: [series], total_available: 1, offset: 0, limit: 10, has_more: false, next_offset: null })
    previewSpy.mockResolvedValue(previewResponse)
    commitSpy.mockResolvedValue({ idempotency_key: 'k', confirmed_issue_ids: [11], already_confirmed_issue_ids: [], needs_review_issue_ids: [12], hydration_queued_issue_ids: [], series_mapping: { provider: 'comicvine', external_id: '99', status: 'confirmed', evidence_source: 'test' } })
  })

  it('runs the shared search → preview → commit flow and refreshes the queue', async () => {
    const onCommitted = vi.fn().mockResolvedValue(undefined)
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={onCommitted} />)

    await waitFor(() => expect(listIssuesSpy).toHaveBeenCalledWith(7, { page_size: 1 }))

    fireEvent.change(screen.getByLabelText('Search ComicVine series'), { target: { value: 'Saga' } })
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Saga', 10, 0))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(previewSpy).toHaveBeenCalledWith({ origin_issue_id: 11, provider: 'comicvine', provider_series_external_id: '99' }))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalled())
    expect(commitSpy.mock.calls[0][0].preview_token).toBe('tok123')
    expect(commitSpy.mock.calls[0][0].approved_row_ids).toEqual(['issue:11'])
    await waitFor(() => expect(onCommitted).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(/1 issue mapped/)).toBeInTheDocument())
  })

  it('surfaces provider failure during search', async () => {
    searchSeriesSpy.mockRejectedValue(new Error('provider down'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('provider down'))
  })

  it('keeps one idempotency key when an identical commit is retried', async () => {
    commitSpy.mockRejectedValueOnce(new Error('response lost'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('response lost'))

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(2))
    expect(commitSpy.mock.calls[0][0].idempotency_key).toBe(commitSpy.mock.calls[1][0].idempotency_key)
  })

  it('mints a new idempotency key when the approved rows change', async () => {
    commitSpy.mockRejectedValue(new Error('commit failed'))
    previewSpy.mockResolvedValue({
      ...previewResponse,
      rows: [
        previewResponse.rows[0],
        { ...previewResponse.rows[1], classification: 'safe_exact_match', default_selected: false, reason: null },
      ],
      counts: { ...previewResponse.counts, safe_exact_match: 2 },
    })
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('Commit 1 safe mapping')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('commit failed'))

    fireEvent.click(screen.getByLabelText('Approve #2 safe exact match'))
    fireEvent.click(screen.getByText('Commit 2 safe mappings'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(2))
    expect(commitSpy.mock.calls[0][0].idempotency_key).not.toBe(commitSpy.mock.calls[1][0].idempotency_key)
  })

  it('keeps the committed summary when only the queue refresh fails', async () => {
    const onCommitted = vi.fn().mockRejectedValue(new Error('cache refresh failed'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={onCommitted} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))

    await waitFor(() => expect(screen.getByText(/1 issue mapped/)).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('could not refresh it yet'))
    expect(onCommitted).toHaveBeenCalled()
  })

  it('does not reuse a commit key for a refreshed preview of the same series', async () => {
    commitSpy.mockRejectedValue(new Error('commit failed'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(1))

    previewSpy.mockResolvedValue({ ...previewResponse, preview_token: 'tok456' })
    fireEvent.click(screen.getByText('Back'))
    await waitFor(() => expect(screen.getByLabelText('Search ComicVine series')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('Commit 1 safe mapping')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Commit 1 safe mapping'))

    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(2))
    expect(commitSpy.mock.calls[1][0].preview_token).toBe('tok456')
    expect(commitSpy.mock.calls[0][0].idempotency_key).not.toBe(commitSpy.mock.calls[1][0].idempotency_key)
  })

  it('explains a commit conflict instead of showing the raw backend code', async () => {
    commitSpy.mockRejectedValue(apiError(409, 'confirmed_mapping_conflict'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Commit 1 safe mapping'))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('already carries a different confirmed ComicVine identity'),
    )
    expect(screen.queryByText(/confirmed_mapping_conflict/)).not.toBeInTheDocument()
  })

  it('explains an unavailable safe scope instead of implying no matches', async () => {
    previewSpy.mockResolvedValue({
      ...previewResponse,
      preview_token: null,
      scope: { status: 'unavailable', scope_key: null, origin_issue_id: 11, series_label: null, basis: 'insufficient_non_thread_evidence' },
      counts: { already_confirmed: 0, safe_exact_match: 0, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
      rows: [],
    })
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('could not scope this series safely'))
    expect(screen.queryByText(/No safe exact mappings are available/)).not.toBeInTheDocument()
    expect(commitSpy).not.toHaveBeenCalled()
  })

  it('waits for the anchor issue before letting the user choose a series', async () => {
    let resolveAnchor: (value: { issues: { id: number }[] }) => void = () => {}
    listIssuesSpy.mockReturnValue(
      new Promise((resolve) => {
        resolveAnchor = resolve
      }),
    )
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: /^Saga/ })).toBeDisabled()
    expect(screen.getByText('Preparing this series…')).toBeInTheDocument()

    resolveAnchor({ issues: [{ id: 11 }] })
    await waitFor(() => expect(screen.getByRole('button', { name: /^Saga/ })).toBeEnabled())
    expect(previewSpy).not.toHaveBeenCalled()
  })

  it('surfaces preview failure without committing', async () => {
    previewSpy.mockRejectedValue(new Error('preview failed'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('preview failed'))
    expect(commitSpy).not.toHaveBeenCalled()
  })

  it('surfaces commit failure and does not report success', async () => {
    commitSpy.mockRejectedValue(new Error('commit failed'))
    const onCommitted = vi.fn()
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={onCommitted} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('commit failed'))
    expect(onCommitted).not.toHaveBeenCalled()
  })

  it('backs out of preview to search without committing', async () => {
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Back'))
    await waitFor(() => expect(screen.getByLabelText('Search ComicVine series')).toBeInTheDocument())
    expect(commitSpy).not.toHaveBeenCalled()
  })

  it('reports when the thread has no anchor issue', async () => {
    listIssuesSpy.mockResolvedValue({ issues: [], total_count: 0, page_size: 1, next_page_token: null })
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('no issues to anchor'))
    expect(previewSpy).not.toHaveBeenCalled()
  })

  it('falls back to no anchor issue when the issue lookup fails', async () => {
    listIssuesSpy.mockRejectedValue(new Error('issue list unavailable'))
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    await waitFor(() => expect(listIssuesSpy).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('no issues to anchor'))
    expect(previewSpy).not.toHaveBeenCalled()
  })

  it('lets the user unselect a safe row before committing', async () => {
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Approve #1 safe exact match'))

    expect(screen.getByText('Commit 0 safe mappings')).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Approve #1 safe exact match'))
    fireEvent.click(screen.getByText('Commit 1 safe mapping'))
    await waitFor(() => expect(commitSpy).toHaveBeenCalledTimes(1))
  })

  it('explains when a series has no safe exact mappings and commits nothing', async () => {
    previewSpy.mockResolvedValue({
      ...previewResponse,
      preview_token: null,
      counts: { ...previewResponse.counts, safe_exact_match: 0 },
      rows: [
        {
          ...previewResponse.rows[1],
          row_id: 'issue:12',
          classification: 'needs_review_ambiguous',
          default_selected: false,
          reason: null,
        },
      ],
    })
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))

    await waitFor(() => expect(screen.getByText(/No safe exact mappings are available/)).toBeVisible())
    expect(screen.getByText('needs review ambiguous')).toBeVisible()
    expect(screen.getByText('Commit 0 safe mappings')).toBeDisabled()
    expect(commitSpy).not.toHaveBeenCalled()
  })

  it('renders sparse provider metadata without empty separators', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Saga',
      results: [{ ...series, publisher: null, start_year: null, issue_count: 0 }],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: /^Saga/ }).textContent).toMatch(/^Saga\s*·\s*$/)
  })

  it('names an unknown preview publisher instead of leaving a gap', async () => {
    previewSpy.mockResolvedValue({ ...previewResponse, provider_series: null })
    render(<MapSeriesDialog thread={threadProp} onClose={vi.fn()} onCommitted={vi.fn()} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Saga'))

    await waitFor(() => expect(screen.getByText(/Unknown publisher/)).toBeVisible())
  })
})
