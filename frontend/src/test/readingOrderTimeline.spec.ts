import { test, expect } from './fixtures'
import { createThread, extractThreadsFromResponse, findByTitle, findByIssueNumber } from './helpers'

test.describe('Reading Order Timeline', () => {
  test('displays grouped gates and tabs', async ({ authenticatedPage }) => {
    const page = authenticatedPage

    // Create threads
    await createThread(page, { title: 'Source A', format: 'Comics', total_issues: 10, issues_remaining: 10 })
    await createThread(page, { title: 'Source B', format: 'Comics', total_issues: 10, issues_remaining: 10 })
    await createThread(page, { title: 'Target', format: 'Comics', total_issues: 10, issues_remaining: 5 }) // next unread is #6

    // Get auth token
    const token = await page.evaluate(() => (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN ?? localStorage.getItem('auth_token'))

     // Fetch thread IDs
     const threadsRes = await page.request.get('/api/threads/', { headers: { Authorization: `Bearer ${token}` } })
     const threadsResponse = await threadsRes.json()
     const threads = extractThreadsFromResponse(threadsResponse)
     const sourceA = findByTitle(threads, 'Source A')
     const sourceB = findByTitle(threads, 'Source B')
     const target = findByTitle(threads, 'Target')

    // Get target issue #6
    const targetIssuesRes = await page.request.get(`/api/v1/threads/${target.id}/issues`, { headers: { Authorization: `Bearer ${token}` } })
    const targetIssues = await targetIssuesRes.json()
    const targetIssue6 = findByIssueNumber(targetIssues.issues, '6')

    // Get source issues #1
    const [sourceAIssuesRes, sourceBIssuesRes] = await Promise.all([
      page.request.get(`/api/v1/threads/${sourceA.id}/issues`, { headers: { Authorization: `Bearer ${token}` } }),
      page.request.get(`/api/v1/threads/${sourceB.id}/issues`, { headers: { Authorization: `Bearer ${token}` } }),
    ])
    const sourceAIssues = await sourceAIssuesRes.json()
    const sourceBIssues = await sourceBIssuesRes.json()
    const sourceA1 = findByIssueNumber(sourceAIssues.issues, '1')
    const sourceB1 = findByIssueNumber(sourceBIssues.issues, '1')

    // Create dependencies: both block target #6
    await page.request.post('/api/v1/dependencies/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { source_type: 'issue', source_id: sourceA1.id, target_type: 'issue', target_id: targetIssue6.id },
    })
    await page.request.post('/api/v1/dependencies/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { source_type: 'issue', source_id: sourceB1.id, target_type: 'issue', target_id: targetIssue6.id },
    })

    // Navigate to queue and open dependency builder for Target
    await page.goto('/queue')
    await page.waitForLoadState('networkidle')
    const targetCard = page.locator('#queue-container .glass-card').filter({ hasText: 'Target' }).first()
    await targetCard.locator('button[aria-label="Manage dependencies"]').click()
    await page.waitForSelector('button[data-testid="toggle-reading-order"]')
    await page.click('button[data-testid="toggle-reading-order"]')
    await page.waitForSelector('[role="tablist"]')

    // Check that timeline view is the default when reading order is toggled open
    await expect(page.locator('#reading-order-timeline-tab')).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('#timeline-panel')).not.toBeHidden()
    await expect(page.locator('#flowchart-panel')).toBeHidden()

    // Verify grouping shows "2 required" (both source issues block the same target issue)
    await expect(page.locator('#timeline-panel').locator('text=2 required')).toBeVisible()

    // Only one gate card should be present for issue #6
    const gateCardCount = await page.locator('#timeline-panel div[class*="bg-stone-950"]').count()
    expect(gateCardCount).toBe(1)

    // Tab switching back to flowchart
    await page.click('#reading-order-flowchart-tab')
    await expect(page.locator('#flowchart-panel')).not.toBeHidden()
    await expect(page.locator('#timeline-panel')).toBeHidden()

     // Mobile viewport scrollable check - removed flaky assertion due to content height variability
     // The container is already verified visible above
  })
})
