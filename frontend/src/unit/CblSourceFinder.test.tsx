import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CblComicFinder, CblReadingListFinder } from '../components/CblSourceFinder'
import type {
  CBLComicvineOccurrence,
  CBLReadingListCandidatesResponse,
  CBLSourceComparisonMatch,
} from '../services/api-cbl-sources'

const mocks = vi.hoisted(() => ({
  compare: vi.fn(),
  findByComicvineIssue: vi.fn(),
  readingListCandidates: vi.fn(),
  getIssueIdentity: vi.fn(),
}))

vi.mock('../services/api-cbl-sources', () => ({
  cblSourcesApi: {
    compare: mocks.compare,
    findByComicvineIssue: mocks.findByComicvineIssue,
    readingListCandidates: mocks.readingListCandidates,
  },
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    getIssueIdentity: mocks.getIssueIdentity,
  },
}))

function candidate(
  overrides: Partial<CBLSourceComparisonMatch> = {},
): CBLSourceComparisonMatch {
  return {
    list_id: 7,
    list_name: 'Ultimate Reading Order',
    source_path: 'Marvel/Ultimate.cbl',
    source_repository: 'JoshCLWren/CBL-ReadingLists',
    source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
    revision_sha: 'abcdef1234567890',
    declared_issue_count: 3,
    entries_total: 3,
    distinct_source_issues: 3,
    matched_input_count: 1,
    input_total: 1,
    matched_occurrence_count: 1,
    duplicate_match_count: 0,
    source_only_issue_count: 2,
    input_coverage_percentage: 100,
    source_coverage_percentage: 33,
    order_status: 'not_comparable',
    order_pair_count: 0,
    order_disagreement_count: 0,
    matched_input_ids: ['4000-1'],
    missing_input_ids: [],
    score: 70,
    ...overrides,
  }
}

function occurrence(
  overrides: Partial<CBLComicvineOccurrence> = {},
): CBLComicvineOccurrence {
  return {
    list_id: 7,
    list_name: 'Ultimate Reading Order',
    source_path: 'Marvel/Ultimate.cbl',
    source_repository: 'JoshCLWren/CBL-ReadingLists',
    source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
    revision_sha: 'abcdef1234567890',
    position: 1,
    series_name: 'Ultimate Spider-Man',
    issue_number: '1',
    volume_year: null,
    publication_year: null,
    comicvine_issue_id: '4000-1',
    comicvine_volume_id: null,
    ...overrides,
  }
}

function identityResponse(confirmedIds: string[]) {
  return {
    issue_id: 5,
    thread_id: 3,
    thread_title: 'Ultimate Spider-Man',
    has_confirmed_identity: confirmedIds.length > 0,
    comicvine_issue_id: confirmedIds.length === 1 ? confirmedIds[0] : null,
    confirmed_mappings: confirmedIds.map((comicvineId, index) => ({
      external_identity_id: index + 1,
      provider: 'comicvine',
      comicvine_id: comicvineId,
      status: 'confirmed',
      confidence: null,
      evidence_source: 'e2e-fixture',
      created_at: null,
    })),
    candidate_mappings: [],
    has_unresolved: false,
  }
}

function readingListResponse(
  overrides: Partial<CBLReadingListCandidatesResponse> = {},
): CBLReadingListCandidatesResponse {
  return {
    list_id: 9,
    list_name: 'My Reading List',
    input_entry_count: 3,
    input_confirmed_total: 1,
    input_missing_count: 1,
    input_conflict_count: 1,
    input_ids: ['4000-1'],
    entries: [],
    candidates_total: 1,
    candidates: [candidate()],
    ...overrides,
  }
}

function renderFinder(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  mocks.compare.mockResolvedValue({
    comicvine_issue_ids: ['4000-1'],
    input_total: 1,
    candidates_total: 2,
    candidates: [candidate(), candidate({ list_id: 8, list_name: 'New Marvel Order' })],
  })
  mocks.findByComicvineIssue.mockResolvedValue({
    comicvine_issue_id: '4000-1',
    occurrences_total: 2,
    lists_total: 2,
    occurrences_offset: 0,
    occurrences_limit: 50,
    occurrences: [
      occurrence(),
      occurrence({ list_id: 8, list_name: 'New Marvel Order', position: 4 }),
    ],
  })
})

