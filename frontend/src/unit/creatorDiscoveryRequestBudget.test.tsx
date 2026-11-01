import { StrictMode } from 'react'
import axios, {
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import CreatorsPage from '../pages/CreatorsPage'
import CreatorDetailPage from '../pages/CreatorDetailPage'
import CreatorComparisonPage from '../pages/CreatorComparisonPage'
import CblBrowserPage from '../pages/CblBrowserPage'
import api from '../services/api'
import type { CrossoverApiDeps } from '../hooks/useCrossovers'
import { useCreatorsList, CREATOR_LIST_PAGE_SIZE } from '../hooks/useCreatorsList'
import type { CreatorListParams, CreatorListResponse } from '../services/api-creators'

/**
 * Recording adapter at the same terminal transport boundary used by #4504's
 * network ledger: real axios request/response interceptors still run, and the
 * recorded identity includes the client `/api` base path plus sorted query.
 */
interface RecordedRequest {
  method: string
  path: string
  query: Record<string, string[]>
  url: string
  sequence: number
  action: string
}

interface LedgerResponse {
  status?: number
  data?: unknown
}

type LedgerHandler = (request: RecordedRequest) => LedgerResponse | undefined

interface DomainLedger {
  requests: RecordedRequest[]
  unhandled: string[]
  beginAction: (action: string) => void
}

const COVERAGE = {
  rated_issues_total: 0,
  rated_issues_with_creator_metadata: 0,
  ratings_complete: true,
  read_unrated_issues_total: 0,
  read_unrated_issues_with_creator_metadata: 0,
  read_unrated_complete: true,
  unread_issues_total: 0,
  unread_issues_with_creator_metadata: 0,
  upcoming_complete: true,
}

function creatorDetailFixture() {
  return {
    summary: {
      canonical_creator_key: 'creator:7',
      display_name: 'Test Creator',
      normalized_roles: ['writer'],
      average_rating: null,
      ratings_count: 0,
      read_unrated_count: 0,
      upcoming_count: 0,
    },
    coverage: COVERAGE,
    role_stats: [],
    series_groups: [],
    series_groups_total: 0,
    series_groups_complete: true,
    rated_issues: [],
    rated_population_scope: 'headline_roles_only' as const,
    headline_roles: ['writer'],
    read_unrated_issues: [],
    upcoming_issues: [],
    next_cursor: null,
    rating_distribution: null,
    insights: null,
  }
}

function teamChemistryFixture() {
  return {
    pairs: [],
    pairs_total: 0,
    min_shared_team_sample: 3,
    max_ranked_pairs: 10,
    coverage: { rated_issues_total: 0, rated_issues_with_creator_metadata: 0, ratings_complete: true },
  }
}

function comparisonFixture() {
  return {
    comparisons: {},
    coverage: COVERAGE,
    insufficient_data_keys: [],
  }
}

function cblBrowseFixture() {
  return {
    scope: 'folder' as const,
    folder: '',
    query: null,
    breadcrumbs: [],
    folders: [],
    items: [],
    page: 1,
    page_size: 50,
    total: 0,
    total_pages: 0,
    has_next: false,
    has_previous: false,
  }
}

function parseUrl(rawUrl: string): Pick<RecordedRequest, 'path' | 'query'> {
  const parsed = new URL(rawUrl, 'http://comic-pile.test')
  const query: Record<string, string[]> = {}
  parsed.searchParams.forEach((value, key) => {
    query[key] = [...(query[key] ?? []), value]
  })
  return { path: parsed.pathname, query }
}

/** Canonicalise query order so equivalent parameter orderings share one row. */
function canonicalQuery(query: Record<string, string[]>): string {
  return Object.keys(query)
    .sort()
    .map((key) => [...query[key]].sort().map((value) => `${key}=${encodeURIComponent(value)}`).join('&'))
    .filter(Boolean)
    .join('&')
}

function canonicalRequest(method: string, path: string, query: Record<string, string[]>): string {
  const search = canonicalQuery(query)
  return `${method.toUpperCase()} ${path}${search ? `?${search}` : ''}`
}

function buildResponse(config: InternalAxiosRequestConfig, response: LedgerResponse): AxiosResponse {
  return {
    data: response.data ?? {},
    status: response.status ?? 200,
    statusText: 'OK',
    headers: {},
    config,
    request: {},
  }
}

const ledger: DomainLedger = { requests: [], unhandled: [], beginAction: () => {} }

function installDomainLedger(handlers: Record<string, LedgerHandler>, initialAction: string) {
  ledger.requests = []
  ledger.unhandled = []
  let action = initialAction
  ledger.beginAction = (next) => {
    action = next
  }
  let sequence = 0

  const adapter: AxiosAdapter = async (config) => {
    const method = (config.method ?? 'get').toUpperCase()
    const { path, query } = parseUrl(axios.getUri(config))
    sequence += 1
    const request: RecordedRequest = {
      method,
      path,
      query,
      url: canonicalRequest(method, path, query),
      sequence,
      action,
    }
    ledger.requests.push(request)
    const response = handlers[`${method} ${path}`]?.(request)
    if (!response) {
      const key = `${method} ${path}`
      if (!ledger.unhandled.includes(key)) ledger.unhandled.push(key)
      throw new Error(`Unhandled domain-ledger request: ${key}`)
    }
    return buildResponse(config, response)
  }

  api.defaults.adapter = adapter
}

function makeCreatorPage(overrides: Partial<CreatorListResponse> = {}): CreatorListResponse {
  return {
    items: [],
    total: 0,
    limit: CREATOR_LIST_PAGE_SIZE,
    offset: 0,
    coverage: COVERAGE,
    ...overrides,
  }
}

const creatorHandlers = {
  'GET /api/v1/creators': () => ({ data: makeCreatorPage() }),
  'GET /api/v1/creators/team-chemistry': () => ({ data: teamChemistryFixture() }),
  'GET /api/v1/creators/compare': () => ({ data: comparisonFixture() }),
  'GET /api/v1/creators/creator%3A7': () => ({ data: creatorDetailFixture() }),
  'GET /api/v1/issue-identity/cbl-sources/browse': () => ({ data: cblBrowseFixture() }),
} satisfies Record<string, LedgerHandler>

function teamChemistryRequests() {
  return ledger.requests.filter(
    (request) => request.url === 'GET /api/v1/creators/team-chemistry',
  )
}

function renderCreatorDetail(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/creators/:creatorKey" element={<CreatorDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  expect(ledger.unhandled).toEqual([])
})

