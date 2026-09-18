import { render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api'
import { creatorsApi } from '../services/creatorsApi'
import { ComicIdentity } from '../pages/RollPage/components/ComicIdentity'
import { queryClient } from '../query/queryClient'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn(), importIssue: vi.fn() } }
})
vi.mock('../services/creatorsApi', () => ({
  creatorsApi: { getSummaries: vi.fn() },
}))
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { list: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] }),
}))

const getIntelligence = vi.mocked(comicVineApi.getIssueIntelligence)
const getSummaries = vi.mocked(creatorsApi.getSummaries)

function baseIntelligence(overrides: Partial<ComicVineIssueIntelligence> = {}): ComicVineIssueIntelligence {
  return {
    comicvine_issue_id: '999',
    comicvine_url: null,
    series_name: 'Test Series',
    series_id: 1,
    issue_number: '1',
    name: 'Issue One',
    description: null,
    image_url: null,
    cover_date: null,
    store_date: null,
    creators: [],
    story_arcs: [],
    ...overrides,
  }
}

function summariesResponse(
  summaries: Record<string, { display_name: string; average_rating: number | null; ratings_count: number; upcoming_count: number; normalized_roles?: string[] }>,
  coverage: Partial<{
    ratings_complete: boolean
    upcoming_complete: boolean
    rated_issues_total: number
    rated_issues_with_creator_metadata: number
    read_unrated_complete: boolean
    read_unrated_issues_total: number
    read_unrated_issues_with_creator_metadata: number
    unread_issues_total: number
    unread_issues_with_creator_metadata: number
  }> = {},
) {
  const normalized: Record<string, { canonical_creator_key: string; display_name: string; normalized_roles: string[]; average_rating: number | null; ratings_count: number; read_unrated_count: number; upcoming_count: number }> = {}
  for (const [key, value] of Object.entries(summaries)) {
    normalized[key] = {
      canonical_creator_key: key,
      display_name: value.display_name,
      normalized_roles: value.normalized_roles ?? [],
      average_rating: value.average_rating,
      ratings_count: value.ratings_count,
      read_unrated_count: 0,
      upcoming_count: value.upcoming_count,
    }
  }
  return {
    summaries: normalized,
    coverage: {
      rated_issues_total: 10,
      rated_issues_with_creator_metadata: coverage.ratings_complete === false ? 5 : 10,
      ratings_complete: coverage.ratings_complete ?? true,
      read_unrated_issues_total: 0,
      read_unrated_issues_with_creator_metadata: 0,
      read_unrated_complete: true,
      unread_issues_total: 10,
      unread_issues_with_creator_metadata: coverage.upcoming_complete === false ? 5 : 10,
      upcoming_complete: coverage.upcoming_complete ?? true,
      ...coverage,
    },
  } satisfies Awaited<ReturnType<typeof creatorsApi.getSummaries>>
}

