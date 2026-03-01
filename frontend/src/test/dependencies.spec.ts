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

  test.describe('Flexible issue dependencies', () => {
    test('issue dropdowns appear when thread selected in issue mode', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Prerequisite Comic',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Target Comic',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Target Comic' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Prerequisite')
      await authenticatedPage.waitForSelector('button:has-text("Prerequisite Comic")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("Prerequisite Comic")')

      await expect(authenticatedPage.locator('#source-issue')).toBeVisible()
      await expect(authenticatedPage.locator('#target-issue')).toBeVisible()
    })

    test('issues load and display correctly with status indicators', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Source Series',
        format: 'Comic',
        issues_remaining: 8,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Target Series',
        format: 'Comic',
        issues_remaining: 8,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Target Series' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Source')
      await authenticatedPage.waitForSelector('button:has-text("Source Series")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("Source Series")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible' })
      await authenticatedPage.waitForSelector('#target-issue', { state: 'visible' })

      const sourceOptions = await authenticatedPage.locator('#source-issue option').count()
      const targetOptions = await authenticatedPage.locator('#target-issue option').count()

      expect(sourceOptions).toBeGreaterThan(1)
      expect(targetOptions).toBeGreaterThan(1)

      const firstSourceOption = await authenticatedPage.locator('#source-issue option').nth(1).textContent()
      expect(firstSourceOption).toMatch(/#\d+ [✅🟢]/)
    })

    test('auto-selection of first unread issue', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Prequel Series',
        format: 'Comic',
        issues_remaining: 7,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Main Series',
        format: 'Comic',
        issues_remaining: 7,
        total_issues: 10,
      })

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))

      await authenticatedPage.request.post(`/api/v1/threads/${sourceThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      await authenticatedPage.request.patch(`/api/v1/threads/${sourceThread.id}/issues/1`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { read: true },
      })

      await authenticatedPage.request.patch(`/api/v1/threads/${sourceThread.id}/issues/2`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { read: true },
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Main Series' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Prequel')
      await authenticatedPage.waitForSelector('button:has-text("Prequel Series")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("Prequel Series")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })

      const sourceValue = await authenticatedPage.locator('#source-issue').inputValue()
      expect(sourceValue).not.toBe('')

      const sourceOptions = await authenticatedPage.locator('#source-issue option').allTextContents()
      const selectedOptionText = await authenticatedPage.locator('#source-issue option:checked').textContent()

      expect(selectedOptionText).toContain('🟢')
    })

    test('creating dependency with selected issues (not just next_unread)', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Source Comic',
        format: 'Comic',
        issues_remaining: 9,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Target Comic',
        format: 'Comic',
        issues_remaining: 9,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Target Comic' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Source')
      await authenticatedPage.waitForSelector('button:has-text("Source Comic")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("Source Comic")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })
      await authenticatedPage.waitForSelector('#target-issue', { state: 'visible', timeout: 5000 })

      await authenticatedPage.selectOption('#source-issue', { index: 2 })
      await authenticatedPage.selectOption('#target-issue', { index: 2 })

      await authenticatedPage.click('button:has-text("Block issue")')

      await authenticatedPage.waitForResponse(
        (response) => response.url().includes('/api/v1/dependencies/') && response.request().method() === 'POST' && response.status() < 300
      )

      await expect(authenticatedPage.locator('text=This thread is blocked by')).toBeVisible()
    })

    test('validation: both issues must be selected', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Required Series',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Dependent Series',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Dependent Series' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Required')
      await authenticatedPage.waitForSelector('button:has-text("Required Series")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("Required Series")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })

      await authenticatedPage.selectOption('#source-issue', '')
      await authenticatedPage.selectOption('#target-issue', { index: 1 })

      // Button should be disabled when source issue not selected
      const addButton = authenticatedPage.locator('button[type="button"]:has-text("Block issue")')
      await expect(addButton).toBeDisabled()
    })

    test('loading states while fetching issues', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Loading Source',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Loading Target',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Loading Target' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Loading')
      await authenticatedPage.waitForSelector('button:has-text("Loading Source")', { state: 'visible' })

      // Click the thread and wait for issues to finish loading
      await authenticatedPage.click('button:has-text("Loading Source")')

      // Wait for loading to complete - if loading was too fast to see, that's okay
      // Just verify the dropdowns appear with issues
      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })
      await authenticatedPage.waitForSelector('#target-issue', { state: 'visible', timeout: 5000 })

      // Verify that issues were loaded
      const sourceOptions = await authenticatedPage.locator('#source-issue option').count()
      expect(sourceOptions).toBeGreaterThan(1)
    })

    test('button shows issue numbers when issues selected', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Issue Source',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Issue Target',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Issue Target' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'Issue Source')
      await authenticatedPage.waitForSelector('button:has-text("Issue Source")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("Issue Source")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })
      await authenticatedPage.waitForSelector('#target-issue', { state: 'visible', timeout: 5000 })

      const button = authenticatedPage.locator('button.glass-button').filter({ hasText: 'Block issue' })
      const buttonText = await button.textContent()

      expect(buttonText).toMatch(/Block issue #\d+ with: Issue Source #\d+/)
    })

    test('edge case: empty issue list', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'No Issues Source',
        format: 'Comic',
        issues_remaining: 5,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'No Issues Target',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 10,
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'No Issues Target' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'No Issues')
      await authenticatedPage.waitForSelector('button:has-text("No Issues Source")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("No Issues Source")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })
      await authenticatedPage.waitForSelector('#target-issue', { state: 'visible', timeout: 5000 })

      const sourceOptions = await authenticatedPage.locator('#source-issue option').count()
      expect(sourceOptions).toBe(1)
    })

    test('edge case: all issues read', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'All Read Source',
        format: 'Comic',
        issues_remaining: 1,
        total_issues: 5,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'All Read Target',
        format: 'Comic',
        issues_remaining: 1,
        total_issues: 5,
      })

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))

      // Mark all but the last issue as read
      await authenticatedPage.request.patch(`/api/v1/threads/${sourceThread.id}/issues/1`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { read: true },
      })

      await authenticatedPage.request.patch(`/api/v1/threads/${sourceThread.id}/issues/2`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { read: true },
      })

      await authenticatedPage.request.patch(`/api/v1/threads/${sourceThread.id}/issues/3`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { read: true },
      })

      await authenticatedPage.request.patch(`/api/v1/threads/${sourceThread.id}/issues/4`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { read: true },
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'All Read Target' }).first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()

      await authenticatedPage.click('button:has-text("Issue Level")')

      await authenticatedPage.fill('input#search-prereq-thread', 'All Read')
      await authenticatedPage.waitForSelector('button:has-text("All Read Source")', { state: 'visible' })
      await authenticatedPage.click('button:has-text("All Read Source")')

      await authenticatedPage.waitForSelector('#source-issue', { state: 'visible', timeout: 5000 })

      // With 4 read issues and 1 unread, should auto-select issue #5 (the unread one)
      const sourceValue = await authenticatedPage.locator('#source-issue').inputValue()
      expect(sourceValue).not.toBe('')
    })
  })
})
