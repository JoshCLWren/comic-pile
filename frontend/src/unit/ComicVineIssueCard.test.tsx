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
  beforeEach(() => getIntelligence.mockReset())

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
})
