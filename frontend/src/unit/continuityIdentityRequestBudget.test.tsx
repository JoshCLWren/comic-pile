import { StrictMode } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterAll, afterEach, beforeEach, describe, expect, it } from 'vitest'
import { AxiosHeaders, type AxiosAdapter } from 'axios'
import api from '../services/api'
import ContinuityPlansIndexPage from '../pages/ContinuityPlansIndexPage'
import ContinuityPlannerPage from '../pages/ContinuityPlannerPage'
import CrossoversPage from '../pages/CrossoversPage'
import IdentityInboxPage from '../pages/IdentityInboxPage'
import ReadingListEditorPage from '../pages/ReadingListEditorPage'
import ReadingPlanDetailPage from '../pages/ReadingPlanDetailPage'
import ReadingPlanEditRoute from '../pages/ReadingPlanEditRoute'
import { useIdentityInboxStatus } from '../hooks/useIdentityInbox'

/**
 * Route request budgets for the reading/continuity and identity surfaces
 * (issue #4503, parent #4499).
 *
 * Every assertion is an actual HTTP method + path + sorted query captured at
 * the axios transport adapter, after the app's real request interceptors. The
 * budgets below are the required requests for each route and UI action, so a
 * newly introduced needless call fails the test. Shared tag components still
 * issue one premature catalog read on plan views; that known cross-domain
 * waste is bounded to at most one occurrence here so it can be removed by its
 * owning change without rewriting these budgets.
 */

type RecordedRequest = {
  method: string
  path: string
  query: Record<string, string[]>
  url: string
}

const requests: RecordedRequest[] = []
const originalAdapter = api.defaults.adapter

type QueryValue = string | number | boolean
type QueryValues = Record<string, QueryValue | QueryValue[]>
type CanonicalQuery = Record<string, string[]>

function canonicalQuery(params: QueryValues | undefined) {
  const query: CanonicalQuery = {}
  if (!params) return query
  for (const key of Object.keys(params).sort()) {
    const value = params[key]
    if (value === undefined || value === null) continue
    const list = Array.isArray(value) ? value : [value]
    query[key] = list.map((entry) => String(entry)).sort()
  }
  return query
}

function canonicalUrl(method: string, path: string, query: CanonicalQuery): string {
  const pairs: string[] = []
  for (const key of Object.keys(query).sort()) {
    for (const value of query[key]) pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
  }
  return `${method} ${path}${pairs.length ? `?${pairs.join('&')}` : ''}`
}

function inboxPage(offset: number, limit: number) {
  const items = Array.from({ length: 25 }, (_, index) => {
    if (index === 0) return inboxItem(1, 'Mister Miracle', 501)
    if (index === 1) return inboxItem(2, 'The Ultimates', 502)
    if (index === 2) return inboxItem(3, 'New Gods', 503)
    return inboxItem(index + 1, `Series ${index + 1}`, 500 + index)
  }).slice(offset, offset + limit)
  return { items, total: 25, offset, limit }
}

function inboxItem(mappingId: number, threadTitle: string, identityId: number) {
  return {
    mapping_id: mappingId,
    issue_id: mappingId * 10,
    thread_id: mappingId * 100,
    thread_title: threadTitle,
    issue_number: '1',
    status: 'unresolved',
    provider: 'comicvine',
    source_entry_summary: `${threadTitle} #1`,
    why_stopped: 'No validated local candidate',
    candidates: [
      {
        external_identity_id: identityId,
        provider: 'comicvine',
        comicvine_id: String(identityId),
        external_url: null,
        metadata_json: {},
        status: 'candidate',
        confidence: 0.8,
        evidence_source: 'title_match',
        evidence_json: { evidence: ['title match'] },
        rejection_reason: null,
      },
    ],
    created_at: null,
    updated_at: null,
  }
}

function planReader(planId: number) {
  return {
    execution_mode: 'legacy',
    plan_id: planId,
    name: 'Plan Seven',
    ordering_mode: 'informational',
    progress: { total_issues: 0, read_issues: 0 },
    available_now: [],
    blocked_next: [],
    lanes: [],
    sources: [],
    release_sources: [],
    release_candidates: [],
  }
}