describe('crossovers request budget', () => {
  const groupsApi = {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    delete: vi.fn(),
    addMember: vi.fn(),
    addIssueRange: vi.fn(),
    removeMember: vi.fn(),
  }
  const threadsApi = { list: vi.fn() }
  const issuesApi = { list: vi.fn() }
  const crossoverApi: CrossoverApiDeps = { groups: groupsApi, threads: threadsApi, issues: issuesApi }

  const annihilation = {
    id: 7,
    name: 'Annihilation',
    created_at: '2026-08-06T00:00:00Z',
    memberships: [{ id: 1, issue_id: 11, thread_id: null, series_title: 'Nova', issue_number: '4' }],
  }

  beforeEach(() => {
    vi.clearAllMocks()
    groupsApi.list.mockResolvedValue([annihilation])
    threadsApi.list.mockResolvedValue({ threads: [], next_page_token: null, active_count: 0 })
  })

  function renderCrossovers(entry: string) {
    return render(
      <MemoryRouter initialEntries={[entry]}>
        <CrossoversPage api={crossoverApi} />
      </MemoryRouter>,
    )
  }

  it('does not enumerate every thread on initial open', async () => {
    renderCrossovers('/continuity-plans/events')

    expect(await screen.findByRole('button', { name: /Annihilation/ })).toBeInTheDocument()
    expect(threadsApi.list).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /Annihilation/ }))

    await waitFor(() => expect(threadsApi.list).toHaveBeenCalledTimes(1))
    expect(threadsApi.list).toHaveBeenCalledWith({ page_size: 100 }, null)
  })

  it('enumerates threads once when a deep link opens a crossover', async () => {
    renderCrossovers('/continuity-plans/events?group=7')

    expect(await screen.findByText('Nova #4')).toBeInTheDocument()
    await waitFor(() => expect(threadsApi.list).toHaveBeenCalledTimes(1))
    expect(groupsApi.list).toHaveBeenCalledTimes(1)
  })

  it('keeps the cold read single under StrictMode', async () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/continuity-plans/events']}>
          <CrossoversPage api={crossoverApi} />
        </MemoryRouter>
      </StrictMode>,
    )

    expect(await screen.findByRole('button', { name: /Annihilation/ })).toBeInTheDocument()
    await waitFor(() => expect(groupsApi.list).toHaveBeenCalledTimes(1))
    expect(threadsApi.list).not.toHaveBeenCalled()
  })
})

describe('creator detail request budget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('defers the expensive team-chemistry read until the disclosure is opened', async () => {
    installDomainLedger(creatorHandlers, 'cold creator detail')
    renderCreatorDetail('/creators/creator:7')

    expect(await screen.findByRole('heading', { name: 'Test Creator' })).toBeInTheDocument()
    expect(ledger.requests.map((request) => request.url)).toEqual([
      'GET /api/v1/creators/creator%3A7?limit=50',
    ])
    expect(teamChemistryRequests()).toHaveLength(0)

    ledger.beginAction('open team chemistry')
    fireEvent.click(screen.getByRole('button', { name: 'Show team chemistry' }))

    await waitFor(() => expect(teamChemistryRequests()).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Hide team chemistry' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('does not request creator detail or team chemistry for a malformed key', async () => {
    installDomainLedger(creatorHandlers, 'malformed creator key')
    renderCreatorDetail('/creators/Stan%20Lee')

    expect(await screen.findByRole('heading', { name: 'Creator not found' })).toBeInTheDocument()
    expect(ledger.requests).toHaveLength(0)
  })
})