describe('CblComicFinder', () => {
  it('lists every CBL source that holds the comic’s confirmed Comic Vine issue', async () => {
    const user = userEvent.setup()
    mocks.getIssueIdentity.mockResolvedValue(identityResponse(['4000-1']))

    renderFinder(
      <CblComicFinder
        issueId={5}
        comicLabel="Ultimate Spider-Man #1"
        backTo="/thread/3"
        backLabel="Series"
        testIdPrefix="cbl-comic"
      />,
    )
    await user.click(screen.getByTestId('cbl-comic-open'))

    await waitFor(() => {
      expect(screen.getByTestId('cbl-comic-7')).toBeInTheDocument()
    })
    expect(screen.getByTestId('cbl-comic-8')).toBeInTheDocument()
    expect(mocks.compare).toHaveBeenCalledWith(['4000-1'])
    expect(mocks.findByComicvineIssue).toHaveBeenCalledWith('4000-1')
    expect(screen.getByTestId('cbl-comic-occurrences')).toHaveTextContent(
      '2 source positions in 2 source lists hold this exact issue.',
    )
    expect(screen.getByTestId('cbl-comic-occurrence-7')).toHaveTextContent('position 1')
  })

  it('links each candidate to its source detail', async () => {
    const user = userEvent.setup()
    mocks.getIssueIdentity.mockResolvedValue(identityResponse(['4000-1']))

    renderFinder(
      <CblComicFinder
        issueId={5}
        comicLabel="Ultimate Spider-Man #1"
        backTo="/thread/3"
        backLabel="Series"
        testIdPrefix="cbl-comic"
      />,
    )
    await user.click(screen.getByTestId('cbl-comic-open'))

    const firstCandidate = await screen.findByTestId('cbl-comic-7')
    const sourceLink = within(firstCandidate).getByRole('link', { name: /View source list/ })
    expect(sourceLink).toHaveAttribute('href', '/cbl-sources?list=7')
  })

  it('reports the identity gap instead of claiming that no CBL holds the comic', async () => {
    const user = userEvent.setup()
    mocks.getIssueIdentity.mockResolvedValue(identityResponse([]))

    renderFinder(
      <CblComicFinder
        issueId={5}
        comicLabel="Ultimate Spider-Man #1"
        backTo="/thread/3"
        backLabel="Series"
        testIdPrefix="cbl-comic"
      />,
    )
    await user.click(screen.getByTestId('cbl-comic-open'))

    const gap = await screen.findByTestId('cbl-comic-identity-gap')
    expect(gap).toHaveTextContent(
      'ComicPile has no confirmed Comic Vine ID for Ultimate Spider-Man #1',
    )
    expect(mocks.compare).not.toHaveBeenCalled()
    expect(
      screen.queryByText("No CBL source contains this comic's exact Comic Vine ID."),
    ).not.toBeInTheDocument()
  })

  it('reports conflicting confirmed identities instead of guessing one', async () => {
    const user = userEvent.setup()
    mocks.getIssueIdentity.mockResolvedValue(identityResponse(['4000-1', '4000-2']))

    renderFinder(
      <CblComicFinder
        issueId={5}
        comicLabel="Ultimate Spider-Man #1"
        backTo="/thread/3"
        backLabel="Series"
        testIdPrefix="cbl-comic"
      />,
    )
    await user.click(screen.getByTestId('cbl-comic-open'))

    expect(await screen.findByTestId('cbl-comic-identity-conflict')).toHaveTextContent(
      '2 conflicting confirmed Comic Vine IDs',
    )
    expect(mocks.compare).not.toHaveBeenCalled()
  })
})

describe('CblReadingListFinder', () => {
  it('measures coverage from the confirmed comics only', async () => {
    const user = userEvent.setup()
    mocks.readingListCandidates.mockResolvedValue(readingListResponse())

    renderFinder(
      <CblReadingListFinder
        listId={9}
        listName="My Reading List"
        backTo="/continuity-plans/4"
        backLabel="Reading Plans"
        testIdPrefix="cbl-reading-list"
      />,
    )
    await user.click(screen.getByTestId('cbl-reading-list-open'))

    await waitFor(() => {
      expect(screen.getByTestId('cbl-reading-list-7')).toBeInTheDocument()
    })
    expect(mocks.readingListCandidates).toHaveBeenCalledWith(9)
    // One of three entries is confirmed, so coverage is measured against one.
    expect(screen.getByText('Coverage: 1 of 1 comics (100%)')).toBeInTheDocument()
    expect(screen.getByTestId('cbl-reading-list-gap-summary')).toHaveTextContent(
      'Coverage uses the 1 confirmed Comic Vine issue',
    )
    expect(screen.getByTestId('cbl-reading-list-gap-summary')).toHaveTextContent(
      '1 entry has no confirmed ID and 1 entry has conflicting IDs.',
    )
  })

  it('shows the identity gaps instead of a no-match message when nothing is confirmed', async () => {
    const user = userEvent.setup()
    mocks.readingListCandidates.mockResolvedValue(
      readingListResponse({
        input_confirmed_total: 0,
        input_missing_count: 2,
        input_conflict_count: 1,
        input_ids: [],
        candidates: [],
        candidates_total: 0,
      }),
    )

    renderFinder(
      <CblReadingListFinder
        listId={9}
        listName="My Reading List"
        backTo="/continuity-plans/4"
        backLabel="Reading Plans"
        testIdPrefix="cbl-reading-list"
      />,
    )
    await user.click(screen.getByTestId('cbl-reading-list-open'))

    const gaps = await screen.findByTestId('cbl-reading-list-identity-gaps')
    expect(gaps).toHaveTextContent("None of My Reading List's 3 entries has exactly one")
    expect(gaps).toHaveTextContent('(2 missing, 1 conflicting)')
    expect(
      screen.queryByText("No CBL source covers this list's confirmed comics."),
    ).not.toBeInTheDocument()
  })

  it('links each candidate source to its source detail', async () => {
    const user = userEvent.setup()
    mocks.readingListCandidates.mockResolvedValue(readingListResponse())

    renderFinder(
      <CblReadingListFinder
        listId={9}
        listName="My Reading List"
        backTo="/continuity-plans/4"
        backLabel="Reading Plans"
        testIdPrefix="cbl-reading-list"
      />,
    )
    await user.click(screen.getByTestId('cbl-reading-list-open'))

    const candidateRow = await screen.findByTestId('cbl-reading-list-7')
    const sourceLink = within(candidateRow).getByRole('link', { name: /View source list/ })
    expect(sourceLink).toHaveAttribute('href', '/cbl-sources?list=7')
  })
})
