/**
 * Issue #1943: Roll desktop layout packs meaningful regions into the viewport.
 *
 * The rating surface now renders a live two-region grid (comic + decision)
 * with reading context and reading boundaries behind collapsed optional cards
 * inside the decision column. The retired three-pillar layout asserted here
 * originally (`rating-region-reading-context` / `rating-region-your-context`)
 * no longer exists; these assertions measure the live surface so they still
 * guard real geometry regressions without demanding removed screens.
 *
 * Acceptance contract:
 * 1. CSS Grid/Flexbox decides placement; no dead acreage or fixed holes.
 * 2. Sparse optional states stay compact.
 * 3. Primary roll info and actions fit a 1920x1080 viewport.
 * 4. Cards are content-sized; no equal-height row stretching.
 * 5. Rich optional content opens inside the decision column, not a peer column.
 * 6. Narrow desktop/tablet reflows without horizontal overflow.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const DESKTOP_VIEWPORT = { width: 1920, height: 1080 }
const NARROW_DESKTOP_VIEWPORT = { width: 1024, height: 900 }

/** Small opaque SVG used so the cover never hits the image optimizer. */
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
  groups: unknown[]
  /** Text expected after opening the Reading Context optional card. */
  contextDetail: string | null
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
    crossovers: [
      {
        id: 500,
        name: 'Crisis Crossover',
        applies_to_current_issue: true,
        membership_kind: 'issue',
        next_member: null,
        average_rating: 4.0,
        ratings_count: 3,
        read_count: 2,
      },
    ],
    local_chain: {
      issues: [
        { issue_id: 99, issue_number: '2', position: 1, status: 'read', relation: 'previous', rating: 4.0, crossover_memberships: [] },
        { issue_id: 100, issue_number: '3', position: 2, status: 'unread', relation: 'current', rating: null, crossover_memberships: [{ id: 500, name: 'Crisis Crossover' }] },
        { issue_id: 101, issue_number: '4', position: 3, status: 'unread', relation: 'next', rating: null, crossover_memberships: [] },
      ],
      edges: [
        {
          id: 1,
          kind: 'dependency',
          source_issue_id: 99,
          target_issue_id: 100,
          source_thread_id: null,
          target_thread_id: null,
          source_label: '#2',
          target_label: '#3',
          source_status: 'read',
          target_status: 'unread',
          note: null,
          explanation: 'The prior issue must be read first.',
        },
      ],
    },
  }
}

function sparseReaderContext() {
  return {
    issue_id: 100,
    series: {
      identity_source: 'unavailable',
      canonical_series_id: null,
      series_name: null,
      average_rating: null,
      ratings_count: 0,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: null,
      lowest_rating: null,
    },
    crossovers: [],
    local_chain: {
      issues: [
        { issue_id: 100, issue_number: '3', position: 1, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
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

function noIdentity() {
  return {
    issue_id: 1,
    thread_id: 1,
    thread_title: 'Layout Thread',
    has_confirmed_identity: false,
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
    groups: [],
    contextDetail: 'Crisis Crossover',
  },
  sparse: {
    readingOrders: [readingOrder(9, 'Solo route')],
    connectedThreads: [connectedThread(202, 'One Connected Thread')],
    readerContext: sparseReaderContext(),
    comicvine: null,
    identity: noIdentity(),
    groups: [],
    contextDetail: 'Solo route',
  },
  noContext: {
    readingOrders: [],
    connectedThreads: [],
    readerContext: null,
    comicvine: null,
    identity: noIdentity(),
    groups: [],
    contextDetail: null,
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
    groups: [],
    contextDetail: null,
  },
} satisfies Record<string, RatingStateRoutes>

async function installRatingRoutes(page: Page, state: RatingStateRoutes): Promise<void> {
  await page.route('**/v2/threads/*/readingOrders', (route) =>
    route.fulfill({ json: { reading_orders: state.readingOrders } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: state.connectedThreads } }),
  )
  await page.route('**/v2/threads/*/reading-order-group-memberships', (route) =>
    route.fulfill({ json: state.groups }),
  )
  await page.route('**/v2/issues/*/reader-context', (route) =>
    route.fulfill({ json: state.readerContext }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: state.comicvine }),
  )
  await page.route('**/v2/issues/*/comicvine', (route) =>
    route.fulfill({ json: state.comicvine }),
  )
  await page.route('**/v2/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: state.identity }),
  )
}

/**
 * Creates a thread, installs the state's data routes, rolls, and enters the
 * rating view. The retired three-pillar settle text is replaced by the live
 * optional-card shell, which is present for every rating session.
 */
async function enterRatingView(
  page: Page,
  title: string,
  state: RatingStateRoutes,
): Promise<void> {
  await installRatingRoutes(page, state)
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
  await page.getByText(title).first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await expect(page.getByTestId('reading-context-card')).toBeVisible()
  await expect(page.getByTestId('reading-boundaries-card')).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) {
      await document.fonts.ready
    }
  })
}

