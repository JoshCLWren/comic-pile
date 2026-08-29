/**
 * Issue #1944: rendered Roll layout invariants across sparse and rich desktop states.
 *
 * Recent Roll regressions passed unit suites because they asserted SVG presence
 * or grid class names instead of what a human actually experiences. These
 * browser checks assert rendered geometry (bounding boxes, viewport overflow,
 * pillar ordering) for the desktop rating view across five stable fixture
 * states:
 *
 * 1. Rich continuity / crossover state.
 * 2. Sparse continuity state.
 * 3. Successful-empty Reading Context.
 * 4. Meaningful user rating/history with little continuity.
 * 5. Cover-heavy comic state.
 *
 * Fixtures are seeded through authenticated APIs (including test-only seed
 * endpoints) so the layout never depends on whichever production comic happens
 * to be in the queue. Tests intentionally never encode pixel-perfect card
 * positions; they fail on *behavior*: horizontal escape, pillar overlap,
 * phantom empty columns, or actions pushed off-screen by whitespace.
 *
 * Regression anchors:
 * - #1627: an empty Reading Context used to render as a blank middle column;
 *   these tests fail if that phantom slot ever returns.
 * - #1885/#1650: the rating view keeps the no-horizontal-overflow contract.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const WIDE_VIEWPORT = { width: 1920, height: 1080 }
const NARROW_VIEWPORT = { width: 1024, height: 900 }

/** A real grid gutter is ~24px; a phantom optional column is hundreds of px. */
const PHANTOM_COLUMN_TOLERANCE_PX = 160
/** A clip/hidden artifact is not a layout: children must stay in the viewport. */
const ESCAPE_TOLERANCE_PX = 2

type Rect = {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

type GridChild = {
  index: number
  rect: Rect
  isComic: boolean
  isReadingContext: boolean
  isYourContext: boolean
  isActions: boolean
}

type LayoutGeometry = {
  viewport: { width: number; height: number }
  doc: { scrollWidth: number; scrollHeight: number }
  grid: Rect | null
  children: GridChild[]
  actionsCell: Rect | null
  cover: Rect | null
  ratingInput: Rect | null
}

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok()).toBeTruthy()
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = await getAuthToken(page)
  const csrf = await getCsrf(page, token)
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
}

async function listIssues(page: Page, threadId: number): Promise<number[]> {
  const token = await getAuthToken(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok(), `issue list failed: ${await response.text()}`).toBeTruthy()
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues.map((issue) => issue.id)
}

async function setPending(page: Page, threadId: number): Promise<void> {
  const token = await getAuthToken(page)
  const response = await page.request.post(`/api/threads/${threadId}/set-pending`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok(), `set-pending failed: ${response.status()} ${await response.text()}`).toBeTruthy()
}

async function seedDependency(
  page: Page,
  headers: Record<string, string>,
  sourceIssueId: number,
  targetIssueId: number,
): Promise<void> {
  const response = await page.request.post('/api/v1/dependencies/', {
    headers,
    data: {
      source_type: 'issue',
      source_id: sourceIssueId,
      target_type: 'issue',
      target_id: targetIssueId,
    },
  })
  expect(response.ok(), `dependency seed failed: ${await response.text()}`).toBeTruthy()
}

async function seedReadingOrder(
  page: Page,
  headers: Record<string, string>,
  name: string,
  threadIds: number[],
): Promise<void> {
  const response = await page.request.post('/api/test/reading-orders', {
    headers,
    data: {
      name,
      items: threadIds.map((threadId, index) => ({ thread_id: threadId, position: index + 1 })),
    },
  })
  expect(response.ok(), `reading order seed failed: ${await response.text()}`).toBeTruthy()
}

