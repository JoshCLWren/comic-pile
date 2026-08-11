import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { comicVineApi } from '../services/api'
import { ComicVineIssueCard } from '../pages/RollPage/components/ComicVineIssueCard'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn() } }
})

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
        name: 'The Big Arc',
        comicvine_url: null,
        related_issues: [
          {
            comicvine_issue_id: '101', series_name: 'Alpha', issue_number: '2', name: null,
            cover_date: null, comicvine_url: null,
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
    expect(screen.getByText('Unread')).toBeInTheDocument()
    expect(screen.getByText('Missing')).toBeInTheDocument()
    expect(screen.getByText('1 in ComicPile · 1 missing')).toBeInTheDocument()
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
    expect(screen.getByText('ComicVine issue 202')).toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.queryByText('View source on ComicVine')).not.toBeInTheDocument()

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
})
