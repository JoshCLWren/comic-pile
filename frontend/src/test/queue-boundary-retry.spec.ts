import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread } from './helpers'

for (const width of [390, 1280]) {
  test(`Queue boundary failure recovers through Retry at ${width}px`, async ({ authenticatedPage: page, allowExpectedBrowserFailures }) => {
    await page.setViewportSize({ width, height: 900 })
    const thread = await createThread(page, { title: 'Boundary retry series', format: 'Issue', issues_remaining: 2, total_issues: 2 })
    let failing = true
    allowExpectedBrowserFailures.allow({ category: 'console', message: '503 (Service Unavailable)' })
    await page.route('**/api/v1/reading-boundaries', async route => {
      await route.fulfill({
        status: failing ? 503 : 200,
        json: failing ? { detail: 'Boundary test failure' } : { threads: {
          [thread.id]: { thread_id: thread.id, state: 'available', summary: 'Ready to read.', blockers: [], historical: [] },
        } },
      })
    })
    await page.goto('/queue')
    const retry = page.getByRole('button', { name: 'Retry reading boundaries' })
    await expect(retry).toBeVisible()
    await expect(page.getByRole('alert').filter({ hasText: 'Rows fall back' })).toHaveCount(1)
    failing = false
    const response = page.waitForResponse(r => r.url().endsWith('/api/v1/reading-boundaries') && r.status() === 200)
    await retry.click()
    await response
    await expect(retry).toHaveCount(0)
    await expect(page.getByText('Boundary retry series', { exact: true }).first()).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}