async function seedCrossover(
  page: Page,
  headers: Record<string, string>,
  name: string,
  memberThreadIds: number[],
  memberIssueIds: number[],
): Promise<void> {
  const createResponse = await page.request.post('/api/v1/reading-order-groups/', {
    headers,
    data: { name },
  })
  expect(createResponse.ok(), `crossover create failed: ${await createResponse.text()}`).toBeTruthy()
  const group = (await createResponse.json()) as { id: number }
  for (const threadId of memberThreadIds) {
    const memberResponse = await page.request.post(
      `/api/v1/reading-order-groups/${group.id}/members`,
      {
        headers,
        data: { thread_id: threadId },
      },
    )
    expect(memberResponse.ok(), `crossover thread member failed: ${await memberResponse.text()}`).toBeTruthy()
  }
  for (const issueId of memberIssueIds) {
    const memberResponse = await page.request.post(
      `/api/v1/reading-order-groups/${group.id}/members`,
      {
        headers,
        data: { issue_id: issueId },
      },
    )
    expect(memberResponse.ok(), `crossover issue member failed: ${await memberResponse.text()}`).toBeTruthy()
  }
}

async function seedIssueIdentity(
  page: Page,
  headers: Record<string, string>,
  issueId: number,
  seriesName: string,
  seriesId: number,
): Promise<void> {
  const response = await page.request.post('/api/test/issue-identity', {
    headers,
    data: { issue_id: issueId, series_name: seriesName, series_id: seriesId },
  })
  expect(response.ok(), `identity seed failed: ${await response.text()}`).toBeTruthy()
}

async function seedThreadIdentity(
  page: Page,
  headers: Record<string, string>,
  threadId: number,
  seriesName: string,
  seriesId: number,
): Promise<void> {
  const response = await page.request.post('/api/test/issue-identity', {
    headers,
    data: { thread_id: threadId, series_name: seriesName, series_id: seriesId },
  })
  expect(response.ok(), `identity seed failed: ${await response.text()}`).toBeTruthy()
}

async function rateCurrentIssue(
  page: Page,
  headers: Record<string, string>,
  rating: number,
  issueNumber: string,
): Promise<void> {
  const response = await page.request.post('/api/v1/rate/', {
    headers,
    data: { rating, finish_session: false, issue_number: issueNumber },
  })
  expect(response.ok(), `rate seed failed: ${await response.text()}`).toBeTruthy()
}

async function openRatingView(page: Page, threadId: number): Promise<void> {
  const contextLoaded = page
    .waitForResponse((response) => response.url().includes('/reader-context'), {
      timeout: 15000,
    })
    .catch(() => null)

  await setPending(page, threadId)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible()
  await contextLoaded
  await page.evaluate(() => document.fonts.ready)
  // Let React settle once the context/intelligence responses have landed so
  // measured heights are final, not mid-skeleton.
  await page.waitForTimeout(400)
}

async function readGeometry(page: Page): Promise<LayoutGeometry> {
  return page.evaluate(() => {
    const rectOf = (element: Element | null): Rect | null => {
      if (!element) return null
      const r = element.getBoundingClientRect()
      return {
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      }
    }

    const grid = document.querySelector('[data-testid="rating-pillars-grid"]')
    const children: GridChild[] = []
    if (grid) {
      Array.from(grid.children).forEach((child, index) => {
        const text = child.textContent ?? ''
        const rect = rectOf(child)!
        children.push({
          index,
          rect,
          isComic: child.querySelector('[data-testid="comic-cover"], [data-testid="cover-placeholder"], #thread-info') !== null,
          isReadingContext: text.includes('Reading Context'),
          isYourContext: text.includes('Your Context'),
          isActions: child.getAttribute('data-testid') === 'rating-actions-grid-cell',
        })
      })
    }

    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      doc: {
        scrollWidth: document.documentElement.scrollWidth,
        scrollHeight: document.documentElement.scrollHeight,
      },
      grid: rectOf(grid),
      children,
      actionsCell: rectOf(document.querySelector('[data-testid="rating-actions-grid-cell"]')),
      cover: rectOf(document.querySelector('[data-testid="comic-cover"]')),
      ratingInput: rectOf(document.querySelector('#rating-input')),
    }
  })
}