function planDetail(planId: number) {
  return {
    id: planId,
    user_id: 1,
    name: 'Plan Seven',
    ordering_mode: 'informational',
    lanes: [],
    nodes: [],
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  }
}

function responseFor(method: string, path: string, query: Record<string, string[]>) {
  if (method !== 'GET') return undefined
  if (path === '/api/v1/continuity-plans/') return []
  if (/^\/api\/v1\/continuity-plans\/\d+\/reader$/.test(path)) {
    return planReader(Number(path.split('/')[4]))
  }
  if (/^\/api\/v1\/continuity-plans\/\d+$/.test(path)) {
    return planDetail(Number(path.split('/')[4]))
  }
  if (path === '/api/v1/identity-inbox') {
    return inboxPage(Number(query.offset?.[0] ?? 0), Number(query.limit?.[0] ?? 20))
  }
  if (path === '/api/v1/threads/') return { threads: [], next_page_token: null, total: 0 }
  if (path === '/api/v1/reading-order-groups/') return []
  if (path === '/api/v1/custom-cbls') {
    return [{ id: 7, name: 'List Seven', description: null, mode: 'strict', issue_count: 0, updated_at: '2026-08-12T00:00:00Z' }]
  }
  if (/^\/api\/v1\/custom-cbls\/\d+$/.test(path)) {
    return {
      id: Number(path.split('/')[4]),
      name: 'List Seven',
      description: null,
      mode: 'strict',
      issue_count: 0,
      updated_at: '2026-08-12T00:00:00Z',
      user_id: 1,
      created_at: '2026-08-12T00:00:00Z',
      entries: [],
    }
  }
  if (path.startsWith('/api/v1/tags/effective/')) {
    return { target_type: 'ContinuityPlan', target_id: 7, direct_tags: [], effective_tags: [] }
  }
  if (path === '/api/v1/tags/') return { tags: [] }
  return []
}

const recorder: AxiosAdapter = async (config) => {
  const method = (config.method ?? 'get').toUpperCase()
  const path = `${config.baseURL ?? ''}${config.url ?? ''}`
  const query = canonicalQuery(config.params)
  requests.push({ method, path, query, url: canonicalUrl(method, path, query) })
  return {
    data: responseFor(method, path, query),
    status: 200,
    statusText: 'OK',
    headers: new AxiosHeaders(),
    config,
  }
}

const GET = (path: string, params: Record<string, string | number> = {}) =>
  canonicalUrl('GET', path, canonicalQuery(params))

const CONTINUITY_INDEX = GET('/api/v1/continuity-plans/')
const THREADS_PAGE = GET('/api/v1/threads/', { page_size: 100 })
const DEPENDENCY_GROUPS = GET('/api/v1/reading-order-groups/')
const PLAN_READER = GET('/api/v1/continuity-plans/7/reader')
const PLAN_DETAIL = GET('/api/v1/continuity-plans/7')
const PLAN_TAGS = GET('/api/v1/tags/effective/plan/7/')
const TAGS_CATALOG = GET('/api/v1/tags/')
const CUSTOM_LISTS = GET('/api/v1/custom-cbls')
const CUSTOM_LIST_SEVEN = GET('/api/v1/custom-cbls/7')
const INBOX_FIRST_PAGE = GET('/api/v1/identity-inbox', { offset: 0, limit: 20 })
const INBOX_SECOND_PAGE = GET('/api/v1/identity-inbox', { offset: 20, limit: 20 })
const INBOX_STATUS_PROBE = GET('/api/v1/identity-inbox', { offset: 0, limit: 1 })

beforeEach(() => {
  requests.length = 0
  api.defaults.adapter = recorder
})

afterEach(() => {
  api.defaults.adapter = originalAdapter
})

afterAll(() => {
  api.defaults.adapter = originalAdapter
})

function urls(): string[] {
  return requests.map((request) => request.url)
}

