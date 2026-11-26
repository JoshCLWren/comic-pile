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

const ROLL_BOOTSTRAP_PATH = '/api/v2/roll/bootstrap'
// #4822 moved /history off the legacy session index onto the owner-scoped
// activity resource. Exercise the real first-page request the page now makes.
const ACTIVITY_PATH = '/api/v2/activity'

const UNAVAILABLE_BODY = JSON.stringify({ detail: 'service_unavailable' })

let fixtureUserCounter = 0

/**
 * Register a disposable real reader for this test.
 *
 * The bounded loading UI requires a failed request on the page's *first*
 * resource. `rollBootstrapApi.get` resolves a session with
 * `POST /api/v2/reading-sessions` before issuing
 * `GET /api/v2/roll/bootstrap`; with the old fake-token mock setup that POST
 * reached the native backend with an invalid token, entered the refresh loop
 * and never let the bootstrap GET fire. A real token keeps every request
 * except the one under test on the genuine backend, so recovery is proven
 * against real data rather than a fabricated payload.
 */
async function registerReader(page: Page): Promise<string> {
  fixtureUserCounter += 1
  const username = `recovery_${Date.now()}_${fixtureUserCounter}_${process.pid}`
  const password = 'TestPass123!'
  const registered = await page.request.post('/api/v2/auth/register', {
    data: { username, email: `${username}@example.com`, password },
  })
  expect(registered.ok(), `register failed: ${registered.status()}`).toBeTruthy()
  const loggedIn = await page.request.post('/api/v2/auth/login', {
    data: { username, password },
  })
  expect(loggedIn.ok(), `login failed: ${loggedIn.status()}`).toBeTruthy()
  // SAFETY: the test reads only access_token from its own disposable user login.
  const data = (await loggedIn.json()) as { access_token: string }
  expect(data.access_token).toBeTruthy()
  return data.access_token
}

async function installAccessToken(page: Page, token: string): Promise<void> {
  await page.addInitScript((value: string) => {
    localStorage.setItem('auth_token', value)
  }, token)
}

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
  }) => {
    await installAccessToken(page, await registerReader(page))
    const markBootstrapHealthy = await failUntilHealthy(page, ROLL_BOOTSTRAP_PATH)

    await page.goto('/')

    // Bounded loading: progress copy plus recovery, never the bare splash.
    await expect(page.getByText(/Still loading/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0)

    markBootstrapHealthy()
    await recoverInPlace(page, ROLL_BOOTSTRAP_PATH)

    await expect(page.getByLabel('Desktop navigation')).toBeVisible()
    await expect(page.getByText(/Still loading/)).toHaveCount(0)
    await expect(page.getByText('Session Error')).toHaveCount(0)
    await expect(page).toHaveURL(/\/$/)
  })

  test('a failed history first page stays recoverable in place without a reload', async ({
    page,
  }) => {
    await installAccessToken(page, await registerReader(page))
    const markActivityHealthy = await failUntilHealthy(page, ACTIVITY_PATH)

    await page.goto('/history')

    await expect(page.getByText(/Still loading/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0)

    markActivityHealthy()
    await recoverInPlace(page, ACTIVITY_PATH)

    await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
    await expect(page.getByText(/Still loading/)).toHaveCount(0)
    await expect(page).toHaveURL(/\/history$/)
  })
})
