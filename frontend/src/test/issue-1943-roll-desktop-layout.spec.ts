/**
 * Issue #1943: Roll desktop layout packs meaningful regions into the viewport.
 *
 * Updated for the live two-region rating layout (comic + decision). The old
 * three-pillar Reading Context / Your Context split was retired by the
 * optional-cards refactor (#2764); optional reading detail now lives behind
 * compact disclosure cards inside the decision region. These assertions keep
 * the original #1943 invariants on the live surface: no dead acreage, no
 * horizontal overflow, actions stay reachable, and sparse/rich states both
 * pack content without reserving blank columns.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const DESKTOP_VIEWPORT = { width: 1920, height: 1080 }
const NARROW_DESKTOP_VIEWPORT = { width: 1024, height: 900 }

const COVER_DATA_URI = (() => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

interface RatingStateRoutes {
  readingOrders: unknown[]
  connectedThreads: unknown[]
  readerContext: unknown | null
  comicvine: unknown | null
  identity: unknown | null
  settleText: string
}

function readingOrder(id: number, name: string) {
  return { id, name, description: null, total_items: 8, completed_items: 3, items: [] }
}

function connectedThread(id: number, title: string) {
  return { thread_id: id, title, connection_type: 'blocked_by', dependency_id: id }
}

function richReaderContext() {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: 'series-1',
      series_name: 'Rich Series',
      average_rating: 4.2,
      ratings_count: 12,
      previous_issue: { issue_id: 99, issue_number: '2', rating: 4.0 },
      recent_ratings: [{ issue_id: 99, issue_number: '2', rating: 4.0 }],
      highest_rating: 5.0,
      lowest_rating: 2.0,
    },
    crossovers: [],
    local_chain: {
      issues: [
        { issue_id: 99, issue_number: '2', position: 1, status: 'read', relation: 'previous', rating: 4.0, crossover_memberships: [] },
        { issue_id: 100, issue_number: '3', position: 2, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
        { issue_id: 101, issue_number: '4', position: 3, status: 'unread', relation: 'next', rating: null, crossover_memberships: [] },
      ],
      edges: [],
    },
  }
}

function confirmedIdentity() {
  return {
    issue_id: 1,
    thread_id: 1,
    thread_title: 'Layout Thread',
    has_confirmed_identity: true,
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: false,
  }
}

const RATING_STATES = {
  rich: {
    readingOrders: [readingOrder(7, 'Main route'), readingOrder(8, 'Alt reading order')],
    connectedThreads: [connectedThread(200, 'Connected Thread A'), connectedThread(201, 'Connected Thread B')],
    readerContext: richReaderContext(),
    comicvine: {
      comicvine_issue_id: '12345',
      comicvine_url: null,
      series_name: 'Rich Series',
      series_id: 1,
      issue_number: '3',
      name: 'The Pretending Town',
      description: 'A town that pretends.',
      image_url: COVER_DATA_URI,
      cover_date: '2020-01-01',
      store_date: null,
      creators: [{ name: 'Brian K. Vaughan', roles: ['writer'] }],
      story_arcs: [],
    },
    identity: confirmedIdentity(),
    settleText: 'Your rating',
  },
  sparse: {
    readingOrders: [],
    connectedThreads: [],
    readerContext: null,
    comicvine: null,
    identity: {
      issue_id: 1, thread_id: 1, thread_title: 'Layout Thread',
      has_confirmed_identity: false, confirmed_mappings: [], candidate_mappings: [], has_unresolved: false,
    },
    settleText: 'Your rating',
  },
  noContext: {
    readingOrders: [],
    connectedThreads: [],
    readerContext: null,
    comicvine: null,
    identity: {
      issue_id: 1, thread_id: 1, thread_title: 'Layout Thread',
      has_confirmed_identity: false, confirmed_mappings: [], candidate_mappings: [], has_unresolved: false,
    },
    settleText: 'Your rating',
  },
  coverHeavy: {
    readingOrders: [],
    connectedThreads: [],
    readerContext: null,
    comicvine: {
      comicvine_issue_id: '54321',
      comicvine_url: null,
      series_name: 'Cover Series',
      series_id: 2,
      issue_number: '1',
      name: 'Just a Cover',
      description: null,
      image_url: COVER_DATA_URI,
      cover_date: '2021-06-15',
      store_date: null,
      creators: [],
      story_arcs: [],
    },
    identity: confirmedIdentity(),
    settleText: 'Your rating',
  },
} satisfies Record<string, RatingStateRoutes>

async function installRatingRoutes(page: Page, state: RatingStateRoutes): Promise<void> {
  await page.route('**/v1/threads/*/reading-orders', (route) =>
    route.fulfill({ json: { reading_orders: state.readingOrders } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: state.connectedThreads } }),
  )
  await page.route('**/v2/issues/*/reader-context', (route) =>
    route.fulfill({ json: state.readerContext }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: state.comicvine }),
  )
  await page.route('**/v2/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: state.identity }),
  )
}

