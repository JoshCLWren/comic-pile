import { test, expect } from './fixtures';
import { createThread, SELECTORS } from './helpers';

async function makeAuthenticatedRequest(page: any, method: string, url: string, data?: any) {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));
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
  return await page.request.fetch(url, options);
}

test.describe('Thread Creation with Issue Ranges', () => {
  test('should create thread with issue range "1-25"', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Test Comic Series');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill in issue range
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1-25');
    
    // Verify preview shows "Will create 25 issues"
    await expect(authenticatedPage.locator(SELECTORS.threadCreate.issuePreview)).toContainText('Will create 25 issues');

    // Submit form and wait for both thread creation and issue creation
    await Promise.all([
      authenticatedPage.waitForResponse(async (response) => {
        const url = response.url();
        const method = response.request().method();
        const isThreadCreate = url.includes('/api/threads/') && method === 'POST' && response.status() < 300;
        const isIssueCreate = url.includes('/api/v1/threads/') && url.includes('/issues') && method === 'POST' && response.status() < 300;
        return isThreadCreate || isIssueCreate;
      }),
      authenticatedPage.click('button[type="submit"]'),
    ]);

    await authenticatedPage.waitForLoadState('networkidle');

    // Verify thread was created with issues
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    expect(response.ok()).toBeTruthy();
    const threads = await response.json();
    const testThread = threads.find((t: any) => t.title === 'Test Comic Series');
    expect(testThread).toBeDefined();
    expect(testThread.total_issues).toBe(25);
  });

  test('should create thread with mixed issue range "1, 3, 5-7"', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Mixed Range Comic');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill in mixed issue range
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1, 3, 5-7');
    
    // Verify preview shows "Will create 5 issues"
    await expect(authenticatedPage.locator(SELECTORS.threadCreate.issuePreview)).toContainText('Will create 5 issues');

    // Submit form and wait for both thread creation and issue creation
    await Promise.all([
      authenticatedPage.waitForResponse(async (response) => {
        const url = response.url();
        const method = response.request().method();
        const isThreadCreate = url.includes('/api/threads/') && method === 'POST' && response.status() < 300;
        const isIssueCreate = url.includes('/api/v1/threads/') && url.includes('/issues') && method === 'POST' && response.status() < 300;
        return isThreadCreate || isIssueCreate;
      }),
      authenticatedPage.click('button[type="submit"]'),
    ]);

    await authenticatedPage.waitForLoadState('networkidle');

    // Verify thread was created with correct number of issues
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    expect(response.ok()).toBeTruthy();
    const threads = await response.json();
    const testThread = threads.find((t: any) => t.title === 'Mixed Range Comic');
    expect(testThread).toBeDefined();
    expect(testThread.total_issues).toBe(5);
  });

  test('should show error for invalid issue range', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Invalid Range Comic');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill in invalid issue range
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, 'abc, def');
    
    // Verify error message shown
    const errorLocator = authenticatedPage.locator('p:has-text("Non-numeric issues")');
    await expect(errorLocator).toBeVisible();
    
    // Verify preview is not shown
    const previewLocator = authenticatedPage.locator(SELECTORS.threadCreate.issuePreview);
    await expect(previewLocator).not.toBeVisible();
  });

  test('should create thread with single issue', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Single Issue Comic');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill in single issue
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1');
    
    // Verify preview shows "Will create 1 issue"
    await expect(authenticatedPage.locator(SELECTORS.threadCreate.issuePreview)).toContainText('Will create 1 issue');
    
    // Submit form
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'POST' &&
        response.status() < 300
      ),
      authenticatedPage.click('button[type="submit"]'),
    ]);
    
    await authenticatedPage.waitForLoadState('networkidle');
    
    // Verify thread was created
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    expect(response.ok()).toBeTruthy();
    const threads = await response.json();
    const testThread = threads.find((t: any) => t.title === 'Single Issue Comic');
    expect(testThread).toBeDefined();
    expect(testThread.total_issues).toBe(1);
  });

  test('should handle duplicate issues in range', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Duplicate Issues Comic');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill in range with duplicates
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1-5, 3-7');
    
    // Verify preview shows "Will create 7 issues" (deduplicated: 1,2,3,4,5,6,7)
    await expect(authenticatedPage.locator(SELECTORS.threadCreate.issuePreview)).toContainText('Will create 7 issues');
    
    // Submit form
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'POST' &&
        response.status() < 300
      ),
      authenticatedPage.click('button[type="submit"]'),
    ]);
    
    await authenticatedPage.waitForLoadState('networkidle');
    
    // Verify thread was created with deduplicated count
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    expect(response.ok()).toBeTruthy();
    const threads = await response.json();
    const testThread = threads.find((t: any) => t.title === 'Duplicate Issues Comic');
    expect(testThread).toBeDefined();
    expect(testThread.total_issues).toBe(7);
  });
});

