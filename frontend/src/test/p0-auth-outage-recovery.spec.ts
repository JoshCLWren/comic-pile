import { test, expect } from '../fixtures/auth-fixtures'

test.describe('Auth Outage Recovery', () => {
  test('reproduces incident: authenticated visit -> auth/me failure -> degraded state -> recovery -> original route', async ({
    page,
    mockApi,
  }) => {
    // Step 1: Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')
    
    // Verify we're on the roll page and authenticated
    await expect(page.locator('[data-app-shell-ready]')).toBeVisible()
    await expect(page.getByText('Checking authentication...')).not.toBeVisible()
    await expect(page.locator('nav')).toBeVisible() // Navigation indicates authenticated state

    // Step 2: Mock /auth/me to return 503 service unavailable
    mockApi.get('/v1/auth/me').as('authMe')
      .reply(503, { 
        message: 'Database unavailable',
        detail: 'database_unavailable'
      })

    // Step 3: Navigate to a route that triggers auth validation
    await page.goto('/queue')
    
    // Wait for the auth validation to occur
    await page.waitForTimeout(2000)
    
    // Step 4: Verify degraded service state is shown
    await expect(page.locator('text=Service Unavailable')).toBeVisible()
    await expect(page.locator('text=ComicPile is temporarily unavailable')).toBeVisible()
    await expect(page.locator('text=Your session is still active')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    
    // Verify the original page content is still there (degraded state overlay)
    await expect(page.locator('nav')).toBeVisible() // Navigation should still be visible
    
    // Step 5: Mock successful auth recovery
    mockApi.get('/v1/auth/me').as('authMeRecovery')
      .reply(200, {
        id: 1,
        username: 'testuser',
        email: 'test@example.com',
        created_at: '2023-01-01T00:00:00Z',
        last_login: '2023-01-01T00:00:00Z',
        preferences: { theme: 'classic' }
      })

    // Step 6: Click retry button
    await page.getByRole('button', { name: 'Try again' }).click()
    
    // Wait for retry to complete
    await page.waitForResponse(response => 
      response.url().includes('/v1/auth/me') && response.status() === 200
    )
    
    // Step 7: Verify recovery and return to original route
    await expect(page.locator('text=Service Unavailable')).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).not.toBeVisible()
    await expect(page.locator('nav')).toBeVisible() // Still authenticated
    
    // Verify we're still on the queue page
    await expect(page.locator('h1')).toContainText('Queue')
  })

  test('handles network errors during auth validation', async ({
    page,
    mockApi,
  }) => {
    // Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')
    
    // Mock network error for /auth/me
    mockApi.get('/v1/auth/me').as('authMe')
      .networkError('Network Error')

    // Navigate to a protected route
    await page.goto('/thread/1')
    
    // Wait for auth validation to fail
    await page.waitForTimeout(2000)
    
    // Verify network error state
    await expect(page.locator('text=Connection Issue')).toBeVisible()
    await expect(page.locator("text=Can't reach ComicPile")).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    
    // Verify session is preserved (navigation still visible)
    await expect(page.locator('nav')).toBeVisible()
  })

  test('preserves session after login followed by auth/me 503', async ({
    page,
    mockApi,
  }) => {
    // Start on login page
    await page.goto('/login')
    
    // Mock successful login but subsequent auth/me failure
    mockApi.post('/v1/auth/login').as('login')
      .reply(200, {
        access_token: 'test-token',
        refresh_token: 'refresh-token'
      })
    
    mockApi.get('/v1/auth/me').as('authMe')
      .reply(503, { message: 'Service unavailable' })

    // Fill and submit login form
    await page.fill('input[name="username"]', 'testuser')
    await page.fill('input[name="password"]', 'password123')
    await page.getByRole('button', { name: 'Login' }).click()
    
    // Wait for login to complete and auth validation to fail
    await page.waitForResponse(response => 
      response.url().includes('/v1/auth/login') && response.status() === 200
    )
    await page.waitForTimeout(2000)
    
    // Verify degraded state is shown instead of redirect to login
    await expect(page.locator('text=Service Unavailable')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    
    // Verify we're not on the login page
    await expect(page).toHaveURL('/login', { timeout: 1000 }).toBe(false)
  })

  test('transitions to unauthenticated when auth/me returns 401 after retries', async ({
    page,
    mockApi,
  }) => {
    // Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')
    
    // Mock 503 then 401 sequence
    mockApi.get('/v1/auth/me').as('authMe')
      .replyOnce(503, { message: 'Service unavailable' })
      .replyOnce(401, { message: 'Unauthorized' })

    // Navigate to protected route
    await page.goto('/queue')
    
    // Wait for first 503 response
    await page.waitForTimeout(2000)
    
    // Verify degraded state
    await expect(page.locator('text=Service Unavailable')).toBeVisible()
    
    // Click retry button
    await page.getByRole('button', { name: 'Try again' }).click()
    
    // Wait for 401 response and transition to unauthenticated
    await page.waitForURL('/login')
    
    // Verify we're on login page
    await expect(page.locator('h1')).toContainText('Login')
    await expect(page.locator('nav')).not.toBeVisible() // No navigation in unauthenticated state
  })

  test('automatic retry with exponential backoff', async ({
    page,
    mockApi,
  }) => {
    // Start with authenticated user
    await mockApi.setupAuthUser()
    await page.goto('/')
    
    // Mock multiple 503 responses followed by success
    mockApi.get('/v1/auth/me').as('authMe')
      .replyOnce(503, { message: 'Service unavailable' })
      .replyOnce(503, { message: 'Service unavailable' })
      .replyOnce(200, {
        id: 1,
        username: 'testuser',
        email: 'test@example.com',
        created_at: '2023-01-01T00:00:00Z',
        last_login: '2023-01-01T00:00:00Z',
        preferences: { theme: 'classic' }
      })

    // Navigate to protected route
    const startTime = Date.now()
    await page.goto('/thread/1')
    
    // Wait for automatic retries to complete
    await page.waitForResponse(response => 
      response.url().includes('/v1/auth/me') && response.status() === 200
    )
    
    const endTime = Date.now()
    const totalTime = endTime - startTime
    
    // Verify exponential backoff took longer than simple delays
    // Should be more than 2 seconds but less than 10 seconds for 3 retries
    expect(totalTime).toBeGreaterThan(2000)
    expect(totalTime).toBeLessThan(10000)
    
    // Verify recovery
    await expect(page.locator('text=Service Unavailable')).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).not.toBeVisible()
    await expect(page.locator('nav')).toBeVisible()
  })
})