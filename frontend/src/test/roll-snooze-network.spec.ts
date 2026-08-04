import type { Page, Request } from '@playwright/test'
import { expect, test } from './fixtures'
import { SELECTORS } from './helpers'

interface ObservedRequest {
  method: string
  pathname: string
}

function observeRequests(page: Page): {
  requests: ObservedRequest[]
  stop: () => void
} {
  const requests: ObservedRequest[] = []
  const capture = (request: Request) => {
    requests.push({
      method: request.method(),
      pathname: new URL(request.url()).pathname,
    })
  }

  page.on('request', capture)
  return {
    requests,
    stop: () => page.off('request', capture),
  }
}

function isFullThreadListGet(request: ObservedRequest): boolean {
  return (
    request.method === 'GET' &&
    (request.pathname === '/api/threads/' || request.pathname === '/api/threads')
  )
}

function isRollReconciliationGet(request: ObservedRequest): boolean {
  return (
    request.method === 'GET' &&
    (request.pathname === '/api/roll/bootstrap' ||
      request.pathname === '/api/roll/bootstrap/' ||
      request.pathname === '/api/sessions/current/')
  )
}

async function enterRatingView(page: Page): Promise<string> {
  await page.goto('/')
  await expect(page.locator('#root')).toBeVisible()

  const firstThread = page.locator('[data-roll-pool] [role="button"]').first()
  await expect(firstThread).toBeVisible({ timeout: 10_000 })
  const title = (await firstThread.locator('p').first().textContent())?.trim()
  expect(title).toBeTruthy()

  await firstThread.click()
  await page.getByText('Read Now', { exact: true }).click()
  await expect(page.locator(SELECTORS.rate.snoozeButton)).toBeVisible({ timeout: 10_000 })
  return title as string
}

test.describe('Roll snooze request sequence', () => {
  test('snooze and unsnooze reconcile visible Roll state without a full thread-list reload', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    const title = await enterRatingView(page)
    const observer = observeRequests(page)

    observer.requests.length = 0
    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname === '/api/snooze/' &&
          response.ok(),
      ),
      page.locator(SELECTORS.rate.snoozeButton).click(),
    ])

    const snoozedToggle = page.getByRole('button', { name: /Snoozed \(1\)/i })
    await expect(snoozedToggle).toBeVisible({ timeout: 10_000 })
    await snoozedToggle.click()
    await expect(page.getByText(title, { exact: true })).toBeVisible()

    await expect
      .poll(() => observer.requests.filter(isRollReconciliationGet).length)
      .toBeGreaterThan(0)
    expect(observer.requests.filter(isRollReconciliationGet).length).toBeLessThanOrEqual(1)
    expect(observer.requests.some(isFullThreadListGet)).toBe(false)

    observer.requests.length = 0
    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname.endsWith('/unsnooze') &&
          response.ok(),
      ),
      page.getByRole('button', { name: 'Unsnooze this comic' }).click({ force: true }),
    ])

    await expect(snoozedToggle).toHaveCount(0, { timeout: 10_000 })
    await expect(page.locator('[data-roll-pool]').getByText(title, { exact: true })).toBeVisible()

    await expect
      .poll(() => observer.requests.filter(isRollReconciliationGet).length)
      .toBeGreaterThan(0)
    expect(observer.requests.filter(isRollReconciliationGet).length).toBeLessThanOrEqual(1)
    expect(observer.requests.some(isFullThreadListGet)).toBe(false)

    observer.stop()
  })
})