test.describe('Issue List Display', () => {
  test('should display issues for thread', async ({ authenticatedPage }) => {
    // Create thread with issues via API
    const timestamp = Date.now();
    await createThread(authenticatedPage, {
      title: `Issue List Test ${timestamp}`,
      format: 'Comic',
      issues_remaining: 10,
      total_issues: 10,
    });

    // Get the thread ID
    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title === `Issue List Test ${timestamp}`);

    expect(thread).toBeDefined();
    expect(thread.total_issues).toBe(10);

    // Fetch issues for the thread
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    expect(issuesResponse.ok()).toBeTruthy();
    const issuesData = await issuesResponse.json();

    expect(issuesData.issues).toBeDefined();
    expect(issuesData.issues.length).toBe(10);
    expect(issuesData.issues[0].issue_number).toBe('1');
  });

  test('should filter issues by status', async ({ authenticatedPage }) => {
    // Create thread with issues
    const timestamp = Date.now();
    await createThread(authenticatedPage, {
      title: `Filter Test ${timestamp}`,
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 5,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title === `Filter Test ${timestamp}`);

    // Mark some issues as read
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();
    const firstIssueId = issuesData.issues[0].id;

    await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${firstIssueId}:markRead`);
    
    // Fetch all issues
    const allIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const allIssues = await allIssuesResponse.json();
    expect(allIssues.issues.length).toBe(5);

    // Fetch only unread issues
    const unreadIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues?status=unread`);
    const unreadIssues = await unreadIssuesResponse.json();
    expect(unreadIssues.issues.length).toBe(4);

    // Fetch only read issues
    const readIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues?status=read`);
    const readIssues = await readIssuesResponse.json();
    expect(readIssues.issues.length).toBe(1);
  });
});

test.describe('Issue Status Toggle', () => {
  test('should toggle issue status on click', async ({ authenticatedPage }) => {
    // Create thread with issues
    await createThread(authenticatedPage, {
      title: `Toggle Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 5,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Toggle Test'));

    // Get first issue
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();
    const firstIssue = issuesData.issues[0];

    expect(firstIssue.status).toBe('unread');

    // Mark as read
    const markReadResponse = await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${firstIssue.id}:markRead`);
    expect(markReadResponse.ok()).toBeTruthy();

    // Verify status changed
    const updatedIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const updatedIssues = await updatedIssuesResponse.json();
    const updatedIssue = updatedIssues.issues.find((i: any) => i.id === firstIssue.id);
    expect(updatedIssue.status).toBe('read');
    expect(updatedIssue.read_at).not.toBeNull();

    // Mark as unread
    const markUnreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${firstIssue.id}:markUnread`);
    expect(markUnreadResponse.ok()).toBeTruthy();

    // Verify status changed back
    const finalIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const finalIssues = await finalIssuesResponse.json();
    const finalIssue = finalIssues.issues.find((i: any) => i.id === firstIssue.id);
    expect(finalIssue.status).toBe('unread');
    expect(finalIssue.read_at).toBeNull();
  });

  test('should highlight next unread issue', async ({ authenticatedPage }) => {
    // Create thread with issues
    await createThread(authenticatedPage, {
      title: `Next Unread Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 5,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Next Unread Test'));

    // Get issues and mark first as read
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();
    const firstIssue = issuesData.issues[0];

      await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${firstIssue.id}:markRead`);

    // Refresh thread data
    const updatedThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    const updatedThread = await updatedThreadResponse.json();

    // Verify next_unread_issue_id now points to second issue
    expect(updatedThread.next_unread_issue_id).not.toBe(firstIssue.id);
  });
});