/**
 * The Roll content must never require horizontal scrolling, and every pillar
 * must stay inside the viewport (nothing clipped or escaped).
 */
function assertFitsViewportWidth(geometry: LayoutGeometry): void {
  expect(
    geometry.doc.scrollWidth,
    'the Roll page must not require horizontal scrolling',
  ).toBeLessThanOrEqual(geometry.viewport.width + ESCAPE_TOLERANCE_PX)
  for (const child of geometry.children) {
    expect(
      child.rect.left,
      `pillar ${child.index} must not start off-screen`,
    ).toBeGreaterThanOrEqual(-ESCAPE_TOLERANCE_PX)
    expect(
      child.rect.right,
      `pillar ${child.index} must not escape the right edge of the viewport`,
    ).toBeLessThanOrEqual(geometry.viewport.width + ESCAPE_TOLERANCE_PX)
  }
}

/**
 * Pillars must tile the grid without physically overlapping. A hairline amount
 * of rounding is allowed; a real collision covers hundreds of square pixels.
 */
function assertPillarsDoNotOverlap(geometry: LayoutGeometry): void {
  const pillars = geometry.children.filter(
    (child) => child.isComic || child.isReadingContext || child.isYourContext,
  )
  for (let i = 0; i < pillars.length; i += 1) {
    for (let j = i + 1; j < pillars.length; j += 1) {
      const a = pillars[i]!.rect
      const b = pillars[j]!.rect
      const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
      const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
      const overlapArea = Math.max(0, overlapWidth) * Math.max(0, overlapHeight)
      expect(
        overlapArea,
        `pillars ${i} and ${j} must not overlap`,
      ).toBeLessThan(64)
    }
  }
}

/**
 * A missing optional region must never leave a column-sized gap: the right
 * pillar sits directly beside the left one, and the actions bar still owns
 * the full right column instead of a squeezed slot.
 */
function assertNoPhantomColumn(geometry: LayoutGeometry): void {
  const comic = geometry.children.find((child) => child.isComic)
  const yourContext = geometry.children.find((child) => child.isYourContext)
  expect(comic, 'a comic pillar must be present').toBeDefined()
  expect(yourContext, 'the Your Context pillar must be present').toBeDefined()

  expect(
    yourContext!.rect.left - comic!.rect.right,
    'no empty column may sit between the comic and Your Context pillars',
  ).toBeLessThan(PHANTOM_COLUMN_TOLERANCE_PX)

  if (geometry.grid && geometry.actionsCell && geometry.grid.width > 0) {
    const actionsShare = geometry.actionsCell.width / geometry.grid.width
    expect(
      actionsShare,
      'the actions bar must occupy a full column, not a slot squeezed by a phantom region',
    ).toBeGreaterThan(0.4)
  }
}

/**
 * The primary actions never escape sideways, and when the whole fixture fits
 * in the viewport they stay above the fold (whitespace must not push them off).
 */
function assertPrimaryActionsReachable(geometry: LayoutGeometry): void {
  const actions = geometry.actionsCell
  expect(actions, 'the actions cell must be present').toBeDefined()
  expect(
    actions!.left,
    'the actions must not escape the left edge',
  ).toBeGreaterThanOrEqual(-ESCAPE_TOLERANCE_PX)
  expect(
    actions!.right,
    'the actions must not escape the right edge of the viewport',
  ).toBeLessThanOrEqual(geometry.viewport.width + ESCAPE_TOLERANCE_PX)

  const contentFits = geometry.doc.scrollHeight <= geometry.viewport.height + 8
  if (contentFits) {
    expect(
      actions!.bottom,
      'primary Roll actions must stay above the fold when the fixture fits',
    ).toBeLessThanOrEqual(geometry.viewport.height + ESCAPE_TOLERANCE_PX)
  }
}

