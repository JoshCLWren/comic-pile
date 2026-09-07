/**
 * Issue #2298: Crossover Reading Order must not be trapped in a short nested
 * scroller on tablets.
 *
 * The Reading Order list used to render inside `max-h-96 overflow-y-auto`, so
 * at tablet portrait a large crossover confined the user to ~5 visible rows in
 * a fixed-height nested pane — reaching later rows and their actions required
 * fighting an inner scroll region on top of page scroll.
 *
 * These browser checks assert rendered geometry at tablet portrait exactly as
 * reported (800×1094 and 820×1180) against a large seeded crossover:
 *
 * 1. The Reading Order list grows with content and has no fixed max-height /
 *    internal scroll channel (no nested scroller at all).
 * 2. Later rows and their "Open" action are reachable through ordinary page
 *    scroll only — the document, not the list box, owns scrolling.
 * 3. No horizontal overflow of reading-order rows.
 * 4. Phone and wide desktop remain usable (non-regression).
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const TABLET_PORTRAIT = { width: 800, height: 1094 } as const
const TABLET_PORTRAIT_820 = { width: 820, height: 1180 } as const
const PHONE = { width: 390, height: 844 } as const
const WIDE_DESKTOP = { width: 1440, height: 900 } as const

const LARGE_CROSSOVER_MEMBER_COUNT = 14

type CrossoverFixture = {
  groupId: number
  lastThreadId: number
}

async function getCsrfToken(
  page: Page,
  token: string | null,
): Promise<string> {
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
  const csrf = await getCsrfToken(page, token)
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
}

/**
 * Seeds a crossover with many thread-level members. Thread memberships render
 * one Reading Order row each and never carry a sequence position, so the list
 * is exactly `LARGE_CROSSOVER_MEMBER_COUNT` rows tall regardless of issue
 * availability.
 */
async function seedLargeCrossover(page: Page): Promise<CrossoverFixture> {
  const headers = await authHeaders(page)
  const threadIds: number[] = []
  for (let i = 1; i <= LARGE_CROSSOVER_MEMBER_COUNT; i += 1) {
    const thread = await createThread(page, {
      title: `Crossover Series ${String(i).padStart(2, '0')}`,
      format: 'Issue',
      issues_remaining: 1,
      total_issues: 1,
    })
    threadIds.push(thread.id)
  }

  const createResponse = await page.request.post('/api/v1/reading-order-groups/', {
    headers,
    data: { name: 'Tablet QA Reading Order Crossover' },
  })
  expect(
    createResponse.ok(),
    `crossover create failed: ${await createResponse.text()}`,
  ).toBeTruthy()
  const group = (await createResponse.json()) as { id: number }

  for (const threadId of threadIds) {
    const memberResponse = await page.request.post(
      `/api/v1/reading-order-groups/${group.id}/members`,
      {
        headers,
        data: { thread_id: threadId },
      },
    )
    expect(
      memberResponse.ok(),
      `crossover thread member failed: ${await memberResponse.text()}`,
    ).toBeTruthy()
  }

  return { groupId: group.id, lastThreadId: threadIds[threadIds.length - 1]! }
}

async function openCrossoverDetail(page: Page, groupId: number): Promise<void> {
  await page.goto(`/crossovers/${groupId}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Reading Order' })).toBeVisible()
  await expect(page.getByTestId('crossover-reading-order')).toBeVisible()
}

/** Scrolls only the document/window, never any nested scroll container. */
async function scrollPageToBottom(page: Page): Promise<void> {
  await page.evaluate(() => {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: 'instant',
    })
  })
  await page.waitForTimeout(80)
}

async function assertPageOwnsScroll(page: Page): Promise<void> {
  const doc = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))

  expect(
    doc.scrollHeight,
    'the page itself must be taller than the viewport so document scroll can reach later rows',
  ).toBeGreaterThan(doc.clientHeight)
  expect(
    doc.scrollWidth,
    'reading-order rows must not overflow the viewport horizontally',
  ).toBeLessThanOrEqual(doc.innerWidth)
}

async function assertReadingOrderGrowsWithContent(page: Page): Promise<void> {
  const list = page.getByTestId('crossover-reading-order')
  const styles = await list.evaluate((element) => {
    const computed = window.getComputedStyle(element)
    return {
      maxHeight: computed.maxHeight,
      overflowY: computed.overflowY,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }
  })

  expect(
    styles.maxHeight,
    'the Reading Order list must not be pinned to a fixed height',
  ).toBe('none')
  expect(
    styles.overflowY,
    'the Reading Order list must not own its own vertical scroll channel',
  ).not.toBe('auto')
  expect(
    styles.overflowY,
    'the Reading Order list must not own its own scroll channel',
  ).not.toBe('scroll')
  expect(
    styles.clientHeight,
    'the Reading Order list must grow with its rows, not stop at ~5 rows',
  ).toBeGreaterThanOrEqual(styles.scrollHeight - 1)
  expect(
    styles.clientHeight,
    'a large Reading Order must render far beyond the old 384px nested pan',
  ).toBeGreaterThan(380)
}

async function assertLastRowReachableViaPageScroll(
  page: Page,
  fixture: CrossoverFixture,
): Promise<void> {
  const rows = page.getByTestId('crossover-member-row')
  await expect(rows).toHaveCount(LARGE_CROSSOVER_MEMBER_COUNT)

  await scrollPageToBottom(page)

  const lastRow = rows.last()
  // Reached by document scroll only: the window scrolled to the bottom, and
  // the final row is now inside the viewport without any inner scroll input.
  await expect(lastRow).toBeInViewport()

  const listScrollTop = await page
    .getByTestId('crossover-reading-order')
    .evaluate((element) => element.scrollTop)
  expect(
    listScrollTop,
    'reaching the final row must not require scrolling the list box itself',
  ).toBe(0)

  // The action associated with the final row is clickable and navigates.
  const openAction = lastRow.getByRole('link', { name: 'Open' })
  await expect(openAction).toBeVisible()
  await openAction.click()
  await expect(page).toHaveURL(new RegExp(`/threads/${fixture.lastThreadId}$`))
}

test.describe('Crossover Reading Order nested scroller (#2298)', () => {
  test('tablet portrait renders the full Reading Order with page-scroll reachability', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_PORTRAIT)

    const fixture = await seedLargeCrossover(page)
    await openCrossoverDetail(page, fixture.groupId)

    await assertReadingOrderGrowsWithContent(page)
    await assertPageOwnsScroll(page)
    await assertLastRowReachableViaPageScroll(page, fixture)
  })

  test('second reported tablet size (820×1180) is equally free of nested scroll', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_PORTRAIT_820)

    const fixture = await seedLargeCrossover(page)
    await openCrossoverDetail(page, fixture.groupId)

    await assertReadingOrderGrowsWithContent(page)
    await assertPageOwnsScroll(page)
    await assertLastRowReachableViaPageScroll(page, fixture)
  })

  test('phone and wide desktop remain usable with no horizontal overflow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const fixture = await seedLargeCrossover(page)

    for (const viewport of [PHONE, WIDE_DESKTOP]) {
      await page.setViewportSize(viewport)
      await openCrossoverDetail(page, fixture.groupId)

      await assertReadingOrderGrowsWithContent(page)
      await assertPageOwnsScroll(page)
      await assertLastRowReachableViaPageScroll(page, fixture)
    }
  })
})