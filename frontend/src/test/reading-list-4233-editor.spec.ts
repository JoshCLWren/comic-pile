import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread } from './helpers'

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

test.describe('Reading List editor 4233', () => {
  test('inserts before a position, moves by position, supports keyboard and mobile/tablet layouts', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const suffix = Date.now()
    const names = [
      `RL4233 Alpha ${suffix}`,
      `RL4233 Beta ${suffix}`,
      `RL4233 Gamma ${suffix}`,
      `RL4233 Delta ${suffix}`,
    ]
    for (const title of names) {
      await createThread(page, { title, format: 'Comics', issues_remaining: 1, total_issues: 1 })
    }
    await createReadingPlan(page, `RL4233 Plan ${suffix}`)
    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('New custom CBL name').fill(`RL4233 List ${suffix}`)
    await page.getByRole('button', { name: 'Create' }).click()

    for (const [i, title] of names.entries()) {
      await page.setViewportSize(i % 2 === 0 ? { width: 390, height: 844 } : { width: 820, height: 1180 })
      await page.getByLabel('Search issues for custom CBL').fill(title)
      await page.getByRole('button', { name: 'Find issues' }).click()
      const result = page.getByRole('button', { name: new RegExp(`${title} #1`) })
      await expect(result).toBeVisible()
      await result.click()
      await expect(builder.getByRole('list', { name: 'Custom CBL ordered issues' })).toContainText(`${title} #1`)
    }

    const orderedList = builder.getByRole('list', { name: 'Custom CBL ordered issues' })
    const titles = orderedList.getByTestId('reading-list-entry-title')
    const originalOrder = names.map((title) => `${title} #1`)
    await expect(titles).toHaveCount(originalOrder.length)
    await expect(titles).toContainText(originalOrder)

    // Save a nonempty baseline so Undo must restore the actual previous order.
    await builder.getByRole('button', { name: 'Save custom CBL' }).click()
    await expect(builder.getByRole('status')).toContainText('Custom CBL saved.')

    await page.setViewportSize({ width: 1280, height: 900 })
    const gammaCard = builder.getByTestId('reading-list-entry').filter({ hasText: `RL4233 Gamma ${suffix} #1` })
    await gammaCard.getByRole('button', { name: /Show settings for/ }).press('Enter')
    await gammaCard.getByRole('button', { name: 'Insert before' }).press('Enter')
    await expect(builder.getByText(/Next added issue will be inserted before position 3/)).toBeVisible()

    const insertTitle = `RL4233 Inserted ${suffix}`
    await createThread(page, { title: insertTitle, format: 'Comics', issues_remaining: 1, total_issues: 1 })
    await page.getByLabel('Search issues for custom CBL').fill(insertTitle)
    await page.getByRole('button', { name: 'Find issues' }).click()
    await page.getByRole('button', { name: new RegExp(`${insertTitle} #1`) }).click()
    await expect(builder.getByRole('list', { name: 'Custom CBL ordered issues' })).toContainText(insertTitle)

    const deltaCard = builder.getByTestId('reading-list-entry').filter({ hasText: `RL4233 Delta ${suffix} #1` })
    await deltaCard.getByRole('button', { name: /Show settings for/ }).click()
    await deltaCard.getByLabel(new RegExp(`Move RL4233 Delta ${suffix} #1 to position`)).fill('1')
    await deltaCard.getByRole('button', { name: 'Move here' }).press('Enter')
    const editedOrder = [names[3], names[0], names[1], insertTitle, names[2]].map((title) => `${title} #1`)
    await expect(titles).toHaveCount(editedOrder.length)
    await expect(titles).toContainText(editedOrder)

    await page.getByRole('button', { name: 'Save custom CBL' }).click()
    await expect(builder.getByRole('status')).toContainText('Custom CBL saved.')
    await expect(builder.getByRole('button', { name: 'Undo last save' })).toBeVisible()

    // Undo is scoped to the active editor session. Reopen the same editor
    // without destroying its snapshot or changing the selected list.
    await builder.getByRole('button', { name: 'Close custom CBLs' }).click()
    await expect(orderedList).toBeHidden()
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await expect(titles).toHaveCount(editedOrder.length)
    await expect(titles).toContainText(editedOrder)

    await builder.getByRole('button', { name: 'Undo last save' }).click()
    await expect(builder.getByRole('status')).toContainText('Read history and ratings were not changed')
    await expect(titles).toHaveCount(originalOrder.length)
    await expect(titles).toContainText(originalOrder)

    // Reload only after Undo, to verify the restored order was persisted.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    const listSelector = builder.getByLabel('Custom CBL', { exact: true })
    const savedOption = listSelector.getByRole('option', { name: new RegExp(`RL4233 List ${suffix}`) })
    await expect(savedOption).toHaveCount(1)
    const listId = await savedOption.getAttribute('value')
    expect(listId).toBeTruthy()
    await listSelector.selectOption(listId!)
    await expect(titles).toHaveCount(originalOrder.length)
    await expect(titles).toContainText(originalOrder)
  })
})
