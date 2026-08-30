/**
 * Issue #1943: Roll desktop layout packs meaningful regions into the viewport.
 *
 * Acceptance contract (from the issue):
 * 1. CSS Grid/Flexbox layout algorithms decide placement — no fixed
 *    grid-row/grid-column coordinates that reserve dead holes.
 * 2. Sparse-continuity states do not reserve large blank acreage.
 * 3. Primary roll info + actions fit a 1920x1080 viewport when content fits.
 * 4. Cards are content-sized — no artificial equal-height row stretching.
 * 5. Rich states use extra columns side-by-side without sparse mimicking them.
 * 6. Narrow desktop/tablet reflows without horizontal overflow.
 * 7. Mobile remains usable (existing mobile tests cover the sticky actions).
 *
 * Tests assert rendered geometry (element boxes, scroll extents, gaps), not
 * Tailwind class strings, so a future styling change cannot silently regress
 * the contract. The four representative states are: rich continuity, sparse
 * continuity, no meaningful reading context, and a cover-heavy column.
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
  settleText: string
}

function readingOrder(id: number, name: string): unknown {
  return { id, name, description: null, total_items: 8, completed_items: 3, items: [] }
}

function connectedThread(id: number, title: string): unknown {
  return { thread_id: id, title, connection_type: 'blocked_by', dependency_id: id }
}

function richReaderContext(): unknown {
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

function sparseReaderContext(): unknown {
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

function confirmedIdentity(): unknown {
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

function noIdentity(): unknown {
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

const RATING_STATES: Record<string, RatingStateRoutes> = {
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
    settleText: 'Your Place in the Story',
  },
  sparse: {
    readingOrders: [readingOrder(9, 'Solo route')],
    connectedThreads: [connectedThread(202, 'One Connected Thread')],
    readerContext: sparseReaderContext(),
    comicvine: null,
    identity: noIdentity(),
    groups: [],
    settleText: 'Reading Routes',
  },
  noContext: {
    readingOrders: [],
    connectedThreads: [],
    readerContext: null,
    comicvine: null,
    identity: noIdentity(),
    groups: [],
    settleText: 'Your Context',
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
    settleText: 'ComicVine linked',
  },
}

async function installRatingRoutes(page: Page, state: RatingStateRoutes): Promise<void> {
  await page.route('**/v1/threads/*/reading-orders', (route) =>
    route.fulfill({ json: { reading_orders: state.readingOrders } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: state.connectedThreads } }),
  )
  await page.route('**/v1/reading-order-groups/threads/*/groups', (route) =>
    route.fulfill({ json: state.groups }),
  )
  await page.route('**/v1/issues/*/reader-context', (route) =>
    route.fulfill({ json: state.readerContext }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: state.comicvine }),
  )
  await page.route('**/v1/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: state.identity }),
  )
  await page.route('**/v1/continuity/readiness', (route) =>
    route.fulfill({
      json: {
        node_type: 'issue',
        node_id: 1,
        is_readable: true,
        evaluated_issue_id: null,
        blockers: [],
      },
    }),
  )
}

