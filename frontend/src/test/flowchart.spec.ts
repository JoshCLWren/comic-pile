import { test, expect } from './fixtures'
import {createThread, clickThreadAction} from './helpers'
import { waitForQueueReady } from './helpers'

async function getIssueIdByNumber(authenticatedPage: any, threadId: number, issueNumber: string, token: string | null | undefined): Promise<number> {
  if (!token) {
    throw new Error('No auth token available')
  }
  const response = await authenticatedPage.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: { 'Authorization': `Bearer ${token}` },
  })
  const data = await response.json()
  const issue = data.issues.find((i: { issue_number: string }) => i.issue_number === issueNumber)
  if (!issue?.id) {
    throw new Error(`Issue #${issueNumber} not found in thread ${threadId}`)
  }
  return issue.id
}

async function openFlowchartView(authenticatedPage: any): Promise<void> {
  await authenticatedPage.click('[data-testid="toggle-reading-order"]')
  await authenticatedPage.click('#reading-order-flowchart-tab')
  await expect(authenticatedPage.locator('[data-testid="flowchart-container"]')).toBeVisible()
}

test.describe('Dependency Flowchart', () => {
test('shows flowchart toggle after creating a dependency', async ({ authenticatedPage }) => {
  await createThread(authenticatedPage, {
    title: 'Flowchart Source',
    format: 'Comics',
    issues_remaining: 3,
    total_issues: 5,
  })

  await createThread(authenticatedPage, {
    title: 'Flowchart Target',
    format: 'Comics',
    issues_remaining: 3,
    total_issues: 5,
  })

  await authenticatedPage.goto('/queue')
  await waitForQueueReady(authenticatedPage)

  // Open dependency builder for the target thread
  const targetCard = authenticatedPage
    .locator('#queue-container .glass-card')
    .filter({ hasText: 'Flowchart Target' })
    .first()
  await clickThreadAction(targetCard, 'Manage dependencies')

  // Search and add a dependency
  await authenticatedPage.fill('input#search-prereq-thread', 'Flowchart Source')
  const dependencyDialog = authenticatedPage.locator('#comic-pile-overlay-root-dialog')
  await dependencyDialog.waitFor({ state: 'visible', timeout: 10000 })
  const sourceResult = dependencyDialog.getByRole('button', {
    name: 'Flowchart Source (Comics)',
    exact: true,
  })
  await expect(sourceResult).toBeVisible()
  await sourceResult.click()

  // The flowchart toggle button should appear
  await authenticatedPage.waitForSelector('[data-testid="toggle-reading-order"]', { state: 'visible', timeout: 10000 })
})
```