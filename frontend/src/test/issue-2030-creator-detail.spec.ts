/**
 * Issue #2030: responsive creator detail route and creator navigation.
 *
 * Acceptance contract (from the issue):
 * 1. `/creators/:creatorKey` renders personal creator detail from #2037.
 * 2. Summary shows average + sample size with a neutral unrated state.
 * 3. Partial metadata coverage is communicated as lower-bound results.
 * 4. Rated/upcoming/read-unrated rows link into existing thread routes.
 * 5. Desktop uses available width; mobile stays single-column with no
 *    horizontal overflow and summary information before long lists.
 * 6. Invalid creator keys produce not-found behavior.
 *
 * The creator payload is fulfilled at the network layer so the spec asserts
 * rendered behavior, not backend fixtures. Backend coverage for the detail
 * contract lives in `tests/test_creator_detail_api.py`.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }

function creatorDetailPayload() {
  return {
    summary: {
      canonical_creator_key: 'creator:7',
      display_name: 'A Very Long Creator Display Name That Must Wrap Without Overflow',
      normalized_roles: ['writer', 'artist'],
      average_rating: 4.5,
      ratings_count: 2,
      read_unrated_count: 1,
      upcoming_count: 1,
    },
    coverage: {
      rated_issues_total: 2,
      rated_issues_with_creator_metadata: 2,
      ratings_complete: true,
      read_unrated_issues_total: 1,
      read_unrated_issues_with_creator_metadata: 1,
      read_unrated_complete: true,
      unread_issues_total: 2,
      unread_issues_with_creator_metadata: 1,
      upcoming_complete: false,
    },
    role_stats: [
      { role: 'writer', issue_count: 3, average_rating: 4.5 },
      { role: 'cover', issue_count: 1, average_rating: null },
    ],
    rated_issues: [
      {
        issue_id: 11,
        issue_number: '1',
        thread_id: 1,
        thread_title: 'Series A With A Long Title That Must Not Overflow',
        status: 'read',
        roles: ['writer'],
        effective_rating: 5,
        rating_timestamp: '2026-01-02T00:00:00Z',
        sort_key: '11',
      },
    ],
    read_unrated_issues: [],
    upcoming_issues: [
      {
        issue_id: 14,
        issue_number: '4',
        thread_id: 3,
        thread_title: 'Series C',
        status: 'unread',
        roles: ['writer'],
        effective_rating: null,
        rating_timestamp: null,
        sort_key: '0000001:0000004:14',
      },
    ],
    next_cursor: null,
  }
}

async function installCreatorRoutes(page: Page) {
  await page.route('**/v1/creators/*', (route) =>
    route.fulfill({ json: creatorDetailPayload() }),
  )
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const doc = document.scrollingElement ?? document.documentElement
    return { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth }
  })
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
}

test.describe('Issue #2030: creator detail route', () => {
  test('desktop renders summary, roles, and issue lists with thread navigation', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorRoutes(page)

    await page.goto('/creators/creator:7', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /A Very Long Creator/ })).toBeVisible({
      timeout: 20000,
    })

    await expect(
      page.locator('[aria-label="Average rating 4.5 out of 5 from 2 ratings"]'),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Roles' })).toBeVisible()
    await expect(page.getByRole('heading', { name: /Rated/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: /Upcoming in ComicPile/ })).toBeVisible()
    // Partial upcoming coverage is disclosed as a lower bound.
    await expect(page.getByText(/lower bounds, not exhaustive totals/)).toBeVisible()

    const ratedLink = page.getByRole('link', { name: /Series A With A Long Title/ })
    await expect(ratedLink).toBeVisible()
    expect(await ratedLink.getAttribute('href')).toBe('/thread/1')

    await expectNoHorizontalOverflow(page)
  })

  test('mobile keeps a single column with summary before history lists', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await installCreatorRoutes(page)

    await page.goto('/creators/creator:7', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /A Very Long Creator/ })).toBeVisible({
      timeout: 20000,
    })

    const boxes = await page.evaluate(() => {
      const rectOf = (text: string) => {
        const el = Array.from(document.querySelectorAll('h1, h2')).find((node) =>
          (node.textContent ?? '').includes(text),
        )
        const rect = el?.getBoundingClientRect()
        return rect ? { top: rect.top, left: rect.left, width: rect.width } : null
      }
      return {
        title: rectOf('A Very Long Creator'),
        rated: rectOf('Rated'),
        upcoming: rectOf('Upcoming in ComicPile'),
        viewportWidth: window.innerWidth,
      }
    })

    expect(boxes.title).not.toBeNull()
    expect(boxes.rated).not.toBeNull()
    expect(boxes.upcoming).not.toBeNull()
    // Summary heading precedes the history lists in visual order.
    expect(boxes.title!.top).toBeLessThan(boxes.rated!.top)
    expect(boxes.rated!.top).toBeLessThanOrEqual(boxes.upcoming!.top)
    // Nothing escapes the narrow viewport.
    expect(boxes.title!.left).toBeGreaterThanOrEqual(-1)
    expect(boxes.title!.left + boxes.title!.width).toBeLessThanOrEqual(boxes.viewportWidth + 1)

    await expectNoHorizontalOverflow(page)
  })

  test('issue rows are keyboard reachable', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorRoutes(page)

    await page.goto('/creators/creator:7', { waitUntil: 'domcontentloaded' })
    const ratedLink = page.getByRole('link', { name: /Series A With A Long Title/ })
    await expect(ratedLink).toBeVisible({ timeout: 20000 })

    await ratedLink.focus()
    const focused = await page.evaluate(() => document.activeElement?.tagName)
    expect(focused).toBe('A')
  })

  test('invalid creator keys produce not-found behavior', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)

    await page.goto('/creators/Stan%20Lee', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Creator not found' })).toBeVisible({
      timeout: 20000,
    })
  })
})
