/**
 * Issue #2774: personal creators browse page.
 *
 * Acceptance contract exercised here (browser behavior the unit tests cannot
 * prove):
 * 1. `/creators` is reachable from the normal app navigation — the desktop
 *    sidebar secondary list and the phone `More` surface.
 * 2. The default view renders personal name, average, rating count, and compact
 *    roles from the bounded #2775 discovery contract.
 * 3. Name search and alphabetical/most-rated/personal-average ordering are
 *    server-side requests against `/api/v1/creators`, never client-side work.
 * 4. Load more appends a later page without dropping or duplicating rows.
 * 5. Two distinct canonical creators sharing a display name stay separate rows
 *    with separate detail links, and a row opens the existing creator detail
 *    page.
 * 6. Empty library and partial-coverage states are truthful.
 * 7. Browsing never issues a live ComicVine/provider request.
 * 8. Phone width stays a single readable column with no horizontal overflow.
 *
 * The list payload is fulfilled at the network layer so this spec asserts
 * rendered behavior, not backend fixtures. Backend coverage for the discovery
 * contract lives in `tests/test_creator_list_api.py`.
 */
import { expect, type Page, type Route } from '@playwright/test'
import { test } from './fixtures'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }

interface CreatorListPayload {
  items: Array<{
    canonical_creator_key: string
    display_name: string
    normalized_roles: string[]
    average_rating: number | null
    ratings_count: number
  }>
  total: number
  limit: number
  offset: number
  coverage: {
    rated_issues_total: number
    rated_issues_with_creator_metadata: number
    ratings_complete: boolean
    read_unrated_issues_total: number
    read_unrated_issues_with_creator_metadata: number
    read_unrated_complete: boolean
    unread_issues_total: number
    unread_issues_with_creator_metadata: number
    upcoming_complete: boolean
  }
}

const COMPLETE_COVERAGE = {
  rated_issues_total: 3,
  rated_issues_with_creator_metadata: 3,
  ratings_complete: true,
  read_unrated_issues_total: 0,
  read_unrated_issues_with_creator_metadata: 0,
  read_unrated_complete: true,
  unread_issues_total: 0,
  unread_issues_with_creator_metadata: 0,
  upcoming_complete: true,
}

function creatorRow(
  key: string,
  displayName: string,
  overrides: Partial<CreatorListPayload['items'][number]> = {},
) {
  return {
    canonical_creator_key: key,
    display_name: displayName,
    normalized_roles: ['writer'],
    average_rating: 4.5,
    ratings_count: 2,
    ...overrides,
  }
}

/** The list endpoint, answered from `respond` with the requested page params. */
async function installCreatorsList(
  page: Page,
  respond: (params: URLSearchParams) => CreatorListPayload,
) {
  const requests: URLSearchParams[] = []
  await page.route(
    (url) => url.pathname === '/api/v1/creators',
    async (route: Route) => {
      const params = new URL(route.request().url()).searchParams
      requests.push(params)
      await route.fulfill({ json: respond(params) })
    },
  )
  return requests
}

async function installCreatorsDetail(page: Page) {
  await page.route(
    (url) => url.pathname.startsWith('/api/v1/creators/'),
    (route) =>
      route.fulfill({
        json: {
          summary: {
            canonical_creator_key: 'creator:7',
            display_name: 'Brian K. Vaughan',
            normalized_roles: ['writer', 'editor'],
            average_rating: 4.5,
            ratings_count: 2,
            read_unrated_count: 0,
            upcoming_count: 0,
          },
          coverage: COMPLETE_COVERAGE,
          role_stats: [],
          rated_issues: [],
          read_unrated_issues: [],
          upcoming_issues: [],
          next_cursor: null,
        },
      }),
  )
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const doc = document.scrollingElement ?? document.documentElement
    return { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth }
  })
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
}