/**
 * Creates a thread, installs the state's data routes, rolls, and enters the
 * rating view. Waits for the state's async content anchor before returning so
 * callers always measure settled geometry.
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
  await expect(page.getByText(state.settleText).first()).toBeVisible({ timeout: 10000 })
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
  readingContext: Box
  yourContext: Box
  yourContextPanel: Box
  actions: Box
  cover: Box
  stretch: {
    readingContextOuter: number
    readingContextInner: number
  }
}

async function readRatingGeometry(page: Page): Promise<RatingGeometry> {
  return page.evaluate(() => {
    const box = (el: Element | null) => {
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { x: r.x, y: r.y, top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
    }
    const grid = document.querySelector('[data-testid="rating-pillars-grid"]')
    const readingContext = document.querySelector('[data-testid="rating-region-reading-context"]')
    const yourContext = document.querySelector('[data-testid="rating-region-your-context"]')
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scrollWidth: document.documentElement.scrollWidth,
      gridClientWidth: grid?.clientWidth ?? 0,
      gridScrollWidth: grid?.scrollWidth ?? 0,
      grid: box(grid),
      comic: box(document.querySelector('[data-testid="rating-region-comic"]')),
      readingContext: box(readingContext),
      yourContext: box(yourContext),
      yourContextPanel: box(yourContext?.firstElementChild ?? null),
      actions: box(document.querySelector('[data-testid="rating-actions-grid-cell"]')),
      cover: box(document.querySelector('[data-testid="comic-cover"]')),
      stretch: {
        readingContextOuter: readingContext?.getBoundingClientRect().height ?? 0,
        readingContextInner: readingContext?.firstElementChild?.getBoundingClientRect().height ?? 0,
      },
    }
  })
}

function assertNoHorizontalOverflow(g: RatingGeometry): void {
  expect(g.gridScrollWidth).toBeLessThanOrEqual(g.gridClientWidth + 1)
  expect(g.scrollWidth).toBeLessThanOrEqual(g.viewport.width)
}

function assertContentSized(g: RatingGeometry): void {
  if (g.readingContext) {
    expect(Math.abs(g.stretch.readingContextOuter - g.stretch.readingContextInner)).toBeLessThan(2)
  }
}

function assertActionsFitViewport(g: RatingGeometry): void {
  expect(g.actions).not.toBeNull()
  expect(g.actions!.top).toBeGreaterThan(0)
  expect(g.actions!.bottom).toBeLessThanOrEqual(g.viewport.height)
}

function assertActionsPackWithYourContext(g: RatingGeometry): void {
  expect(g.yourContext).not.toBeNull()
  expect(g.yourContextPanel).not.toBeNull()
  expect(g.actions).not.toBeNull()
  expect(g.actions!.top).toBeGreaterThanOrEqual(g.yourContextPanel!.bottom)
  expect(g.actions!.top - g.yourContextPanel!.bottom).toBeLessThanOrEqual(32)
  expect(Math.abs(g.actions!.left - g.yourContext!.left)).toBeLessThanOrEqual(2)
  expect(Math.abs(g.actions!.right - g.yourContext!.right)).toBeLessThanOrEqual(2)
  expect(g.actions!.bottom).toBeLessThanOrEqual(g.yourContext!.bottom + 2)
}

test.describe('Roll desktop layout packs regions into the viewport (issue #1943)', () => {
  test('rich continuity packs three regions side-by-side without stretching or dead acreage', async ({
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

    // Rich states may use extra columns: all three regions sit in one row.
    expect(g.comic).not.toBeNull()
    expect(g.readingContext).not.toBeNull()
    expect(g.yourContext).not.toBeNull()
    const tops = [g.comic!.top, g.readingContext!.top, g.yourContext!.top]
    expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(2)
    expect(g.comic!.x).toBeLessThan(g.readingContext!.x)
    expect(g.readingContext!.x).toBeLessThan(g.yourContext!.x)

    // Cards are content-sized, not stretched to a shared equal-height row.
    assertContentSized(g)

    // Primary actions stay with Your Context instead of waiting for the
    // tallest Comic/Reading Context column to finish.
    assertActionsPackWithYourContext(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })

  test('sparse continuity keeps actions with compact user context and no reserved blanks', async ({
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
    expect(g.readingContext).not.toBeNull()

    // Compact Reading Context stays compact: no track-wide blank filler.
    expect(g.stretch.readingContextOuter).toBeLessThanOrEqual(600)
    assertContentSized(g)

    // The dashboard actions pack with user context instead of being delayed by
    // another column's height.
    assertActionsPackWithYourContext(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)

    // Narrow desktop/tablet reflows without horizontal overflow.
    await page.setViewportSize(NARROW_DESKTOP_VIEWPORT)
    const narrow = await readRatingGeometry(page)
    assertNoHorizontalOverflow(narrow)
    expect(narrow.grid!.top).toBeGreaterThanOrEqual(0)
  })

  test('omits the Reading Context pillar entirely when there is no meaningful continuity content', async ({
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
    await expect(page.getByText('Reading Context')).toHaveCount(0)

    const g = await readRatingGeometry(page)
    expect(g.comic).not.toBeNull()
    expect(g.yourContext).not.toBeNull()

    // Without Reading Context the dashboard stays compact and primary actions
    // remain attached to the user workflow rather than the comic column height.
    assertActionsPackWithYourContext(g)
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

    // Regression guard for the production failure: a tall cover may make the
    // Comic column long, but it must not make the independent action controls
    // wait below that column before they become reachable.
    assertActionsPackWithYourContext(g)
    assertActionsFitViewport(g)
    assertNoHorizontalOverflow(g)
  })
})
