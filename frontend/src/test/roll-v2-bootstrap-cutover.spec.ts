/**
 * Issue #2719: cut the idle Roll screen over to the v2 bootstrap.
 *
 * These browser checks assert the production contract directly:
 * 1. The idle Roll path makes zero requests to the v1 bootstrap alias.
 * 2. The single v2 response is the only pool source (`rollable`, no
 *    `roll_pool` join) and it renders comic-first rows.
 * 3. A d100 pool with a long title stays horizontally contained at phone
 *    width.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import {
  authHeaders,
  createThread,
  gotoRollPage,
} from './helpers'

interface BootstrapPayload {
  rollable?: unknown[]
  roll_pool?: unknown
}

test.describe('Issue #2719: idle Roll v2 bootstrap cutover', () => {
  test('uses exactly one v2 bootstrap source and renders pool rows', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'V2 Bootstrap Thread'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    let legacyBootstrapRequests = 0
    let v2BootstrapRequests = 0
    page.on('request', (request) => {
      if (request.method() !== 'GET') return
      if (request.url().includes('/api/v1/roll/bootstrap')) legacyBootstrapRequests++
      if (request.url().includes('/api/v2/roll/bootstrap')) v2BootstrapRequests++
    })

    const v2Response = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v2/roll/bootstrap') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
    )
    await gotoRollPage(page)
    // SAFETY: the test reads only the two bootstrap fields asserted below.
    const payload = (await (await v2Response).json()) as BootstrapPayload

    expect(v2BootstrapRequests).toBeGreaterThanOrEqual(1)
    expect(legacyBootstrapRequests).toBe(0)
    expect(Array.isArray(payload.rollable)).toBe(true)
    expect(payload.roll_pool).toBeUndefined()

    await expect(
      page.getByTestId('roll-pool-row').filter({ hasText: title }).first(),
    ).toBeVisible({ timeout: 20_000 })
  })

  test('a d100 pool with a long title stays contained at phone width', async ({
    authenticatedWithLargeQueuePage,
  }) => {
    const page = authenticatedWithLargeQueuePage
    const longTitle =
      'The Unfathomably Long Running Cosmic Saga of the Ever Expanding Multiverse Deluxe Anniversary Edition'

    await createThread(page, {
      title: longTitle,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    await page.setViewportSize({ width: 390, height: 844 })

    const headers = await authHeaders(page)
    const seeded = await page.request.post('/api/v1/roll/set-die?die=100', { headers })
    expect(seeded.ok(), `set-die failed: ${seeded.status()}`).toBeTruthy()

    let legacyBootstrapRequests = 0
    page.on('request', (request) => {
      if (
        request.method() === 'GET' &&
        request.url().includes('/api/v1/roll/bootstrap')
      ) {
        legacyBootstrapRequests++
      }
    })

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    const rows = page.getByTestId('roll-pool-row')
    await expect(rows.first()).toBeVisible({ timeout: 20_000 })
    expect(await rows.count()).toBeGreaterThanOrEqual(60)
    await expect(
      page.getByTestId('roll-pool-row').filter({ hasText: longTitle }).first(),
    ).toBeVisible()

    const overflow = await page.evaluate(() => {
      const root = document.getElementById('root')
      return {
        documentOverflow:
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
        rootOverflow: root ? root.scrollWidth - root.clientWidth : 0,
      }
    })
    expect(overflow.documentOverflow).toBeLessThanOrEqual(1)
    expect(overflow.rootOverflow).toBeLessThanOrEqual(1)
    expect(legacyBootstrapRequests).toBe(0)
  })
})
