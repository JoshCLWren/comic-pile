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

function waitForLoaded() {
  return waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())
}

describe('ComicIdentity', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    importIssue.mockReset()
    refreshMetadata.mockReset()
  })

  it('reports truncated story arcs and links the arc on ComicVine', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '110',
      comicvine_url: null,
      series_name: 'Alpha',
      series_id: 8,
      issue_number: '1',
      name: 'Opening',
      description: null,
      image_url: 'https://images.example/110.jpg',
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 43,
        total_related_count: 5,
        name: 'Long Arc',
        comicvine_url: 'https://comicvine.example/arc/43',
        related_issues: [
          {
            comicvine_issue_id: '111', series_name: 'Alpha', issue_number: '2',
            name: 'Second Part', cover_date: null, comicvine_url: null,
            comicpile_matches: [],
          },
          {
            comicvine_issue_id: '112', series_name: 'Alpha', issue_number: '3',
            name: 'Third Part', cover_date: null, comicvine_url: null,
            comicpile_matches: [],
          },
        ],
      }],
    })

    renderWithToast(<ComicIdentity issueId={10} />)
    await waitForLoaded()

    expect(screen.getByText('(2 of 5 shown)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View story arc on ComicVine' })).toHaveAttribute(
      'href',
      'https://comicvine.example/arc/43',
    )
  })

  it('renders large cover image and expanded metadata for full intelligence', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '100',
      comicvine_url: 'https://comicvine.example/100',
      series_name: 'Alpha',
      series_id: 8,
      issue_number: '1',
      name: 'Opening',
      description: 'A bold beginning.',
      image_url: 'https://images.example/100.jpg',
      cover_date: '2026-01-01',
      store_date: null,
      creators: [{ name: 'Writer One', roles: ['writer'] }, { name: 'Artist One', roles: ['penciler', 'inker'] }],
      story_arcs: [{
        comicvine_arc_id: 42,
        total_related_count: null,
        name: 'The Big Arc',
        comicvine_url: null,
        related_issues: [
          {
            comicvine_issue_id: '101', series_name: 'Alpha', issue_number: '2',
            name: 'Second Part', cover_date: null, comicvine_url: null,
            comicpile_matches: [{ issue_id: 2, thread_id: 1, thread_title: 'Alpha', issue_number: '2', status: 'unread' }],
          },
          {
            comicvine_issue_id: '102', series_name: 'Beta', issue_number: '1', name: null,
            cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
        ],
      }],
    })

    renderWithToast(<ComicIdentity issueId={1} />)
    await waitForLoaded()

    // Cover image should be visible immediately (not in a collapsed card) and
    // loaded directly from the provider CDN, never via the ComicPile API.
    const cover = await screen.findByAltText('')
    expect(cover).toBeInTheDocument()
    expect(cover).toHaveAttribute('src', 'https://images.example/100.jpg')
    expect(cover).not.toHaveAttribute('srcset')

    // Cover/store date
    expect(screen.getByText('Jan 1, 2026')).toBeInTheDocument()

    // Creators with roles
    expect(screen.getByText('Writer One')).toBeInTheDocument()
    expect(screen.getByText('Artist One')).toBeInTheDocument()
    expect(screen.getByText((c) => c.includes('writer'))).toBeInTheDocument()
    expect(screen.getByText((c) => c.includes('penciler, inker'))).toBeInTheDocument()

    // Description
    expect(screen.getByText('A bold beginning.')).toBeInTheDocument()

    // Story arc metadata - primary and secondary are now separate
    expect(screen.getByText('The Big Arc')).toBeInTheDocument()
    expect(screen.getByText('Alpha #2')).toBeInTheDocument()
    expect(screen.getByText('Second Part')).toBeInTheDocument()
    expect(screen.getByText('Beta #1')).toBeInTheDocument()
    expect(screen.getByText('Unread')).toBeInTheDocument()
    expect(screen.getByText('Not in ComicPile')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add Beta #1 to ComicPile/i })).toBeInTheDocument()

    // ComicVine source link
    expect(screen.getByText('View issue on ComicVine')).toBeInTheDocument()
  })

  it('renders placeholder when cover image is missing', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '200',
      comicvine_url: null,
      series_name: 'Test Series',
      series_id: 9,
      issue_number: '5',
      name: 'Test Issue',
      description: 'Description here',
      image_url: null,
      cover_date: null,
      store_date: '2026-06-15',
      creators: [],
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={2} />)
    await waitForLoaded()

    // Should show placeholder SVG, not an img tag
    const placeholder = screen.getByTestId('cover-placeholder')
    expect(placeholder).toBeInTheDocument()
    expect(screen.queryByAltText('')).not.toBeInTheDocument()

    expect(screen.getByText('Jun 15, 2026')).toBeInTheDocument()
  })

  it('handles cover image load failure gracefully', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '300',
      comicvine_url: null,
      series_name: 'Fail Series',
      series_id: 10,
      issue_number: '10',
      name: 'Fail Issue',
      description: null,
      image_url: 'https://images.example/broken.jpg',
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={3} />)
    await waitForLoaded()

    const cover = await screen.findByAltText('')
    expect(cover).toBeInTheDocument()

    fireEvent.error(cover)

    // Should fall back to placeholder
    await waitFor(() => {
      expect(screen.queryByAltText('')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('cover-placeholder')).toBeInTheDocument()
  })

  it('shows Show more/Show less for long creator lists', async () => {
    const manyCreators = Array.from({ length: 10 }, (_, i) => ({
      name: `Creator ${i + 1}`,
      roles: ['writer'],
    }))

    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '400',
      comicvine_url: null,
      series_name: 'Many Creators',      series_id: 11,
      issue_number: '1',
      name: 'Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: manyCreators,
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={4} />)
    await waitForLoaded()

    // Initially only first 6 creators shown
    await waitFor(() => expect(screen.getByText('Creator 1')).toBeInTheDocument())
    expect(screen.getByText('Creator 6')).toBeInTheDocument()
    expect(screen.queryByText('Creator 7')).not.toBeInTheDocument()

    // Show more button
    const showMoreButton = screen.getByRole('button', { name: /show all 10/i })
    fireEvent.click(showMoreButton)

    expect(screen.getByText('Creator 7')).toBeInTheDocument()
    expect(screen.getByText('Creator 10')).toBeInTheDocument()

    // Show less button
    const showLessButton = screen.getByRole('button', { name: /show less/i })
    fireEvent.click(showLessButton)

    expect(screen.getByText('Creator 1')).toBeInTheDocument()
    expect(screen.queryByText('Creator 7')).not.toBeInTheDocument()
  })

  it('keeps the Show all creators control outside the summary so activating it cannot collapse the disclosure', async () => {
    const manyCreators = Array.from({ length: 10 }, (_, i) => ({
      name: `Creator ${i + 1}`,
      roles: ['writer'],
    }))

    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '401',
      comicvine_url: null,
      series_name: 'Many Creators',
      series_id: 11,
      issue_number: '1',
      name: 'Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: manyCreators,
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={4} />)
    await waitForLoaded()

    const showAllButton = screen.getByRole('button', { name: /show all 10/i })
    expect(showAllButton.closest('summary')).toBeNull()

    fireEvent.click(showAllButton)
    await waitFor(() => expect(screen.getByText('Creator 10')).toBeInTheDocument())
    const creatorsDetails = showAllButton.closest('details')
    expect(creatorsDetails).not.toBeNull()
    expect(creatorsDetails?.open).toBe(true)
  })

  it('expands creator and story-arc disclosures by default once metadata loads', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '402',
      comicvine_url: null,
      series_name: 'Expanded',
      series_id: 17,
      issue_number: '1',
      name: 'Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [{ name: 'Creator One', roles: ['writer'] }],
      story_arcs: [{
        comicvine_arc_id: 7,
        total_related_count: null,
        name: 'Arc Seven',
        comicvine_url: null,
        related_issues: [],
      }],
    })

    renderWithToast(<ComicIdentity issueId={4} />)
    await waitForLoaded()

    await waitFor(() => expect(screen.getByText('Creator One')).toBeInTheDocument())
    const creatorsDetails = screen.getByText('Creators').closest('details')
    expect(creatorsDetails?.open).toBe(true)

    const storyArcsDetails = screen.getByText('Story arcs (1)').closest('details')
    expect(storyArcsDetails?.open).toBe(true)
  })

  it('names the section via aria-label when the issue title is missing', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '403',
      comicvine_url: null,
      series_name: 'Untitled Series',
      series_id: 18,
      issue_number: '1',
      name: null,
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={4} />)
    await waitForLoaded()

    const section = screen.getByRole('region', { name: 'Comic details' })
    expect(section).toBeInTheDocument()
  })

  it('shows Show more/Show less for long story arc lists', async () => {
    const manyArcs = Array.from({ length: 5 }, (_, i) => ({
      comicvine_arc_id: i + 1,
      name: `Arc ${i + 1}`,
      comicvine_url: null,
      total_related_count: null,
      related_issues: [],
    }))

    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '500',
      comicvine_url: null,
      series_name: 'Many Arcs',
      series_id: 12,
      issue_number: '1',
      name: 'Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: manyArcs,
    })

    renderWithToast(<ComicIdentity issueId={5} />)
    await waitForLoaded()

    // Initially only first 3 arcs shown
    await waitFor(() => expect(screen.getByText('Arc 1')).toBeInTheDocument())
    expect(screen.getByText('Arc 3')).toBeInTheDocument()
    expect(screen.queryByText('Arc 4')).not.toBeInTheDocument()

    // Show more button
    const showMoreButton = screen.getByRole('button', { name: /show all 5 story arcs/i })
    fireEvent.click(showMoreButton)

    await waitFor(() => expect(screen.getByText('Arc 4')).toBeInTheDocument())
    expect(screen.getByText('Arc 5')).toBeInTheDocument()

    // Show less button
    const showLessButton = screen.getByRole('button', { name: /show fewer arcs/i })
    fireEvent.click(showLessButton)

    await waitFor(() => expect(screen.getByText('Arc 1')).toBeInTheDocument())
    expect(screen.queryByText('Arc 4')).not.toBeInTheDocument()
  })

  it('shows Show more/Show less for related issues within an arc', async () => {
    const manyIssues = Array.from({ length: 8 }, (_, i) => ({
      comicvine_issue_id: `${i + 1}`,
      series_name: 'Series',
      issue_number: `${i + 1}`,
      name: `Issue ${i + 1}`,
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [],
    }))

    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '600',
      comicvine_url: null,
      series_name: 'Many Issues',
      series_id: 13,
      issue_number: '1',
      name: 'Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 1,
        total_related_count: null,
        name: 'Big Arc',
        comicvine_url: null,
        related_issues: manyIssues,
      }],
    })

    renderWithToast(<ComicIdentity issueId={6} />)
    await waitForLoaded()

    await waitFor(() => expect(screen.getByText('Big Arc')).toBeInTheDocument())

    // Initially only first 5 issues shown - primary and secondary are separate
    expect(screen.getByText('Series #1')).toBeInTheDocument()
    expect(screen.getByText('Issue 1')).toBeInTheDocument()
    expect(screen.getByText('Series #5')).toBeInTheDocument()
    expect(screen.getByText('Issue 5')).toBeInTheDocument()
    expect(screen.queryByText('Series #6')).not.toBeInTheDocument()

    // Button should say "Show all 8 issues" initially
    const showMoreButton = screen.getByRole('button', { name: /show all 8 issues/i })
    expect(showMoreButton).toBeInTheDocument()
    fireEvent.click(showMoreButton)

    await waitFor(() => expect(screen.getByText('Series #6')).toBeInTheDocument())
    expect(screen.getByText('Issue 6')).toBeInTheDocument()
    expect(screen.getByText('Series #8')).toBeInTheDocument()
    expect(screen.getByText('Issue 8')).toBeInTheDocument()

    // Show fewer button
    const showLessButton = screen.getByRole('button', { name: /show fewer/i })
    fireEvent.click(showLessButton)

    await waitFor(() => expect(screen.getByText('Series #1')).toBeInTheDocument())
    expect(screen.queryByText('Series #6')).not.toBeInTheDocument()
  })

  it('renders nothing when issue has no confirmed ComicVine mapping', async () => {
    getIntelligence.mockResolvedValue(null)
    const { container } = renderWithToast(<ComicIdentity issueId={9} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(9))
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('shows a retryable error when metadata loading fails and recovers', async () => {
    const metadataError = Object.assign(new Error('metadata unavailable'), {
      response: { status: 400 },
    })
    getIntelligence
      .mockRejectedValueOnce(metadataError)
      .mockResolvedValueOnce(null)
    const { container } = renderWithToast(<ComicIdentity issueId={3} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load comic details: metadata unavailable',
    )
    expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Retry comic details' }))
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('ignores a response that arrives after the component unmounts', async () => {
    let resolveRequest: ((value: null) => void) | undefined
    getIntelligence.mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const { unmount } = renderWithToast(<ComicIdentity issueId={4} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(4))

    unmount()
    resolveRequest?.(null)
    await Promise.resolve()
    await Promise.resolve()
  })

  it('opens Add to ComicPile dialog when clicking add button for a missing issue', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '300',
      comicvine_url: null,
      series_name: 'Batman',
      series_id: 1,
      issue_number: '125',
      name: 'The Dark Knight',
      description: null,
      image_url: 'https://images.example/300.jpg',
      cover_date: '2025-06-01',
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 100,
        name: 'Knightfall (Storyline)',
        comicvine_url: null,
        total_related_count: 1,
        related_issues: [
          {
            comicvine_issue_id: '301', series_name: 'Batman', issue_number: '126',
            name: null, cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
        ],
      }],
    })

    renderWithToast(<ComicIdentity issueId={5} />)
    await waitForLoaded()
    const addButton = screen.getByRole('button', { name: /Add Batman #126 to ComicPile/i })
    fireEvent.click(addButton)
    expect(await screen.findByTestId('add-to-comicpile-dialog')).toBeInTheDocument()
    expect(screen.getByText('ComicVine Issue')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Batman #126')).toBeInTheDocument()
  })

  it('closes Add to ComicPile dialog when onClose is called', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '400',
      comicvine_url: null,
      series_name: 'Spider-Man',
      series_id: 2,
      issue_number: '50',
      name: 'Amazing',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 200,
        name: 'Clone Saga',
        comicvine_url: null,
        total_related_count: 1,
        related_issues: [
          {
            comicvine_issue_id: '401', series_name: 'Spider-Man', issue_number: '51',
            name: null, cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
        ],
      }],
    })

    renderWithToast(<ComicIdentity issueId={6} />)
    await waitForLoaded()
    const addButton = screen.getByRole('button', { name: /Add Spider-Man #51 to ComicPile/i })
    fireEvent.click(addButton)
    await waitFor(() => expect(screen.getByTestId('add-to-comicpile-dialog')).toBeInTheDocument())

    const closeButton = screen.getByRole('button', { name: /Close/i })
    fireEvent.click(closeButton)
    await waitFor(() => expect(screen.queryByTestId('add-to-comicpile-dialog')).not.toBeInTheDocument())
  })

  it('calls onAdded callback when issue is added via dialog', async () => {
    importIssue.mockResolvedValue({
      thread_id: 42,
      issue_id: 1,
      external_identity_id: 1,
      reading_order_id: null,
      position: 1,
      total_items: 1,
    })
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '500',
      comicvine_url: null,
      series_name: 'X-Men',
      series_id: 3,
      issue_number: '100',
      name: 'Mutant',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 300,
        name: 'Age of Apocalypse',
        comicvine_url: null,
        total_related_count: 1,
        related_issues: [
          {
            comicvine_issue_id: '501', series_name: 'X-Men', issue_number: '101',
            name: null, cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
        ],
      }],
    })

    renderWithToast(<ComicIdentity issueId={7} />)
    await waitForLoaded()
    const addButton = screen.getByRole('button', { name: /Add X-Men #101 to ComicPile/i })
    fireEvent.click(addButton)
    await waitFor(() => expect(screen.getByTestId('add-to-comicpile-dialog')).toBeInTheDocument())

    const confirmButton = screen.getByRole('button', { name: /Add to ComicPile/i })
    fireEvent.click(confirmButton)
    await waitFor(() => expect(screen.queryByTestId('add-to-comicpile-dialog')).not.toBeInTheDocument())
    expect(importIssue).toHaveBeenCalled()
    expect(getIntelligence).toHaveBeenCalledTimes(2)
  })

  it('does not request metadata when no issue is selected', () => {
    const { container } = renderWithToast(<ComicIdentity issueId={null} />)
    expect(getIntelligence).not.toHaveBeenCalled()
    expect(container).toBeEmptyDOMElement()
  })

  it('handles sparse metadata gracefully', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '700',
      comicvine_url: null,
      series_name: null,
      series_id: null,
      issue_number: null,
      name: null,
      description: null,
      image_url: null,
      cover_date: null,
      store_date: 'Coming soon',
      creators: [{ name: 'Artist Only', roles: [] }],
      story_arcs: [
        {
          comicvine_arc_id: 50,
          total_related_count: null,
          name: 'First Arc',
          comicvine_url: null,
          related_issues: [{
            comicvine_issue_id: '701',
            series_name: null,
            issue_number: null,
            name: 'Named Special',
            cover_date: null,
            comicvine_url: null,
            comicpile_matches: [{
              issue_id: 20,
              thread_id: 2,
              thread_title: 'Specials',
              issue_number: '1',
              status: 'read',
            }],
          }],
        },
        {
          comicvine_arc_id: 51,
          total_related_count: null,
          name: 'Second Arc',
          comicvine_url: null,
          related_issues: [{
            comicvine_issue_id: '702',
            series_name: null,
            issue_number: null,
            name: null,
            cover_date: null,
            comicvine_url: null,
            comicpile_matches: [],
          }],
        },
      ],
    })

    const { container: _container } = renderWithToast(<ComicIdentity issueId={7} />)
    await waitForLoaded()
    // Summary text is split, check for the arc count in the summary
    expect(screen.getByText((content) => content.includes('Story arcs') && content.includes('2'))).toBeInTheDocument()
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
    expect(screen.getByText('Artist Only')).toBeInTheDocument()
    expect(screen.getByText('Named Special')).toBeInTheDocument()
    expect(screen.getByText('ComicVine issue 702')).toBeInTheDocument()
    expect(screen.queryByText('Untitled ComicVine issue')).not.toBeInTheDocument()
    expect(screen.queryByText(/ComicVine #\d+/)).not.toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.getByText('Not in ComicPile')).toBeInTheDocument()
    expect(screen.queryByText('View source on ComicVine')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Add ComicVine issue 702 to ComicPile/i }),
    ).toBeInTheDocument()
  })

  it('description is in a collapsible details element', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '800',
      comicvine_url: null,
      series_name: 'Test',
      series_id: 14,
      issue_number: '1',
      name: 'Test Issue',
      description: 'A very long description that should be collapsible.',
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={8} />)
    await waitForLoaded()

    // Description should be in a details/summary
    const summary = screen.getByText('Summary')
    expect(summary).toBeInTheDocument()

    // Click to expand
    fireEvent.click(summary)
    expect(screen.getByText('A very long description that should be collapsible.')).toBeInTheDocument()
  })

  it('story arcs section is collapsible via details/summary', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '900',
      comicvine_url: null,
      series_name: 'Test',
      series_id: 15,
      issue_number: '1',
      name: 'Test Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 1,
        total_related_count: null,
        name: 'Test Arc',
        comicvine_url: null,
        related_issues: [],
      }],
    })

    renderWithToast(<ComicIdentity issueId={9} />)
    await waitForLoaded()

    // Story arcs section should exist with details/summary structure
    const details = screen.getByText('Story arcs (1)').closest('details')
    expect(details).toBeInTheDocument()
    expect(screen.getByText('Test Arc')).toBeInTheDocument()

    // Click summary - verifies the interactive structure exists
    const summary = screen.getByText('Story arcs (1)')
    fireEvent.click(summary)
  })

  it('story arc issue list reflows with the page instead of a clipped nested scroller', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '1101',
      comicvine_url: null,
      series_name: 'Test',
      series_id: 17,
      issue_number: '1',
      name: 'Test Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 41,
        total_related_count: null,
        name: 'Deep Arc',
        comicvine_url: null,
        related_issues: Array.from({ length: 8 }, (_, index) => ({
          comicvine_issue_id: `${1102 + index}`,
          series_name: 'Test',
          issue_number: `${index + 1}`,
          name: null,
          cover_date: null,
          comicvine_url: null,
          comicpile_matches: [],
        })),
      }],
    })

    renderWithToast(<ComicIdentity issueId={11} />)
    await waitForLoaded()

    const list = screen.getByTestId('story-arc-issue-list')
    expect(list).toBeInTheDocument()
    expect(list).not.toHaveClass('max-h-48', 'max-h-64', 'overflow-y-auto', 'overscroll-contain')
    expect(list).toHaveClass('space-y-1.5')
  })

  it('creators section is collapsible via details/summary', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '1000',
      comicvine_url: null,
      series_name: 'Test',
      series_id: 16,
      issue_number: '1',
      name: 'Test Issue',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [{ name: 'Test Creator', roles: ['writer'] }],
      story_arcs: [],
    })

    renderWithToast(<ComicIdentity issueId={10} />)
    await waitForLoaded()

    // Creators section should exist with details/summary structure
    const details = screen.getByText('Creators').closest('details')
    expect(details).toBeInTheDocument()
    expect(screen.getByText('Test Creator')).toBeInTheDocument()

    // Click summary - verifies the interactive structure exists
    const summary = screen.getByText('Creators')
    fireEvent.click(summary)
  })

  describe('narrow phone viewport cover geometry', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: 390,
      })
      window.dispatchEvent(new Event('resize'))
    })

    afterEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: 1024,
      })
      window.dispatchEvent(new Event('resize'))
    })

    it('preserves portrait cover geometry data attributes on a narrow phone viewport', async () => {
      getIntelligence.mockResolvedValue({
        comicvine_issue_id: '9001',
        comicvine_url: null,
        series_name: 'Phone Test',
        series_id: 1,
        issue_number: '1',
        name: 'Phone Cover',
        description: null,
        image_url: 'https://images.example/phone-cover.jpg',
        cover_date: '2026-01-01',
        store_date: null,
        creators: [],
        story_arcs: [],
      })

      renderWithToast(<ComicIdentity issueId={99} />)
      await waitForLoaded()

      const cover = screen.getByTestId('comic-cover')
      const aspectRatio = Number(cover.getAttribute('data-cover-aspect-ratio'))
      const heightCap = Number(cover.getAttribute('data-cover-height-cap-vh'))
      const widthCap = Number(cover.getAttribute('data-cover-width-cap-vh'))

      expect(Number.isFinite(aspectRatio)).toBe(true)
      expect(aspectRatio).toBeGreaterThan(0)
      expect(heightCap).toBe(45)
      expect(Number.isFinite(widthCap)).toBe(true)
      expect(widthCap).toBeGreaterThan(0)
      expect(widthCap).toBeCloseTo(heightCap * aspectRatio)
      expect(cover.className).not.toContain('max-h-')
    })

    it('updates cover geometry to intrinsic aspect ratio after the image loads on a narrow phone viewport', async () => {
      getIntelligence.mockResolvedValue({
        comicvine_issue_id: '9002',
        comicvine_url: null,
        series_name: 'Phone Intrinsic',
        series_id: 1,
        issue_number: '2',
        name: 'Phone Intrinsic Cover',
        description: null,
        image_url: 'https://images.example/phone-intrinsic.jpg',
        cover_date: '2026-01-01',
        store_date: null,
        creators: [],
        story_arcs: [],
      })

      renderWithToast(<ComicIdentity issueId={100} />)
      await waitForLoaded()

      const cover = screen.getByTestId('comic-cover')
      const img = cover.querySelector('img')
      expect(img).not.toBeNull()

      act(() => {
        if (!img) {
          throw new Error('Image element not found')
        }
        Object.defineProperty(img, 'naturalWidth', { value: 400 })
        Object.defineProperty(img, 'naturalHeight', { value: 600 })
        img.dispatchEvent(new Event('load'))
      })

      const updatedAspectRatio = Number(cover.getAttribute('data-cover-aspect-ratio'))
      expect(updatedAspectRatio).toBeCloseTo(400 / 600)
      const updatedWidthCap = Number(cover.getAttribute('data-cover-width-cap-vh'))
      expect(updatedWidthCap).toBeCloseTo(45 * updatedAspectRatio)
    })
  })

  describe('cover loading lifecycle transition', () => {
    it('keeps one stable portrait footprint and no dark frame from metadata loading through image completion', async () => {
      let resolveRequest: ((value: ComicVineIssueIntelligence | null) => void) | undefined
      getIntelligence.mockImplementation(() => new Promise((resolve) => {
        resolveRequest = resolve
      }))

      renderWithToast(<ComicIdentity issueId={101} />)
      await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(101))

      const loadingCover = screen.getByTestId('comic-cover')
      const loadingAspect = Number(loadingCover.getAttribute('data-cover-aspect-ratio'))
      expect(loadingAspect).toBeCloseTo(2 / 3)
      expect(loadingCover.getAttribute('data-cover-height-cap-vh')).toBe('45')
      expect(loadingCover.className).toContain('animate-pulse')
      expect(loadingCover.className).toContain('bg-[var(--theme-bg-hover)]')
      expect(loadingCover.className).not.toMatch(/bg-(?:white|stone)/)

      await act(async () => {
        resolveRequest?.({
          comicvine_issue_id: '9003',
          comicvine_url: null,
          series_name: 'Transition Test',
          series_id: 1,
          issue_number: '1',
          name: 'Transition Cover',
          description: null,
          image_url: 'https://images.example/transition.jpg',
          cover_date: '2026-01-01',
          store_date: null,
          creators: [],
          story_arcs: [],
        })
      })

      await waitForLoaded()

      const loadedCover = screen.getByTestId('comic-cover')
      const loadedAspect = Number(loadedCover.getAttribute('data-cover-aspect-ratio'))
      expect(loadedAspect).toBeCloseTo(2 / 3)
      expect(loadedCover.getAttribute('data-cover-height-cap-vh')).toBe('45')
      expect(loadedCover.className).toContain('bg-[var(--theme-bg-hover)]')
      expect(loadedCover.className).not.toMatch(/bg-(?:white|stone)/)
      expect(loadedCover.className).not.toContain('max-h-')
      expect(loadedCover.querySelector('img')).not.toBeNull()
    })
  })
})

