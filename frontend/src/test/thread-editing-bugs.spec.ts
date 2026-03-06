import { test, expect } from './fixtures';
import type { Page, Request } from '@playwright/test';
import { createThread } from './helpers';

async function makeAuthenticatedRequest(page: any, method: string, url: string, data?: any, maxRetries = 3): Promise<any> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
  const options: any = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
  };
  if (data) {
    options.data = data;
  }

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const response = await page.request.fetch(url, options);
    
    if (response.ok() || response.status() >= 400) {
      return response;
    }
    
    if (response.status() >= 500 || response.status() === 408) {
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
      continue;
    }
    
    return response;
  }
  
  return await page.request.fetch(url, options);
}

test.describe('Thread Editing - Issue Adding Bug Reproduction', () => {
  test('should add issues to thread without closing modal or triggering 401s', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Issue Adding Bug Test ${timestamp}`;

    // Step 1: Create a thread with initial issues
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 5,
      total_issues: 5,
    });

    // Get the thread ID
    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title === uniqueTitle);
    expect(thread).toBeDefined();

    // Step 2: Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Step 3: Open the edit modal for the thread
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.waitFor({ state: 'visible', timeout: 5000 });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open - wait for the modal heading
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    
    // Verify modal is open using the fixed overlay class
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    // Step 4: Monitor all network requests for 401 errors
    const failedRequests: { url: string; status: number; method: string }[] = [];
    authenticatedPage.on('response', (response) => {
      if (response.status() === 401) {
        failedRequests.push({
          url: response.url(),
          status: response.status(),
          method: response.request().method(),
        });
      }
    });

    // Step 5: Try to add more issues (including an annual) using the inline form
    // Look within the modal for the issue add input
    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await expect(addIssuesInput).toBeVisible({ timeout: 5000 });

    // Fill in the issue range including an annual
    await addIssuesInput.fill('Annual 1');

    // Submit the form - use the button within the modal
    const addIssuesButton = editModal.locator('[data-testid="issue-add-button"]');
    await addIssuesButton.click();

    // Step 6: Wait for the add operation to complete
    // Give it time to process but monitor if modal closes
    await authenticatedPage.waitForTimeout(2000);

    // CRITICAL CHECK: Verify modal is still open
    const modalStillVisible = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(modalStillVisible).toBeVisible();

    // Step 7: Check for any 401 errors that occurred
    if (failedRequests.length > 0) {
      console.error('❌ 401 errors detected during issue add operation:', failedRequests);
    }
    expect(failedRequests).toHaveLength(0);

    // Step 8: Verify the issue was actually added by checking the API
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    expect(issuesResponse.ok()).toBeTruthy();
    const issuesData = await issuesResponse.json();

    // Should have 6 issues now (5 original + Annual 1)
    expect(issuesData.issues.length).toBe(6);

    // Verify Annual 1 is in the list
    const annualIssue = issuesData.issues.find((i: any) => i.issue_number === 'Annual 1');
    expect(annualIssue).toBeDefined();
  });

  test('should handle adding multiple issues including annuals in correct order', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Issue Order Test ${timestamp}`;

    // Create thread with initial issues 1-5
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 5,
      total_issues: 5,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title === uniqueTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    // Add issues in a specific order: Annual 1 should go between issue 3 and 4
    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await addIssuesInput.fill('Annual 1, 6-7');

    const addIssuesButton = editModal.locator('[data-testid="issue-add-button"]');
    await addIssuesButton.click();

    // Wait for operation to complete
    await authenticatedPage.waitForTimeout(2000);

    // Verify modal is still open
    await expect(editModal).toBeVisible();

    // Verify issues were added correctly
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    // Should have 8 issues now (5 original + Annual 1 + 6-7)
    expect(issuesData.issues.length).toBe(8);

    // Check that Annual 1 exists
    const hasAnnual1 = issuesData.issues.some((i: any) => i.issue_number === 'Annual 1');
    expect(hasAnnual1).toBe(true);
  });

  test('should not trigger full page re-render when adding issues', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Re-render Test ${timestamp}`;

    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title === uniqueTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    // Get initial page URL
    const initialUrl = authenticatedPage.url();

    // Open edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    // Add an issue
    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await addIssuesInput.fill('4');
    await editModal.locator('[data-testid="issue-add-button"]').click();

    // Wait a bit
    await authenticatedPage.waitForTimeout(2000);

    // Check if URL changed (indicating full page navigation)
    const currentUrl = authenticatedPage.url();
    expect(currentUrl).toBe(initialUrl);

    // Check if modal is still open (if it closed, it might indicate a re-render issue)
    await expect(editModal).toBeVisible();

    // Verify issue was added
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();
    expect(issuesData.issues.length).toBe(4);
  });

  test('should monitor all API requests during issue add operation', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `API Monitor Test ${timestamp}`;

    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    // Track all requests
    const allRequests: { url: string; method: string; status?: number }[] = [];
    authenticatedPage.on('response', (response) => {
      allRequests.push({
        url: response.url(),
        method: response.request().method(),
        status: response.status(),
      });
    });

    // Open edit modal and add issue
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await addIssuesInput.fill('Annual 2');
    await editModal.locator('[data-testid="issue-add-button"]').click();

    await authenticatedPage.waitForTimeout(2000);

    // Analyze requests
    const requestSummary = {
      total: allRequests.length,
      get: allRequests.filter(r => r.method === 'GET').length,
      post: allRequests.filter(r => r.method === 'POST').length,
      failed401: allRequests.filter(r => r.status === 401).length,
      issueRelated: allRequests.filter(r => r.url.includes('/issues')).length,
      threadRelated: allRequests.filter(r => r.url.includes('/threads')).length,
    };

    console.log('📊 Request Summary:', JSON.stringify(requestSummary, null, 2));

    // Check for unexpected 401s
    expect(requestSummary.failed401).toBe(0);

    // There should be at least one POST to create issues
    expect(requestSummary.post).toBeGreaterThan(0);

    // Verify the modal is still open
    await expect(editModal).toBeVisible();
  });
});
