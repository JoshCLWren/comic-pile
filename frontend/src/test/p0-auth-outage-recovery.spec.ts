import { test, expect } from './auth-fixtures'

/**
 * AUTH outage recovery contract: a transient auth/me failure must surface the
 * degraded-service overlay while the session is preserved, and a successful
 * retry must restore the original route.
 *
 * Mocks are persistent (replyAlways/networkErrorAlways) because the app
 * retries auth validation on a bounded exponential backoff; one-shot replies
 * would exhaust the queue and let later retries hit the real backend, ending
 * the session under test.
 */
test.describe('Auth Outage Recovery', () => {
  const mockUser = {
    id: 1,
    username: 'testuser',
    email: 'test@example.com',
    created_at: '2023-01-01T00:00:00Z',
    last_login: '2023-01-01T00:00:00Z',
    preferences: { theme: 'classic' },
  }

  test('reproduces incident: authenticated visit -> auth/me failure -> degraded state -> recovery -> original route', async ({
    page,
    mockApi,
  }) => {
    let refreshCalls = 0
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/auth/refresh')) refreshCalls += 1
    })
    await page.addInitScript(() => localStorage.setItem('auth_token', 'test-access-token'))
    // Step 1: Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')

    // Verify we're on the roll page and authenticated
    await expect(page.locator('[data-app-shell-ready]')).toBeVisible()
    await expect(page.getByText('Checking authentication...')).not.toBeVisible()
    await expect(page.getByLabel('Desktop navigation')).toBeVisible() // Navigation indicates authenticated state

    // Step 2: Persistent auth/me outage (survives bounded retries)
    mockApi.get('/v1/auth/me').as('authMe').replyAlways(503, {
      message: 'Database unavailable',
      detail: 'database_unavailable',
    })

    // Step 3: Navigate to a route that triggers auth validation
    await page.goto('/queue')
    await page.waitForTimeout(2000)

    // Step 4: Verify degraded service state is shown
    await expect(page.locator('text=Service Unavailable')).toBeVisible()
    await expect(page.locator('text=ComicPile is temporarily unavailable')).toBeVisible()
    await expect(page.locator('text=Your session is still active')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()

    // The authenticated route stays put behind the degraded overlay (the
    // sidebar nav hides while degraded, so the URL is the session anchor).
    await expect(page).toHaveURL(/\/queue/)

    // Step 5: Recover — auth/me starts succeeding again
    mockApi.get('/v1/auth/me').as('authMeRecovery').replyAlways(200, mockUser)

    const recovered = page.waitForResponse(
      (response) => response.url().includes('/v1/auth/me') && response.status() === 200,
    )
    // A background backoff retry may already be in flight when we switch the
    // mock; either it or the explicit retry completes `recovered`.
    await page
      .getByRole('button', { name: 'Try again' })
      .click({ timeout: 2000 })
      .catch(() => undefined)
    await recovered

    // Step 6: Verify recovery on the original route
    await expect(page.locator('text=Service Unavailable')).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).not.toBeVisible()
    await expect(page.getByLabel('Desktop navigation')).toBeVisible() // Still authenticated
    await expect(page.locator('h1')).toContainText('Queue')
    expect(refreshCalls).toBe(0)
    expect(await page.evaluate(() => localStorage.getItem('auth_token'))).toBe('test-access-token')
  })

  test('handles network errors during auth validation', async ({
    page,
    mockApi,
  }) => {
    // Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')
    await expect(page.getByLabel('Desktop navigation')).toBeVisible()

    // Persistent network failure for /auth/me
    mockApi.get('/v1/auth/me').as('authMe').networkErrorAlways('Network Error')

    // Navigate to a protected route
    await page.goto('/thread/1')

    // Wait for auth validation to fail
    await page.waitForTimeout(2000)

    // Verify network error state
    await expect(page.locator('text=Connection Issue')).toBeVisible()
    await expect(page.locator("text=Can't reach ComicPile")).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()

    // Session is preserved: degraded state never bounces to the login screen
    await expect(page).not.toHaveURL('/login')
  })

  test('preserves session after login followed by auth/me 503', async ({
    page,
    mockApi,
  }) => {
    // Start on login page
    await page.goto('/login')

    // Mock successful login but subsequent auth/me failure
    mockApi.post('/v1/auth/login').as('login').reply(200, {
      access_token: 'test-access-token',
      refresh_token: 'refresh-token',
    })
    mockApi.get('/v1/auth/me').as('authMe').replyAlways(503, {
      message: 'Service unavailable',
    })

    // Fill and submit login form
    await page.fill('input[name="username"]', 'testuser')
    await page.fill('input[name="password"]', 'password123')
    const loginDone = page.waitForResponse(
      (response) => response.url().includes('/v1/auth/login') && response.status() === 200,
    )
    await page.getByRole('button', { name: 'Sign In' }).click()
    await loginDone
    await page.waitForTimeout(1000)

    // An outage during hydration must not masquerade as bad credentials
    await expect(page.getByText(/invalid username or password/i)).not.toBeVisible()
    const token = await page.evaluate(() => localStorage.getItem('auth_token'))
    expect(token).toBe('test-access-token')

    // The protected route renders the degraded shell instead of login
    await page.goto('/queue')
    await expect(page.locator('text=Service Unavailable')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    await expect(page).toHaveURL(/\/queue/)
  })

  test('transitions to unauthenticated when auth/me returns 401 after retries', async ({
    page,
    mockApi,
  }) => {
    // Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')
    await expect(page.getByLabel('Desktop navigation')).toBeVisible()

    // Degrade first, then make auth/me definitively unauthorized
    mockApi.get('/v1/auth/me').as('authMe').replyAlways(503, { message: 'Service unavailable' })

    // Navigate to protected route
    await page.goto('/queue')

    // Verify degraded state
    await expect(page.locator('text=Service Unavailable')).toBeVisible()
    await expect(page).toHaveURL(/\/queue/)

    // Retry now hits a definitive 401: silent refresh cannot save the
    // session, so the app must transition to unauthenticated.
    mockApi.get('/v1/auth/me').as('authMe401').replyAlways(401, { message: 'Unauthorized' })
    const sawLogin = page.waitForURL('**/login')
    await page
      .getByRole('button', { name: 'Try again' })
      .click({ timeout: 2000 })
      .catch(() => undefined)
    await sawLogin

    // Verify we're on the login page and navigation is gone
    await expect(page.locator('h1')).toContainText(/welcome/i)
    await expect(page.getByLabel('Desktop navigation')).not.toBeVisible()
  })

  test('automatic retry with exponential backoff', async ({
    page,
    mockApi,
  }) => {
    // Start with authenticated user. Wait for bootstrap auth/me to settle so
    // the ladder below is the only thing left in the mock queue (goto()
    // resolves at domcontentloaded, before React's auth validation runs).
    await mockApi.setupAuthUser()
    const bootstrapped = page.waitForResponse(
      (response) => response.url().includes('/v1/auth/me') && response.status() === 200,
    )
    await page.goto('/')
    await bootstrapped

    // Ladder: two 503s then success. Delay after failure N is
    // ~1s * 2^(N-1) (+10% jitter), so recovery lands around 3-4s —
    // measurably slower than a single fixed delay, well under 10s.
    mockApi.get('/v1/auth/me').as('authMeFirst').replyOnce(503, { message: 'Service unavailable' })
    mockApi.get('/v1/auth/me').as('authMeSecond').replyOnce(503, { message: 'Service unavailable' })
    mockApi.get('/v1/auth/me').as('authMeRecovered').replyOnce(200, mockUser)

    // Navigate to protected route and wait for recovery
    const startTime = Date.now()
    const recovered = page.waitForResponse(
      (response) => response.url().includes('/v1/auth/me') && response.status() === 200,
    )
    await page.goto('/thread/1')
    await recovered

    const endTime = Date.now()
    const totalTime = endTime - startTime

    // Verify exponential backoff took longer than simple delays
    expect(totalTime).toBeGreaterThan(2000)
    expect(totalTime).toBeLessThan(10000)

    // Verify recovery
    await expect(page.locator('text=Service Unavailable')).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).not.toBeVisible()
    await expect(page.getByLabel('Desktop navigation')).toBeVisible()
  })
})