describe('creator search cancellation', () => {
  it('aborts a superseded creator-list request instead of leaving it in flight', async () => {
    const calls: Array<{
      params: CreatorListParams
      config?: { signal?: AbortSignal }
    }> = []
    let resolveFirst: ((page: CreatorListResponse) => void) | undefined

    const listApi = {
      getList: (params: CreatorListParams = {}, config?: { signal?: AbortSignal }) => {
        calls.push({ params, config })
        if (params.search === 'ro') {
          return new Promise<CreatorListResponse>((resolve) => {
            resolveFirst = resolve
          })
        }
        return Promise.resolve(makeCreatorPage())
      },
    }

    const { rerender } = renderHook(
      ({ search }: { search: string }) => useCreatorsList({ search }, listApi),
      { initialProps: { search: 'ro' } },
    )

    await waitFor(() => expect(calls).toHaveLength(1))
    const firstSignal = calls[0]?.config?.signal
    expect(firstSignal).toBeInstanceOf(AbortSignal)
    expect(firstSignal?.aborted).toBe(false)

    rerender({ search: 'rob' })

    await waitFor(() => expect(calls).toHaveLength(2))
    await waitFor(() => expect(firstSignal?.aborted).toBe(true))
    expect(calls[1]?.config?.signal?.aborted).toBe(false)

    resolveFirst?.(makeCreatorPage())
  })
})

describe('creator request lifecycle', () => {
  it('does not duplicate the cold creator read across StrictMode or a warm remount', async () => {
    installDomainLedger(creatorHandlers, 'cold creators browse')
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
    })
    const element = (
      <QueryClientProvider client={client}>
        <StrictMode>
          <MemoryRouter initialEntries={['/creators']}>
            <Routes>
              <Route path="/creators" element={<CreatorsPage />} />
            </Routes>
          </MemoryRouter>
        </StrictMode>
      </QueryClientProvider>
    )

    const first = render(element)
    expect(await screen.findByRole('heading', { name: 'Creators you rated' })).toBeInTheDocument()
    await waitFor(() => expect(ledger.requests).toHaveLength(1))
    expect(ledger.requests[0]?.url).toBe('GET /api/v1/creators?limit=20&sort=name')
    // #4500 integration: the library-wide team-chemistry read stays inert on
    // the default browse view until its own disclosure is opened.
    expect(teamChemistryRequests()).toHaveLength(0)

    ledger.beginAction('unchanged rerender')
    first.rerender(element)
    expect(ledger.requests).toHaveLength(1)

    first.unmount()
    ledger.beginAction('warm remount')
    render(element)
    expect(await screen.findByRole('heading', { name: 'Creators you rated' })).toBeInTheDocument()
    expect(ledger.requests).toHaveLength(1)
  })
})

describe('comparison and CBL discovery request budgets', () => {
  it('requests the deduped, sorted comparison key set exactly once', async () => {
    installDomainLedger(creatorHandlers, 'cold creator comparison')
    render(
      <MemoryRouter initialEntries={['/creators/compare?keys=creator:7,creator:12']}>
        <Routes>
          <Route path="/creators/compare" element={<CreatorComparisonPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(ledger.requests).toHaveLength(1))
    expect(ledger.requests[0]?.url).toBe(
      'GET /api/v1/creators/compare?keys=creator%3A12%2Ccreator%3A7',
    )
  })

  it('browses the CBL root once on cold open without detail, preview, or graph reads', async () => {
    installDomainLedger(creatorHandlers, 'cold CBL source browser')
    render(
      <MemoryRouter initialEntries={['/cbl-sources']}>
        <Routes>
          <Route path="/cbl-sources" element={<CblBrowserPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'CBL Sources' })).toBeInTheDocument()
    await waitFor(() => expect(ledger.requests).toHaveLength(1))
    expect(ledger.requests[0]?.url).toBe(
      'GET /api/v1/issue-identity/cbl-sources/browse?folder=&page=1&page_size=50',
    )
  })

  it('records the actual axios crossover rows before and after expansion', async () => {
    installDomainLedger(
      {
        'GET /api/v1/reading-order-groups/': () => ({
          data: [
            {
              id: 7,
              name: 'Annihilation',
              created_at: '2026-08-06T00:00:00Z',
              memberships: [
                { id: 1, issue_id: 11, thread_id: null, series_title: 'Nova', issue_number: '4' },
              ],
            },
          ],
        }),
        'GET /api/v1/threads/': () => ({
          data: { threads: [], next_page_token: null, active_count: 0 },
        }),
      },
      'cold crossovers',
    )
    render(
      <MemoryRouter initialEntries={['/continuity-plans/events']}>
        <Routes>
          <Route path="/continuity-plans/events" element={<CrossoversPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('button', { name: /Annihilation/ })).toBeInTheDocument()
    await waitFor(() => expect(ledger.requests).toHaveLength(1))
    expect(ledger.requests[0]?.url).toBe('GET /api/v1/reading-order-groups/')

    ledger.beginAction('expand crossover')
    fireEvent.click(screen.getByRole('button', { name: /Annihilation/ }))

    await waitFor(() => expect(ledger.requests).toHaveLength(2))
    expect(ledger.requests[1]?.url).toBe('GET /api/v1/threads/?page_size=100')
  })
})