describe('ComicIdentity creator analytics (issue #2029)', () => {
  beforeEach(() => {
    getIntelligence.mockReset()
    getSummaries.mockReset()
    queryClient.clear()
  })

  function renderIdentity(issueId = 1) {
    return render(
      <QueryClientProvider client={queryClient}>
        <ComicIdentity issueId={issueId} />
      </QueryClientProvider>,
    )
  }

  it('shows personal average + rated sample size when ratings exist', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [
        { creator_id: 123, name: 'Grant Morrison', roles: ['writer'] },
      ],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:123': { display_name: 'Grant Morrison', average_rating: 4.3, ratings_count: 17, upcoming_count: 9 },
    }, { ratings_complete: true, upcoming_complete: true }))

    renderIdentity()
    await waitFor(() => expect(screen.getByTestId('creator-row')).toBeInTheDocument())

    await waitFor(() => expect(getSummaries).toHaveBeenCalledTimes(1))
    expect(getSummaries).toHaveBeenCalledWith(['creator:123'])

    await waitFor(() => expect(screen.getByText('Grant Morrison')).toBeInTheDocument())
    expect(screen.getByText('4.3')).toBeInTheDocument()
    expect(screen.getByText('★', { selector: 'span' }) || screen.getByLabelText(/Average rating 4\.3/)).toBeTruthy()
    expect(screen.getByLabelText(/Average rating 4\.3 out of 5 from 17 ratings/)).toBeInTheDocument()
    expect(screen.getByText('17 rated')).toBeInTheDocument()
    expect(screen.getByText('9 unread')).toBeInTheDocument()
  })

  it('never shows 0★ for zero-rated creators', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 10, name: 'New Creator', roles: ['artist'] }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:10': { display_name: 'New Creator', average_rating: null, ratings_count: 0, upcoming_count: 2 },
    }))

    renderIdentity()
    await waitFor(() => expect(getSummaries).toHaveBeenCalled())

    await waitFor(() => expect(screen.getByText('0 rated')).toBeInTheDocument())
    expect(screen.queryByLabelText(/Average rating/)).not.toBeInTheDocument()
    expect(screen.queryByText('★ 0')).not.toBeInTheDocument()
    expect(screen.queryByText('0★')).not.toBeInTheDocument()
  })

  it('uses one bounded batch request for multiple stable creators, no per-creator fan-out', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [
        { creator_id: 1, name: 'A One', roles: ['writer'] },
        { creator_id: 2, name: 'B Two', roles: ['artist'] },
        { creator_id: 3, name: 'C Three', roles: ['inker'] },
      ],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:1': { display_name: 'A One', average_rating: 4.0, ratings_count: 5, upcoming_count: 1 },
      'creator:2': { display_name: 'B Two', average_rating: null, ratings_count: 0, upcoming_count: 0 },
      'creator:3': { display_name: 'C Three', average_rating: 3.5, ratings_count: 2, upcoming_count: 3 },
    }))

    renderIdentity()
    await waitFor(() => expect(getSummaries).toHaveBeenCalledTimes(1))
    const args = getSummaries.mock.calls[0][0]
    expect(args).toEqual(expect.arrayContaining(['creator:1', 'creator:2', 'creator:3']))
    expect(args.length).toBe(3)

    await waitFor(() => expect(screen.getAllByTestId('creator-row').length).toBe(3))
  })

  it('complete unread counts are shown only when upcoming_complete is true', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 77, name: 'Writer A', roles: ['writer'] }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:77': { display_name: 'Writer A', average_rating: 4.1, ratings_count: 4, upcoming_count: 9 },
    }, { upcoming_complete: true }))

    renderIdentity()
    await waitFor(() => expect(screen.getByText('9 unread')).toBeInTheDocument())
  })

  it('partial upcoming coverage shows 9+ unread with accessible label', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 88, name: 'Artist B', roles: ['penciler'] }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:88': { display_name: 'Artist B', average_rating: 4.2, ratings_count: 3, upcoming_count: 9 },
    }, { upcoming_complete: false }))

    renderIdentity()
    await waitFor(() => expect(screen.getByText('9+ unread')).toBeInTheDocument())
    expect(screen.getByLabelText('At least 9 unread, partial coverage')).toBeInTheDocument()
    expect(screen.queryByText('9 unread')).not.toBeInTheDocument()
  })

  it('partial rating coverage is represented honestly with + and accessible text', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 91, name: 'Writer C', roles: ['writer'] }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:91': { display_name: 'Writer C', average_rating: 3.8, ratings_count: 17, upcoming_count: 2 },
    }, { ratings_complete: false, upcoming_complete: true }))

    renderIdentity()
    await waitFor(() => expect(screen.getByLabelText(/partial coverage — lower bound/)).toBeInTheDocument())
    expect(screen.getByText('17+ rated')).toBeInTheDocument()
    expect(screen.getByLabelText(/Average rating 3\.8.*partial coverage/)).toBeInTheDocument()
  })

  it('creators without stable ID render name/roles without guessed analytics lookup', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [
        { creator_id: 100, name: 'Stable One', roles: ['writer'] },
        { creator_id: null, name: 'Unknown ID', roles: ['cover'] },
        { creator_id: null, name: 'No ID Field', roles: ['writer'] },
      ],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:100': { display_name: 'Stable One', average_rating: 4.5, ratings_count: 2, upcoming_count: 1 },
    }))

    renderIdentity()
    await waitFor(() => expect(getSummaries).toHaveBeenCalledWith(['creator:100']))
    expect(getSummaries.mock.calls[0][0]).not.toContain('creator:null')
    expect(getSummaries.mock.calls[0][0].length).toBe(1)

    await waitFor(() => expect(screen.getByText('Unknown ID')).toBeInTheDocument())
    expect(screen.getByText('No ID Field')).toBeInTheDocument()

    const rows = screen.getAllByTestId('creator-row')
    const unknownRow = rows.find((row) => within(row).queryByText('Unknown ID'))
    expect(unknownRow).toBeTruthy()
    expect(within(unknownRow!).queryByText(/rated/)).toBeNull()
    expect(within(unknownRow!).queryByText(/unread/)).toBeNull()
  })

  it('does not block creator names while analytics are loading', async () => {
    let resolveSummaries!: (value: Awaited<ReturnType<typeof creatorsApi.getSummaries>>) => void
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 200, name: 'Loading Creator', roles: ['writer'] }],
    }))
    getSummaries.mockImplementation(
      () => new Promise<Awaited<ReturnType<typeof creatorsApi.getSummaries>>>((resolve) => { resolveSummaries = resolve }),
    )

    renderIdentity()
    await waitFor(() => expect(screen.getByText('Loading Creator')).toBeInTheDocument())
    expect(screen.queryByText(/rated/)).not.toBeInTheDocument()

    resolveSummaries(summariesResponse({
      'creator:200': { display_name: 'Loading Creator', average_rating: 4.0, ratings_count: 1, upcoming_count: 0 },
    }))
    await waitFor(() => expect(screen.getByText('1 rated')).toBeInTheDocument())
  })

  it('retains creator list on analytics failure without error wall', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 300, name: 'Fail Creator', roles: ['writer'] }],
    }))
    getSummaries.mockRejectedValue(new Error('network failure'))

    renderIdentity()
    await waitFor(() => expect(screen.getByText('Fail Creator')).toBeInTheDocument())
    await waitFor(() => expect(getSummaries).toHaveBeenCalled())

    expect(screen.queryByText(/Failed to load/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Error/)).not.toBeInTheDocument()
    expect(screen.queryByText(/rated/)).not.toBeInTheDocument()
  })

  it('long creator names/roles/stats wrap without horizontal overflow', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{
        creator_id: 400,
        name: 'A Very Long Creator Name That Should Wrap And Not Cause Horizontal Overflow On Narrow Mobile Viewports',
        roles: ['writer', 'penciler', 'inker', 'colorist with a remarkably long role description'],
      }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:400': { display_name: 'Long Creator', average_rating: 4.321, ratings_count: 12, upcoming_count: 5 },
    }))

    const { container } = renderIdentity()
    await waitFor(() => expect(screen.getByText(/A Very Long Creator Name/)).toBeInTheDocument())

    const row = screen.getByTestId('creator-row')
    expect(row.className).toContain('flex-wrap')
    expect(row.className).toContain('break-words')
    expect(row.className).toContain('min-w-0')
    // Parent list should not have overflow-x clipping hidden approach that forces scroll
    const list = container.querySelector('#creators-list')
    expect(list).not.toBeNull()
    // No inline style that forces single line
    expect(row.className).not.toContain('whitespace-nowrap')
    expect(row.className).not.toContain('overflow-x-auto')
  })

  it('preserves rating precision without rounding away distinctions', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 500, name: 'Precise Creator', roles: ['writer'] }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:500': { display_name: 'Precise Creator', average_rating: 4.33, ratings_count: 3, upcoming_count: 0 },
    }))
    renderIdentity()
    await waitFor(() => expect(screen.getByText('4.33')).toBeInTheDocument())
  })

  it('does not render 0+ unread when upcoming partial but count is zero', async () => {
    getIntelligence.mockResolvedValue(baseIntelligence({
      creators: [{ creator_id: 600, name: 'Zero Upcoming', roles: ['writer'] }],
    }))
    getSummaries.mockResolvedValue(summariesResponse({
      'creator:600': { display_name: 'Zero Upcoming', average_rating: 4.0, ratings_count: 2, upcoming_count: 0 },
    }, { upcoming_complete: false }))
    renderIdentity()
    await waitFor(() => expect(screen.getByText('Zero Upcoming')).toBeInTheDocument())
    await waitFor(() => expect(getSummaries).toHaveBeenCalled())
    // Should not show 0+ unread (omit when zero and partial)
    expect(screen.queryByText('0+ unread')).not.toBeInTheDocument()
    expect(screen.queryByText('0 unread')).not.toBeInTheDocument()
  })
})
