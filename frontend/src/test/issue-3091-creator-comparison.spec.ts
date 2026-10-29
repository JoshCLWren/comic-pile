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
 * 4. Thin samples are explicit (a `Small sample` badge per affected card plus
 *    one shared explanatory banner) and partial metadata is a lower bound,
 *    never an exhaustive total.
 * 5. Phone width stacks comparison cards with no horizontal overflow.
 * 6. Four creators lay out as two balanced rows with no card-edge overflow at
 *    1280 or at a 200%-zoom(~640px) viewport (#3459).
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
    min_rated_issues_per_series: 5,
    unread_upcoming_count: 2,
    read_unrated_count: 1,
    unread_issue_refs: [],
    read_unrated_issue_refs: [],
    max_issue_refs_per_group: 5,
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

/**
 * Issue #3459: no compare value or distribution label may run past its card
 * edge. `scrollWidth` includes overflowing descendants even when the card
 * itself is not a scroll container, so it catches the pre-fix implicit-column
 * overflow the `sm:col-span-2` cells caused in a single-column inner grid.
 */
async function expectCardsContained(page: Page) {
  const overflows = await page
    .getByTestId('creator-comparison-card')
    .evaluateAll((cards) => cards.map((card) => card.scrollWidth - card.clientWidth))
  expect(overflows.length).toBeGreaterThan(0)
  for (const overflow of overflows) {
    expect(overflow).toBeLessThanOrEqual(1)
  }
}

/** Number of cards per visual row, derived from their rendered top edges. */
async function cardRowCounts(page: Page): Promise<number[]> {
  const tops = await page
    .getByTestId('creator-comparison-card')
    .evaluateAll((cards) =>
      cards.map((card) => Math.round(card.getBoundingClientRect().top)),
    )
  const rows = new Map<number, number>()
  for (const top of tops) {
    const existing = [...rows.keys()].find((key) => Math.abs(key - top) <= 2)
    const key = existing ?? top
    rows.set(key, (rows.get(key) ?? 0) + 1)
  }
  return [...rows.values()]
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
    await expect(page.getByText('Small sample', { exact: true })).toBeVisible()
    await expect(page.getByText(/fewer than 5 rated comics/)).toBeVisible()
    await expect(page.getByText(/less representative/)).toBeVisible()
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
      'creator:21': comparisonItem('creator:21', 'Few Ratings Creator', {
        average_rating: 5,
        median_rating: 5,
        ratings_count: 4,
        top_rating_rate: 1,
        rating_distribution: { '5': 4 },
        insufficient_data: false,
      }),
      'creator:22': comparisonItem('creator:22', 'Many Ratings Creator', {
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

    await page.goto('/creators/compare?keys=creator:21,creator:22', {
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

  test('four creators lay out without an orphan card or edge overflow (#3459)', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorComparison(page, {
      'creator:1': comparisonItem('creator:1', 'Creator One'),
      'creator:2': comparisonItem('creator:2', 'Creator Two'),
      'creator:3': comparisonItem('creator:3', 'Creator Three'),
      'creator:4': comparisonItem('creator:4', 'Creator Four'),
    })

    await page.goto('/creators/compare?keys=creator:1,creator:2,creator:3,creator:4', {
      waitUntil: 'domcontentloaded',
    })

    await expect(page.getByRole('heading', { name: 'Creator Comparison' })).toBeVisible({
      timeout: 20000,
    })
    await expect(page.getByText('Comparing 4 creators')).toBeVisible()
    await expect(page.getByTestId('creator-comparison-card')).toHaveCount(4)

    // Values and distribution labels stay inside their cards, and the page
    // never scrolls sideways.
    await expectCardsContained(page)
    await expectNoHorizontalOverflow(page)

    // Four creators form two balanced rows of two, never a 3 + 1 orphan.
    expect(await cardRowCounts(page)).toEqual([2, 2])

    // 200% browser zoom on a 1280px window presents a ~640 CSS px viewport.
    // The overflow was worse there, so re-check the containment boundary.
    await page.setViewportSize({ width: 640, height: 800 })
    await expectCardsContained(page)
    await expectNoHorizontalOverflow(page)
  })
})

/** Issue #3462: creator compare silently omits unresolved deep-link keys */
const MIXED_KEYS = ['creator:7', 'creator:99999']

test('3462 - valid 2-creator comparison renders', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  await installCreatorsList(page)
  await installCreatorComparison(page, {
    'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
    'creator:12': comparisonItem('creator:12', 'Steve McNiven'),
  })
  await page.goto('/creators/compare?keys=creator:7,creator:12')
  await expect(page.getByText('Comparing 2 creators')).toBeVisible()
  await expect(page.getByText('Brian K. Vaughan')).toBeVisible()
  await expect(page.getByText('Steve McNiven')).toBeVisible()
})

test('3462 - one valid + one nonexistent shows mixed notice', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  await installCreatorsList(page)
  await installCreatorComparison(page, {
    'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
  })
  await page.goto('/creators/compare?keys=creator:7,creator:99999')
  await expect(page.getByText('Comparing 1 creator')).toBeVisible()
  await expect(page.getByText('One or more requested creators could not be included')).toBeVisible()
  await expect(page.getByText('Brian K. Vaughan')).toBeVisible()
})

test('3462 - two nonexistent keys shows none-available message with back link', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  await installCreatorsList(page)
  await installCreatorComparison(page, {})
  await page.goto('/creators/compare?keys=creator:99999,creator:88888')
  await expect(page.getByText('None of the selected creators are available in your library')).toBeVisible()
  await expect(page.getByRole('link', { name: /Back to Creators/i })).toBeVisible()
})