describe('ComicIdentity creator metadata contract (#5841)', () => {
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
      comicvine_url: 'https://comicvine.example/100',
      series_name: 'Test Series',
      series_id: 1,
      issue_number: '1',
      name: 'Test Issue',
      description: null,
      image_url: 'https://images.example/100.jpg',
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
      ...overrides,
    }
  }

  function refreshResult(
    outcome: 'complete' | 'no_credits' | 'not_confirmed' | 'provider_unavailable' | 'rate_limited' | 'timeout' | 'invalid_response',
    options: { refreshed?: boolean; retryAfter?: number | null } = {},
  ) {
    return {
      issue_id: 1,
      refreshed: options.refreshed ?? false,
      comicvine_issue_id: '100',
      outcome,
      retry_after_seconds: options.retryAfter ?? null,
    }
  }

  it('hydrates a roster-only exact issue once and never shows a queued spinner', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'not_deep_fetched' }))
    refreshMetadata.mockResolvedValue(refreshResult('complete', { refreshed: true }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-not_hydrated')).toHaveTextContent('Creator credits not yet fetched')
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
    expect(screen.queryByText(/queued for fetch/)).not.toBeInTheDocument()
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))
    // No repeat request: one bounded awaited attempt per deliberate open.
    expect(refreshMetadata).toHaveBeenCalledTimes(1)
  })

  it('leaves needs_hydration to an explicit Retry', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-not_hydrated')).toHaveTextContent('Creator credits not yet hydrated')
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeInTheDocument()
    expect(refreshMetadata).not.toHaveBeenCalled()
  })

  it.each(['refresh_pending', 'refresh_running'] as const)(
    'reports %s truthfully as not hydrated instead of an indefinite progress state',
    async (status) => {
      getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: status }))

      renderIdentity()
      await waitForLoaded()

      expect(screen.getByTestId('creator-status-not_hydrated')).toBeInTheDocument()
      expect(screen.queryByText(/queued for fetch|being fetched|queued|refreshing/i)).not.toBeInTheDocument()
      expect(screen.queryByTestId('creator-status-hydrating')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeInTheDocument()
      expect(refreshMetadata).not.toHaveBeenCalled()
    },
  )

  it('reports a deferred provider as unavailable with its declared delay', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({
      metadata_status: 'refresh_deferred',
      refresh_retry_after_seconds: 60,
    }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-unavailable')).toHaveTextContent(
      'ComicVine is unavailable right now. Your mapping is safe — try again in 60s.',
    )
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
  })

  it('reports a stored failure without pretending it is still running', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'refresh_failed' }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-failed')).toHaveTextContent('Creator credits could not be loaded')
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
    expect(screen.queryByTestId('creator-status-hydrating')).not.toBeInTheDocument()
  })

  it('renders a legitimate empty credit result without failure copy or a spinner', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({
      metadata_status: 'deep_fetched_no_credits',
      image_url: null,
    }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByTestId('creator-status-no_credits')).toHaveTextContent(
      'ComicVine currently has no creator credits',
    )
    expect(screen.queryByRole('button', { name: 'Retry refresh' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-hydrating')).not.toBeInTheDocument()
  })

  it('renders persisted names, roles and cover after an explicit Retry without remapping', async () => {
    getIntelligence
      .mockResolvedValueOnce(intelligenceResponse({ metadata_status: 'needs_hydration' }))
      .mockResolvedValue(intelligenceResponse({
        metadata_status: 'complete',
        creators: [
          { name: 'Recovered Writer', roles: ['writer'] },
          { name: 'Recovered Artist', roles: ['penciler', 'inker'] },
        ],
      }))
    refreshMetadata.mockResolvedValue(refreshResult('complete', { refreshed: true }))

    renderIdentity()
    await waitForLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.getByText('Recovered Writer')).toBeInTheDocument())
    expect(screen.getByText('Recovered Artist')).toBeInTheDocument()
    expect(screen.getByText(/penciler, inker/)).toBeInTheDocument()
    expect(screen.getByAltText('')).toHaveAttribute('src', 'https://images.example/100.jpg')
    expect(screen.queryByTestId('creator-status-not_hydrated')).not.toBeInTheDocument()
    expect(refreshMetadata).toHaveBeenCalledTimes(1)
  })

  it('keeps mapping and cover intact and offers Retry after a provider failure', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockResolvedValue(refreshResult('provider_unavailable'))

    renderIdentity()
    await waitForLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(screen.getByTestId('creator-status-unavailable')).toBeInTheDocument())
    expect(screen.getByTestId('creator-status-unavailable')).toHaveTextContent('Your mapping is safe')
    expect(screen.getByAltText('')).toHaveAttribute('src', 'https://images.example/100.jpg')
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
  })

  it('honors a provider Retry-After and does not issue a duplicate request', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockResolvedValue(refreshResult('rate_limited', { retryAfter: 30 }))

    renderIdentity()
    await waitForLoaded()

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByTestId('creator-status-rate_limited')).toHaveTextContent('in 30s'))

    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('creator-status-rate_limited')).toHaveTextContent('in 30s')
  })

  it('disables the Retry action while the request is in flight', async () => {
    let resolveRetry: ((value: ReturnType<typeof refreshResult>) => void) | undefined
    refreshMetadata.mockImplementation(() => new Promise((resolve) => {
      resolveRetry = resolve
    }))
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))

    renderIdentity()
    await waitForLoaded()

    const button = screen.getByRole('button', { name: 'Retry refresh' })
    fireEvent.click(button)
    await waitFor(() => expect(button).toBeDisabled())
    expect(screen.getByTestId('creator-status-hydrating')).toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-not_hydrated')).not.toBeInTheDocument()

    fireEvent.click(button)
    expect(refreshMetadata).toHaveBeenCalledTimes(1)

    await act(async () => {
      resolveRetry?.(refreshResult('complete', { refreshed: true }))
    })
    await waitFor(() => expect(button).toBeEnabled())
  })

  it.each([
    ['timeout', 'did not answer in time'],
    ['invalid_response', 'invalid response'],
  ] as const)('reports %s as a truthful retryable outcome', async (outcome, expected) => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockResolvedValue(refreshResult(outcome))

    renderIdentity()
    await waitForLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))

    await waitFor(() => expect(screen.getByTestId(`creator-status-${outcome}`)).toHaveTextContent(expected))
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
  })

  it('reports an empty provider result distinctly from a failure', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockResolvedValue(refreshResult('no_credits'))

    renderIdentity()
    await waitForLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))

    await waitFor(() => expect(screen.getByTestId('creator-status-no_credits')).toBeInTheDocument())
    expect(screen.queryByTestId('creator-status-failed')).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-unavailable')).not.toBeInTheDocument()
  })

  it('keeps the map action as the recovery path for an unconfirmed identity', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockResolvedValue(refreshResult('not_confirmed'))

    renderIdentity()
    await waitForLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))

    await waitFor(() => expect(screen.getByTestId('creator-status-not_confirmed')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Retry refresh' })).not.toBeInTheDocument()
  })

  it('reports a failed transport with retry still available', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockRejectedValue(new Error('network unavailable'))

    renderIdentity()
    await waitForLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))

    await waitFor(() => expect(screen.getByTestId('creator-status-failed')).toHaveTextContent(
      'Could not request creator credits. Try again.',
    ))
    expect(screen.getByRole('button', { name: 'Retry refresh' })).toBeEnabled()
  })

  it('does not re-read the exact issue after unmount', async () => {
    let resolveRetry: ((value: ReturnType<typeof refreshResult>) => void) | undefined
    refreshMetadata.mockImplementation(() => new Promise((resolve) => {
      resolveRetry = resolve
    }))
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))

    const { unmount } = renderIdentity()
    await waitForLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledTimes(1))
    expect(getIntelligence).toHaveBeenCalledTimes(1)

    unmount()
    await act(async () => {
      resolveRetry?.(refreshResult('complete', { refreshed: true }))
    })
    expect(getIntelligence).toHaveBeenCalledTimes(1)
  })

  it('drops a terminal outcome when the confirmed identity changes', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'needs_hydration' }))
    refreshMetadata.mockResolvedValue(refreshResult('provider_unavailable'))

    const { rerender } = renderIdentity(1)
    await waitForLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }))
    await waitFor(() => expect(screen.getByTestId('creator-status-unavailable')).toBeInTheDocument())

    getIntelligence.mockResolvedValue(intelligenceResponse({
      comicvine_issue_id: '200',
      metadata_status: 'complete',
      creators: [{ name: 'Writer B', roles: ['writer'] }],
    }))
    rerender(<ComicIdentity issueId={2} />)

    await waitFor(() => expect(screen.getByText('Writer B')).toBeInTheDocument())
    expect(screen.queryByTestId('creator-status-unavailable')).not.toBeInTheDocument()
  })

  it('does not claim a status for an unrecognized or absent server state', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({ metadata_status: 'some_future_status' }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.queryByTestId('creator-status-not_hydrated')).not.toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-failed')).not.toBeInTheDocument()
    expect(refreshMetadata).not.toHaveBeenCalled()
  })

  it('never renders a status when credits are already visible', async () => {
    getIntelligence.mockResolvedValue(intelligenceResponse({
      metadata_status: 'refresh_failed',
      creators: [{ name: 'Existing Writer', roles: ['writer'] }],
    }))

    renderIdentity()
    await waitForLoaded()

    expect(screen.getByText('Existing Writer')).toBeInTheDocument()
    expect(screen.queryByTestId('creator-status-failed')).not.toBeInTheDocument()
  })
})