type Box = {
  x: number
  y: number
  top: number
  left: number
  right: number
  bottom: number
  width: number
  height: number
} | null

interface RatingGeometry {
  viewport: { width: number; height: number }
  scrollWidth: number
  gridClientWidth: number
  gridScrollWidth: number
  grid: Box
  comic: Box
  decision: Box
  contextCard: Box
  boundariesCard: Box
  actions: Box
  cover: Box
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
      contextCard: box(document.querySelector('[data-testid="reading-context-card"]')),
      boundariesCard: box(document.querySelector('[data-testid="reading-boundaries-card"]')),
      actions: box(document.querySelector('[data-testid="rating-actions"]')),
      cover: box(document.querySelector('[data-testid="comic-cover"]')),
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

function assertActionsPackWithDecision(g: RatingGeometry): void {
  expect(g.decision).not.toBeNull()
  expect(g.actions).not.toBeNull()
  expect(g.actions!.top).toBeGreaterThanOrEqual(g.decision!.top - 1)
  expect(g.actions!.bottom).toBeLessThanOrEqual(g.decision!.bottom + 2)
  // The decision region carries the rating-view padding, so the action card
  // is inset from the region box rather than flush with it.
  expect(Math.abs(g.actions!.left - g.decision!.left)).toBeLessThanOrEqual(20)
  expect(Math.abs(g.actions!.right - g.decision!.right)).toBeLessThanOrEqual(20)
}

test.describe('Roll desktop layout packs regions into the viewport (issue #1943)', () => {
  test('rich continuity packs regions side-by-side with content-sized optional cards', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Rich Layout Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingView(page, 'Rich Layout Thread', RATING_STATES.rich)

    const g = await readRatingGeometry(page)
    expect(g.comic).not.toBeNull()
    expect(g.decision).not.toBeNull()
    expect(g.contextCard).not.toBeNull()
    expect(g.boundariesCard).not.toBeNull()
    const tops = [g.comic!.top, g.decision!.top]
    expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(2)
    expect(g.comic!.x).toBeLessThan(g.decision!.x)

    // Optional cards live inside the decision stack, not in a peer column.
    expect(g.contextCard!.left).toBeGreaterThanOrEqual(g.decision!.left - 1)
    expect(g.contextCard!.right).toBeLessThanOrEqual(g.decision!.right + 1)

    // Rich optional content is reachable by opening the disclosure.
    await page.getByTestId('reading-context-button').click()
    await expect(page.getByTestId('reading-context-content')).toBeVisible()
    await expect(page.getByText('Crisis Crossover').first()).toBeVisible()
    await expect(page.getByText('Main route').first()).toBeVisible()

    assertActionsPackWithDecision(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })

  test('sparse continuity keeps optional cards compact and actions reachable', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Sparse Layout Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingView(page, 'Sparse Layout Thread', RATING_STATES.sparse)

    const g = await readRatingGeometry(page)
    expect(g.contextCard).not.toBeNull()

    // Collapsed optional cards stay compact: no reserved content acreage.
    expect(g.contextCard!.height).toBeLessThanOrEqual(160)
    expect(g.boundariesCard!.height).toBeLessThanOrEqual(160)

    await page.getByTestId('reading-context-button').click()
    await expect(page.getByText('Solo route').first()).toBeVisible()

    assertActionsPackWithDecision(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)

    // Narrow desktop/tablet reflows without horizontal overflow.
    await page.setViewportSize(NARROW_DESKTOP_VIEWPORT)
    const narrow = await readRatingGeometry(page)
    assertNoHorizontalOverflow(narrow)
    expect(narrow.grid!.top).toBeGreaterThanOrEqual(0)
  })

  test('keeps the retired three-pillar regions out of the live rating surface', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'No Context Layout Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingView(page, 'No Context Layout Thread', RATING_STATES.noContext)

    await expect(page.getByTestId('rating-region-reading-context')).toHaveCount(0)
    await expect(page.getByTestId('rating-region-your-context')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Your Reading Boundaries', exact: true })).toHaveCount(0)

    const g = await readRatingGeometry(page)
    expect(g.comic).not.toBeNull()
    expect(g.decision).not.toBeNull()

    // With no continuity content the optional cards still collapse cleanly.
    await page.getByTestId('reading-context-button').click()
    await expect(page.getByTestId('reading-context-content')).toBeVisible()
    await expect(page.getByText('Solo route')).toHaveCount(0)

    assertActionsPackWithDecision(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })

  test('a cover-heavy column cannot push the action controls below the fold', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Cover Heavy Layout Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingView(page, 'Cover Heavy Layout Thread', RATING_STATES.coverHeavy)

    const g = await readRatingGeometry(page)
    expect(g.cover).not.toBeNull()
    expect(g.cover!.height).toBeLessThanOrEqual(g.viewport.height * 0.5)

    // A tall cover may make the comic column long, but the decision column's
    // actions must remain independently reachable in the viewport.
    assertActionsPackWithDecision(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })
})
