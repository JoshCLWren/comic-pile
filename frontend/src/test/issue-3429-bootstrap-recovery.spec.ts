/**
 * Issue #3429: the app could sit on a loading splash for 45+ seconds until a
 * manual reload.
 *
 * Todd reported /roll and /history stuck on their loading splash for over 45
 * seconds on a cold first load, with a manual reload restoring service
 * immediately. A bootstrap request that is slow to start, slow to answer, or
 * dropped outright used to leave both pages on a bare "Loading..." screen with
 * no signal and no way forward, so recovery required a full page reload.
 *
 * These browser checks cover both halves of the corrected contract:
 *
 * 1. A failing first page bounds the loading state with real progress copy and
 *    an in-place Retry affordance instead of an indefinite splash.
 * 2. Once the backend recovers, Retry transitions straight into the normal app
 *    with no reload and no navigation away from the route under test.
 *
 * 503 is used on purpose. It is the status the shared retry policy keeps
 * retrying, so the bounded state is exercised exactly as production sees it,
 * and the API client deliberately stays console-silent for 503 so this outage
 * does not pollute browser-health evidence.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './auth-fixtures'

const ROLL_BOOTSTRAP_PATH = '/api/v1/roll/bootstrap'
const SESSION_LIST_PATH = '/api/v1/sessions/'

const UNAVAILABLE_BODY = JSON.stringify({ detail: 'service_unavailable' })

/**
 * Fail one GET endpoint until the returned callback is invoked, then pass it
 * through to the real backend so recovery is proven against genuine data
 * rather than a fabricated stub payload.
 */
async function failUntilHealthy(page: Page, pathname: string): Promise<() => void> {
  let healthy = false
  await page.route(
    (url) => url.pathname === pathname,
    async (route) => {
      if (healthy) {
        await route.fallback()
        return
      }
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: UNAVAILABLE_BODY,
      })
    },
  )
  return () => {
    healthy = true
  }
}

/**
 * Recover without a forced reload.
 *
 * The Retry click is best-effort: a scheduled retry can win the race and boot
 * the app on its own, which satisfies the same contract. The response wait and
 * the final assertions are what prove the transition happened.
 */
async function recoverInPlace(page: Page, pathname: string): Promise<void> {
  const recovered = page.waitForResponse(
    (response) => response.url().includes(pathname) && response.status() === 200,
    { timeout: 30_000 },
  )
  await page
    .getByRole('button', { name: 'Retry' })
    .click({ timeout: 5_000 })
    .catch(() => undefined)
  await recovered
}

test.describe('Bootstrap recovery (issue #3429)', () => {
  test('a failed roll bootstrap stays recoverable in place without a reload', async ({
    page,
    mockApi,
  }) => {
    const markBootstrapHealthy = await failUntilHealthy(page, ROLL_BOOTSTRAP_PATH)

    await mockApi.setupAuthUser()
    await page.goto('/')

    // Bounded loading: progress copy plus recovery, never the bare splash.
    await expect(page.getByText('Still loading')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0)

    markBootstrapHealthy()
    await recoverInPlace(page, ROLL_BOOTSTRAP_PATH)

    await expect(page.getByLabel('Desktop navigation')).toBeVisible()
    await expect(page.getByText('Still loading')).toHaveCount(0)
    await expect(page.getByText('Session Error')).toHaveCount(0)
    await expect(page).toHaveURL(/\/$/)
  })

  test('a failed history first page stays recoverable in place without a reload', async ({
    page,
    mockApi,
  }) => {
    const markSessionsHealthy = await failUntilHealthy(page, SESSION_LIST_PATH)

    await mockApi.setupAuthUser()
    await page.goto('/history')

    await expect(page.getByText('Still loading')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0)

    markSessionsHealthy()
    await recoverInPlace(page, SESSION_LIST_PATH)

    await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
    await expect(page.getByText('Still loading')).toHaveCount(0)
    await expect(page).toHaveURL(/\/history$/)
  })
})
