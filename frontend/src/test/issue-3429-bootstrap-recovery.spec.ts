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
 *
 * These tests use a genuinely registered user, not a mocked auth session. The
 * shipped Roll client resolves its reading session (`POST /v2/readingSessions`)
 * before it reads `GET /v2/roll/bootstrap`; a fake token answers the mocked
 * auth endpoints but is rejected by that real resolution write (401), so the
 * bootstrap request is never issued and a fake-token "recovery" can never reach
 * the backend. A real token keeps the fail-then-recover path on genuine data.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { test } from './auth-fixtures'
import { generateTestUser } from './helpers'

const ROLL_BOOTSTRAP_PATH = '/api/v2/roll/bootstrap'
// #4822 moved /history off the legacy session index onto the owner-scoped
// activity resource. Exercise the real first-page request the page now makes.
const ACTIVITY_PATH = '/api/v2/activity'

const UNAVAILABLE_BODY = JSON.stringify({ detail: 'service_unavailable' })

/**
 * Register a real user before navigation and install its token for the page.
 *
 * The reading-session resolution write and the post-recovery read both need a
 * credential the backend accepts; a mocked auth session cannot satisfy them.
 */
async function registerRealUser(page: Page, request: APIRequestContext): Promise<void> {
  const user = generateTestUser()
  const registered = await request.post('/api/v2/auth/register', {
    data: {
      username: user.username,
      email: user.email,
      password: user.password,
    },
  })
  expect(registered.ok(), `register failed: ${registered.status()}`).toBeTruthy()
  const loggedIn = await request.post('/api/v2/auth/login', {
    data: { username: user.username, password: user.password },
  })
  expect(loggedIn.ok(), `login failed: ${loggedIn.status()}`).toBeTruthy()
  // SAFETY: the login response was asserted ok above; this reads only the access token field
  const body = (await loggedIn.json()) as { access_token?: string }
  const token = body.access_token
  expect(token, 'login response must carry an access token').toBeTruthy()
  await page.addInitScript((accessToken: string) => {
    localStorage.setItem('auth_token', accessToken)
    // SAFETY: the api client reads this global token slot, which the test sets directly
    const clientWindow = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
    clientWindow.__COMIC_PILE_ACCESS_TOKEN = accessToken
  }, token!)
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
 * Assert the bounded, recoverable state without pinning one transient copy.
 *
 * The first failure replaces the bare splash with progress copy and Retry. If
 * the shared retry budget is exhausted before the assertion, the explicit
 * failure panel keeps the same Retry affordance. Both are the #3429 contract;
 * the only forbidden state is an indefinite bare "Loading..." splash.
 */
async function expectBoundedRecovery(page: Page): Promise<void> {
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0)
  await expect(
    page
      .getByText(/Still loading/)
      .or(page.getByText('Session Error'))
      .or(page.getByText('Failed to load activity')),
  ).toBeVisible()
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
    request,
  }) => {
    const markBootstrapHealthy = await failUntilHealthy(page, ROLL_BOOTSTRAP_PATH)

    await registerRealUser(page, request)
    await page.goto('/')

    // Bounded loading: progress copy or the explicit failure panel, plus
    // recovery — never the bare splash.
    await expectBoundedRecovery(page)

    markBootstrapHealthy()
    await recoverInPlace(page, ROLL_BOOTSTRAP_PATH)

    await expect(page.getByLabel('Desktop navigation')).toBeVisible()
    await expect(page.getByText(/Still loading/)).toHaveCount(0)
    await expect(page.getByText('Session Error')).toHaveCount(0)
    await expect(page).toHaveURL(/\/$/)
  })

  test('a failed history first page stays recoverable in place without a reload', async ({
    page,
    request,
  }) => {
    const markActivityHealthy = await failUntilHealthy(page, ACTIVITY_PATH)

    await registerRealUser(page, request)
    await page.goto('/history')

    await expectBoundedRecovery(page)

    markActivityHealthy()
    await recoverInPlace(page, ACTIVITY_PATH)

    await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
    await expect(page.getByText(/Still loading/)).toHaveCount(0)
    await expect(page).toHaveURL(/\/history$/)
  })
})
