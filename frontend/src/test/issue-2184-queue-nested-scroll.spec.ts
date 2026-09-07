/**
 * Issue #2184: Queue must keep the same scroll surface before and after the
 * virtualization threshold (>50 threads).
 *
 * Before the fix, crossing the threshold created a fixed-height nested
 * `overflowY: auto` container inside `#queue-container` — users experienced a
 * sudden "boxed-in" Queue appearing partway through scrolling.
 *
 * After the fix, the window owns scrolling at every thread count:
 *
 * 1. No nested vertical scroll channel on `#queue-container` in either state.
 * 2. No fixed-height box forces a second scrollbar.
 * 3. The last thread is reachable by window scroll only (`scrollTop === 0`
 *    on `#queue-container`).
 * 4. Window scroll to the top reveals the first thread again.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { waitForQueueReady } from './helpers'

const NO_NESTED_VERTICAL = new Set(['auto', 'scroll'])

async function assertNoNestedScroll(page: import('@playwright/test').Page): Promise<void> {
  await waitForQueueReady(page)
  const container = page.locator('#queue-container')
  await expect(container).toBeVisible()
  await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toBeVisible()

  const before = await container.evaluate((element) => {
    const style = window.getComputedStyle(element)
    return {
      overflowY: style.overflowY,
      inlineHeight: (element as HTMLElement).style.height,
    }
  })
  expect(
    NO_NESTED_VERTICAL.has(before.overflowY),
    'pre-threshold #queue-container must not own a nested vertical scroll channel',
  ).toBe(false)
  expect(before.inlineHeight, 'pre-threshold #queue-container must have no fixed-height inline style').toBe('')

  // Scroll the window (the only scroll surface) to trigger the next page load.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))

  // After the threshold is crossed the virtualized list replaces the plain
  // list. The same no-nested-scroll contract must still hold.
  await expect(page.getByText('Test Thread 60')).toBeVisible({ timeout: 10000 })

  const after = await container.evaluate((element) => {
    const style = window.getComputedStyle(element)
    return {
      overflowY: style.overflowY,
      inlineHeight: (element as HTMLElement).style.height,
      scrollTop: element.scrollTop,
    }
  })
  expect(
    NO_NESTED_VERTICAL.has(after.overflowY),
    'post-threshold #queue-container must not own a nested vertical scroll channel',
  ).toBe(false)
  expect(after.inlineHeight, 'post-threshold #queue-container must have no fixed-height inline style').toBe('')
  expect(after.scrollTop, 'queue-list scrollTop must stay 0 — the window owns scrolling').toBe(0)

  // Scroll back to the top to confirm the first thread remains reachable.
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect(page.getByText('Test Thread 1')).toBeVisible()
}

test.describe('Queue nested scroll after threshold (#2184)', () => {
  test('desktop keeps the window as the single scroll surface across the threshold', async ({
    authenticatedWithLargeQueuePage,
  }) => {
    const page = authenticatedWithLargeQueuePage
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await assertNoNestedScroll(page)
  })

  test('narrow/mobile keeps the window as the single scroll surface across the threshold', async ({
    authenticatedWithLargeQueuePage,
  }) => {
    const page = authenticatedWithLargeQueuePage
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await assertNoNestedScroll(page)
  })
})
