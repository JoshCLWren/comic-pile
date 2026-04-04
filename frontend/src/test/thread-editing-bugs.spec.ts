import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';
import { createThread, extractThreadsFromResponse, findByTitle } from './helpers';

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

  let lastResponse: Response | undefined;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const response = await page.request.fetch(url, options);
    lastResponse = response;

    if (response.ok() || (response.status() >= 400 && response.status() < 500 && response.status() !== 408)) {
      return response;
    }

    if (response.status() >= 500 || response.status() === 408) {
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
      continue;
    }

    return response;
  }

  return lastResponse!;
}

async function waitForIssueMutation(page: Page, trigger: () => Promise<void>): Promise<void> {
  await Promise.all([
    page.waitForResponse(
      response =>
        response.request().method() === 'POST' &&
        response.url().includes('/issues') &&
        response.status() === 201
    ),
    trigger(),
  ]);
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
    const threads = extractThreadsFromResponse(await threadsResponse.json());
    const thread = findByTitle(threads, uniqueTitle);
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
    await waitForIssueMutation(authenticatedPage, () => addIssuesButton.click());
    await authenticatedPage.waitForLoadState('networkidle');

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

  test('should add issues with Enter without submitting the edit form', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Issue Enter Key Test ${timestamp}`;

    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 5,
      total_issues: 5,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = extractThreadsFromResponse(await threadsResponse.json());
    const thread = findByTitle(threads, uniqueTitle);
    expect(thread).toBeDefined();

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await addIssuesInput.fill('Annual 1');

    await waitForIssueMutation(authenticatedPage, () => addIssuesInput.press('Enter'));
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(editModal).toBeVisible();
    await expect(editModal.locator('h2')).toContainText('Edit Thread');

    const issuesResponse = await makeAuthenticatedRequest(
      authenticatedPage,
      'GET',
      `/api/v1/threads/${thread.id}/issues`
    );
    expect(issuesResponse.ok()).toBeTruthy();
    const issuesData = await issuesResponse.json();
    expect(issuesData.issues.length).toBe(6);
    expect(issuesData.issues.map((issue: any) => issue.issue_number)).toContain('Annual 1');
  });

  test('should preserve native validation when saving the edit modal', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Issue Validation Test ${timestamp}`;

    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 5,
      total_issues: 5,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    const titleInput = editModal.locator('input').first();
    await titleInput.fill('');

    await editModal.getByRole('button', { name: 'Save Changes' }).click();

    await expect(editModal).toBeVisible();
    const validationMessage = await titleInput.evaluate((input: HTMLInputElement) => input.validationMessage);
    expect(validationMessage).not.toBe('');
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
    const threads = extractThreadsFromResponse(await threadsResponse.json());
    const thread = findByTitle(threads, uniqueTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    // Monitor for 401 errors
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

    // Open edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    // Add issues in request order; backend appends new issues after all existing ones.
    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await addIssuesInput.fill('Annual 1, 6-7');

    const addIssuesButton = editModal.locator('[data-testid="issue-add-button"]');
    await waitForIssueMutation(authenticatedPage, () => addIssuesButton.click());
    await authenticatedPage.waitForLoadState('networkidle');

    // Verify modal is still open
    await expect(editModal).toBeVisible();

    // Check for 401 errors
    expect(failedRequests).toHaveLength(0);

    // Verify issues were added correctly
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    // Should have 8 issues now (5 original + Annual 1 + 6-7)
    expect(issuesData.issues.length).toBe(8);

    const appendedIssues = issuesData.issues.slice(-3);
    expect(appendedIssues.map((issue: any) => issue.issue_number)).toEqual(['Annual 1', '6', '7']);
    expect(appendedIssues.map((issue: any) => issue.position)).toEqual([6, 7, 8]);
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
    const threads = extractThreadsFromResponse(await threadsResponse.json());
    const thread = findByTitle(threads, uniqueTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    // Get initial page URL
    const initialUrl = authenticatedPage.url();

    // Monitor for 401 errors
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

    // Open edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });

    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    // Add an issue
    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await addIssuesInput.fill('4');
    await waitForIssueMutation(
      authenticatedPage,
      () => editModal.locator('[data-testid="issue-add-button"]').click()
    );
    await authenticatedPage.waitForLoadState('networkidle');

    // Check if URL changed (indicating full page navigation)
    const currentUrl = authenticatedPage.url();
    expect(currentUrl).toBe(initialUrl);

    // Check if modal is still open (if it closed, it might indicate a re-render issue)
    await expect(editModal).toBeVisible();

    // Check for 401 errors
    expect(failedRequests).toHaveLength(0);

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
      issue_range: '1-2',
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
    await expect(addIssuesInput).toBeVisible({ timeout: 5000 });
    await addIssuesInput.fill('Annual 2');

    const addIssuesButton = editModal.locator('[data-testid="issue-add-button"]');
    await expect(addIssuesButton).toBeVisible({ timeout: 5000 });
    await waitForIssueMutation(authenticatedPage, () => addIssuesButton.click());
    await authenticatedPage.waitForResponse(
      response =>
        response.request().method() === 'GET' &&
        response.url().includes('/issues') &&
        response.status() === 200
    );
    await authenticatedPage.waitForLoadState('networkidle');

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

  test('should add annual issue to existing migrated thread', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Migrated Thread Test ${timestamp}`;

    // Step 1: Create thread with issues 21-31
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 11,
      issue_range: '21-31',
    });

    // Get the thread ID
    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = extractThreadsFromResponse(await threadsResponse.json());
    const thread = findByTitle(threads, uniqueTitle);
    expect(thread).toBeDefined();
    expect(thread.id).toBeDefined();

    // Step 2: Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Step 3: Open the edit modal for the thread
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.waitFor({ state: 'visible', timeout: 5000 });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    
    // Verify modal is open
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    // Step 3.5: Monitor all network requests for 401 errors during the operation
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

    // Step 4: Add "Annual 3" using the add issues form
    const addIssuesInput = editModal.locator('[data-testid="issue-add-input"]');
    await expect(addIssuesInput).toBeVisible({ timeout: 5000 });
    await addIssuesInput.fill('Annual 3');

    const addIssuesButton = editModal.locator('[data-testid="issue-add-button"]');
    await waitForIssueMutation(authenticatedPage, () => addIssuesButton.click());
    await authenticatedPage.waitForLoadState('networkidle');

    // CRITICAL CHECK: Verify modal stays open after adding issues
    // This was the bug - the modal would close unexpectedly
    const modalStillVisible = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(modalStillVisible).toBeVisible();

    // Check for any 401 errors that occurred during the operation
    if (failedRequests.length > 0) {
      console.error('❌ 401 errors detected during issue add operation:', failedRequests);
    }
    expect(failedRequests).toHaveLength(0);

    // Wait for network to settle after issues list refresh
    // The modal's issues list needs to refetch after adding, which involves:
    // 1. POST request to add the issue
    // 2. GET request to refresh issues list
    // 3. React state update and re-render
    await authenticatedPage.waitForLoadState('networkidle');

    // Wait for issues list to finish loading (not in loading state)
    await expect(editModal.locator('text=Loading issues…')).not.toBeVisible({ timeout: 10000 });

    // If the issues list is truncated (>5 issues and collapsed), expand to show all
    const showAllButton = editModal.locator('button:has-text("Show all")');
    if (await showAllButton.count() > 0) {
      await showAllButton.click();
      // Wait for the list to expand (the button text should change)
      await expect(editModal.locator('button:has-text("Show fewer")')).toBeVisible({ timeout: 5000 });
    }

    // Verify issues list in modal refreshed and shows the new annual issue
    // Increased timeout to 10s to account for: network latency, API response time, state update, re-render
    const annualInModal = editModal.getByRole('button', {
      name: /^Toggle issue #Annual 3$/,
    });
    await expect(annualInModal).toBeVisible({ timeout: 10000 });

    // Step 6: Verify annual was added by checking the API
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    expect(issuesResponse.ok()).toBeTruthy();
    const issuesData = await issuesResponse.json();

    // Should have 12 issues now (11 original + Annual 3)
    expect(issuesData.issues.length).toBe(12);

    // Verify Annual 3 is in the list
    const annualIssue = issuesData.issues.find((i: any) => i.issue_number === 'Annual 3');
    expect(annualIssue).toBeDefined();

    // Step 7: Verify annual appears at end (API appends new issues after all existing)
    const lastIssue = issuesData.issues[issuesData.issues.length - 1];
    
    expect(lastIssue.issue_number).toBe('Annual 3');
    expect(lastIssue.position).toBe(12);

    // Verify thread metadata was updated
    const threadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    expect(threadResponse.ok()).toBeTruthy();
    const threadData = await threadResponse.json();
    
    expect(threadData.total_issues).toBe(12);
    expect(threadData.issues_remaining).toBe(12);
  });
});
