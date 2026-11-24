/**
 * Regression for #5525: Queue Read & Rate opens a direct exact-owned-issue
 * editor without replacing a pending random Roll offer or checking eligibility.
 * Supersedes #2153's legacy set-pending handoff contract.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForQueueReady, SELECTORS } from './helpers'

test.describe('P0 #5525: Queue manual issue reading', () => {
  test('Read & Rate opens the correct issue and saves via direct Rust v2 without set-pending', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Direct Issue Target'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 4,
      total_issues: 4,
    })

    // Visit Roll first: a warm bootstrap must not be overwritten by a manual
    // click in Queue, even if it currently contains a pending random offer.
    await gotoRollPage(page)
    await page.locator(SELECTORS.navigation.queueLink).first().click()
    await waitForQueueReady(page)

    const writes: string[] = []
    page.on('request', (request) => {
      if (request.method() !== 'GET') {
        writes.push(`${request.method()} ${new URL(request.url()).pathname}`)
      }
    })

    const row = page.locator(SELECTORS.threadList.threadItem).filter({ hasText: title })
    await row.getByRole('button', { name: 'Read & Rate', exact: true }).click()
    const panel = page.getByTestId('direct-read-issue-panel')
    await expect(panel).toBeVisible()
    const card = panel.getByRole('article', { name: `Issue ${title} #1` })
    await expect(card).toBeVisible()
    expect(writes.some((write) => write.includes('set-pending'))).toBe(false)

    await card.getByRole('button', { name: 'Read now', exact: true }).click()
    await expect(card.getByRole('slider')).toBeVisible()
    // Opening and canceling are reads only; neither pending Roll nor history
    // can be changed before Save.
    expect(writes.some((write) => write.includes('/api/v2/issues/'))).toBe(false)
    await card.getByRole('button', { name: 'Cancel', exact: true }).click()

    await card.getByRole('button', { name: 'Read now', exact: true }).click()
    const slider = card.getByRole('slider')
    await slider.press('End')
    await slider.press('ArrowLeft')
    await slider.press('ArrowLeft')
    await expect(slider).toHaveValue('4')
    const saveResponse = page.waitForResponse(
      (response) => response.url().includes('/api/v2/issues/') && response.request().method() === 'PATCH',
    )
    await card.getByRole('button', { name: 'Mark read & save' }).click()
    const response = await saveResponse
    expect(response.ok(), await response.text()).toBeTruthy()
    expect(response.request().postDataJSON()).toEqual(expect.objectContaining({
      source: 'direct',
      status: 'read',
      rating: 4,
      idempotency_key: expect.any(String),
    }))
    expect(writes.some((write) => write.includes('set-pending'))).toBe(false)
    await expect(page).toHaveURL(/\/queue$/)
  })

  test('an unavailable exact-issue lookup reports a retry without changing Roll', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Unavailable Direct Issue'
    const thread = await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await waitForQueueReady(page)
    await page.route(`**/api/v1/threads/${thread.id}/issues?*`, async (route) =>
      route.fulfill({ status: 503, json: { detail: 'Issue lookup temporarily unavailable' } }),
    )
    const row = page.locator(SELECTORS.threadList.threadItem).filter({ hasText: title })
    await row.getByRole('button', { name: 'Read & Rate', exact: true }).click()
    const panel = page.getByTestId('direct-read-issue-panel')
    await expect(panel.getByRole('alert')).toContainText('Issue lookup temporarily unavailable')
    await expect(panel.getByRole('button', { name: 'Retry issue lookup' })).toBeEnabled()
    await expect(page).toHaveURL(/\/queue$/)
  })
})
