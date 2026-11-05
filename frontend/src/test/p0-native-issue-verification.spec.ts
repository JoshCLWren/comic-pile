/**
 * P0-NATIVE-ISSUE: Verify Rust native issue endpoint works in production browser flows.
 *
 * This test verifies that the Rust `PATCH /api/v2/issues/{issue_id}` endpoint
 * (issue #4443) works correctly in authenticated production browser flows.
 *
 * Related issues:
 * - #4443: Rust implementation of PATCH /api/v2/issues/{issue_id}
 * - #4445: App-wide parity: expose direct read/rate on every actionable issue view
 * - #4453: 409 regression fix - Rust doesn't check eligibility, only ownership
 * - #4337: Legacy rating retirement (Route retirement record)
 *
 * The key verification:
 * - The PATCH response comes from the native Rust handler (x-comicpile-api-runtime: rust)
 * - The response schema matches the OpenAPI contract
 * - The rating is persisted correctly
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

test.describe('P0-NATIVE-ISSUE: Rust native issue endpoint verification', () => {
  /**
   * Helper to wait for the rate PATCH response and return it.
   */
  async function waitForNativePatchResponse(page: Page): Promise<{
    response: Awaited<ReturnType<typeof page.waitForResponse>>;
  }> {
    const rateResponse = page.waitForResponse(
      (resp) => resp.url().includes('/api/v2/issues/') && resp.request().method() === 'PATCH',
    )
    await page.locator('button[data-testid="save-and-continue"]').click()
    const response = await rateResponse
    return { response }
  }

  test('verified native PATCH request from authenticated user via Roll flow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    // Create a thread with issues
    await createThread(page, {
      title: 'Native Patch Verification Thread',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    // Roll the die to get an issue in the pool
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })

    // Click on the thread to open the rating view
    await page.getByText('Native Patch Verification Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    // Submit a rating
    const ratingInput = page.locator('#rating-input')
    await ratingInput.fill('4.5')

    // Wait for the PATCH response from the native endpoint
    const { response } = await waitForNativePatchResponse(page)

    // Verify the response is successful
    expect(await response.ok()).toBeTruthy()

    // Verify the response body matches the expected schema
    const responseBody = (await response.json()) as Record<string, unknown>

    // IssueReadRateResponse schema validation
    expect(responseBody.issue).toBeDefined()
    const issue = responseBody.issue as Record<string, unknown>
    expect(issue.issue_id).toBeGreaterThan(0)
    expect(issue.thread_id).toBeGreaterThan(0)
    expect(issue.thread_title).toBe('Native Patch Verification Thread')
    expect(issue.issue_number).toBeDefined()
    expect(issue.status).toBe('read')
    expect(issue.rating).toBe(4.5)
    expect(issue.read_at).toBeDefined()
    expect(issue.has_confirmed_identity).toBeDefined()
    expect(issue.mapping_state).toBeDefined()

    const thread = responseBody.thread as Record<string, unknown>
    expect(thread).toBeDefined()
    expect(thread.thread_id).toBeGreaterThan(0)
    expect(thread.status).toBeDefined()
    expect(thread.issues_remaining).toBeLessThanOrEqual(1)
    expect(thread.next_unread_issue_id).toBeDefined()

    expect(responseBody.read_event_created).toBe(true)
    expect(responseBody.rating_event_created).toBe(true)
    expect(responseBody.replayed).toBe(false)
    expect(responseBody.final_rating).toBe(4.5)

    // CRITICAL VERIFICATION: The response must come from native Rust
    const runtimeHeader = response.headers()['x-comicpile-api-runtime']
    expect(runtimeHeader, 'Native issue endpoint must return rust runtime header').toBe('rust')
  })

  test('verified 404 for non-owned issue from authenticated user', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    // First, set up authentication headers
    const token = await page.evaluate(() => localStorage.getItem('auth_token'))
    expect(token).toBeTruthy()

    // Attempt to read an issue that definitely doesn't belong to this user
    // Use a very high ID that's unlikely to exist
    const response = await page.request.patch('/api/v2/issues/999999', {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        status: 'read',
        idempotency_key: 'test-non-owned-issue',
      },
    })

    // Should get 404 Not Found (issue not found for this reader)
    expect(response.status()).toBe(404)
    const body = await response.json()
    expect(body.detail).toContain('not found')
  })

  test('verified 401 for unauthenticated request to PATCH /api/v2/issues/{id}', async ({
    page,
  }) => {
    // Clear any stored auth
    await page.evaluate(() => {
      localStorage.removeItem('auth_token')
      delete (window as any).__COMIC_PILE_ACCESS_TOKEN
    })

    // Attempt to make a PATCH request without authentication
    const response = await page.request.patch('/api/v2/issues/1', {
      data: {
        status: 'read',
        idempotency_key: 'unauth-test',
      },
    })

    expect(response.status()).toBe(401)
  })

  test('verified native runtime for roll_offer source rating', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    // Create multiple threads
    await createThread(page, {
      title: 'Roll Offer Rating Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    // Roll
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })

    // Click on the thread - this triggers a roll_offer source rating
    await page.getByText('Roll Offer Rating Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    // Submit a 4.5 rating (above threshold, should trigger die stepping)
    const ratingInput = page.locator('#rating-input')
    await ratingInput.fill('4.5')

    const { response } = await waitForNativePatchResponse(page)

    expect(await response.ok()).toBeTruthy()
    const responseBody = (await response.json()) as Record<string, unknown>

    // For roll_offer source with rating >= 4.0, die_after should be set
    expect(responseBody.die_after).toBeGreaterThan(0)
    expect(responseBody.source_roll_event_id).toBeGreaterThan(0)

    // CRITICAL: Verify native Rust runtime
    expect(response.headers()['x-comicpile-api-runtime']).toBe('rust')
  })

  test('verified retry key prevents duplicate events', async ({ authenticatedPage }) => {
    const page = authenticatedPage

    await createThread(page, {
      title: 'Idempotency Retry Thread',
      format: 'Issue',
      issues_remaining: 1,
      total_issues: 1,
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    // Roll and select
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Idempotency Retry Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    // Submit first rating
    const ratingInput = page.locator('#rating-input')
    await ratingInput.fill('5')

    const { response: response1 } = await waitForNativePatchResponse(page)

    expect(await response1.ok()).toBeTruthy()
    const responseBody1 = (await response1.json()) as Record<string, unknown>
    expect(responseBody1.replayed).toBe(false)
    expect(responseBody1.read_event_created).toBe(true)
    expect(responseBody1.rating_event_created).toBe(true)

    // Wait a moment and submit the same rating again
    // The idempotency key is stored in the client and reused for retries
    // The same payload with the same key should return replayed=true
    await page.waitForTimeout(500)
    await ratingInput.fill('5')

    const { response: response2 } = await waitForNativePatchResponse(page)

    expect(await response2.ok()).toBeTruthy()
    const responseBody2 = (await response2.json()) as Record<string, unknown>
    expect(responseBody2.replayed).toBe(true)
    expect(responseBody2.read_event_created).toBe(false) // No new read event
    expect(responseBody2.rating_event_created).toBe(false) // No new rating event
  })

  test('verified OpenAPI schema compliance for IssueReadRateResponse', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await createThread(page, {
      title: 'Schema Compliance Thread',
      format: 'Comic',
      issues_remaining: 1,
      total_issues: 1,
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Schema Compliance Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    const ratingInput = page.locator('#rating-input')
    await ratingInput.fill('3.5')

    const { response } = await waitForNativePatchResponse(page)

    expect(await response.ok()).toBeTruthy()
    const responseBody = (await response.json()) as Record<string, unknown>

    // Validate all required fields from the OpenAPI schema
    // IssueReadRateResponse required fields
    expect(responseBody).toHaveProperty('issue')
    expect(responseBody).toHaveProperty('thread')
    expect(responseBody).toHaveProperty('read_event_created')
    expect(responseBody).toHaveProperty('rating_event_created')
    expect(responseBody).toHaveProperty('replayed')
    expect(responseBody).toHaveProperty('final_rating')

    // IssueCard required fields
    const issue = responseBody.issue as Record<string, unknown>
    expect(issue).toHaveProperty('issue_id')
    expect(issue).toHaveProperty('thread_id')
    expect(issue).toHaveProperty('thread_title')
    expect(issue).toHaveProperty('issue_number')
    expect(issue).toHaveProperty('status')
    expect(issue).toHaveProperty('has_confirmed_identity')
    expect(issue).toHaveProperty('mapping_state')

    // Validate status enum values
    const validStatuses = ['read', 'unread', 'skipped']
    expect(validStatuses).toContain(issue.status)

    // Optional fields that should exist but can be null
    expect(issue).toHaveProperty('read_at') // Can be null
    expect(issue).toHaveProperty('rating') // Can be null
    expect(issue).toHaveProperty('comicvine_issue_id') // Can be null
    expect(issue).toHaveProperty('cover_image_url') // Can be null

    // Validate rating type (number or null)
    if (issue.rating !== null) {
      expect(typeof issue.rating).toBe('number')
      expect(issue.rating).toBeGreaterThanOrEqual(0)
      expect(issue.rating).toBeLessThanOrEqual(5)
    }

    // Validate issue_number type (number or null)
    if (issue.issue_number !== null) {
      expect(typeof issue.issue_number).toBe('number')
      expect(issue.issue_number).toBeGreaterThan(0)
    }

    // ThreadProgress required fields
    const thread = responseBody.thread as Record<string, unknown>
    expect(thread).toHaveProperty('thread_id')
    expect(thread).toHaveProperty('status')
    expect(thread).toHaveProperty('issues_remaining')

    // Validate thread status enum
    expect(validStatuses).toContain(thread.status)

    // Validate issues_remaining type (integer)
    expect(typeof thread.issues_remaining).toBe('number')
    expect(thread.issues_remaining).toBeGreaterThanOrEqual(0)

    // ThreadProgress optional fields
    expect(thread).toHaveProperty('next_unread_issue_id') // Can be null
    expect(thread).toHaveProperty('reading_progress') // Can be null
    expect(thread).toHaveProperty('last_rating') // Can be null

    // Validate last_rating type (number or null)
    if (thread.last_rating !== null) {
      expect(typeof thread.last_rating).toBe('number')
      expect(thread.last_rating).toBeGreaterThanOrEqual(0)
      expect(thread.last_rating).toBeLessThanOrEqual(5)
    }

    // Validate reading_progress type (number or null)
    if (thread.reading_progress !== null) {
      expect(typeof thread.reading_progress).toBe('number')
      expect(thread.reading_progress).toBeGreaterThanOrEqual(0)
      expect(thread.reading_progress).toBeLessThanOrEqual(1)
    }

    // die_after is optional and null for direct source
    expect(responseBody).toHaveProperty('die_after') // Can be null

    // Validate die_after type (number or null)
    if (responseBody.die_after !== null) {
      expect(typeof responseBody.die_after).toBe('number')
      expect(responseBody.die_after).toBeGreaterThan(0)
    }
  })
})