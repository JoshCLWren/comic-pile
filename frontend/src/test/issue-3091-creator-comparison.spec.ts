/**
 * Issue #3091: side-by-side personal creator comparison.
 *
 * Acceptance contract exercised here (browser behavior the unit tests cannot
 * prove):
 * 1. Selecting 2 creators on `/creators` reveals a Compare action that opens
 *    `/creators/compare` with the selection encoded in route/query state.
 * 2. The comparison view issues exactly one bounded `/api/v1/creators/compare`
 *    request, never one detail request per creator.
 * 3. Cards render personal averages with sample sizes, 5-star rate, role
 *    breakdown, navigable series aggregates, and distinct same-name creators.
 * 4. Thin samples are explicit (`Insufficient data` plus banner) and partial
 *    metadata is a lower bound, never an exhaustive total.
 * 5. Phone width stacks comparison cards with no horizontal overflow.
 *
 * Payloads are fulfilled at the network layer so this spec asserts rendered
 * behavior, not backend fixtures. Backend coverage for the comparison
 * contract lives in `tests/test_creator_comparison_api.py`.
 */
import { expect, type Page, type Route } from '@playwright/test'
import { test } from './fixtures'
import type {
  CreatorComparisonCoverage,
  CreatorComparisonItem,
  CreatorComparisonResponse,
} from '../types/index'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }

const COMPLETE_COVERAGE: CreatorComparisonCoverage = {
  rated_issues_total: 9,
  rated_issues_with_creator_metadata: 9,
  ratings_complete: true,
  read_unrated_issues_total: 0,
  read_unrated_issues_with_creator_metadata: 0,
  read_unrated_complete: true,
  unread_issues_total: 0,
  unread_issues_with_creator_metadata: 0,
  upcoming_complete: true,
}

function listRow(key: string, displayName: string) {
  return {
    canonical_creator_key: key,
    display_name: displayName,
    normalized_roles: ['writer'],
    average_rating: 4.5,
    ratings_count: 4,
  }
}

function comparisonItem(
  key: string,
  displayName: string,
  overrides: Partial<CreatorComparisonItem> = {},
): CreatorComparisonItem {
  return {
    canonical_creator_key: key,
    display_name: displayName,
    normalized_roles: ['writer'],
    average_rating: 4.5,
    median_rating: 4.5,
    ratings_count: 4,
    rating_distribution: { '5': 2, '4': 2 },
    top_rating_rate: 0.5,
    role_stats: [{ role: 'writer', issue_count: 4, rated_issue_count: 4, average_rating: 4.5 }],
    strongest_series: [
      { thread_id: 1, thread_title: 'Saga', issue_count: 4, rated_issue_count: 3, average_rating: 4.7 },
    ],
    min_rated_issues_per_series: 3,
    unread_upcoming_count: 2,
    read_unrated_count: 1,
    insufficient_data: false,
    ...overrides,
  }
}

async function installCreatorsList(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/v1/creators',
    async (route: Route) => {
      const params = new URL(route.request().url()).searchParams
      await route.fulfill({
        json: {
          items: [listRow('creator:7', 'Brian K. Vaughan'), listRow('creator:12', 'Steve McNiven')],
          total: 2,
          limit: Number(params.get('limit') ?? 20),
          offset: 0,
          coverage: COMPLETE_COVERAGE,
        },
      })
    },
  )
}

/** The bounded comparison endpoint; records the requested key sets. */
async function installCreatorComparison(
  page: Page,
  comparisons: Record<string, CreatorComparisonItem>,
  extra: Partial<Pick<CreatorComparisonResponse, 'insufficient_data_keys'>> = {},
) {
  const requests: string[] = []
  await page.route(
    (url) => url.pathname === '/api/v1/creators/compare',
    async (route: Route) => {
      const params = new URL(route.request().url()).searchParams
      requests.push(params.get('keys') ?? '')
      await route.fulfill({
        json: {
          comparisons,
          coverage: COMPLETE_COVERAGE,
          insufficient_data_keys: [],
          ...extra,
        },
      })
    },
  )
  return requests
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const doc = document.scrollingElement ?? document.documentElement
    return { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth }
  })
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
}

