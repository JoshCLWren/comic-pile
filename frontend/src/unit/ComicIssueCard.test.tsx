/**
 * Shared direct-issue card (#4444).
 *
 * Guards the owner contract: the exact provider CDN URL is passed through
 * unchanged, every owned issue stays actionable while blocked/unmapped, the
 * default fast rating is 3.5 editable before save, rating corrections write
 * without a new read event, and manual mode never promises die/queue effects.
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IssueCard, IssueReadRateResponse } from '../services/issueCardsApi'

const { patchIssueSpy, fetchCardsSpy, getIssueIdentitySpy } = vi.hoisted(() => ({
  patchIssueSpy: vi.fn(),
  fetchCardsSpy: vi.fn(),
  getIssueIdentitySpy: vi.fn(),
}))

vi.mock('../services/issueCardsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/issueCardsApi')>()
  return {
    ...actual,
    issueCardsApi: { fetchCards: fetchCardsSpy, patchIssue: patchIssueSpy },
  }
})

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    searchSeries: vi.fn().mockResolvedValue({ results: [] }),
    getSeriesIssues: vi.fn().mockResolvedValue({ comicvine_volume_id: 42, series_name: '', issues: [] }),
    getIssueIntelligence: vi.fn().mockResolvedValue(null),
    getIssueIdentity: getIssueIdentitySpy,
    confirmIdentity: vi.fn(),
    replaceIdentity: vi.fn(),
    removeIdentity: vi.fn(),
    refreshMetadata: vi.fn(),
  },
}))

vi.mock('../query/queryClient', () => ({
  queryClient: {
    invalidateQueries: vi.fn().mockResolvedValue(undefined),
    setQueryData: vi.fn(),
  },
}))

import { ComicIssueCard } from '../components/ComicIssueCard'

const PROVIDER_URL = 'https://comicvine.gamespot.com/a/uploads/scale_medium/36956-hellboy-in-hell-3.jpg'

const UNREAD_CARD: IssueCard = {
  issue_id: 77,
  thread_id: 7,
  thread_title: 'Hellboy in Hell',
  issue_number: '3',
  status: 'unread',
  read_at: null,
  rating: null,
  has_confirmed_identity: true,
  mapping_state: 'confirmed',
  comicvine_issue_id: '36956',
  cover_image_url: PROVIDER_URL,
}

const READ_CARD: IssueCard = {
  ...UNREAD_CARD,
  status: 'read',
  read_at: '2026-10-01T00:00:00.000Z',
  rating: 4.5,
}

function renderCard(props?: Partial<Parameters<typeof ComicIssueCard>[0]>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ComicIssueCard
        issueId={77}
        card={UNREAD_CARD}
        threadTitle="Hellboy in Hell"
        issueNumber="3"
        status="unread"
        variant="featured"
        {...props}
      />
    </QueryClientProvider>,
  )
}

function readResponse(card: IssueCard): IssueReadRateResponse {
  return {
    issue: card,
    thread: { thread_id: 7, status: 'active', issues_remaining: 5, next_unread_issue_id: 78, reading_progress: null, last_rating: 4.5 },
    read_event_created: true,
    rating_event_created: true,
    replayed: false,
    final_rating: 4.5,
    die_after: null,
  }
}

beforeEach(() => {
  patchIssueSpy.mockReset()
  fetchCardsSpy.mockReset()
  getIssueIdentitySpy.mockReset()
  patchIssueSpy.mockResolvedValue(readResponse({ ...UNREAD_CARD, status: 'read', rating: 3.5 }))
  getIssueIdentitySpy.mockResolvedValue({
    issue_id: 77,
    thread_id: 7,
    thread_title: 'Hellboy in Hell',
    has_confirmed_identity: true,
    comicvine_issue_id: '36956',
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: false,
  })
})

describe('ComicIssueCard', () => {
  it('passes the exact provider CDN URL through as img src (no ComicPile endpoint)', () => {
    renderCard()
    // SAFETY: getByAltText returns the cover img element for the rendered card.
    const img = screen.getByAltText('Cover for Hellboy in Hell #3') as HTMLImageElement
    expect(img.getAttribute('src')).toBe(PROVIDER_URL)
    expect(img.src).toContain('comicvine.gamespot.com')
    expect(img.src).not.toContain('/image')
  })

  it('shows a CSS/text placeholder for unmapped art while reading stays available', () => {
    renderCard({ card: { ...UNREAD_CARD, cover_image_url: null, has_confirmed_identity: false, mapping_state: 'unmapped', comicvine_issue_id: null } })
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Read now' })).toBeTruthy()
    expect(screen.getByTestId('comic-mapping-map')).toBeTruthy()
  })

  it('offers Add to ComicPile for a provider-only entry instead of mapping controls', () => {
    const onAddToLibrary = vi.fn()
    renderCard({ isOwned: false, onAddToLibrary })
    fireEvent.click(screen.getByRole('button', { name: 'Add to ComicPile' }))
    expect(onAddToLibrary).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('comic-mapping-map')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Read now' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Rate / Mark read' })).toBeNull()
    expect(patchIssueSpy).not.toHaveBeenCalled()
  })

  it('keeps a blocked issue actionable: advisory only, never a disabled Read now', () => {
    renderCard({ advisory: 'Normally follows B.P.R.D.' })
    expect(screen.getByTestId('comic-issue-availability')).toHaveTextContent('Normally follows B.P.R.D.')
    // SAFETY: getByRole returns the Read now button element.
    const readNow = screen.getByRole('button', { name: 'Read now' }) as HTMLButtonElement
    expect(readNow.disabled).toBe(false)
    expect(screen.getByRole('button', { name: 'Rate / Mark read' })).toBeTruthy()
  })

  it('opens the rating editor without writing, defaulting to 3.5, then saves one direct write', async () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Read now' }))
    expect(patchIssueSpy).not.toHaveBeenCalled()
    expect(screen.getByText('Rate Hellboy in Hell #3')).toBeTruthy()
    const slider = screen.getByRole('slider')
    // SAFETY: the slider role is rendered as an input element.
    expect((slider as HTMLInputElement).value).toBe('3.5')

    // The manual editor must not promise Roll-only die/queue effects.
    expect(screen.queryByText(/Moves this series/)).toBeNull()
    expect(screen.getByText(/Direct read only/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledTimes(1))
    expect(patchIssueSpy).toHaveBeenCalledWith(
      77,
      expect.objectContaining({ status: 'read', rating: 3.5, idempotencyKey: expect.stringMatching(/^direct-/) }),
    )
  })

  it('edits the rating before save', async () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Read now' }))
    fireEvent.change(screen.getByRole('slider'), { target: { value: '4.5' } })
    // SAFETY: the slider role is rendered as an input element.
    expect((screen.getByRole('slider') as HTMLInputElement).value).toBe('4.5')
    fireEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledTimes(1))
    expect(patchIssueSpy).toHaveBeenCalledWith(77, expect.objectContaining({ status: 'read', rating: 4.5 }))
  })

  it('cancels with no mutations', () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Read now' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patchIssueSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Read now' })).toBeTruthy()
  })

  it('corrects an already-read rating without creating another read', async () => {
    patchIssueSpy.mockResolvedValue(readResponse({ ...READ_CARD, rating: 5 }))
    renderCard({ card: READ_CARD, status: 'read' })
    expect(screen.getByText(/Rated 4\.5/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    expect(patchIssueSpy).not.toHaveBeenCalled()
    // SAFETY: the slider role is rendered as an input element.
    expect((screen.getByRole('slider') as HTMLInputElement).value).toBe('4.5')
    fireEvent.change(screen.getByRole('slider'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save rating' }))
    await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledTimes(1))
    expect(patchIssueSpy).toHaveBeenCalledWith(77, expect.objectContaining({ rating: 5 }))
    // SAFETY: the mocked patchIssue records the direct mutation body as its second argument.
    const body = patchIssueSpy.mock.calls[0][1] as { status?: string }
    expect(body.status).toBeUndefined()
  })

  it('marks unread as a distinct correction', async () => {
    patchIssueSpy.mockResolvedValue(readResponse({ ...READ_CARD, status: 'unread', rating: null }))
    renderCard({ card: READ_CARD, status: 'read' })
    fireEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
    await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledTimes(1))
    expect(patchIssueSpy).toHaveBeenCalledWith(77, expect.objectContaining({ status: 'unread' }))
  })

  it('reuses the idempotency key when retrying an ambiguous failed save', async () => {
    patchIssueSpy.mockRejectedValueOnce(new Error('Network error. Please check your connection.'))
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Read now' }))
    fireEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledTimes(2))
    expect(patchIssueSpy.mock.calls[0][1].idempotencyKey).toMatch(/^direct-/)
    expect(patchIssueSpy.mock.calls[1][1].idempotencyKey).toBe(patchIssueSpy.mock.calls[0][1].idempotencyKey)
  })

  it('keeps slider descriptions unique when multiple issue cards are edited', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <ComicIssueCard issueId={77} card={UNREAD_CARD} threadTitle="Hellboy in Hell" issueNumber="3" status="unread" />
        <ComicIssueCard issueId={78} card={{ ...UNREAD_CARD, issue_id: 78, issue_number: '4' }} threadTitle="Hellboy in Hell" issueNumber="4" status="unread" />
      </QueryClientProvider>,
    )
    for (const button of screen.getAllByRole('button', { name: 'Read now' })) fireEvent.click(button)
    // SAFETY: the slider role is rendered as an input element.
    const sliders = screen.getAllByRole('slider') as HTMLInputElement[]
    expect(sliders).toHaveLength(2)
    expect(sliders[0].id).not.toBe(sliders[1].id)
    expect(sliders[0].getAttribute('aria-describedby')).not.toBe(sliders[1].getAttribute('aria-describedby'))
    for (const slider of sliders) {
      expect(document.getElementById(slider.getAttribute('aria-describedby') ?? '')).not.toBeNull()
    }
  })

  it('keeps reading actions usable if mapping is hidden', () => {
    renderCard({ showMapping: false, advisory: 'Normally follows an unread issue.' })
    expect(screen.getByRole('button', { name: 'Read now' })).not.toBeDisabled()
    expect(screen.queryByTestId('comic-mapping-action')).toBeNull()
  })

  it('renders a compact placeholder without a cover or a provider identity', () => {
    renderCard({ card: null, variant: 'compact', threadTitle: 'An Annual', issueNumber: 'Annual 1', showMapping: false })
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toHaveAttribute('aria-label', 'No cover for An Annual #Annual 1')
    expect(screen.getByRole('button', { name: 'Read now' })).not.toBeDisabled()
  })

  it('does not fetch the per-issue identity GET when the batch supplies mapping state', () => {
    renderCard()
    expect(getIssueIdentitySpy).not.toHaveBeenCalled()
    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Mapped')
  })
})
