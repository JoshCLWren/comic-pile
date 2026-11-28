import { test, expect } from '@playwright/test'
import { createThread, getAuthToken, loginUser, registerUser } from './helpers'

test('standalone saved Reading Lists can be reopened by stable ID across sessions', async ({ page, browser, baseURL }) => {
  const suffix = Date.now()
  const reader = { username: `listreader${suffix}`, email: `listreader${suffix}@example.com`, password: 'ListReaderTest123!' }
  const other = { username: `listother${suffix}`, email: `listother${suffix}@example.com`, password: 'ListReaderTest123!' }
  const name = `Shared list name ${suffix}`
  const series = [`List First ${suffix}`, `List Second ${suffix}`]
  await registerUser(page, reader)
  for (const title of series) {
    await createThread(page, { title,issues_remaining: 1, total_issues: 1 })
  }

  await page.goto('/continuity-plans')
  await page.getByRole('button', { name: 'Reading Lists', exact: true }).click()
  await expect(page).toHaveURL(/\/reading-lists$/)
  await page.getByLabel('New custom CBL name').fill(name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page).toHaveURL(/\/reading-lists\/\d+$/)
  const firstId = Number(page.url().split('/').pop())
  expect(firstId).toBeGreaterThan(0)
  await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue(name)

  for (const title of series) {
    await page.getByLabel('Search issues for custom CBL').fill(title)
    await page.getByRole('button', { name: 'Find issues' }).click()
    await page.getByRole('button', { name: `${title} #1`, exact: false }).click()
  }
  await page.getByRole('button', { name: 'Save custom CBL' }).click()
  await expect(page.locator('section[aria-labelledby="custom-cbl-heading"]').getByRole('status')).toContainText('Custom CBL saved.')
  const ordered = page.getByRole('list', { name: 'Custom CBL ordered issues' })
  await expect(ordered.getByTestId('reading-list-entry')).toHaveCount(2)
  await expect(ordered.getByTestId('reading-list-entry').nth(0)).toContainText(series[0])
  await expect(ordered.getByTestId('reading-list-entry').nth(1)).toContainText(series[1])

  // A second list may have the exact same name but must open a different ID.
  await page.getByLabel('New custom CBL name').fill(name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page).not.toHaveURL(new RegExp(`/reading-lists/${firstId}$`))
  await expect(page).toHaveURL(/\/reading-lists\/\d+$/)
  const secondId = Number(page.url().split('/').pop())
  expect(secondId).not.toBe(firstId)
  await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue(name)
  await page.getByLabel('Search issues for custom CBL').fill(series[1])
  await page.getByRole('button', { name: 'Find issues' }).click()
  await page.getByRole('button', { name: `${series[1]} #1`, exact: false }).click()
  await page.getByRole('radio', { name: /^Strict/ }).check()
  await page.getByRole('button', { name: 'Save custom CBL' }).click()
  await expect(page.locator('section[aria-labelledby="custom-cbl-heading"]').getByRole('status')).toContainText('Custom CBL saved.')

  await page.goto('/queue')
  await page.goto('/continuity-plans')
  await page.getByRole('button', { name: 'Reading Lists', exact: true }).click()
  await page.getByLabel('Custom CBL', { exact: true }).selectOption(String(firstId))
  await expect(page).toHaveURL(new RegExp(`/reading-lists/${firstId}$`))
  await expect(ordered.getByTestId('reading-list-entry').nth(0)).toContainText(series[0])
  await expect(ordered.getByTestId('reading-list-entry').nth(1)).toContainText(series[1])
  await expect(page.getByRole('radio', { name: /^Loose/ })).toBeChecked()
  await page.getByLabel('Custom CBL', { exact: true }).selectOption(String(secondId))
  await expect(page).toHaveURL(new RegExp(`/reading-lists/${secondId}$`))
  await expect(page.getByRole('radio', { name: /^Strict/ })).toBeChecked()
  await page.reload()
  await expect(page.getByRole('radio', { name: /^Strict/ })).toBeChecked()

  const fresh = await browser.newContext({ baseURL })
  try {
    const freshPage = await fresh.newPage()
    await freshPage.goto('/login')
    await loginUser(freshPage, reader)
    await freshPage.goto('/continuity-plans')
    await freshPage.getByRole('button', { name: 'Reading Lists', exact: true }).click()
    await freshPage.getByLabel('Custom CBL', { exact: true }).selectOption(String(firstId))
    await expect(freshPage.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue(name)
    await expect(freshPage.getByRole('radio', { name: /^Loose/ })).toBeChecked()
    const restored = freshPage.getByRole('list', { name: 'Custom CBL ordered issues' })
    await expect(restored.getByTestId('reading-list-entry').nth(0)).toContainText(series[0])
    await expect(restored.getByTestId('reading-list-entry').nth(1)).toContainText(series[1])
    await freshPage.getByRole('textbox', { name: 'Description', exact: true }).fill('Updated after signing in again')
    await freshPage.getByRole('button', { name: 'Save custom CBL' }).click()
    await expect(freshPage.locator('section[aria-labelledby="custom-cbl-heading"]').getByRole('status')).toContainText('Custom CBL saved.')
    await freshPage.reload()
    await expect(freshPage.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Updated after signing in again')
  } finally {
    await fresh.close()
  }

  const isolated = await browser.newContext({ baseURL })
  try {
    const otherPage = await isolated.newPage()
    await registerUser(otherPage, other)
    await otherPage.goto('/reading-lists')
    await otherPage.getByLabel('New custom CBL name').fill(name)
    await otherPage.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(otherPage).toHaveURL(/\/reading-lists\/\d+$/)
    const otherId = Number(otherPage.url().split('/').pop())
    expect(otherId).not.toBe(firstId)
    expect(otherId).not.toBe(secondId)
    const selector = otherPage.getByLabel('Custom CBL', { exact: true })
    await expect(selector).toHaveValue(String(otherId))
    await expect(selector.locator(`option[value="${firstId}"]`)).toHaveCount(0)
    await expect(selector.locator(`option[value="${secondId}"]`)).toHaveCount(0)
    const token = await getAuthToken(otherPage)
    expect(token).toBeTruthy()
    const denied = await otherPage.request.get(`/api/v2/reading-lists/${firstId}`, { headers: { Authorization: `Bearer ${token}` } })
    expect([403, 404]).toContain(denied.status())
  } finally {
    await isolated.close()
  }
})
