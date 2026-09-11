/**
 * ISSUE-2297: The Story Arcs list on the Roll rating surface must reflow with
 * the page at tablet portrait instead of trapping arc actions inside a small
 * fixed-height nested scroller.
 *
 * Before the fix, each arc's issue list rendered inside a `max-h-48
 * overflow-y-auto` pane (~192px) that gained its own horizontal and vertical
 * scrollbars, clipping the Add to ComicPile actions and requiring precise
 * inner scrolling to reach lower issues.
 *
 * This spec reproduces the rating view at the reported 800x1094 viewport with
 * an arc containing more issues than the old pane could show, then asserts the
 * rendered geometry contract:
 *   - The arc issue list is not an independently scrollable clipped pane.
 *   - Arc cards carry no internal horizontal overflow (no one-character crush).
 *   - Every arc action is reachable through ordinary page scroll.
 *   - The document adds no horizontal overflow.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const REPORTED_TABLET_VIEWPORT = { width: 800, height: 1094 }
const ARC_ISSUE_COUNT = 14

function arcIssue(index: number) {
  const number = `${index + 1}`
  return {
    comicvine_issue_id: `970${index}`,
    series_name: 'Dawn of Everything',
    issue_number: number,
    name: `Part ${number}: The Long Walk`,
    cover_date: null,
    comicvine_url: null,
    comicpile_matches:
      index < 2
        ? [{
            issue_id: 1000 + index,
            thread_id: 1,
            thread_title: 'Dawn of Everything',
            issue_number: number,
            status: 'unread',
          }]
        : [],
  }
}

function longArcIntelligence() {
  return {
    comicvine_issue_id: '12345',
    comicvine_url: null,
    series_name: 'Dawn of Everything',
    series_id: 1,
    issue_number: '3',
    name: 'The Turning Point',
    description: null,
    image_url: null,
    cover_date: '2026-01-01',
    store_date: null,
    creators: [],
    story_arcs: [
      {
        comicvine_arc_id: 700,
        name: 'The Age of Aftermath',
        comicvine_url: null,
        total_related_count: ARC_ISSUE_COUNT,
        related_issues: Array.from({ length: ARC_ISSUE_COUNT }, (_, index) => arcIssue(index)),
      },
    ],
  }
}

function confirmedIdentity() {
  return {
    issue_id: 1,
    thread_id: 1,
    thread_title: 'Story Arc Thread',
    has_confirmed_identity: true,
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: false,
  }
}

function minimalReaderContext() {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: 'series-1',
      series_name: 'Dawn of Everything',
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
        {
          issue_id: 100,
          issue_number: '3',
          position: 1,
          status: 'unread',
          relation: 'current',
          rating: null,
          crossover_memberships: [],
        },
      ],
      edges: [],
    },
  }
}

async function installRatingRoutes(page: Page): Promise<void> {
  await page.route('**/v1/threads/*/reading-orders', (route) =>
    route.fulfill({ json: { reading_orders: [] } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: [] } }),
  )
  await page.route('**/v1/reading-order-groups/threads/*/groups', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/v1/issues/*/reader-context', (route) =>
    route.fulfill({ json: minimalReaderContext() }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: longArcIntelligence() }),
  )
  await page.route('**/v1/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: confirmedIdentity() }),
  )
}

/**
 * Rolls into the rating view for a fresh thread. All data routes are already
 * installed so the Comic column renders the deterministic long-arc identity.
 */
async function enterRatingViewWithLongArc(page: Page): Promise<void> {
  await installRatingRoutes(page)
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
  await page.getByText('Story Arc Thread').first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  // The Story Arcs disclosure auto-expands once ComicVine intelligence loads.
  await expect(page.getByText('Story arcs (1)')).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('The Age of Aftermath')).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) {
      await document.fonts.ready
    }
  })
}

test.describe('issue #2297: story arcs list reflows with the page at tablet portrait', () => {
  test('arc issues are reachable by page scroll, not a clipped nested scroller', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(REPORTED_TABLET_VIEWPORT)

    await createThread(page, {
      title: 'Story Arc Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingViewWithLongArc(page)

    // Expand every issue in the arc so the full list is present (the layout
    // must never need an inner scroller to reach the tail).
    await page.getByRole('button', { name: `Show all ${ARC_ISSUE_COUNT} issues` }).click()
    const lastAddButton = page.getByRole('button', {
      name: `Add Dawn of Everything #${ARC_ISSUE_COUNT} to ComicPile`,
    })
    await expect(lastAddButton).toBeVisible()

    const arcScrollClaims = await page.$$eval(
      '[data-testid="story-arc-issue-list"]',
      (lists) =>
        lists.map((list) => {
          const style = window.getComputedStyle(list)
          const scrollable = style.overflowY === 'auto' || style.overflowY === 'scroll'
          const clientHeight = list.clientHeight
          const scrollHeight = list.scrollHeight
          return {
            overflowY: style.overflowY,
            maxHeight: style.maxHeight,
            clientHeight,
            scrollHeight,
            clipped: scrollable && scrollHeight > clientHeight + 1,
          }
        }),
    )

    expect(arcScrollClaims.length).toBeGreaterThan(0)
    for (const claim of arcScrollClaims) {
      // No fixed-height pane: the container is intentionally content-sized and
      // must not introduce an independently scrollable clipped action region.
      expect(claim.maxHeight).toBe('none')
      expect(claim.clipped).toBe(false)
    }

    // Arc issue cards must lay out without an internal horizontal scroller.
    const overflowCards = await page.$$eval(
      '[data-testid="story-arc-issue-list"] > div',
      (cards) =>
        cards.filter((card) => card.scrollWidth > card.clientWidth + 1).length,
    )
    expect(overflowCards).toBe(0)

    // The document itself must not gain horizontal page overflow.
    const documentExtents = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(documentExtents.scrollWidth).toBeLessThanOrEqual(documentExtents.innerWidth + 1)

    // Every arc action is reachable through ordinary page scroll: scroll to the
    // bottom and the last card's Add button must be on screen, unclipped.
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await expect(lastAddButton).toBeInViewport()
    const lastButtonBox = await lastAddButton.boundingBox()
    expect(lastButtonBox).not.toBeNull()
    expect(lastButtonBox!.x).toBeGreaterThanOrEqual(0)
    expect(lastButtonBox!.x + lastButtonBox!.width).toBeLessThanOrEqual(REPORTED_TABLET_VIEWPORT.width + 1)
  })
})