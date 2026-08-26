import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { comicVineApi } from '../services/api'
import { ComicIdentity } from '../pages/RollPage/components/ComicIdentity'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn(), importIssue: vi.fn() } }
})

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: {
    list: vi.fn().mockResolvedValue({ reading_orders: [] }),
  },
}))

vi.mock('../contexts/useToast', () => ({
  useToast: () => ({
    showToast: vi.fn(),
    removeToast: vi.fn(),
    toasts: [],
  }),
}))

const getIntelligence = vi.mocked(comicVineApi.getIssueIntelligence)
const importIssue = vi.mocked(comicVineApi.importIssue)

function waitForLoaded() {
  return waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())
}

describe('ComicIdentity', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    importIssue.mockReset()
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

    render(<ComicIdentity issueId={1} />)
    await waitForLoaded()

    // Cover image should be visible immediately (not in a collapsed card) and
    // served through the edge-cacheable optimizer with the canonical source.
    const cover = await screen.findByAltText('')
    expect(cover).toBeInTheDocument()
    expect(cover).toHaveAttribute(
      'src',
      '/api/v1/images/optimize?url=https%3A%2F%2Fimages.example%2F100.jpg&width=720',
    )
    const srcSet = cover.getAttribute('srcset') ?? ''
    expect(srcSet).toContain('/api/v1/images/optimize?url=https%3A%2F%2Fimages.example%2F100.jpg&width=240')
    expect(srcSet).toContain('720w')

    // Series name and issue number
    expect(screen.getByText('Alpha #1')).toBeInTheDocument()

    // Issue/story title
    expect(screen.getByText('Opening')).toBeInTheDocument()

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

    render(<ComicIdentity issueId={2} />)
    await waitForLoaded()

    // Should show placeholder SVG, not an img tag
    const placeholder = screen.getByTestId('cover-placeholder')
    expect(placeholder).toBeInTheDocument()
    expect(screen.queryByAltText('')).not.toBeInTheDocument()

    expect(screen.getByText('Test Series #5')).toBeInTheDocument()
    expect(screen.getByText('Test Issue')).toBeInTheDocument()
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

    render(<ComicIdentity issueId={3} />)
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

    render(<ComicIdentity issueId={4} />)
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

    render(<ComicIdentity issueId={4} />)
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

    render(<ComicIdentity issueId={4} />)
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

    render(<ComicIdentity issueId={4} />)
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

    render(<ComicIdentity issueId={5} />)
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

    render(<ComicIdentity issueId={6} />)
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
    const { container } = render(<ComicIdentity issueId={9} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(9))
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('fails closed when metadata loading fails', async () => {
    getIntelligence.mockRejectedValue(new Error('metadata unavailable'))
    const { container } = render(<ComicIdentity issueId={3} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(3))
    await waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())
    expect(container).toBeEmptyDOMElement()
  })

  it('ignores a response that arrives after the component unmounts', async () => {
    let resolveRequest: ((value: null) => void) | undefined
    getIntelligence.mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const { unmount } = render(<ComicIdentity issueId={4} />)
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

    render(<ComicIdentity issueId={5} />)
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

    render(<ComicIdentity issueId={6} />)
    await waitForLoaded()
    const addButton = screen.getByRole('button', { name: /Add Spider-Man #51 to ComicPile/i })
    fireEvent.click(addButton)
    await waitFor(() => expect(screen.getByTestId('add-to-comicpile-dialog')).toBeInTheDocument())

    const closeButton = screen.getByRole('button', { name: /Close/i })
    fireEvent.click(closeButton)
    await waitFor(() => expect(screen.queryByTestId('add-to-comicpile-dialog')).not.toBeInTheDocument())
  })

  it('calls onAdded callback when issue is added via dialog', async () => {
    importIssue.mockResolvedValue({ thread_id: 42 })
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

    render(<ComicIdentity issueId={7} />)
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
    const { container } = render(<ComicIdentity issueId={null} />)
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

    const { container: _container } = render(<ComicIdentity issueId={7} />)
    await waitForLoaded()
    expect(screen.getByText('ComicVine')).toBeInTheDocument()
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

    render(<ComicIdentity issueId={8} />)
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

    render(<ComicIdentity issueId={9} />)
    await waitForLoaded()

    // Story arcs section should exist with details/summary structure
    const details = screen.getByText('Story arcs (1)').closest('details')
    expect(details).toBeInTheDocument()
    expect(screen.getByText('Test Arc')).toBeInTheDocument()

    // Click summary - verifies the interactive structure exists
    const summary = screen.getByText('Story arcs (1)')
    fireEvent.click(summary)
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

    render(<ComicIdentity issueId={10} />)
    await waitForLoaded()

    // Creators section should exist with details/summary structure
    const details = screen.getByText('Creators').closest('details')
    expect(details).toBeInTheDocument()
    expect(screen.getByText('Test Creator')).toBeInTheDocument()

    // Click summary - verifies the interactive structure exists
    const summary = screen.getByText('Creators')
    fireEvent.click(summary)
  })
})