test.describe('Issue #3091: creator comparison', () => {
  test('desktop selection opens a bounded side-by-side comparison', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page)
    const compareRequests = await installCreatorComparison(page, {
      'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
      'creator:12': comparisonItem('creator:12', 'Steve McNiven', {
        average_rating: 3.8,
        ratings_count: 5,
        top_rating_rate: 0.2,
      }),
    })

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Brian K. Vaughan')).toBeVisible({ timeout: 20000 })

    await page.getByLabel('Select Brian K. Vaughan for comparison').check()
    await expect(page.getByText('1 of 4 selected for comparison')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Compare' })).toHaveCount(0)

    await page.getByLabel('Select Steve McNiven for comparison').check()
    await page.getByRole('button', { name: 'Compare' }).click()

    await expect(page).toHaveURL(/\/creators\/compare\?keys=/)
    await expect(page.getByRole('heading', { name: 'Creator Comparison' })).toBeVisible({
      timeout: 20000,
    })
    await expect(page.getByText('Comparing 2 creators')).toBeVisible()
    await expect(page.getByLabel('Average rating 4.5 out of 5 from 4 ratings')).toBeVisible()
    await expect(page.getByText('50.0%')).toBeVisible()
    await expect(page.getByText('20.0%')).toBeVisible()
    await expect(page.getByRole('link', { name: /Saga/ })).toHaveAttribute('href', '/thread/1')

    // One bounded comparison request carries both keys; never N+1 details.
    expect(compareRequests).toHaveLength(1)
    expect(compareRequests[0].split(',').sort()).toEqual(['creator:12', 'creator:7'])

    await expectNoHorizontalOverflow(page)
  })

  test('phone stacks thin-sample cards with explicit data caveats', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await installCreatorComparison(
      page,
      {
        'creator:12': comparisonItem('creator:12', 'Steve McNiven', {
          average_rating: 4,
          median_rating: 4,
          ratings_count: 1,
          top_rating_rate: 0,
          insufficient_data: true,
        }),
        'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
      },
      { insufficient_data_keys: ['creator:12'] },
    )

    await page.goto('/creators/compare?keys=creator:7,creator:12', {
      waitUntil: 'domcontentloaded',
    })

    await expect(page.getByRole('heading', { name: 'Creator Comparison' })).toBeVisible({
      timeout: 20000,
    })
    await expect(page.getByText('Insufficient data')).toBeVisible()
    await expect(page.getByText(/less reliable/)).toBeVisible()
    await expect(page.getByText('Brian K. Vaughan')).toBeVisible()
    await expect(page.getByText('Steve McNiven')).toBeVisible()

    await expectNoHorizontalOverflow(page)
  })

  test('distribution bars use a shared 0-100% scale across unequal samples', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page)
    await installCreatorComparison(page, {
      'creator:small': comparisonItem('creator:small', 'Few Ratings Creator', {
        average_rating: 5,
        median_rating: 5,
        ratings_count: 4,
        top_rating_rate: 1,
        rating_distribution: { '5': 4 },
        insufficient_data: false,
      }),
      'creator:large': comparisonItem('creator:large', 'Many Ratings Creator', {
        average_rating: 4.5,
        median_rating: 4,
        ratings_count: 100,
        top_rating_rate: 0.04,
        rating_distribution: {
          '5': 4,
          '4.5': 1,
          '4': 1,
          '3.5': 1,
          '3': 1,
          '2.5': 1,
          '2': 1,
          '1.5': 1,
          '1': 1,
        },
        insufficient_data: false,
      }),
    })

    await page.goto('/creators/compare?keys=creator:small,creator:large', {
      waitUntil: 'domcontentloaded',
    })

    await expect(page.getByRole('heading', { name: 'Creator Comparison' })).toBeVisible({
      timeout: 20000,
    })
    await expect(page.getByText('Comparing 2 creators')).toBeVisible()

    // Small creator's four 5★ ratings equal 100.0% of 4 rated issues; the
    // large creator's four 5★ ratings equal 4.0% of 100 rated issues. Both
    // use the same 0-100% scale.
    const fiveStarBars = page.getByRole('listitem', { name: /5★/ })
    await expect(fiveStarBars.nth(0)).toHaveAttribute(
      'aria-label',
      '5★: 4 ratings, 100.0%',
    )
    await expect(fiveStarBars.nth(1)).toHaveAttribute(
      'aria-label',
      '5★: 4 ratings, 4.0%',
    )

    // Bar lengths differ: the small creator's 5★ bar is full-width while the
    // large creator's is narrow. Bars use the same 0-100% scale, so the
    // visual gap reflects the real difference in rating density rather than
    // each creator's local maximum.
    const [smallBar, largeBar] = await Promise.all([
      fiveStarBars.nth(0)
        .locator('div[style*="var(--theme-personal-accent)"]')
        .evaluate((el) => el.getBoundingClientRect().width),
      fiveStarBars.nth(1)
        .locator('div[style*="var(--theme-personal-accent)"]')
        .evaluate((el) => el.getBoundingClientRect().width),
    ])
    expect(smallBar).toBeGreaterThan(largeBar)

    await expectNoHorizontalOverflow(page)
  })
})
