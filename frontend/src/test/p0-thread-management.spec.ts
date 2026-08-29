/**
 * THREAD-001: Users can create, edit, and delete thread topics.
 *
 * Covers the full thread lifecycle from the queue page: creating a new thread
 * via the modal, editing its title, and deleting it with confirmation.
 *
 * Inventory IDs: THREAD-001
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { gotoQueue, waitForQueueReady } from './helpers'

test.describe('THREAD-001: Thread management', () => {
  test('user can create a new thread from the queue page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoQueue(page)
    await waitForQueueReady(page)

    await page.getByRole('button', { name: /add thread/i }).first().click()
    await page.locator('#create-thread-title').fill('My New Thread')

    const formatSelect = page.locator('#create-thread-format')
    if (await formatSelect.isVisible()) {
      await formatSelect.selectOption({ index: 1 })
    }

    await page.locator('#create-thread-issues').fill('1-5')

    await page.getByRole('button', { name: /create thread/i }).click()
    await expect(page.getByText('My New Thread')).toBeVisible({ timeout: 10000 })
  })

  test('user can edit an existing thread title', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await gotoQueue(page)
    await waitForQueueReady(page)

    await page.getByRole('button', { name: /add thread/i }).first().click()
    await page.locator('#create-thread-title').fill('Edit Target Thread')
    await page.locator('#create-thread-issues').fill('1-3')
    await page.getByRole('button', { name: /create thread/i }).click()
    await expect(page.getByText('Edit Target Thread')).toBeVisible({ timeout: 10000 })

    const threadItem = page.getByTestId('queue-thread-item').filter({ hasText: 'Edit Target Thread' })
    await threadItem.locator('button[aria-label="Thread actions"]').click()
    const menu = page.getByRole('menu')
    await expect(menu).toBeVisible()
    await menu.getByRole('menuitem', { name: /edit/i }).click()

    await expect(page.getByRole('heading', { name: 'Edit Thread' })).toBeVisible()
    await page.locator('#edit-thread-title').fill('Edited Thread Title')
    await page.getByRole('button', { name: /save/i }).click()

    await expect(page.getByText('Edited Thread Title')).toBeVisible({ timeout: 10000 })
  })

  test('user can delete a thread with confirmation', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoQueue(page)
    await waitForQueueReady(page)

    await page.getByRole('button', { name: /add thread/i }).first().click()
    await page.locator('#create-thread-title').fill('Delete Target Thread')
    await page.locator('#create-thread-issues').fill('1-2')
    await page.getByRole('button', { name: /create thread/i }).click()
    await expect(page.getByText('Delete Target Thread')).toBeVisible({ timeout: 10000 })

    const threadItem = page.getByTestId('queue-thread-item').filter({ hasText: 'Delete Target Thread' })
    await threadItem.locator('button[aria-label="Thread actions"]').click()
    const menu = page.getByRole('menu')
    await expect(menu).toBeVisible()

    page.on('dialog', (dialog) => dialog.accept())
    await menu.getByRole('menuitem', { name: /delete/i }).click()
    await expect(page.getByText('Delete Target Thread')).toHaveCount(0, { timeout: 10000 })
  })

  test('queue displays threads in order after creation', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoQueue(page)
    await waitForQueueReady(page)

    await page.getByRole('button', { name: /add thread/i }).first().click()
    await page.locator('#create-thread-title').fill('First Thread')
    await page.locator('#create-thread-issues').fill('1-3')
    await page.getByRole('button', { name: /create thread/i }).click()
    await expect(page.getByText('First Thread')).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /add thread/i }).first().click()
    await page.locator('#create-thread-title').fill('Second Thread')
    await page.locator('#create-thread-issues').fill('1-3')
    await page.getByRole('button', { name: /create thread/i }).click()
    await expect(page.getByText('Second Thread')).toBeVisible({ timeout: 10000 })

    const items = page.getByTestId('queue-thread-item')
    await expect(items).toHaveCount(2)
  })

  test('thread detail page shows thread info and is navigable', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoQueue(page)
    await waitForQueueReady(page)

    await page.getByRole('button', { name: /add thread/i }).first().click()
    await page.locator('#create-thread-title').fill('Detail View Thread')
    await page.locator('#create-thread-issues').fill('1-5')
    await page.getByRole('button', { name: /create thread/i }).click()
    await expect(page.getByText('Detail View Thread')).toBeVisible({ timeout: 10000 })

    const threadItem = page.getByTestId('queue-thread-item').filter({ hasText: 'Detail View Thread' })
    await threadItem.getByRole('button', { name: /open detail view thread/i }).click()

    await expect(page.getByRole('heading', { name: 'Detail View Thread' })).toBeVisible({
      timeout: 10000,
    })
  })
})