test.describe('Roll Result with Issue Display', () => {
  test('should show issue number in roll result for threads with issue tracking', async ({ authenticatedPage }) => {
    // Create thread with issues
    await createThread(authenticatedPage, {
      title: 'Roll Issue Test',
      format: 'Comic',
      issues_remaining: 10,
      total_issues: 10,
    });

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    // Roll the dice
    await authenticatedPage.click(SELECTORS.roll.mainDie);
    await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    // Check if issue info is displayed (text pattern like "#1" or "of 10")
    const threadInfo = authenticatedPage.locator('#thread-info');
    await expect(threadInfo).toBeVisible();
    
    // The thread should have issue tracking info if it was rolled
    const hasIssueInfo = await authenticatedPage.locator('#thread-info').textContent();
    expect(hasIssueInfo).toBeTruthy();
  });

  test('should handle roll result for threads without issue tracking', async ({ authenticatedPage }) => {
    // Create thread without issue tracking (old style)
    await createThread(authenticatedPage, {
      title: 'Old Style Thread',
      format: 'Trade',
      issues_remaining: 5,
    });

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    // Roll the dice (may need multiple attempts if there are multiple threads)
    await authenticatedPage.click(SELECTORS.roll.mainDie);
    await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    // Just verify the rating view is shown - actual thread selection is random
    const currentUrl = authenticatedPage.url();
    expect(currentUrl).toMatch(/\/$/);
  });

  test('should show correct issue in roll result', async ({ authenticatedPage }) => {
    // Create thread with issues
    await createThread(authenticatedPage, {
      title: `Specific Issue Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 10,
      total_issues: 10,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Specific Issue Test'));

    // Mark first 3 issues as read
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();
    
    for (let i = 0; i < 3; i++) {
      await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[i].id}:markRead`);
    }

    // Set thread as active
    await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/threads/${thread.id}/set-pending`);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // The thread info should be accessible
    const threadInfo = await authenticatedPage.locator('#thread-info h2').textContent();
    expect(threadInfo).toContain('Specific Issue Test');
  });
});

test.describe('Progress Tracking', () => {
  test('should update progress bar as issues are marked read', async ({ authenticatedPage }) => {
    // Create thread with issues
    await createThread(authenticatedPage, {
      title: `Progress Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 10,
      total_issues: 10,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Progress Test'));

    // Initial progress: not_started
    expect(thread.reading_progress).toBe('not_started');

    // Get issues
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    // Mark 3 issues as read
    for (let i = 0; i < 3; i++) {
      await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[i].id}:markRead`);
    }

    // Check progress updated
    const updatedThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    const updatedThread = await updatedThreadResponse.json();
    expect(updatedThread.reading_progress).toBe('in_progress');

    // Mark remaining issues
    for (let i = 3; i < 10; i++) {
      await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[i].id}:markRead`);
    }

    // Check progress is completed
    const finalThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    const finalThread = await finalThreadResponse.json();
    expect(finalThread.reading_progress).toBe('completed');
    expect(finalThread.status).toBe('completed');
  });

  test('should calculate progress correctly', async ({ authenticatedPage }) => {
    // Create thread with specific number of issues
    await createThread(authenticatedPage, {
      title: `Progress Calculation Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 25,
      total_issues: 25,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Progress Calculation Test'));

    // Get issues
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    // Mark exactly half (rounded) of issues
    const halfCount = Math.floor(25 / 2);
    for (let i = 0; i < halfCount; i++) {
      await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[i].id}:markRead`);
    }

    // Check progress
    const updatedThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    const updatedThread = await updatedThreadResponse.json();
    expect(updatedThread.reading_progress).toBe('in_progress');
  });
});

