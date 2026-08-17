import { beforeAll, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { comicVineApi } from '../services/api'
import { ComicPillar } from '../pages/RollPage/components/ComicVineIssueCard'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn() } }
})

const getIntelligence = vi.mocked(comicVineApi.getIssueIntelligence)

function mockDesktop(isDesktop = true) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: isDesktop,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
}

beforeAll(() => {
  mockDesktop(true)
})

describe('ComicPillar', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
  })

  it('displays full metadata expanded by default with large cover on desktop', async () => {
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

    render(<ComicPillar issueId={1} />)
    expect(await screen.findByText('Alpha #1')).toBeInTheDocument()
    expect(screen.getByText('Opening')).toBeInTheDocument()
    expect(screen.getByText('A bold beginning.')).toBeInTheDocument()
    expect(screen.getByText('Writer One')).toBeInTheDocument()
    expect(screen.getByText('The Big Arc')).toBeInTheDocument()
    expect(screen.getByText('Alpha #2 — Second Part: The Plot Thickens')).toBeInTheDocument()
    expect(screen.getByText('Beta #102')).toBeInTheDocument()
    expect(screen.getByText('1 in ComicPile · 1 missing')).toBeInTheDocument()
    expect(screen.getByText('View source on ComicVine')).toBeInTheDocument()
    const cover = screen.getByAlt('Cover art for Alpha #1 — Opening')
    expect(cover).toBeInTheDocument()
  })

  it('labels every story-arc issue with series number and title without requiring expansion', async () => {
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

    render(<ComicPillar issueId={1} />)
    expect(await screen.findByText('Fantastic Four #583')).toBeInTheDocument()
    expect(screen.getByText('Three')).toBeInTheDocument()
    expect(screen.getByText('Fantastic Four #584 — Three, Part Two: Congratulations, Mister Grimm. You`re Handsome Again!')).toBeInTheDocument()
    expect(screen.getByText('The Amazing Spider-Man #657 — Torch Song')).toBeInTheDocument()
    expect(screen.getByText('Fantastic Four Adventures #28')).toBeInTheDocument()
    expect(screen.getByText('0 in ComicPile · 3 missing')).toBeInTheDocument()
  })

  it('renders nothing when the issue has no confirmed ComicVine mapping', async () => {
    getIntelligence.mockResolvedValue(null)
    const { container } = render(<ComicPillar issueId={9} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(9))
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('shows a cover placeholder when the image fails to load on desktop', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '201',
      comicvine_url: null,
      series_name: 'X-Men',
      series_id: 3,
      issue_number: '7',
      name: null,
      description: null,
      image_url: 'https://images.example/broken-cover.jpg',
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
    })

    const { container } = render(<ComicPillar issueId={2} />)
    expect(await screen.findByText('X-Men #7')).toBeInTheDocument()
    const cover = screen.getByAlt('Cover art for X-Men #7')
    expect(cover).toBeInTheDocument()
    fireEvent.error(cover)
    expect(container.querySelector('img')).toBeNull()
  })

  it('handles sparse metadata, read matches, and cover fallback on desktop', async () => {
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
      ],
    })

    mockDesktop(true)
    const { container } = render(<ComicPillar issueId={2} />)
    expect(await screen.findByText('ComicVine')).toBeInTheDocument()
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
    expect(screen.getByText('Artist Only')).toBeInTheDocument()
    expect(screen.getByText('Named Special')).toBeInTheDocument()
    expect(screen.queryByText('View source on ComicVine')).not.toBeInTheDocument()

    const cover = container.querySelector('img')
    if (cover) {
      fireEvent(cover, new Event('error'))
    }
    expect(container.querySelector('img')).toBeNull()
  })

  it('does not request metadata when no issue is selected', async () => {
    const { container } = render(<ComicPillar issueId={null} />)
    expect(getIntelligence).not.toHaveBeenCalled()
    expect(container).toBeEmptyDOMElement()
  })

  it('fails closed when metadata loading fails', async () => {
    getIntelligence.mockRejectedValue(new Error('metadata unavailable'))
    const { container } = render(<ComicPillar issueId={3} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(3))
    await waitFor(() => expect(screen.queryByLabelText('Loading ComicVine details')).not.toBeInTheDocument())
    expect(container).toBeEmptyDOMElement()
  })

  it('ignores a response that arrives after the component unmounts', async () => {
    let resolveRequest: ((value: null) => void) | undefined
    getIntelligence.mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const { unmount } = render(<ComicPillar issueId={4} />)
    await waitFor(() => expect(getIntelligence).toHaveBeenCalledWith(4))

    unmount()
    resolveRequest?.(null)
    await Promise.resolve()
    await Promise.resolve()
  })

  it('reveals secondary metadata on mobile when Show more is activated', async () => {
    mockDesktop(false)
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '300',
      comicvine_url: 'https://comicvine.example/300',
      series_name: 'Detective',
      series_id: 5,
      issue_number: '12',
      name: 'The Clue',
      description: 'A short description.',
      image_url: 'https://images.example/300.jpg',
      cover_date: '2026-03-15',
      store_date: null,
      creators: [{ name: 'Penciler', roles: ['pencils'] }, { name: 'Inker', roles: ['inks'] }],
      story_arcs: [{
        comicvine_arc_id: 99,
        name: 'Mystery Run',
        comicvine_url: null,
        related_issues: [{
          comicvine_issue_id: '301',
          series_name: 'Detective',
          issue_number: '13',
          name: null,
          cover_date: null,
          comicvine_url: null,
          comicpile_matches: [],
        }],
      }],
    })

    render(<ComicPillar issueId={5} />)
    expect(await screen.findByText('Detective #12')).toBeInTheDocument()
    expect(screen.getByText('A short description.')).toBeInTheDocument()
    expect(screen.getByText('Show more')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Show more'))
    expect(screen.getByText('Penciler')).toBeInTheDocument()
    expect(screen.getByText('Mystery Run')).toBeInTheDocument()
    expect(screen.getByText('Detective #13')).toBeInTheDocument()
    expect(screen.getByText('View source on ComicVine')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Show less'))
    expect(screen.queryByText('Penciler')).not.toBeInTheDocument()
  })

  it('displays source link with accessible keyboard focus', async () => {
    getIntelligence.mockResolvedValue({
      comicvine_issue_id: '400',
      comicvine_url: 'https://comicvine.example/400',
      series_name: 'Action',
      series_id: 1,
      issue_number: '1',
      name: null,
      description: null,
      image_url: null,
      cover_date: null,
      store_date: null,
      creators: [],
      story_arcs: [],
    })

    render(<ComicPillar issueId={6} />)
    const link = await screen.findByRole('link', { name: /view source on comicvine/i })
    expect(link).toHaveAttribute('href', 'https://comicvine.example/400')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(link).toHaveAttribute('tabindex', '0')
  })
})