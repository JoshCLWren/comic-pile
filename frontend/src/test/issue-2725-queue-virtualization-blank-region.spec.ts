import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'
import {
  queueCardMentionsTitle,
  readAppScrollState,
  readQueueViewport,
  scrollAppTo,
  scrollAppUntil,
  waitForQueueReady,
} from './helpers'

/**
 * Production Queue blank-region regression (#2725).
 *
 * The page scroller is `#root`, not the window. A suite that scrolls
 * `window`, injects a fake virtualizer, or counts every mounted card will
 * miss the failure: only the first virtualization window stays painted
 * while the spacer grows into a giant empty region.
 *
 * This spec uses the real Queue composition path, a 250-thread fixture,
 * and the real `#root` scroller.
 */

const FIRST_PAGE_SIZE = 50
const TOTAL_THREADS = 250

async function expectViewportPainted(page: Page, label: string): Promise<void> {
  const snapshot = await readQueueViewport(page)
  expect(
    snapshot.visibleCount,
    `${label}: viewport must keep painted Queue cards (got ${JSON.stringify(snapshot)})`,
  ).toBeGreaterThan(0)
  expect(
    snapshot.mounted,
    `${label}: virtualization must window rows instead of mounting the whole Queue`,
  ).toBeLessThan(TOTAL_THREADS)
}

async function threadIsVisible(page: Page, title: string): Promise<boolean> {
  const snapshot = await readQueueViewport(page)
  return snapshot.visibleTitles.some((text) => queueCardMentionsTitle(text, title))
}

async function scrollUntilThreadVisible(page: Page, title: string): Promise<void> {
  await scrollAppUntil(
    page,
    async () => threadIsVisible(page, title),
    `visible card for ${title}`,
  )
  await expectViewportPainted(page, `after reaching ${title}`)
}

test.describe('Queue virtualization blank region (#2725)', () => {
  test.describe.configure({ timeout: 480_000 })
  test('keeps painted cards while scrolling a 250-thread Queue on the real page scroller', async ({
    authenticatedWithProductionQueuePage,
  }) => {
    const page = authenticatedWithProductionQueuePage
    await page.setViewportSize({ width: 1440, height: 900 })

    const listUrls: string[] = []
    page.on('request', (request) => {
      const url = request.url()
      if (url.includes('/v1/threads/') || url.includes('/api/threads')) {
        if (request.method() === 'GET') {
          listUrls.push(url)
        }
      }
    })

    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await waitForQueueReady(page)
    await expect(page.getByTestId('queue-thread-item').first()).toBeVisible()
    await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toBeVisible()

    const scroller = await readAppScrollState(page)
    expect(
      scroller.rootOverflowY === 'auto' || scroller.rootOverflowY === 'scroll',
      'production page scrolling is owned by #root',
    ).toBe(true)
    expect(scroller.rootScrollHeight).toBeGreaterThan(scroller.rootClientHeight)

    const firstPageBounded = listUrls.some((url) => /page_size=50\b/.test(url))
    expect(
      firstPageBounded,
      `first Queue request must stay bounded to ${FIRST_PAGE_SIZE}: ${listUrls.join(', ')}`,
    ).toBe(true)

    await expectViewportPainted(page, 'initial page')
    const initial = await readQueueViewport(page)
    expect(initial.mounted).toBeLessThanOrEqual(FIRST_PAGE_SIZE)
    expect(initial.visibleIndexes.some((index) => index >= 0 && index < 15)).toBe(true)

    const listRequestsBeforeScroll = listUrls.length

    await scrollUntilThreadVisible(page, 'Test Thread 40')
    await expectViewportPainted(page, 'past the first painted window')
    const midFirstPage = await readQueueViewport(page)
    expect(
      midFirstPage.visibleIndexes.some((index) => index >= 20),
      `scrolling #root must advance the virtual window, not leave #9–#11 stranded: ${JSON.stringify(midFirstPage)}`,
    ).toBe(true)

    await scrollUntilThreadVisible(page, 'Test Thread 100')
    await expectViewportPainted(page, 'page 2 boundary')
    expect(listUrls.length).toBeGreaterThan(listRequestsBeforeScroll)

    await scrollUntilThreadVisible(page, 'Test Thread 150')
    await expectViewportPainted(page, 'page 3 boundary')

    await scrollUntilThreadVisible(page, 'Test Thread 200')
    await expectViewportPainted(page, 'page 4 boundary')

    await scrollUntilThreadVisible(page, 'Test Thread 250')
    await expectViewportPainted(page, 'final page')
    await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toHaveCount(0)

    await scrollAppTo(page, 0)
    await expect.poll(async () => {
      const snapshot = await readQueueViewport(page)
      return snapshot.visibleTitles.some((text) => queueCardMentionsTitle(text, 'Test Thread 1'))
    }).toBe(true)
    await expectViewportPainted(page, 'after scrolling back to top')

    await scrollUntilThreadVisible(page, 'Test Thread 75')
    await expectViewportPainted(page, 'after scrolling back down through loaded pages')

    const queueContainer = page.locator('#queue-container')
    const overflowY = await queueContainer.evaluate((el) => window.getComputedStyle(el).overflowY)
    expect(['auto', 'scroll'].includes(overflowY)).toBe(false)
  })

  test('keeps painted cards across sort keys on a narrower viewport', async ({
    authenticatedWithProductionQueuePage,
  }) => {
    const page = authenticatedWithProductionQueuePage
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await waitForQueueReady(page)

    const sorts = ['Title', 'Position', 'Recently added'] as const
    for (const sort of sorts) {
      await page.getByRole('button', { name: sort, exact: true }).click()
      await waitForQueueReady(page)
      await expect(page.getByTestId('queue-thread-item').first()).toBeVisible()
      await expectViewportPainted(page, `${sort} initial`)

      await scrollAppUntil(
        page,
        async () => {
          const snapshot = await readQueueViewport(page)
          return snapshot.visibleCount > 0 && snapshot.visibleIndexes.some((index) => index >= 20)
        },
        `${sort} advanced virtual window`,
      )
      await expectViewportPainted(page, `${sort} after scrolling`)

      await scrollAppTo(page, 0)
      await expectViewportPainted(page, `${sort} after returning to top`)
    }
  })
})
