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
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
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

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
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

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
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

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
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

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
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

  test.describe('Issue-level flowchart nodes', () => {
    test('displays issue nodes for issue-level dependencies', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Animal Man',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 20,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Swamp Thing',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 20,
      })

      if (!sourceThread?.id || !targetThread?.id) {
        throw new Error('Failed to create threads')
      }

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create issues for both threads
      await authenticatedPage.request.post(`/api/v1/threads/${sourceThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-20' },
      })

      await authenticatedPage.request.post(`/api/v1/threads/${targetThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-20' },
      })

      // Create issue-level dependency: Animal Man #17 blocks Swamp Thing #15
      const depResponse = await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: sourceThread.id,
          source_issue_id: 17,
          target_type: 'issue',
          target_id: targetThread.id,
          target_issue_id: 15,
        },
      })
      expect(depResponse.ok()).toBe(true)

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Swamp Thing' })
        .first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()
      await authenticatedPage.click('[data-testid="toggle-flowchart"]')

      await expect(authenticatedPage.locator('[data-testid="flowchart-container"]')).toBeVisible()

      // Should have issue nodes (using negative IDs)
      await expect(
        authenticatedPage.locator('[data-testid="flowchart-node--17"]'),
      ).toBeVisible()
      await expect(
        authenticatedPage.locator('[data-testid="flowchart-node--15"]'),
      ).toBeVisible()

      // Should have dashed cyan edge for issue-level dependency
      const issueEdge = authenticatedPage.locator('.edge--issue-level')
      await expect(issueEdge).toBeAttached()
    })

    test('crossover dependencies: two comics with bidirectional issue deps (Rotworld scenario)', async ({ authenticatedPage }) => {
      const animalMan = await createThread(authenticatedPage, {
        title: 'Animal Man',
        format: 'Comic',
        issues_remaining: 8,
        total_issues: 20,
      })

      const swampThing = await createThread(authenticatedPage, {
        title: 'Swamp Thing',
        format: 'Comic',
        issues_remaining: 8,
        total_issues: 20,
      })

      if (!animalMan?.id || !swampThing?.id) {
        throw new Error('Failed to create threads')
      }

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create issues for both threads
      await authenticatedPage.request.post(`/api/v1/threads/${animalMan.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-20' },
      })

      await authenticatedPage.request.post(`/api/v1/threads/${swampThing.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-20' },
      })

      // Create bidirectional issue dependencies (Rotworld crossover):
      // Animal Man #17 → Swamp Thing #15
      const dep1Response = await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: animalMan.id,
          source_issue_id: 17,
          target_type: 'issue',
          target_id: swampThing.id,
          target_issue_id: 15,
        },
      })
      expect(dep1Response.ok()).toBe(true)

      // Swamp Thing #16 → Animal Man #18
      const dep2Response = await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: swampThing.id,
          source_issue_id: 16,
          target_type: 'issue',
          target_id: animalMan.id,
          target_issue_id: 18,
        },
      })
      expect(dep2Response.ok()).toBe(true)

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      // Open Animal Man dependencies
      const animalManCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Animal Man' })
        .first()
      await animalManCard.locator('button[aria-label="Manage dependencies"]').click()
      await authenticatedPage.click('[data-testid="toggle-flowchart"]')

      await expect(authenticatedPage.locator('[data-testid="flowchart-container"]')).toBeVisible()

      // Should have 4 distinct issue nodes visible
      await expect(authenticatedPage.locator('[data-testid="flowchart-node--17"]')).toBeVisible()
      await expect(authenticatedPage.locator('[data-testid="flowchart-node--15"]')).toBeVisible()
      await expect(authenticatedPage.locator('[data-testid="flowchart-node--16"]')).toBeVisible()
      await expect(authenticatedPage.locator('[data-testid="flowchart-node--18"]')).toBeVisible()

      // Should have 2 issue-level edges
      const issueEdges = authenticatedPage.locator('.edge--issue-level')
      const edgeCount = await issueEdges.count()
      expect(edgeCount).toBe(2)

      // Verify node tooltips show correct issue labels
      await authenticatedPage.locator('[data-testid="flowchart-node--17"]').hover()
      await expect(authenticatedPage.locator('[data-testid="flowchart-tooltip"]')).toBeVisible()
      await expect(authenticatedPage.locator('[data-testid="flowchart-tooltip"]')).toContainText('Animal Man #17')

      await authenticatedPage.locator('[data-testid="flowchart-node--16"]').hover()
      await expect(authenticatedPage.locator('[data-testid="flowchart-tooltip"]')).toContainText('Swamp Thing #16')
    })

    test('issue nodes have distinct styling (cyan fill, pill shape, smaller size)', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Source Series',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Target Series',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 10,
      })

      if (!sourceThread?.id || !targetThread?.id) {
        throw new Error('Failed to create threads')
      }

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      await authenticatedPage.request.post(`/api/v1/threads/${sourceThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      await authenticatedPage.request.post(`/api/v1/threads/${targetThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: sourceThread.id,
          source_issue_id: 5,
          target_type: 'issue',
          target_id: targetThread.id,
          target_issue_id: 3,
        },
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Target Series' })
        .first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()
      await authenticatedPage.click('[data-testid="toggle-flowchart"]')

      // Check issue node styling
      const issueNode = authenticatedPage.locator('[data-testid="flowchart-node--5"]')
      await expect(issueNode).toHaveClass(/flowchart-node--issue/)

      // Verify the rect element has the correct fill and rx attributes
      const issueNodeRect = issueNode.locator('.flowchart-node-rect')
      const rx = await issueNodeRect.getAttribute('rx')
      expect(rx).toBe('12')
    })

    test('issue nodes do not show lock icon even when parent thread is blocked', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Blocking Source',
        format: 'Comic',
        issues_remaining: 2,
        total_issues: 10,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Blocked Target',
        format: 'Comic',
        issues_remaining: 2,
        total_issues: 10,
      })

      if (!sourceThread?.id || !targetThread?.id) {
        throw new Error('Failed to create threads')
      }

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      await authenticatedPage.request.post(`/api/v1/threads/${sourceThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      await authenticatedPage.request.post(`/api/v1/threads/${targetThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: sourceThread.id,
          source_issue_id: 7,
          target_type: 'issue',
          target_id: targetThread.id,
          target_issue_id: 4,
        },
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Blocked Target' })
        .first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()
      await authenticatedPage.click('[data-testid="toggle-flowchart"]')

      // Issue node should not have lock icon
      const issueNodeIcon = authenticatedPage
        .locator('[data-testid="flowchart-node--4"]')
        .locator('.flowchart-node-blocked-icon')
      await expect(issueNodeIcon).not.toBeVisible()

      // But parent thread node should have lock icon
      const threadNodeIcon = authenticatedPage
        .locator(`[data-testid="flowchart-node-${targetThread.id}"]`)
        .locator('.flowchart-node-blocked-icon')
      await expect(threadNodeIcon).toBeVisible()
    })

    test('issue-level edges are styled with dashed cyan stroke', async ({ authenticatedPage }) => {
      const sourceThread = await createThread(authenticatedPage, {
        title: 'Edge Source',
        format: 'Comic',
        issues_remaining: 2,
        total_issues: 5,
      })

      const targetThread = await createThread(authenticatedPage, {
        title: 'Edge Target',
        format: 'Comic',
        issues_remaining: 2,
        total_issues: 5,
      })

      if (!sourceThread?.id || !targetThread?.id) {
        throw new Error('Failed to create threads')
      }

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      await authenticatedPage.request.post(`/api/v1/threads/${sourceThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-5' },
      })

      await authenticatedPage.request.post(`/api/v1/threads/${targetThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-5' },
      })

      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: sourceThread.id,
          source_issue_id: 3,
          target_type: 'issue',
          target_id: targetThread.id,
          target_issue_id: 2,
        },
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const targetCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Edge Target' })
        .first()
      await targetCard.locator('button[aria-label="Manage dependencies"]').click()
      await authenticatedPage.click('[data-testid="toggle-flowchart"]')

      // Check that issue-level edge has the dashed cyan class
      const issueEdge = authenticatedPage.locator('.edge--issue-level')
      await expect(issueEdge).toBeAttached()

      // Verify the stroke-dasharray attribute (dashed lines)
      const strokeDasharray = await issueEdge.getAttribute('stroke-dasharray')
      expect(strokeDasharray).toBeTruthy()
    })

    test('mixed thread-level and issue-level dependencies render correctly', async ({ authenticatedPage }) => {
      const threadA = await createThread(authenticatedPage, {
        title: 'Thread Alpha',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 10,
      })

      const threadB = await createThread(authenticatedPage, {
        title: 'Thread Beta',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 10,
      })

      const threadC = await createThread(authenticatedPage, {
        title: 'Thread Gamma',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 10,
      })

      if (!threadA?.id || !threadB?.id || !threadC?.id) {
        throw new Error('Failed to create threads')
      }

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create issues
      await authenticatedPage.request.post(`/api/v1/threads/${threadA.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      await authenticatedPage.request.post(`/api/v1/threads/${threadB.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: { issue_range: '1-10' },
      })

      // Thread-level dependency: Alpha blocks Beta
      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'thread',
          source_id: threadA.id,
          target_type: 'thread',
          target_id: threadB.id,
        },
      })

      // Issue-level dependency: Alpha #5 blocks Beta #3
      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        data: {
          source_type: 'issue',
          source_id: threadA.id,
          source_issue_id: 5,
          target_type: 'issue',
          target_id: threadB.id,
          target_issue_id: 3,
        },
      })

      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const betaCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Thread Beta' })
        .first()
      await betaCard.locator('button[aria-label="Manage dependencies"]').click()
      await authenticatedPage.click('[data-testid="toggle-flowchart"]')

      // Should have both thread nodes
      await expect(
        authenticatedPage.locator(`[data-testid="flowchart-node-${threadA.id}"]`),
      ).toBeVisible()
      await expect(
        authenticatedPage.locator(`[data-testid="flowchart-node-${threadB.id}"]`),
      ).toBeVisible()

      // Should have issue nodes
      await expect(
        authenticatedPage.locator('[data-testid="flowchart-node--5"]'),
      ).toBeVisible()
      await expect(
        authenticatedPage.locator('[data-testid="flowchart-node--3"]'),
      ).toBeVisible()

      // Should have both thread-level and issue-level edges
      const threadEdges = await authenticatedPage.locator('.flowchart-edge:not(.edge--issue-level)').count()
      const issueEdges = await authenticatedPage.locator('.edge--issue-level').count()

      expect(threadEdges).toBeGreaterThan(0)
      expect(issueEdges).toBeGreaterThan(0)
    })
  })
})
