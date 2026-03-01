import { test, expect } from './fixtures'
import { createThread } from './helpers'

test.describe('Dependencies', () => {
  test('creates dependency from queue UI and shows blocked indicator', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Source Thread',
      format: 'Comic',
      issues_remaining: 3,
    })

    await createThread(authenticatedPage, {
      title: 'Target Thread',
      format: 'Comic',
      issues_remaining: 3,
    })

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Target Thread' }).first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()

    await authenticatedPage.fill('input#search-prereq-thread', 'Source')
    await authenticatedPage.waitForSelector('button:has-text("Source Thread")', { state: 'visible' })
    await authenticatedPage.click('button:has-text("Source Thread")')
    await authenticatedPage.click('button:has-text("Block")')

    await authenticatedPage.waitForResponse(
      (response) => response.url().includes('/api/v1/dependencies/') && response.request().method() === 'POST' && response.status() < 300
    )

    await authenticatedPage.click('button[aria-label="Close modal"]')
    await authenticatedPage.waitForLoadState('networkidle')

    await expect(
      authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Target Thread' })
        .locator('[aria-label="Blocked thread"]')
    ).toBeVisible()
  })

  test('blocked thread cannot be read from action sheet', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'A Prequel',
      format: 'Comic',
      issues_remaining: 2,
    })

    await createThread(authenticatedPage, {
      title: 'B Main Story',
      format: 'Comic',
      issues_remaining: 2,
    })

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))
    const threadsResponse = await authenticatedPage.request.get('/api/threads/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    const threads = await threadsResponse.json()

    const source = threads.find((thread: { title: string; id: number }) => thread.title === 'A Prequel')
    const target = threads.find((thread: { title: string; id: number }) => thread.title === 'B Main Story')

    if (!source || !target) {
      throw new Error(`Failed to find expected threads: source=${source?.id}, target=${target?.id}`)
    }

    await authenticatedPage.request.post('/api/v1/dependencies/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data: {
        source_type: 'thread',
        source_id: source.id,
        target_type: 'thread',
        target_id: target.id,
      },
    })

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    // Wait for the blocked indicator to appear (means blocked state was loaded)
    await expect(
      authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'B Main Story' })
        .locator('[aria-label="Blocked thread"]')
    ).toBeVisible()

    await authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'B Main Story' })
      .first()
      .click()

    // Wait for action sheet modal to open
    await authenticatedPage.waitForSelector('button:has-text("Read Now")', { state: 'visible' })

    // Set up dialog handler that auto-accepts and captures the message
    let dialogMessage = ''
    authenticatedPage.on('dialog', async (dialog) => {
      dialogMessage = dialog.message()
      await dialog.accept()
    })

    await authenticatedPage.click('button:has-text("Read Now")')

    // Wait a bit for the dialog handler to fire
    await authenticatedPage.waitForTimeout(500)

    expect(dialogMessage.toLowerCase()).toContain('blocked')
  })
})