/**
 * Cards may be tall when their content is rich, but they must never stretch
 * into full-viewport empty slabs just to consume viewport height.
 */
function assertCardsAreContentSized(geometry: LayoutGeometry): void {
  for (const child of geometry.children) {
    if (child.isActions) continue
    const heightShare = child.rect.height / geometry.viewport.height
    expect(
      heightShare,
      `pillar ${child.index} must not be stretched across nearly the whole viewport`,
    ).toBeLessThan(0.92)
  }
  if (geometry.actionsCell) {
    expect(
      geometry.actionsCell.height / geometry.viewport.height,
      'the actions bar must not be stretched into a full-viewport slab',
    ).toBeLessThan(0.5)
  }
}

test.describe('Roll desktop layout invariants (#1944)', () => {
  test('successful-empty Reading Context stays absent instead of reserving a blank slot', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_VIEWPORT)
    await createThread(page, {
      title: 'Empty Context Comic',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    }).then((thread) => listIssues(page, thread.id))

    const thread = await createThread(page, {
      title: 'Empty Context Comic',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await openRatingView(page, thread.id)

    // Absent, not merely visually blank: the heading must not exist in the DOM.
    const grid = page.getByTestId('rating-pillars-grid')
    await expect(grid.getByText('Reading Context', { exact: true })).toHaveCount(0)

    const geometry = await readGeometry(page)
    assertFitsViewportWidth(geometry)
    assertPillarsDoNotOverlap(geometry)
    assertNoPhantomColumn(geometry)
    assertPrimaryActionsReachable(geometry)
    assertCardsAreContentSized(geometry)
  })

  test('rich continuity and crossover content lays out in three useful columns without overflow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_VIEWPORT)

    const target = await createThread(page, {
      title: 'Fixture One',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const blocker = await createThread(page, {
      title: 'Fixture Two',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const downstream = await createThread(page, {
      title: 'Fixture Three',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    const headers = await authHeaders(page)
    const targetIssues = await listIssues(page, target.id)
    const blockerIssues = await listIssues(page, blocker.id)

    // Fixture Two#1 → Fixture One#1 makes Two a blocked-by connection, and
    // Fixture One#2 → Fixture Three#1 gives One an outgoing block edge.
    await seedDependency(page, headers, blockerIssues[0]!, targetIssues[0]!)
    await seedDependency(page, headers, targetIssues[1]!, (await listIssues(page, downstream.id))[0]!)

    await seedReadingOrder(page, headers, 'Crossover Route', [target.id, blocker.id])
    await seedCrossover(page, headers, 'Crisis on Fixture Pile', [target.id], [blockerIssues[0]!])
    await seedThreadIdentity(page, headers, target.id, 'Fixtureverse', 612001)

    await openRatingView(page, target.id)

    await expect(page.getByText('Reading Context', { exact: true })).toBeVisible()
    await expect(page.getByText('Where you are in Fixtureverse')).toBeVisible()
    await expect(page.getByText('Dependency & Continuity Edges')).toBeVisible()
    // Crossover membership renders after expanding the current issue's context.
    await page.getByRole('button', { name: 'Show context for Fixtureverse issue 1' }).click()
    await expect(page.getByRole('button', { name: 'Open Crisis on Fixture Pile crossover' })).toBeVisible()
    await page.waitForTimeout(200)

    const geometry = await readGeometry(page)
    expect(geometry.children).toHaveLength(4)
    const readingContextChild = geometry.children.find((child) => child.isReadingContext)
    expect(readingContextChild, 'the Reading Context pillar must be present').toBeDefined()

    assertFitsViewportWidth(geometry)
    assertPillarsDoNotOverlap(geometry)
    assertCardsAreContentSized(geometry)
    assertPrimaryActionsReachable(geometry)

    // The rich pillar is genuinely full of content, not a decorated shell.
    expect(
      readingContextChild!.rect.height,
      'a rich Reading Context pillar must be substantial',
    ).toBeGreaterThan(200)
    expect(
      readingContextChild!.rect.height / geometry.viewport.height,
      'even the richest pillar must leave room for the rest of the cockpit',
    ).toBeLessThan(0.92)
  })

  test('sparse continuity content is real but never bloats into empty cards', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_VIEWPORT)

    const blocked = await createThread(page, {
      title: 'Blocked Core Comic',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const anchor = await createThread(page, {
      title: 'Blocking Anchor Comic',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const headers = await authHeaders(page)
    await seedDependency(page, headers, (await listIssues(page, anchor.id))[0]!, (await listIssues(page, blocked.id))[0]!)

    await openRatingView(page, blocked.id)

    await expect(page.getByText('Reading Context', { exact: true })).toBeVisible()
    await expect(page.getByText('Blocked by:')).toBeVisible()

    const geometry = await readGeometry(page)
    const readingContextChild = geometry.children.find((child) => child.isReadingContext)
    expect(readingContextChild, 'the Reading Context pillar must be present').toBeDefined()

    assertFitsViewportWidth(geometry)
    assertPillarsDoNotOverlap(geometry)
    assertPrimaryActionsReachable(geometry)
    assertCardsAreContentSized(geometry)

    // Sparse continuity means a compact pillar: it must not dominate the grid.
    expect(
      readingContextChild!.rect.height / geometry.viewport.height,
      'sparse continuity content must not stretch into a full-column slab',
    ).toBeLessThan(0.6)
  })

  test('meaningful reading history renders compactly without a phantom Reading Context', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_VIEWPORT)

    const thread = await createThread(page, {
      title: 'Historic Core Comic',
      format: 'Issue',
      issues_remaining: 5,
      total_issues: 5,
    })
    const headers = await authHeaders(page)
    // Confirm the whole run so the rated issues count as same-series history.
    await seedThreadIdentity(page, headers, thread.id, 'Historyverse', 612002)

    // Rate three issues to build meaningful recent-history data.
    for (let issueNumber = 1; issueNumber <= 3; issueNumber += 1) {
      await setPending(page, thread.id)
      await rateCurrentIssue(page, headers, 4.0, String(issueNumber))
    }

    await openRatingView(page, thread.id)

    // No Reading Context pillar in this little-continuity state, but the
    // history is visible in Your Context via the series panel.
    await expect(page.getByTestId('rating-pillars-grid').getByText('Reading Context', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Historyverse history')).toBeVisible()
    await expect(page.getByText('3 rated')).toBeVisible()
    await expect(page.getByText('Recent ratings')).toBeVisible()

    const geometry = await readGeometry(page)
    assertFitsViewportWidth(geometry)
    assertPillarsDoNotOverlap(geometry)
    assertNoPhantomColumn(geometry)
    assertPrimaryActionsReachable(geometry)
    assertCardsAreContentSized(geometry)
  })

  test('cover-heavy state consumes vertical space without burying actions in whitespace', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_VIEWPORT)

    const thread = await createThread(page, {
      title: 'Cover Heavy Impact',
      format: 'Issue',
      issues_remaining: 1,
      total_issues: 1,
    })
    const headers = await authHeaders(page)
    await seedThreadIdentity(page, headers, thread.id, 'Covertopia', 612003)

    await openRatingView(page, thread.id)

    await expect(page.getByTestId('comic-cover')).toBeVisible()

    const geometry = await readGeometry(page)
    expect(geometry.cover, 'a confirmed identity must render the cover frame').toBeDefined()
    expect(
      geometry.cover!.height,
      'the cover frame must actually consume meaningful vertical space',
    ).toBeGreaterThanOrEqual(math.floor(0.45 * geometry.viewport.height))

    assertFitsViewportWidth(geometry)
    assertPillarsDoNotOverlap(geometry)
    assertPrimaryActionsReachable(geometry)

    // The tall cover must not force the actions more than about one extra
    // screenful below the top of the cover.
    if (geometry.actionsCell && geometry.cover) {
      const reachDistance = geometry.actionsCell.top - geometry.cover.top
      expect(
        reachDistance,
        'the tall cover must not push the actions far off the first screenful',
      ).toBeLessThanOrEqual(geometry.viewport.height * 1.5)
    }
  })

  test('narrowing the viewport reflows the grid instead of overlapping or escaping', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_VIEWPORT)

    const target = await createThread(page, {
      title: 'Reflow Target Comic',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const anchor = await createThread(page, {
      title: 'Reflow Anchor Comic',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const headers = await authHeaders(page)
    await seedDependency(page, headers, (await listIssues(page, anchor.id))[0]!, (await listIssues(page, target.id))[0]!)
    await seedReadingOrder(page, headers, 'Reflow Route', [target.id])
    await seedThreadIdentity(page, headers, target.id, 'Reflowverse', 612004)

    await openRatingView(page, target.id)
    await expect(page.getByText('Where you are in Reflowverse')).toBeVisible()

    const wide = await readGeometry(page)
    assertFitsViewportWidth(wide)
    assertPillarsDoNotOverlap(wide)

    // Wide (xl): the actions sit on the middle column's second row, beside the
    // Your Context pillar rather than below it.
    const wideYour = wide.children.find((child) => child.isYourContext)
    const wideActions = wide.actionsCell
    expect(wideYour, 'Your Context must be present at the wide layout').toBeDefined()
    expect(wideActions, 'the actions cell must be present at the wide layout').toBeDefined()
    expect(
      wideActions!.top,
      'at the wide layout the actions must start on the same row as Your Context',
    ).toBeLessThan(wideYour!.rect.bottom)

    // Narrow to a tablet-sized desktop: content must reflow, not collide.
    await page.setViewportSize(NARROW_VIEWPORT)
    await page.waitForTimeout(300)

    const narrow = await readGeometry(page)
    assertFitsViewportWidth(narrow)
    assertPillarsDoNotOverlap(narrow)

    const narrowYour = narrow.children.find((child) => child.isYourContext)
    const narrowActions = narrow.actionsCell
    expect(narrowYour, 'Your Context must be present at the narrow layout').toBeDefined()
    expect(narrowActions, 'the actions cell must be present at the narrow layout').toBeDefined()
    expect(
      narrowActions!.top,
      'at the narrow layout the actions must reflow below the pillars',
    ).toBeGreaterThanOrEqual(narrowYour!.rect.bottom - 4)

    if (narrow.grid && narrowActions && narrow.grid.width > 0) {
      expect(
        narrowActions!.width / narrow.grid.width,
        'the actions bar must stretch across the single narrow column',
      ).toBeGreaterThan(0.9)
    }
  })

  // Direct synthesis of the test-only seeding from the states above.
  test.describe('fixture sanity', () => {
    test('identity seeding is idempotent across a thread reload', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage
      await page.setViewportSize(WIDE_VIEWPORT)

      const thread = await createThread(page, {
        title: 'Idempotent Identity Comic',
        format: 'Issue',
        issues_remaining: 2,
        total_issues: 2,
      })
      const headers = await authHeaders(page)
      for (let attempt = 0; attempt < 2; attempt += 1) {
        await seedThreadIdentity(page, headers, thread.id, 'Idempotentverse', 612005)
      }
      await openRatingView(page, thread.id)
      await expect(page.getByText('Idempotentverse #1', { exact: false })).toBeVisible()
      // Even with duplicate seeding the confirmation must not be lost.
      expect(await visibleElements(page, '[data-testid="comic-cover"]')).toBeGreaterThan(0)
    })
  })
})