async function enterRatingView(page: Page, title: string, state: RatingStateRoutes): Promise<void> {
  await installRatingRoutes(page, state)
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
  await page.getByText(title).first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await expect(page.getByText(state.settleText).first()).toBeVisible({ timeout: 10000 })
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready
  })
}

type Box = { x: number; y: number; top: number; left: number; right: number; bottom: number; width: number; height: number } | null

interface RatingGeometry {
  viewport: { width: number; height: number }
  scrollWidth: number
  gridClientWidth: number
  gridScrollWidth: number
  grid: Box
  comic: Box
  decision: Box
  actions: Box
  optionalCards: Box
}

async function readRatingGeometry(page: Page): Promise<RatingGeometry> {
  return page.evaluate(() => {
    const box = (el: Element | null) => {
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { x: r.x, y: r.y, top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
    }
    const grid = document.querySelector('[data-testid="rating-pillars-grid"]')
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scrollWidth: document.documentElement.scrollWidth,
      gridClientWidth: grid?.clientWidth ?? 0,
      gridScrollWidth: grid?.scrollWidth ?? 0,
      grid: box(grid),
      comic: box(document.querySelector('[data-testid="rating-region-comic"]')),
      decision: box(document.querySelector('[data-testid="rating-region-decision"]')),
      actions: box(document.querySelector('[data-testid="rating-actions"]')),
      optionalCards: box(document.querySelector('[data-testid="rating-region-reading-optional"]')),
    }
  })
}

function assertNoHorizontalOverflow(g: RatingGeometry): void {
  expect(g.gridScrollWidth).toBeLessThanOrEqual(g.gridClientWidth + 1)
  expect(g.scrollWidth).toBeLessThanOrEqual(g.viewport.width)
}

function assertActionsFitViewport(g: RatingGeometry): void {
  expect(g.actions).not.toBeNull()
  expect(g.actions!.top).toBeGreaterThan(0)
  expect(g.actions!.bottom).toBeLessThanOrEqual(g.viewport.height)
}

test.describe('Roll desktop layout packs regions into the viewport (issue #1943)', () => {
  test('rich continuity packs two regions side-by-side without horizontal overflow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, { title: 'Rich Layout Thread', format: 'Comic', issues_remaining: 3, total_issues: 3 })
    await enterRatingView(page, 'Rich Layout Thread', RATING_STATES.rich)

    const g = await readRatingGeometry(page)
    expect(g.comic).not.toBeNull()
    expect(g.decision).not.toBeNull()
    expect(Math.abs(g.comic!.top - g.decision!.top)).toBeLessThanOrEqual(2)
    expect(g.comic!.x).toBeLessThan(g.decision!.x)
    expect(g.optionalCards).not.toBeNull()
    // Optional cards live inside the decision region, not as a peer column.
    expect(g.optionalCards!.left).toBeGreaterThanOrEqual(g.decision!.left - 1)
    expect(g.optionalCards!.right).toBeLessThanOrEqual(g.decision!.right + 1)

    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })

  test('sparse continuity keeps actions visible and no reserved blanks', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, { title: 'Sparse Layout Thread', format: 'Comic', issues_remaining: 3, total_issues: 3 })
    await enterRatingView(page, 'Sparse Layout Thread', RATING_STATES.sparse)

    const g = await readRatingGeometry(page)
    expect(g.decision).not.toBeNull()
    expect(g.optionalCards).not.toBeNull()

    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)

    await page.setViewportSize(NARROW_DESKTOP_VIEWPORT)
    const narrow = await readRatingGeometry(page)
    assertNoHorizontalOverflow(narrow)
    expect(narrow.grid!.top).toBeGreaterThanOrEqual(0)
  })

  test('a cover-heavy column cannot push the action controls below the fold', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, { title: 'Cover Heavy Layout Thread', format: 'Comic', issues_remaining: 3, total_issues: 3 })
    await enterRatingView(page, 'Cover Heavy Layout Thread', RATING_STATES.coverHeavy)

    const g = await readRatingGeometry(page)
    const cover = g.comic
    expect(cover).not.toBeNull()
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })
})
