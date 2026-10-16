import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only csrf_token from the response body
  const data = await response.json() as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page) {
  const token = await getAuthToken(page)
  expect(token).toBeTruthy()
  const csrf = await getCsrf(page, token)
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
    Authorization: `Bearer ${token}`,
  }
}

async function getFirstIssueId(page: Page, threadId: number): Promise<number> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the response fields listed in this type
  const data = await response.json() as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

async function createReadingPlan(page: Page, name: string): Promise<number> {
  await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'New Reading Plan' }).click()
  await expect(page.getByRole('heading', { name: 'New Reading Plan' })).toBeVisible()
  await page.getByLabel('Plan name').fill(name)
  await page.getByRole('radio', { name: /^Strict/i }).check()
  await page.getByRole('button', { name: 'Save plan' }).click()
  await expect(page).toHaveURL(/\/continuity-plans\/\d+/)
  const planId = Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
  expect(planId).toBeGreaterThan(0)
  return planId
}

/**
 * #3668: the Reading List editor exposes strict/loose mode, hold/after-previous
 * gates, and list-local skips, and requires explicit confirmation of changed
 * waits before a gate edit persists.
 */
test.describe('Reading List gate authoring', () => {
  test('saves mode, gate, and skip intent and preserves them across reload', async ({
    authenticatedPage,
    allowExpectedBrowserFailures,
  }) => {
    const page = authenticatedPage
    // The first gate save deliberately receives a 409 confirmation-required
    // response; the browser logs that handled response as a console error.
    allowExpectedBrowserFailures.allow({ category: 'console', message: '409' })
    const first = await createThread(page, {
      title: 'Gate First Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const skipped = await createThread(page, {
      title: 'Gate Skipped Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const last = await createThread(page, {
      title: 'Gate Last Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    await getFirstIssueId(page, first.id)
    await getFirstIssueId(page, last.id)

    const fixtureSuffix = `${skipped.id}-${Date.now()}`
    const listName = `Gate Regression ${fixtureSuffix}`
    await createReadingPlan(page, `Gate Regression Plan ${fixtureSuffix}`)

    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('New custom CBL name').fill(listName)
    await page.getByRole('button', { name: 'Create' }).click()

    for (const series of ['Gate First Series', 'Gate Skipped Series', 'Gate Last Series']) {
      await page.getByLabel('Search issues for custom CBL').fill(series)
      await page.getByRole('button', { name: 'Find issues' }).click()
      await page.getByRole('button', { name: new RegExp(`${series} #1`) }).click()
    }

    await builder.getByRole('radio', { name: /^Strict/ }).check()
    await builder.getByLabel('Skip Gate Skipped Series #1 in this list').check()
    await builder.getByLabel('Wait behavior for Gate Last Series #1').selectOption('hold')

    await expect(builder.getByText('Skipped in this list', { exact: true })).toBeVisible()
    await expect(
      builder.getByText('Waits on Gate First Series #1.').first(),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Save custom CBL' }).click()

    const confirmation = page.getByRole('dialog', { name: 'Confirm waiting changes' })
    await expect(confirmation).toBeVisible()
    await expect(confirmation).toContainText('Gate Last Series #1')
    await expect(confirmation).toContainText('now waits on Gate First Series #1')
    await confirmation.getByRole('button', { name: 'Confirm and save' }).click()

    await expect(builder.getByRole('status')).toContainText('Custom CBL saved.')

    await page.reload({ waitUntil: 'domcontentloaded' })
    const reloadedBuilder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await reloadedBuilder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('Custom CBL', { exact: true }).selectOption({ index: 1 })

    await expect(reloadedBuilder.getByRole('radio', { name: /^Strict/ })).toBeChecked()
    await expect(
      reloadedBuilder.getByLabel('Wait behavior for Gate Last Series #1'),
    ).toHaveValue('hold')
    await expect(
      reloadedBuilder.getByLabel('Skip Gate Skipped Series #1 in this list'),
    ).toBeChecked()
  })
})
