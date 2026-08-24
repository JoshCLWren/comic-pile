import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { comicVineApi } from '../services/api'
import { ComicVineIssueCard } from '../pages/RollPage/components/ComicVineIssueCard'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn() } }
})

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: {
    list: vi.fn().mockResolvedValue({ reading_orders: [] }),
    getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }),
    insertItem: vi.fn().mockResolvedValue({}),
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

describe('ComicVineIssueCard', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
  })

  it('progressively reveals metadata and mapped versus missing story-arc issues', async () => {
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
      creators: [{ name: 'Writer One', roles: ['writer'] }],
      story_arcs: [{
        comicvine_arc_id: 42,
        total_related_count: null,
        name: 'The Big Arc',
        comicvine_url: null,
        related_issues: [
          {
            comicvine_issue_id: '101', series_name: 'Alpha', issue_number: '2',
            name: 'Second Part: The Plot Thickens', cover_date: null, comicvine_url: null,
            comicpile_matches: [{ issue_id: 2, thread_id: 1, thread_title: 'Alpha', issue_number: '2', status: 'unread' }],
          },
          {
            comicvine_issue_id: '102', series_name: 'Beta', issue_number: '1', name: null,
            cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
        ],
      }],
    })

    render(<ComicVineIssueCard issueId={1} />)
    expect(await screen.findByText('Alpha #1')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Comic details'))
    expect(screen.getByText('A bold beginning.')).toBeInTheDocument()
    expect(screen.getByText('Writer One')).toBeInTheDocument()
    // Primary identity and secondary title are now separate elements
    expect(screen.getByText('Alpha #2')).toBeInTheDocument()
    expect(screen.getByText('Second Part: The Plot Thickens')).toBeInTheDocument()
    expect(screen.getByText('Beta #1')).toBeInTheDocument()
    expect(screen.getByText('Unread')).toBeInTheDocument()
    expect(screen.getByText('Not in ComicPile')).toBeInTheDocument()
    expect(screen.getByText('1 in ComicPile · 1 missing')).toBeInTheDocument()
    // Add to ComicPile button for missing issue
    expect(screen.getByRole('button', { name: /Add Beta #1 to ComicPile/i })).toBeInTheDocument()
  })

  it('labels every story-arc issue with its series, number, and title', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '583',
      comicvine_url: 'https://comicvine.example/583',
      series_name: 'Fantastic Four',
      series_id: 9,
      issue_number: '583',
      name: 'Three, Part One: In Latveria, the Flowers Bloom in Winter',
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [{
        comicvine_arc_id: 70,
        total_related_count: null,
        name: 'Three',
        comicvine_url: null,
        related_issues: [
          {
            comicvine_issue_id: '584', series_name: 'Fantastic Four', issue_number: '584',
            name: 'Three, Part Two: Congratulations, Mister Grimm. You`re Handsome Again!',
            cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
          {
            comicvine_issue_id: '657', series_name: 'The Amazing Spider-Man', issue_number: '657',
            name: 'Torch Song', cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
          {
            comicvine_issue_id: '28', series_name: 'Fantastic Four Adventures', issue_number: '28',
            name: null, cover_date: null, comicvine_url: null, comicpile_matches: [],
          },
        ],
      }],
    })

    render(<ComicVineIssueCard issueId={1} />)
    expect(await screen.findByText('Three')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Comic details'))
    // Primary identity and secondary title are now separate elements
    expect(screen.getByText('Fantastic Four #584')).toBeInTheDocument()
    expect(screen.getByText("Three, Part Two: Congratulations, Mister Grimm. You`re Handsome Again!")).toBeInTheDocument()
    expect(screen.getByText('The Amazing Spider-Man #657')).toBeInTheDocument()
    expect(screen.getByText('Torch Song')).toBeInTheDocument()
    expect(screen.getByText('Fantastic Four Adventures #28')).toBeInTheDocument()
    expect(screen.getByText('0 in ComicPile · 3 missing')).toBeInTheDocument()
    // Add to ComicPile buttons for all missing issues
    expect(screen.getByRole('button', { name: /Add Fantastic Four #584 to ComicPile/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add The Amazing Spider-Man #657 to ComicPile/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add Fantastic Four Adventures #28 to ComicPile/i })).toBeInTheDocument()
  })

  it('renders nothing when the issue has no confirmed ComicVine mapping', async () => {
    getIntelligence.mockResolvedValue(null)
    const { container } = render(<ComicVineIssueCard issueId={9} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(9))
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('handles sparse metadata, read matches, and a cover image failure', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '200',
      comicvine_url: null,
      series_name: null,
      series_id: null,
      issue_number: null,
      name: null,
      description: null,
      image_url: 'https://images.example/broken.jpg',
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
            comicvine_issue_id: '201',
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
            comicvine_issue_id: '202',
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

    const { container } = render(<ComicVineIssueCard issueId={2} />)
    expect(await screen.findByText('ComicVine')).toBeInTheDocument()
    expect(screen.getByText('2 story arcs')).toBeInTheDocument()
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
    expect(screen.getByText('Artist Only')).toBeInTheDocument()
    expect(screen.getByText('Named Special')).toBeInTheDocument()
    expect(screen.getByText('Untitled ComicVine issue')).toBeInTheDocument()
    expect(screen.queryByText(/ComicVine issue \d+/)).not.toBeInTheDocument()
    expect(screen.queryByText(/ComicVine #\d+/)).not.toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.getByText('Not in ComicPile')).toBeInTheDocument()
    expect(screen.queryByText('View source on ComicVine')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Add Untitled ComicVine issue to ComicPile/i }),
    ).toBeInTheDocument()

    const cover = container.querySelector('img')
    expect(cover).not.toBeNull()
    fireEvent.error(cover!)
    expect(container.querySelector('img')).toBeNull()
  })

  it('does not request metadata when no issue is selected', () => {
    const { container } = render(<ComicVineIssueCard issueId={null} />)
    expect(getIntelligence).not.toHaveBeenCalled()
    expect(container).toBeEmptyDOMElement()
  })

  it('fails closed when metadata loading fails', async () => {
    getIntelligence.mockRejectedValue(new Error('metadata unavailable'))
    const { container } = render(<ComicVineIssueCard issueId={3} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(3))
    await waitFor(() => expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument())
    expect(container).toBeEmptyDOMElement()
  })

  it('ignores a response that arrives after the card unmounts', async () => {
    let resolveRequest: ((value: null) => void) | undefined
    getIntelligence.mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const { unmount } = render(<ComicVineIssueCard issueId={4} />)
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

    render(<ComicVineIssueCard issueId={5} />)
    expect(await screen.findByText('Batman #125')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Comic details'))
    const addButton = screen.getByRole('button', { name: /Add Batman #126 to ComicPile/i })
    fireEvent.click(addButton)
    expect(await screen.findByTestId('add-to-comicpile-dialog')).toBeInTheDocument()
    expect(screen.getByText('ComicVine Issue')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Batman #126')).toBeInTheDocument()
  })
})