test.describe('Issue #2774: creators browse page', () => {
  test('desktop sidebar reaches the browse page and renders personal rows', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const requests = await installCreatorsList(page, (params) => ({
      items: [
        creatorRow('creator:7', 'Brian K. Vaughan', {
          normalized_roles: ['writer', 'editor'],
          ratings_count: 7,
        }),
        creatorRow('creator:12', 'Steve McNiven', {
          normalized_roles: ['artist'],
          average_rating: null,
          ratings_count: 1,
        }),
      ],
      total: 2,
      limit: Number(params.get('limit') ?? 20),
      offset: Number(params.get('offset') ?? 0),
      coverage: COMPLETE_COVERAGE,
    }))

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page
      .getByRole('navigation', { name: 'Desktop navigation' })
      .getByRole('link', { name: 'Creators page' })
      .click()
    await expect(page).toHaveURL(/\/creators$/)

    await expect(page.getByRole('heading', { name: 'Creators you rated' })).toBeVisible({
      timeout: 20000,
    })
    await expect(page.getByText('Brian K. Vaughan')).toBeVisible()
    await expect(page.getByText('writer, editor')).toBeVisible()
    await expect(page.getByText('7 rated issues')).toBeVisible()
    await expect(page.getByText('4.5★')).toBeVisible()
    await expect(page.getByText('1 rated issue')).toBeVisible()
    await expect(page.getByText('Showing 2 of 2 creators')).toBeVisible()

    // The default view is one bounded page, ordered server-side by name.
    expect(requests).toHaveLength(1)
    expect(requests[0].get('sort')).toBe('name')
    expect(Number(requests[0].get('limit'))).toBeLessThanOrEqual(50)
    expect(requests[0].get('search')).toBeNull()

    await expectNoHorizontalOverflow(page)
  })

  test('search and ordering are server-side requests, not client sorting', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const requests = await installCreatorsList(page, (params) => {
      const search = params.get('search')
      const items = search ? [creatorRow('creator:7', 'Brian K. Vaughan')] : []
      return {
        items,
        total: items.length,
        limit: Number(params.get('limit') ?? 20),
        offset: 0,
        coverage: COMPLETE_COVERAGE,
      }
    })

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('No rated creators yet. Rating an issue adds its creators here.')).toBeVisible({
      timeout: 20000,
    })

    await page.getByLabel('Search creators by name').fill('vaughan')
    await expect(page.getByText('Brian K. Vaughan')).toBeVisible({ timeout: 20000 })
    // The empty-library state resolves into a search result set.
    await expect(page.getByText('Showing 1 of 1 creators')).toBeVisible()

    await page.getByLabel('Sort').selectOption('average_rating')
    await expect(page.getByText('Brian K. Vaughan')).toBeVisible()

    const searches = requests.filter((params) => params.get('search') !== null)
    expect(searches).toHaveLength(1)
    expect(searches[0].get('search')).toBe('vaughan')
    expect(requests.at(-1)!.get('sort')).toBe('average_rating')
    // A keystroke must not fan out one request per character.
    expect(requests.length).toBeLessThan(5)
  })

  test('an empty search result is distinct from an empty library', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page, (params) => ({
      items: [],
      total: 0,
      limit: Number(params.get('limit') ?? 20),
      offset: 0,
      coverage: COMPLETE_COVERAGE,
    }))

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('No rated creators yet. Rating an issue adds its creators here.')).toBeVisible({
      timeout: 20000,
    })

    await page.getByLabel('Search creators by name').fill('Nobody')
    await expect(page.getByText('No creators match these filters.')).toBeVisible({ timeout: 20000 })
  })

  test('load more appends a later page without duplicating a repeated row', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const requests = await installCreatorsList(page, (params) => {
      const offset = Number(params.get('offset') ?? 0)
      const limit = Number(params.get('limit') ?? 20)
      if (offset === 0) {
        return {
          items: [creatorRow('creator:7', 'Brian K. Vaughan'), creatorRow('creator:9', 'Alex Kim')],
          total: 3,
          limit,
          offset,
          coverage: COMPLETE_COVERAGE,
        }
      }
      // The server repeats `creator:9` at the page boundary; the page must not.
      return {
        items: [creatorRow('creator:9', 'Alex Kim'), creatorRow('creator:21', 'Jill Thompson')],
        total: 3,
        limit,
        offset,
        coverage: COMPLETE_COVERAGE,
      }
    })

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Showing 2 of 3 creators')).toBeVisible({ timeout: 20000 })

    await page.getByRole('button', { name: 'Load more' }).click()
    await expect(page.getByText('Showing 3 of 3 creators')).toBeVisible({ timeout: 20000 })
    await expect(page.getByText('Jill Thompson')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0)

    // Alex Kim is one canonical creator even though the server repeated the row.
    await expect(page.getByRole('link', { name: /Alex Kim/ })).toHaveCount(1)
    expect(requests.map((params) => params.get('offset'))).toEqual(['0', '2'])
  })

  test('two distinct creators sharing a display name stay separate rows', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page, (params) => ({
      items: [creatorRow('creator:7', 'Alex Kim'), creatorRow('creator:9', 'Alex Kim')],
      total: 2,
      limit: Number(params.get('limit') ?? 20),
      offset: 0,
      coverage: COMPLETE_COVERAGE,
    }))

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    const links = page.getByRole('link', { name: /Alex Kim/ })
    await expect(links).toHaveCount(2)
    await expect(links.nth(0)).toHaveAttribute('href', '/creators/creator%3A7')
    await expect(links.nth(1)).toHaveAttribute('href', '/creators/creator%3A9')
  })

  test('a row opens the existing creator detail page', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page, (params) => ({
      items: [creatorRow('creator:7', 'Brian K. Vaughan')],
      total: 1,
      limit: Number(params.get('limit') ?? 20),
      offset: 0,
      coverage: COMPLETE_COVERAGE,
    }))
    await installCreatorsDetail(page)

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await page.getByRole('link', { name: /Brian K. Vaughan/ }).click()
    await expect(page).toHaveURL(/\/creators\/creator%3A7$/)
    await expect(page.getByRole('heading', { name: 'Brian K. Vaughan' })).toBeVisible({
      timeout: 20000,
    })
  })

  test('partial metadata coverage is disclosed as a lower bound', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page, (params) => ({
      items: [creatorRow('creator:7', 'Brian K. Vaughan')],
      total: 1,
      limit: Number(params.get('limit') ?? 20),
      offset: 0,
      coverage: { ...COMPLETE_COVERAGE, ratings_complete: false },
    }))

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(/Partial list: some rated issues are still missing creator metadata/)).toBeVisible({
      timeout: 20000,
    })
  })

  test('browsing never contacts a live provider', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await installCreatorsList(page, (params) => ({
      items: [creatorRow('creator:7', 'Brian K. Vaughan')],
      total: 1,
      limit: Number(params.get('limit') ?? 20),
      offset: 0,
      coverage: COMPLETE_COVERAGE,
    }))

    const providerRequests: string[] = []
    page.on('request', (request) => {
      if (/comicvine|comicvineapi/i.test(request.url())) {
        providerRequests.push(request.url())
      }
    })

    await page.goto('/creators', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Brian K. Vaughan')).toBeVisible({ timeout: 20000 })
    expect(providerRequests).toEqual([])
  })

  test('phone keeps a single column reachable from the More surface', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await installCreatorsList(page, (params) => ({
      items: [
        creatorRow('creator:7', 'A Very Long Creator Display Name That Must Wrap Without Overflow', {
          normalized_roles: ['writer', 'penciler', 'inker', 'colorist', 'letterer'],
          ratings_count: 12,
        }),
      ],
      total: 1,
      limit: Number(params.get('limit') ?? 20),
      offset: 0,
      coverage: COMPLETE_COVERAGE,
    }))

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'More pages' }).click()
    await page.locator('#secondary-navigation').getByRole('link', { name: 'Creators' }).click()
    await expect(page).toHaveURL(/\/creators$/)

    await expect(page.getByLabel('Search creators by name')).toBeVisible({ timeout: 20000 })
    await expect(page.getByLabel('Sort')).toBeVisible()

    const geometry = await page.evaluate(() => {
      const doc = document.scrollingElement ?? document.documentElement
      const controls = document.querySelector('#creators-search')?.getBoundingClientRect()
      const sort = document.querySelector('#creators-sort')?.getBoundingClientRect()
      const list = document.querySelector('[aria-labelledby="creators-results-heading"]')
      return {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        controlsLeft: controls?.left ?? null,
        controlsRight: controls ? controls.right : null,
        sortLeft: sort?.left ?? null,
        sortRight: sort ? sort.right : null,
        listColumns: list
          ? window.getComputedStyle(list.querySelector('ul') ?? list).gridTemplateColumns
          : null,
      }
    })

    expect(geometry.controlsLeft).not.toBeNull()
    expect(geometry.controlsLeft!).toBeGreaterThanOrEqual(-1)
    expect(geometry.controlsRight!).toBeLessThanOrEqual(geometry.clientWidth + 1)
    expect(geometry.sortLeft!).toBeGreaterThanOrEqual(-1)
    expect(geometry.sortRight!).toBeLessThanOrEqual(geometry.clientWidth + 1)
    // A single-column stack: the browse list is not a horizontal track.
    expect(geometry.listColumns === null || !geometry.listColumns.includes(' ')).toBe(true)

    await expectNoHorizontalOverflow(page)
  })
})
