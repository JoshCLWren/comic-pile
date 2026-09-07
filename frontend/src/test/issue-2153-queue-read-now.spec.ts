/**
 * Issue #2153: Queue → Read Now must land on the rating view for the chosen
 * thread, never on an empty Roll page with no comic selected.
 *
 * The regression reproduces the user path exactly: Roll is visited first (so
 * the roll bootstrap query is cached and fresh), the user moves to Queue via
 * in-app navigation, and clicks Read on an eligible thread with a known
 * next unread issue.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForQueueReady, SELECTORS } from './helpers'

test.describe('Issue #2153: Queue Read Now handoff', () => {
  test('Read Now from Queue opens the rating view for that thread and its next unread issue', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Read Now Target'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 4,
      total_issues: 4,
    })

    // Visit Roll first so the bootstrap cache is warm with no pending thread.
    await gotoRollPage(page)

    // Move to Queue through the app shell (client-side navigation keeps the
    // React Query cache alive, which is the state the bug depends on).
    await page.locator(SELECTORS.navigation.queueLink).first().click()
    await waitForQueueReady(page)

    const threadItem = page
      .locator(SELECTORS.threadList.threadItem)
      .filter({ hasText: title })
    await expect(threadItem).toBeVisible()

    const setPendingResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/set-pending') && response.request().method() === 'POST',
    )
    await threadItem.getByRole('button', { name: 'Read', exact: true }).click()
    expect((await setPendingResponse).ok()).toBeTruthy()

    // The handoff must land on Roll in rating view for the chosen thread.
    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 15000 })
    const heading = page.locator('#selected-issue-heading')
    await expect(heading).toContainText(title)
    await expect(heading).toContainText('#1')
    await expect(page.locator(SELECTORS.roll.mainDie)).toHaveCount(0)
  })

  test('Read Now on a thread the server rejects stays on Queue with an actionable error', async ({
    authenticatedPage,
    allowExpectedBrowserFailures,
  }) => {
    const page = authenticatedPage
    allowExpectedBrowserFailures.allow(
      { category: 'console', message: 'set-pending' },
      { category: 'console', message: 'API Validation Error Details' },
      { category: 'console', message: 'Request failed with status code 400' },
    )
    const title = 'Rejected Read Target'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await waitForQueueReady(page)

    await page.route('**/set-pending', (route) =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Thread has no issues remaining' }),
      }),
    )

    const dialogMessage = new Promise<string>((resolve) => {
      page.once('dialog', (dialog) => {
        resolve(dialog.message())
        void dialog.dismiss()
      })
    })

    const threadItem = page
      .locator(SELECTORS.threadList.threadItem)
      .filter({ hasText: title })
    await threadItem.getByRole('button', { name: 'Read', exact: true }).click()

    expect(await dialogMessage).toContain('Thread has no issues remaining')
    await expect(page).toHaveURL(/\/queue$/)
    await waitForQueueReady(page)
  })
})
