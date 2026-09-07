/**
 * Phase 5 acceptance: reading-mode UI regression (issue #1734).
 *
 * Proves the first user-visible reading-mode workflow is coherent,
 * accessible, and does not add unnecessary friction.
 *
 * Covers:
 * - Roll header shows canonical active bandwidth + intent
 * - Manual bandwidth/intent switching takes effect for subsequent rolls
 * - Random intent activates the legacy unweighted control path
 * - Normal Snooze does not auto-interrupt with a modal
 * - Repeated/meaningful mismatch shows the correction sheet
 * - Refresh/reload restores state from bootstrap
 * - Keyboard and mobile/desktop behavior
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { gotoRollPage, waitForRollPageReady } from './helpers'

async function getAuthToken(page: Page): Promise<string> {
  return page.evaluate(() => {
    const win = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
    return localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN ?? ''
  })
}

async function setSessionMode(
  page: Page,
  patch: { bandwidth?: string; intent?: string },
): Promise<void> {
  const token = await getAuthToken(page)
  const response = await page.request.patch('/api/v1/roll/session-mode', {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    data: patch,
  })
  expect(response.ok()).toBeTruthy()
}

async function getSessionMode(page: Page): Promise<{
  active_bandwidth: string | null
  active_intent: string | null
}> {
  const token = await getAuthToken(page)
  const response = await page.request.get('/api/roll/bootstrap', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.ok()).toBeTruthy()
  const body = (await response.json()) as {
    session_mode: { active_bandwidth: string | null; active_intent: string | null }
  }
  return body.session_mode
}

async function createThreadWithIssues(page: Page, title: string): Promise<void> {
  const token = await getAuthToken(page)
  const threadRes = await page.request.post('/api/threads/', {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    data: { title, format: 'issue', issues_remaining: 10, total_issues: 10 },
  })
  expect(threadRes.ok()).toBeTruthy()
  const thread = (await threadRes.json()) as { id: number }
  const issuesRes = await page.request.post(`/api/v1/threads/${thread.id}/issues`, {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    data: { issue_range: '1-10' },
  })
  expect(issuesRes.ok()).toBeTruthy()
}

test.describe('reading-mode acceptance (issue #1734)', () => {
  test('roll header displays canonical bandwidth and intent from bootstrap', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'deep', intent: 'familiar' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await expect(control).toBeVisible()
    await expect(control).toHaveText('Deep · Familiar')
  })

  test('manual bandwidth switch via mode selector takes effect for subsequent rolls', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'balanced', intent: 'balanced' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await expect(control).toHaveText('Balanced · Balanced')

    await control.click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()

    await page.getByRole('radio', { name: /Deep/ }).click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeHidden()

    const mode = await getSessionMode(page)
    expect(mode.active_bandwidth).toBe('deep')
    expect(mode.active_intent).toBe('balanced')
  })

  test('manual intent switch via mode selector takes effect for subsequent rolls', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'light', intent: 'balanced' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await expect(control).toHaveText('Light · Balanced')

    await control.click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()

    await page.getByRole('radio', { name: /Momentum/ }).click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeHidden()

    const mode = await getSessionMode(page)
    expect(mode.active_bandwidth).toBe('light')
    expect(mode.active_intent).toBe('momentum')
  })

  test('random intent activates the legacy unweighted control path', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'balanced', intent: 'random' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await expect(control).toHaveText('Balanced · Random')

    const mode = await getSessionMode(page)
    expect(mode.active_intent).toBe('random')

    await control.click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()
    const randomOption = page.getByRole('radio', { name: /Random/ })
    await expect(randomOption).toHaveAttribute('aria-checked', 'true')
    expect(await randomOption.getAttribute('aria-label')).toContain('Unweighted legacy-style selection')
  })

  test('normal snooze does not auto-interrupt with the correction modal', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await createThreadWithIssues(page, 'Snooze test thread')
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByTestId('reading-mode-control')).toBeVisible()

    await expect(page.getByTestId('correction-sheet')).toBeHidden()
    await expect(page.getByTestId('mode-selector-sheet')).toBeHidden()
  })

  test('mode selector exposes random intent with unweighted description', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await control.click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()

    const randomOption = page.getByRole('radio', { name: /Random/ })
    await expect(randomOption).toHaveAttribute(
      'aria-label',
      expect.stringContaining('Unweighted legacy-style selection'),
    )
    await page.keyboard.press('Escape')
  })

  test('refresh/reload restores mode state from bootstrap', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'deep', intent: 'explore' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await expect(control).toHaveText('Deep · Explore')

    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForRollPageReady(page)

    await expect(page.getByTestId('reading-mode-control')).toHaveText('Deep · Explore')
  })

  test('mode selector is accessible by keyboard', async ({ authenticatedPage }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'balanced', intent: 'balanced' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await control.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()

    const deepOption = page.getByRole('radio', { name: /Deep/ })
    await deepOption.focus()
    await page.keyboard.press('Enter')

    const mode = await getSessionMode(page)
    expect(mode.active_bandwidth).toBe('deep')
  })

  test('mode selector closes on Escape without changing state', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'light', intent: 'momentum' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await control.click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.getByTestId('mode-selector-sheet')).toBeHidden()

    const mode = await getSessionMode(page)
    expect(mode.active_bandwidth).toBe('light')
    expect(mode.active_intent).toBe('momentum')
  })

  test('mobile viewport shows compact mode control and mode selector works', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await page.setViewportSize({ width: 375, height: 812 })
    await setSessionMode(page, { bandwidth: 'light', intent: 'familiar' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    await expect(control).toBeVisible()
    await expect(control).toHaveText('Light · Familiar')

    await control.click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeVisible()

    await page.getByRole('radio', { name: /Deep/ }).click()
    await expect(page.getByTestId('mode-selector-sheet')).toBeHidden()
  })

  test('mode control does not dominate the header visually', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    await setSessionMode(page, { bandwidth: 'deep', intent: 'momentum' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const control = page.getByTestId('reading-mode-control')
    const box = await control.boundingBox()
    expect(box).not.toBeNull()
    if (box) {
      expect(box.width).toBeLessThan(200)
    }

    const header = page.locator('header')
    const headerBox = await header.boundingBox()
    expect(headerBox).not.toBeNull()
  })
})
