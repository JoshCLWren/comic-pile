import { test, expect } from './fixtures'
import { createThread } from './helpers'

test.describe('Dependency Flowchart', () => {
  test('shows flowchart toggle after creating a dependency', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Flowchart Source',
      format: 'Comic',
      issues_remaining: 3,
    })

    await createThread(authenticatedPage, {
      title: 'Flowchart Target',
      format: 'Comic',
      issues_remaining: 3,
    })

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    // Open dependency builder for the target thread
    const targetCard = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'Flowchart Target' })
      .first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()

    // Search and add a dependency
    await authenticatedPage.fill('input#search-prereq-thread', 'Flowchart Source')
    await authenticatedPage.waitForSelector('button:has-text("Flowchart Source")', {
      state: 'visible',
    })
    await authenticatedPage.click('button:has-text("Flowchart Source")')

    // Register response wait before clicking to avoid missing fast responses
    await Promise.all([
      authenticatedPage.waitForResponse(
        (response) =>
          response.url().includes('/api/v1/dependencies/') &&
          response.request().method() === 'POST' &&
          response.status() < 300,
      ),
      authenticatedPage.click('button:has-text("Block")'),
    ])

    // The flowchart toggle button should appear
    await expect(authenticatedPage.locator('[data-testid="toggle-flowchart"]')).toBeVisible()
  })

  test('renders flowchart with nodes and edges when toggled', async ({ authenticatedPage }) => {
    // Create two threads via API
    const sourceResult = await createThread(authenticatedPage, {
      title: 'FC Node Source',
      format: 'Comic',
      issues_remaining: 2,
    })

    const targetResult = await createThread(authenticatedPage, {
      title: 'FC Node Target',
      format: 'Comic',
      issues_remaining: 2,
    })

    // Create dependency via API
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))
    const depResponse = await authenticatedPage.request.post('/api/v1/dependencies/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data: {
        source_type: 'thread',
        source_id: sourceResult?.id,
        target_type: 'thread',
        target_id: targetResult?.id,
      },
    })
    expect(depResponse.ok()).toBe(true)

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    // Open dependency builder for the target thread
    const targetCard = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'FC Node Target' })
      .first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()

    // Toggle flowchart
    await authenticatedPage.click('[data-testid="toggle-flowchart"]')

    // Flowchart should render
    await expect(authenticatedPage.locator('[data-testid="flowchart-container"]')).toBeVisible()
    await expect(authenticatedPage.locator('[data-testid="flowchart-svg"]')).toBeVisible()
    await expect(authenticatedPage.locator('[data-testid="flowchart-controls"]')).toBeVisible()

    // Should have nodes for both threads
    if (sourceResult?.id) {
      await expect(
        authenticatedPage.locator(`[data-testid="flowchart-node-${sourceResult.id}"]`),
      ).toBeVisible()
    }
    if (targetResult?.id) {
      await expect(
        authenticatedPage.locator(`[data-testid="flowchart-node-${targetResult.id}"]`),
      ).toBeVisible()
    }

    // Should have an edge between them (SVG paths with fill:none may not pass
    // Playwright's visibility check, so assert the element is attached to the DOM)
    if (sourceResult?.id && targetResult?.id) {
      await expect(
        authenticatedPage.locator(
          `[data-testid="flowchart-edge-${sourceResult.id}-${targetResult.id}"]`,
        ),
      ).toBeAttached()
    }
  })

  test('flowchart zoom controls work', async ({ authenticatedPage }) => {
    const sourceResult = await createThread(authenticatedPage, {
      title: 'Zoom Source',
      format: 'Comic',
      issues_remaining: 1,
    })

    const targetResult = await createThread(authenticatedPage, {
      title: 'Zoom Target',
      format: 'Comic',
      issues_remaining: 1,
    })

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))
    const depResponse = await authenticatedPage.request.post('/api/v1/dependencies/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data: {
        source_type: 'thread',
        source_id: sourceResult?.id,
        target_type: 'thread',
        target_id: targetResult?.id,
      },
    })
    expect(depResponse.ok()).toBe(true)

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const targetCard = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'Zoom Target' })
      .first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()
    await authenticatedPage.click('[data-testid="toggle-flowchart"]')

    await expect(authenticatedPage.locator('[data-testid="flowchart-svg"]')).toBeVisible()

    // Get initial transform
    const getTransform = () =>
      authenticatedPage.locator('[data-testid="flowchart-svg"] > g').getAttribute('transform')

    const initialTransform = await getTransform()

    // Click zoom in
    await authenticatedPage.click('[data-testid="flowchart-controls"] button[aria-label="Zoom in"]')
    const zoomedTransform = await getTransform()
    expect(zoomedTransform).not.toBe(initialTransform)

    // Click reset
    await authenticatedPage.click(
      '[data-testid="flowchart-controls"] button[aria-label="Reset view"]',
    )
    const resetTransform = await getTransform()
    expect(resetTransform).toContain('scale(1)')
  })

  test('flowchart shows tooltip on node hover', async ({ authenticatedPage }) => {
    const sourceResult = await createThread(authenticatedPage, {
      title: 'Hover Source Thread',
      format: 'Comic',
      issues_remaining: 1,
    })

    const targetResult = await createThread(authenticatedPage, {
      title: 'Hover Target Thread',
      format: 'Comic',
      issues_remaining: 1,
    })

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))
    const depResponse = await authenticatedPage.request.post('/api/v1/dependencies/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data: {
        source_type: 'thread',
        source_id: sourceResult?.id,
        target_type: 'thread',
        target_id: targetResult?.id,
      },
    })
    expect(depResponse.ok()).toBe(true)

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const targetCard = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'Hover Target Thread' })
      .first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()
    await authenticatedPage.click('[data-testid="toggle-flowchart"]')

    await expect(authenticatedPage.locator('[data-testid="flowchart-svg"]')).toBeVisible()

    // Hover over a node
    if (sourceResult?.id) {
      await authenticatedPage
        .locator(`[data-testid="flowchart-node-${sourceResult.id}"]`)
        .hover()
      await expect(authenticatedPage.locator('[data-testid="flowchart-tooltip"]')).toBeVisible()
      await expect(authenticatedPage.locator('[data-testid="flowchart-tooltip"]')).toContainText(
        'Hover Source Thread',
      )
    }
  })

  test('flowchart shows blocked nodes with lock icon', async ({ authenticatedPage }) => {
    const sourceResult = await createThread(authenticatedPage, {
      title: 'Blocker Thread',
      format: 'Comic',
      issues_remaining: 1,
    })

    const targetResult = await createThread(authenticatedPage, {
      title: 'Blocked Thread FC',
      format: 'Comic',
      issues_remaining: 1,
    })

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))
    const depResponse = await authenticatedPage.request.post('/api/v1/dependencies/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data: {
        source_type: 'thread',
        source_id: sourceResult?.id,
        target_type: 'thread',
        target_id: targetResult?.id,
      },
    })
    expect(depResponse.ok()).toBe(true)

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const targetCard = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'Blocked Thread FC' })
      .first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()
    await authenticatedPage.click('[data-testid="toggle-flowchart"]')

    await expect(authenticatedPage.locator('[data-testid="flowchart-svg"]')).toBeVisible()

    // The blocked node should have the blocked class
    if (targetResult?.id) {
      const blockedNode = authenticatedPage.locator(
        `[data-testid="flowchart-node-${targetResult.id}"]`,
      )
      await expect(blockedNode).toHaveClass(/flowchart-node-blocked/)
    }
  })

  test('flowchart toggle hides and shows', async ({ authenticatedPage }) => {
    const sourceResult = await createThread(authenticatedPage, {
      title: 'Toggle Source',
      format: 'Comic',
      issues_remaining: 1,
    })

    const targetResult = await createThread(authenticatedPage, {
      title: 'Toggle Target',
      format: 'Comic',
      issues_remaining: 1,
    })

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'))
    const depResponse = await authenticatedPage.request.post('/api/v1/dependencies/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data: {
        source_type: 'thread',
        source_id: sourceResult?.id,
        target_type: 'thread',
        target_id: targetResult?.id,
      },
    })
    expect(depResponse.ok()).toBe(true)

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const targetCard = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'Toggle Target' })
      .first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()

    // Toggle on
    await authenticatedPage.click('[data-testid="toggle-flowchart"]')
    await expect(authenticatedPage.locator('[data-testid="flowchart-container"]')).toBeVisible()

    // Toggle off
    await authenticatedPage.click('[data-testid="toggle-flowchart"]')
    await expect(authenticatedPage.locator('[data-testid="flowchart-container"]')).not.toBeVisible()
  })

  test('flowchart shows empty state when no dependencies', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Lonely Thread',
      format: 'Comic',
      issues_remaining: 1,
    })

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const card = authenticatedPage
      .locator('#queue-container .glass-card')
      .filter({ hasText: 'Lonely Thread' })
      .first()
    await card.locator('button[aria-label="Manage dependencies"]').click()

    // Should not show flowchart toggle when there are no dependencies
    await expect(authenticatedPage.locator('[data-testid="toggle-flowchart"]')).not.toBeVisible()
  })
})