test('3462 - bad syntax shows readable explanation', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  await page.goto('/creators/compare?keys=badkey,creator:7')
  await expect(page.getByText('Invalid creator key format')).toBeVisible()
  await expect(page.getByText('Back to Creators')).toBeVisible()
})

test('3462 - 5-key URL shows accepted-input explanation', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  await page.goto('/creators/compare?keys=creator:1,creator:2,creator:3,creator:4,creator:5')
  await expect(page.getByText('Comparison accepts 2 to 4 creator keys')).toBeVisible()
  await expect(page.getByText('Back to Creators')).toBeVisible()
})

test('3462 - reload retains valid keys', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  await installCreatorsList(page)
  await installCreatorComparison(page, {
    'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
    'creator:12': comparisonItem('creator:12', 'Steve McNiven'),
  })
  await page.goto('/creators/compare?keys=creator:7,creator:12')
  await page.reload()
  await expect(page.getByText('Comparing 2 creators')).toBeVisible()
})

/**
 * Issue #3624: comparison selection is durable in `?keys=` and survives a
 * round trip to `/creators/compare`, both through browser history and through
 * the explicit Change selection control. Selected checkboxes stay enabled so a
 * single creator can be dropped without rebuilding the set (#3582).
 */
test('3624 - browser back from compare restores the selected creators', async ({
  authenticatedPage,
}) => {
  const page = authenticatedPage
  await installCreatorsList(page)
  await installCreatorComparison(page, {
    'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
    'creator:12': comparisonItem('creator:12', 'Steve McNiven'),
  })

  await page.goto('/creators')
  await page.getByLabel('Select Brian K. Vaughan for comparison').check()
  await page.getByLabel('Select Steve McNiven for comparison').check()
  await expect(page.getByText('2 of 4 selected for comparison')).toBeVisible()

  await page.getByRole('button', { name: 'Compare' }).click()
  await expect(page.getByText('Comparing 2 creators')).toBeVisible()

  await page.goBack()

  await expect(page.getByLabel('Select Brian K. Vaughan for comparison')).toBeChecked()
  await expect(page.getByLabel('Select Steve McNiven for comparison')).toBeChecked()
  await expect(page.getByRole('button', { name: 'Compare' })).toBeVisible()
})

test('3624 - Change selection returns with editable restored checkboxes', async ({
  authenticatedPage,
}) => {
  const page = authenticatedPage
  await installCreatorsList(page)
  await installCreatorComparison(page, {
    'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
    'creator:12': comparisonItem('creator:12', 'Steve McNiven'),
  })

  await page.goto('/creators?keys=creator:7,creator:12')
  await expect(page.getByLabel('Select Brian K. Vaughan for comparison')).toBeChecked()
  await expect(page.getByLabel('Select Steve McNiven for comparison')).toBeChecked()

  await page.getByRole('button', { name: 'Compare' }).click()
  await expect(page.getByText('Comparing 2 creators')).toBeVisible()
  await page.getByRole('link', { name: 'Change selection' }).click()

  await expect(page.getByLabel('Select Brian K. Vaughan for comparison')).toBeChecked()
  await expect(page.getByLabel('Select Steve McNiven for comparison')).toBeChecked()
  expect(new URL(page.url()).searchParams.get('keys')).toBe('creator:7,creator:12')

  // A restored checkbox stays enabled; dropping one writes the exact new set.
  await page.getByLabel('Select Brian K. Vaughan for comparison').uncheck()
  await expect(page.getByText('1 of 4 selected for comparison')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('keys')).toBe('creator:12')
})

/**
 * Issue #4208: the #3624 dedupe/validate contract. A repeated identity must not
 * be counted twice, and an unknown key must be named instead of blanking the
 * comparison, consuming a selection slot, or riding back through Change
 * selection.
 */
test('4208 - duplicate and unknown keys are named, never counted or trusted', async ({
  authenticatedPage,
}) => {
  const page = authenticatedPage
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await installCreatorsList(page)
  const compareRequests = await installCreatorComparison(page, {
    'creator:7': comparisonItem('creator:7', 'Brian K. Vaughan'),
  })

  // The exact QA deep link: one real creator, one repeated identity, one bogus key.
  await page.goto('/creators/compare?keys=creator:7,creator:7,creator:99999999')

  await expect(page.getByText('Comparing 1 creator')).toBeVisible({ timeout: 20000 })
  await expect(page.getByRole('alert')).toContainText('creator:99999999')
  expect(compareRequests).toHaveLength(1)

  // The unknown key is dropped on the way back instead of being handed over.
  await page.getByRole('link', { name: 'Change selection' }).click()
  await expect(page).toHaveURL(/\/creators\?keys=creator%3A7$/)
  await expect(page.getByText('1 of 4 selected for comparison')).toBeVisible()
  await expect(page.getByLabel('Select Brian K. Vaughan for comparison')).toBeChecked()
  await expect(page.getByLabel('Select Steve McNiven for comparison')).not.toBeChecked()
  expect(new URL(page.url()).searchParams.get('keys')).toBe('creator:7')

  // A duplicated list URL collapses to one identity per creator.
  await page.goto('/creators?keys=creator:7,creator:7,creator:12,creator:12')
  await expect(page.getByText('2 of 4 selected for comparison')).toBeVisible()
  await expect
    .poll(() => new URL(page.url()).searchParams.get('keys'))
    .toBe('creator:7,creator:12')
})