describe('cached non-2:3 cover ratio on image URL change', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    importIssue.mockReset()
  })

  it('updates the Roll frame ratio when a cached cover changes image URL', async () => {
    getIntelligence
      .mockResolvedValueOnce({
        comicvine_issue_id: '9001',
        comicvine_url: null,
        series_name: 'First Cover',
        series_id: 1,
        issue_number: '1',
        name: 'First Cover',
        description: null,
        image_url: 'https://images.example/first.jpg',
        cover_date: '2026-01-01',
        store_date: null,
        creators: [],
        story_arcs: [],
      })
      .mockResolvedValueOnce({
        comicvine_issue_id: '9002',
        comicvine_url: null,
        series_name: 'Second Cover',
        series_id: 1,
        issue_number: '2',
        name: 'Second Cover',
        description: null,
        image_url: 'https://images.example/second.jpg',
        cover_date: '2026-01-01',
        store_date: null,
        creators: [],
        story_arcs: [],
      })

    const { rerender } = renderWithToast(<ComicIdentity issueId={1} />)
    await waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())

    const firstCover = screen.getByTestId('comic-cover')
    const firstImage = firstCover.querySelector('img')
    expect(firstImage).not.toBeNull()
    act(() => {
      if (!firstImage) throw new Error('first image missing')
      Object.defineProperty(firstImage, 'naturalWidth', { value: 300, configurable: true })
      Object.defineProperty(firstImage, 'naturalHeight', { value: 400, configurable: true })
      firstImage.dispatchEvent(new Event('load'))
    })
    expect(Number(firstCover.getAttribute('data-cover-aspect-ratio'))).toBeCloseTo(300 / 400)

    rerender(<ComicIdentity issueId={2} />)
    await waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())

    const secondCover = screen.getByTestId('comic-cover')
    const secondImage = secondCover.querySelector('img')
    expect(secondImage).not.toBeNull()
    act(() => {
      if (!secondImage) throw new Error('second image missing')
      Object.defineProperty(secondImage, 'naturalWidth', { value: 500, configurable: true })
      Object.defineProperty(secondImage, 'naturalHeight', { value: 400, configurable: true })
      secondImage.dispatchEvent(new Event('load'))
    })
    expect(Number(secondCover.getAttribute('data-cover-aspect-ratio'))).toBeCloseTo(500 / 400)
  })
})