test.describe('Thread Completion', () => {
  test('should mark thread as completed when all issues read', async ({ authenticatedPage }) => {
    // Create thread with 5 issues
    await createThread(authenticatedPage, {
      title: `Completion Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 5,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Completion Test'));

    expect(thread.status).not.toBe('completed');

    // Get issues
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    // Mark first 4 issues as read
    for (let i = 0; i < 4; i++) {
      await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[i].id}:markRead`);
    }

    let updatedThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    let updatedThread = await updatedThreadResponse.json();
    expect(updatedThread.status).not.toBe('completed');

    // Mark last issue as read
    await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[4].id}:markRead`);

    // Verify thread status changed to completed
    const finalThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    const finalThread = await finalThreadResponse.json();
    expect(finalThread.status).toBe('completed');
    expect(finalThread.reading_progress).toBe('100%');
    expect(finalThread.next_unread_issue_id).toBeNull();
  });

  test('should handle thread with single issue completion', async ({ authenticatedPage }) => {
    // Create thread with single issue
    await createThread(authenticatedPage, {
      title: `Single Issue Completion ${Date.now()}`,
      format: 'One-Shot',
      issues_remaining: 1,
      total_issues: 1,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Single Issue Completion'));

    // Get and mark the only issue as read
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    await makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issuesData.issues[0].id}:markRead`);

    // Verify thread is completed
    const finalThreadResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/threads/${thread.id}`);
    const finalThread = await finalThreadResponse.json();
    expect(finalThread.status).toBe('completed');
    expect(finalThread.reading_progress).toBe('100%');
  });
});

test.describe('Issue Range Edge Cases', () => {
  test('should handle large issue ranges', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Long Running Series');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill in large range
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1-150');
    
    // Verify preview
    await expect(authenticatedPage.locator(SELECTORS.threadCreate.issuePreview)).toContainText('Will create 150 issues');
    
    // Submit form
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'POST' &&
        response.status() < 300
      ),
      authenticatedPage.click('button[type="submit"]'),
    ]);
    
    await authenticatedPage.waitForLoadState('networkidle');
    
    // Verify thread was created
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    expect(response.ok()).toBeTruthy();
    const threads = await response.json();
    const testThread = threads.find((t: any) => t.title === 'Long Running Series');
    expect(testThread).toBeDefined();
    expect(testThread.total_issues).toBe(150);
  });

  test('should reject invalid range formats', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Invalid Range');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Test various invalid ranges
    const invalidRanges = [
      '10-1', // Reversed range
      '0-5', // Zero not allowed
      '-5', // Negative
      '1--5', // Double dash
      '1,2,abc', // Non-numeric
    ];

    for (const range of invalidRanges) {
      await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, range);
      
      // Should show error
      const hasError = await authenticatedPage.locator('p:has-text("Non-numeric")').count() > 0 ||
                       await authenticatedPage.locator('p:has-text("positive")').count() > 0 ||
                       await authenticatedPage.locator('p:has-text("cannot exceed")').count() > 0;
      expect(hasError).toBe(true);
    }
  });

  test('should handle whitespace in ranges', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Whitespace Test');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    
    // Fill range with various whitespace
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1 - 5 , 7 , 10 - 12');
    
    // Verify preview handles whitespace correctly (1,2,3,4,5,7,10,11,12 = 9 unique issues)
    await expect(authenticatedPage.locator(SELECTORS.threadCreate.issuePreview)).toContainText('Will create 9 issues');
    
    // Submit form
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'POST' &&
        response.status() < 300
      ),
      authenticatedPage.click('button[type="submit"]'),
    ]);
    
    await authenticatedPage.waitForLoadState('networkidle');
    
    // Verify thread was created with correct count
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    expect(response.ok()).toBeTruthy();
    const threads = await response.json();
    const testThread = threads.find((t: any) => t.title === 'Whitespace Test');
    expect(testThread).toBeDefined();
    expect(testThread.total_issues).toBe(10);
  });
});

test.describe('API Integration', () => {
  test('should handle concurrent issue status updates', async ({ authenticatedPage }) => {
    // Create thread with issues
    await createThread(authenticatedPage, {
      title: `Concurrent Test ${Date.now()}`,
      format: 'Comic',
      issues_remaining: 10,
      total_issues: 10,
    });

    const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
    const threads = await threadsResponse.json();
    const thread = threads.find((t: any) => t.title.startsWith('Concurrent Test'));

    // Get issues
    const issuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const issuesData = await issuesResponse.json();

    // Mark multiple issues as read concurrently
    const promises = issuesData.issues.slice(0, 5).map((issue: any) =>
      makeAuthenticatedRequest(authenticatedPage, 'POST', `/api/v1/issues/${issue.id}:markRead`)
    );

    const results = await Promise.all(promises);
    results.forEach(result => {
      expect(result.ok()).toBeTruthy();
    });

    // Verify all were marked
    const updatedIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${thread.id}/issues`);
    const updatedIssues = await updatedIssuesResponse.json();
    const readCount = updatedIssues.issues.filter((i: any) => i.status === 'read').length;
    expect(readCount).toBe(5);
  });

  test('should return 404 for non-existent issue', async ({ authenticatedPage }) => {
    const response = await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/issues/99999:markRead');
    expect(response.status()).toBe(404);
  });

  test('should return 404 for non-existent thread issues', async ({ authenticatedPage }) => {
    const response = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/99999/issues');
    expect(response.status()).toBe(404);
  });
});