function count(url: string): number {
  return urls().filter((recorded) => recorded === url).length
}

function expectExact(expected: string[]) {
  const remaining = [...urls()]
  for (const url of expected) {
    const index = remaining.indexOf(url)
    expect(index, `missing required request ${url}\nrecorded: ${urls().join('\n')}`).toBeGreaterThanOrEqual(0)
    remaining.splice(index, 1)
  }
  // Shared tag catalog reads are bounded separately; nothing else may appear.
  expect(remaining.filter((url) => url !== TAGS_CATALOG), `unexpected requests\nrecorded: ${urls().join('\n')}`).toEqual([])
  expect(count(TAGS_CATALOG), `premature tag catalog reads\nrecorded: ${urls().join('\n')}`).toBeLessThanOrEqual(1)
}

function TagBadgeProbe() {
  useIdentityInboxStatus(true)
  return null
}

function renderRoute(entry: string, { withBadge = false, strict = false } = {}) {
  const tree = (
    <MemoryRouter initialEntries={[entry]}>
      {withBadge && <TagBadgeProbe />}
      <Routes>
        <Route path="/continuity-plans" element={<ContinuityPlansIndexPage />} />
        <Route path="/continuity-plans/new" element={<ContinuityPlannerPage />} />
        <Route path="/continuity-plans/events" element={<CrossoversPage />} />
        <Route path="/continuity-plans/:id" element={<ReadingPlanDetailPage />} />
        <Route path="/continuity-plans/:id/edit" element={<ReadingPlanEditRoute legacyEditor={<ContinuityPlannerPage />} />} />
        <Route path="/reading-lists/:id" element={<ReadingListEditorPage />} />
        <Route path="/identity-inbox" element={<IdentityInboxPage />} />
      </Routes>
    </MemoryRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

async function settle(minRequests: number) {
  await waitFor(() => expect(requests.length).toBeGreaterThanOrEqual(minRequests))
  await act(async () => {
    await Promise.resolve()
  })
  await act(async () => {
    await Promise.resolve()
  })
}

describe('/continuity-plans', () => {
  it('cold load issues one plans list request', async () => {
    renderRoute('/continuity-plans')
    await screen.findByRole('heading', { name: 'Reading Plans' })
    await settle(1)
    expectExact([CONTINUITY_INDEX])
  })

  it('warm remount reuses the cached list without another request', async () => {
    const first = renderRoute('/continuity-plans')
    await screen.findByRole('heading', { name: 'Reading Plans' })
    await settle(1)
    first.unmount()
    requests.length = 0

    renderRoute('/continuity-plans')
    await screen.findByRole('heading', { name: 'Reading Plans' })
    await act(async () => {
      await Promise.resolve()
    })
    expectExact([])
  })

  it('StrictMode double mount does not duplicate the list request', async () => {
    renderRoute('/continuity-plans', { strict: true })
    await screen.findByRole('heading', { name: 'Reading Plans' })
    await settle(1)
    expectExact([CONTINUITY_INDEX])
  })
})

describe('/continuity-plans/new', () => {
  it('cold load requests threads and dependency groups once', async () => {
    renderRoute('/continuity-plans/new')
    await settle(2)
    expectExact([THREADS_PAGE, DEPENDENCY_GROUPS])
  })

  it('StrictMode double mount does not duplicate planner collections', async () => {
    renderRoute('/continuity-plans/new', { strict: true })
    await settle(2)
    expectExact([THREADS_PAGE, DEPENDENCY_GROUPS])
  })
})

describe('/continuity-plans/events', () => {
  it('cold load requests crossover groups and threads once', async () => {
    renderRoute('/continuity-plans/events')
    await settle(2)
    expectExact([DEPENDENCY_GROUPS, THREADS_PAGE])
  })
})

describe('/continuity-plans/:id', () => {
  it('cold load requests the reader and plan tags once', async () => {
    renderRoute('/continuity-plans/7')
    await screen.findByRole('heading', { name: 'Plan Seven' })
    await settle(2)
    expectExact([PLAN_READER, PLAN_TAGS])
  })

  it('opening the closed tag editor does not add a duplicate catalog read', async () => {
    renderRoute('/continuity-plans/7')
    await screen.findByRole('heading', { name: 'Plan Seven' })
    await settle(2)
    requests.length = 0

    await userEvent.click(screen.getByRole('button', { name: 'Edit tags' }))
    await act(async () => {
      await Promise.resolve()
    })
    expectExact([])
  })

  it('focus and visibility restore do not refetch the plan', async () => {
    renderRoute('/continuity-plans/7')
    await screen.findByRole('heading', { name: 'Plan Seven' })
    await settle(2)
    requests.length = 0

    await act(async () => {
      window.dispatchEvent(new Event('focus'))
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expectExact([])
  })

  it('warm remount reuses both reader and tag caches', async () => {
    const first = renderRoute('/continuity-plans/7')
    await screen.findByRole('heading', { name: 'Plan Seven' })
    await settle(2)
    first.unmount()
    requests.length = 0

    renderRoute('/continuity-plans/7')
    await screen.findByRole('heading', { name: 'Plan Seven' })
    await act(async () => {
      await Promise.resolve()
    })
    expectExact([])
  })
})

describe('/continuity-plans/:id/edit', () => {
  it('cold legacy edit requests the plan, planner collections, and tags once', async () => {
    renderRoute('/continuity-plans/7/edit')
    await settle(4)
    expectExact([PLAN_READER, PLAN_DETAIL, THREADS_PAGE, DEPENDENCY_GROUPS, PLAN_TAGS])
  })
})

describe('/reading-lists/:id', () => {
  it('cold load requests the list index and the selected list once', async () => {
    renderRoute('/reading-lists/7')
    await screen.findByRole('heading', { name: 'Edit Reading List' })
    await settle(2)
    expectExact([CUSTOM_LISTS, CUSTOM_LIST_SEVEN])
  })
})

describe('/identity-inbox', () => {
  it('cold load uses the page list and suppresses the duplicate badge probe', async () => {
    renderRoute('/identity-inbox', { withBadge: true })
    await screen.findByText('Mister Miracle')
    await settle(1)
    expect(urls()).toEqual([INBOX_FIRST_PAGE])
    expect(count(INBOX_STATUS_PROBE)).toBe(0)
  })

  it('does not re-probe the total on a warm revisit to the inbox route', async () => {
    const first = renderRoute('/identity-inbox', { withBadge: true })
    await screen.findByText('Mister Miracle')
    await settle(1)
    first.unmount()
    requests.length = 0

    renderRoute('/identity-inbox', { withBadge: true })
    await screen.findByText('Mister Miracle')
    await act(async () => {
      await Promise.resolve()
    })
    expect(count(INBOX_STATUS_PROBE)).toBe(0)
  })

  it('pagination requests the next page once and reuses page one on the way back', async () => {
    renderRoute('/identity-inbox', { withBadge: true })
    await screen.findByText('Mister Miracle')
    await settle(1)
    requests.length = 0

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle(1)
    expectExact([INBOX_SECOND_PAGE])

    requests.length = 0
    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await act(async () => {
      await Promise.resolve()
    })
    expectExact([])
  })

  it('confirming a candidate refetches the current page without a badge probe', async () => {
    renderRoute('/identity-inbox', { withBadge: true })
    await screen.findByText('Mister Miracle')
    await settle(1)
    requests.length = 0

    await userEvent.click(screen.getByRole('button', { name: /Mister Miracle/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(count(INBOX_FIRST_PAGE)).toBe(1))
    expect(urls()).toContain('POST /api/v1/identity-inbox/1/confirm')
    expect(count(INBOX_STATUS_PROBE)).toBe(0)
  })

  it('focus and visibility restore do not refetch the inbox', async () => {
    renderRoute('/identity-inbox', { withBadge: true })
    await screen.findByText('Mister Miracle')
    await settle(1)
    requests.length = 0

    await act(async () => {
      window.dispatchEvent(new Event('focus'))
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(urls()).toEqual([])
  })
})
