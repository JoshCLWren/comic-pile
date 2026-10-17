/**
 * Issue #3092: strongest and weakest work on creator detail.
 *
 * Acceptance contract (from the issue):
 * 1. Creator detail surfaces strongest, weakest, and most-rated series when
 *    the minimum rated sample is met.
 * 2. Individual highest/lowest rated issues are clearly distinguished from
 *    aggregate series conclusions.
 * 3. Insufficient series data is disclosed instead of hiding it.
 * 4. Every conclusion drills into its supporting thread.
 * 5. Mobile stays single-column with no horizontal overflow.
 *
 * The creator payload is fulfilled at the network layer so the spec asserts
 * rendered behavior. Backend coverage lives in `tests/test_creator_detail_api.py`.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }

function seriesGroup(overrides: Record<string, unknown> = {}) {
  return {
    series_key: 'thread:1',
    thread_id: 1,
    thread_title: 'Strong Series',
    rated_issue_count: 4,
    average_rating: 4.5,
    lowest_rating: 4,
    highest_rating: 5,
    roles: ['writer'],
    unread_issue_count: 0,
    read_unrated_issue_count: 0,
    metadata_complete: true,
    sort_key: '0001',
    ...overrides,
  }
}

function creatorInsightsPayload(insights: Record<string, unknown>) {
  return {
    summary: {
      canonical_creator_key: 'creator:7',
      display_name: 'Insight Creator',
      normalized_roles: ['writer'],
      average_rating: 4,
      ratings_count: 7,
      read_unrated_count: 0,
      upcoming_count: 0,
    },
    coverage: {
      rated_issues_total: 7,
      rated_issues_with_creator_metadata: 7,
      ratings_complete: true,
      read_unrated_issues_total: 0,
      read_unrated_issues_with_creator_metadata: 0,
      read_unrated_complete: true,
      unread_issues_total: 0,
      unread_issues_with_creator_metadata: 0,
      upcoming_complete: true,
    },
    role_stats: [{ role: 'writer', issue_count: 7, rated_issue_count: 7, average_rating: 4 }],
    series_groups: [],
    series_groups_total: 0,
    series_groups_complete: true,
    rated_issues: [],
    read_unrated_issues: [],
    upcoming_issues: [],
    next_cursor: null,
    rating_distribution: null,
    insights,
  }
}

function qualifiedInsights() {
  return {
    has_sufficient_data: true,
    min_sample_threshold: 3,
    highest_rated_series: seriesGroup(),
    lowest_rated_series: seriesGroup({
      series_key: 'thread:2',
      thread_id: 2,
      thread_title: 'Weak Series',
      rated_issue_count: 3,
      average_rating: 2,
    }),
    most_rated_series: seriesGroup(),
    highest_rated_issue: { issue_id: 11, thread_id: 1, thread_title: 'Strong Series', rating: 5 },
    lowest_rated_issue: { issue_id: 12, thread_id: 2, thread_title: 'Weak Series', rating: 1 },
  }
}

async function installCreatorRoutes(page: Page, insights: Record<string, unknown>) {
  await page.route('**/v1/creators/*', (route) =>
    route.fulfill({ json: creatorInsightsPayload(insights) }),
  )
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const doc = document.scrollingElement ?? document.documentElement
    return { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth }
  })
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
}

test.describe('Issue #3092: strongest and weakest work', () => {
  test('surfaces series conclusions and separate individual extremes with thread links', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorRoutes(page, qualifiedInsights())

    await page.goto('/creators/creator:7', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Insight Creator' })).toBeVisible({
      timeout: 20000,
    })

    await expect(page.getByRole('heading', { name: 'Strongest and weakest work' })).toBeVisible()
    await expect(page.getByText('Strongest series')).toBeVisible()
    await expect(page.getByText('Weakest series')).toBeVisible()

    const strongestLink = page.getByRole('link', { name: /Strongest series/ })
    await expect(strongestLink).toBeVisible()
    expect(await strongestLink.getAttribute('href')).toBe('/thread/1')
    const weakestLink = page.getByRole('link', { name: /Weakest series/ })
    expect(await weakestLink.getAttribute('href')).toBe('/thread/2')

    // Individual extremes are explicitly separated from series conclusions.
    await expect(page.getByText(/single ratings, not series conclusions/)).toBeVisible()
    await expect(page.getByText('Highest-rated issue')).toBeVisible()
    await expect(page.getByText('Lowest-rated issue')).toBeVisible()

    await expectNoHorizontalOverflow(page)
  })

  test('discloses insufficient series data while still showing individual extremes', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorRoutes(page, {
      has_sufficient_data: false,
      min_sample_threshold: 3,
      highest_rated_series: null,
      lowest_rated_series: null,
      most_rated_series: null,
      highest_rated_issue: { issue_id: 11, thread_id: 1, thread_title: 'Lone Series', rating: 5 },
      lowest_rated_issue: { issue_id: 12, thread_id: 1, thread_title: 'Lone Series', rating: 1 },
    })

    await page.goto('/creators/creator:7', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Insight Creator' })).toBeVisible({
      timeout: 20000,
    })

    await expect(page.getByText(/Not enough rated series yet/)).toBeVisible()
    await expect(page.getByText('Strongest series')).not.toBeVisible()
    await expect(page.getByText('Highest-rated issue')).toBeVisible()
    await expect(page.getByText('Lowest-rated issue')).toBeVisible()
  })

  test('keeps the insights section compact and single-column on mobile', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await installCreatorRoutes(page, qualifiedInsights())

    await page.goto('/creators/creator:7', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Strongest and weakest work' })).toBeVisible({
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
        title: rectOf('Insight Creator'),
        insights: rectOf('Strongest and weakest work'),
        viewportWidth: window.innerWidth,
      }
    })

    expect(boxes.title).not.toBeNull()
    expect(boxes.insights).not.toBeNull()
    expect(boxes.title!.top).toBeLessThan(boxes.insights!.top)
    expect(boxes.insights!.left).toBeGreaterThanOrEqual(-1)
    expect(boxes.insights!.left + boxes.insights!.width).toBeLessThanOrEqual(boxes.viewportWidth + 1)

    await expectNoHorizontalOverflow(page)
  })
})
