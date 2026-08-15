import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Reading Route Explanation', () => {
  test('opens from route summary, inspects content, and returns to rating with state preserved', async ({ authenticatedWithThreadsPage, request }) => {
    const page = authenticatedWithThreadsPage;
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    // Create a thread with issues and reading order
    const threadResponse = await request.post('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'Route Test Thread',
        format: 'Comics',
        issues_remaining: 5,
        total_issues: 10,
      },
    });
    const thread = await threadResponse.json();

    await request.post(`/api/v1/threads/${thread.id}/issues`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: { issue_range: '1-10' },
    });

    // Create a reading order and add the thread to it
    const orderResponse = await request.post('/api/reading-orders/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: 'Test Reading Order',
        thread_ids: [thread.id],
      },
    });
    const readingOrder = await orderResponse.json();

    // Add thread items to the reading order
    const issuesResponse = await request.get(`/api/v1/threads/${thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const issuesData = await issuesResponse.json();
    const issueIds = issuesData.issues.map((i: { id: number }) => i.id);

    await request.post(`/api/reading-orders/${readingOrder.id}/items`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: { issue_ids: issueIds },
    });

    // Navigate to roll page and roll to get into rating view
    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie, { state: 'visible', timeout: 10000 });
    await page.click(SELECTORS.roll.mainDie);
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

    // Find and click the "Explain route" button for our reading order
    const explainButton = page.getByRole('button', { name: new RegExp(`Explain route.*${readingOrder.name}`) });
    await expect(explainButton).toBeVisible({ timeout: 5000 });
    await explainButton.click();

    // Verify the explanation modal opens
    const modal = page.getByRole('dialog', { name: new RegExp(`Route Test Thread.*#\\d+`) });
    await expect(modal).toBeVisible();

    // Verify key sections are present
    await expect(page.getByText('Why this issue is next')).toBeVisible();
    await expect(page.getByText('Continuity eligibility')).toBeVisible();
    await expect(page.getByText('Named reading routes')).toBeVisible();
    await expect(page.getByText('Test Reading Order')).toBeVisible();
    await expect(page.getByText('Membership is informational')).toBeVisible();

    // Close the modal with Escape
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();

    // Verify rating view state is preserved
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
    const ratingValue = await page.locator('#rating-value').textContent();
    expect(ratingValue).toBe('3.0'); // Default rating
  });

  test('shows blocked state with direct blockers and readable prerequisites', async ({ authenticatedWithThreadsPage, request }) => {
    const page = authenticatedWithThreadsPage;
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    // Create blocker thread
    const blockerResponse = await request.post('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'Blocker Thread',
        format: 'Comics',
        issues_remaining: 3,
        total_issues: 5,
      },
    });
    const blockerThread = await blockerResponse.json();
    await request.post(`/api/v1/threads/${blockerThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-5' },
    });

    // Create blocked thread
    const blockedResponse = await request.post('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'Blocked Thread',
        format: 'Comics',
        issues_remaining: 5,
        total_issues: 10,
      },
    });
    const blockedThread = await blockedResponse.json();
    await request.post(`/api/v1/threads/${blockedThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-10' },
    });

    // Get issue IDs
    const blockerIssuesResponse = await request.get(`/api/v1/threads/${blockerThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blockerIssuesData = await blockerIssuesResponse.json();
    const blockerLastIssue = blockerIssuesData.issues[blockerIssuesData.issues.length - 1];

    const blockedIssuesResponse = await request.get(`/api/v1/threads/${blockedThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blockedIssuesData = await blockedIssuesResponse.json();
    const blockedFirstIssue = blockedIssuesData.issues[0];

    // Create dependency: blocker issue must be read before blocked issue
    await request.post('/api/v1/dependencies/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        source_type: 'issue',
        source_id: blockerLastIssue.id,
        target_type: 'issue',
        target_id: blockedFirstIssue.id,
      },
    });

    // Create reading order for blocked thread
    const orderResponse = await request.post('/api/reading-orders/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: 'Blocked Order',
        thread_ids: [blockedThread.id],
      },
    });
    const readingOrder = await orderResponse.json();

    const blockedIssueIds = blockedIssuesData.issues.map((i: { id: number }) => i.id);
    await request.post(`/api/reading-orders/${readingOrder.id}/items`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: { issue_ids: blockedIssueIds },
    });

    // Set blocked thread as pending and open rating view
    await request.post(`/api/threads/${blockedThread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 10000 });

    // Click Explain route
    const explainButton = page.getByRole('button', { name: new RegExp(`Explain route.*${readingOrder.name}`) });
    await expect(explainButton).toBeVisible({ timeout: 5000 });
    await explainButton.click();

    // Verify modal shows blocked state
    const modal = page.getByRole('dialog', { name: new RegExp(`Blocked Thread.*#\\d+`) });
    await expect(modal).toBeVisible();

    // Check for blocked eligibility
    await expect(page.getByText('Blocked by continuity')).toBeVisible();

    // Check for direct blockers section
    await expect(page.getByText('Unresolved direct blockers')).toBeVisible();
    await expect(page.getByText('Blocker Thread')).toBeVisible();

    // Check for readable prerequisites section
    await expect(page.getByText('Currently readable prerequisites')).toBeVisible();

    // Close modal
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();

    // Verify rating view preserved
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
  });

  test('shows convergent prerequisite lanes', async ({ authenticatedWithThreadsPage, request }) => {
    const page = authenticatedWithThreadsPage;
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    // Create two prerequisite threads
    const prereq1Response = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Prerequisite A', format: 'Comics', issues_remaining: 2, total_issues: 5 },
    });
    const prereq1Thread = await prereq1Response.json();
    await request.post(`/api/v1/threads/${prereq1Thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-5' },
    });

    const prereq2Response = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Prerequisite B', format: 'Comics', issues_remaining: 2, total_issues: 5 },
    });
    const prereq2Thread = await prereq2Response.json();
    await request.post(`/api/v1/threads/${prereq2Thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-5' },
    });

    // Create target thread
    const targetResponse = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Convergence Target', format: 'Comics', issues_remaining: 5, total_issues: 10 },
    });
    const targetThread = await targetResponse.json();
    await request.post(`/api/v1/threads/${targetThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-10' },
    });

    // Get issue IDs
    const prereq1IssuesResponse = await request.get(`/api/v1/threads/${prereq1Thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const prereq1IssuesData = await prereq1IssuesResponse.json();
    const prereq1LastIssue = prereq1IssuesData.issues[prereq1IssuesData.issues.length - 1];

    const prereq2IssuesResponse = await request.get(`/api/v1/threads/${prereq2Thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const prereq2IssuesData = await prereq2IssuesResponse.json();
    const prereq2LastIssue = prereq2IssuesData.issues[prereq2IssuesData.issues.length - 1];

    const targetIssuesResponse = await request.get(`/api/v1/threads/${targetThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const targetIssuesData = await targetIssuesResponse.json();
    const targetFirstIssue = targetIssuesData.issues[0];

    // Create convergent dependencies: both prerequisites must be read before target
    await request.post('/api/v1/dependencies/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { source_type: 'issue', source_id: prereq1LastIssue.id, target_type: 'issue', target_id: targetFirstIssue.id },
    });
    await request.post('/api/v1/dependencies/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { source_type: 'issue', source_id: prereq2LastIssue.id, target_type: 'issue', target_id: targetFirstIssue.id },
    });

    // Create reading order
    const orderResponse = await request.post('/api/reading-orders/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { name: 'Convergence Order', thread_ids: [targetThread.id] },
    });
    const readingOrder = await orderResponse.json();

    const targetIssueIds = targetIssuesData.issues.map((i: { id: number }) => i.id);
    await request.post(`/api/reading-orders/${readingOrder.id}/items`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_ids: targetIssueIds },
    });

    // Set target thread as pending
    await request.post(`/api/threads/${targetThread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 10000 });

    // Click Explain route
    const explainButton = page.getByRole('button', { name: new RegExp(`Explain route.*${readingOrder.name}`) });
    await expect(explainButton).toBeVisible({ timeout: 5000 });
    await explainButton.click();

    // Verify modal shows convergent lanes
    const modal = page.getByRole('dialog', { name: new RegExp(`Convergence Target.*#\\d+`) });
    await expect(modal).toBeVisible();

    // Check for bounded prerequisite chain section
    await expect(page.getByText('Bounded prerequisite chain')).toBeVisible();
    await expect(page.getByText('Parallel lane 1')).toBeVisible();
    await expect(page.getByText('Parallel lane 2')).toBeVisible();
    await expect(page.getByText('Prerequisite A')).toBeVisible();
    await expect(page.getByText('Prerequisite B')).toBeVisible();

    // Close modal
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();

    // Verify rating view preserved
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
  });

  test('shows verified downstream unlocks', async ({ authenticatedWithThreadsPage, request }) => {
    const page = authenticatedWithThreadsPage;
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    // Create current thread
    const currentResponse = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Current Thread', format: 'Comics', issues_remaining: 5, total_issues: 10 },
    });
    const currentThread = await currentResponse.json();
    await request.post(`/api/v1/threads/${currentThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-10' },
    });

    // Create downstream thread
    const downstreamResponse = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Downstream Thread', format: 'Comics', issues_remaining: 3, total_issues: 5 },
    });
    const downstreamThread = await downstreamResponse.json();
    await request.post(`/api/v1/threads/${downstreamThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-5' },
    });

    // Get issue IDs
    const currentIssuesResponse = await request.get(`/api/v1/threads/${currentThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const currentIssuesData = await currentIssuesResponse.json();
    const currentLastIssue = currentIssuesData.issues[currentIssuesData.issues.length - 1];

    const downstreamIssuesResponse = await request.get(`/api/v1/threads/${downstreamThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const downstreamIssuesData = await downstreamIssuesResponse.json();
    const downstreamFirstIssue = downstreamIssuesData.issues[0];

    // Create dependency: current must be read before downstream
    await request.post('/api/v1/dependencies/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { source_type: 'issue', source_id: currentLastIssue.id, target_type: 'issue', target_id: downstreamFirstIssue.id },
    });

    // Create reading order
    const orderResponse = await request.post('/api/reading-orders/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { name: 'Unlock Order', thread_ids: [currentThread.id] },
    });
    const readingOrder = await orderResponse.json();

    const currentIssueIds = currentIssuesData.issues.map((i: { id: number }) => i.id);
    await request.post(`/api/reading-orders/${readingOrder.id}/items`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_ids: currentIssueIds },
    });

    // Set current thread as pending
    await request.post(`/api/threads/${currentThread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 10000 });

    // Click Explain route
    const explainButton = page.getByRole('button', { name: new RegExp(`Explain route.*${readingOrder.name}`) });
    await expect(explainButton).toBeVisible({ timeout: 5000 });
    await explainButton.click();

    // Verify modal shows downstream unlocks
    const modal = page.getByRole('dialog', { name: new RegExp(`Current Thread.*#\\d+`) });
    await expect(modal).toBeVisible();

    await expect(page.getByText('Verified downstream unlocks')).toBeVisible();
    await expect(page.getByText('Downstream Thread')).toBeVisible();

    // Close modal
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();

    // Verify rating view preserved
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
  });

  test('handles cyclic continuity state with bounded diagnostic', async ({ authenticatedWithThreadsPage, request }) => {
    const page = authenticatedWithThreadsPage;
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    // Create a thread that will have cyclic state (this tests the diagnostic display)
    const threadResponse = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Cycle Test Thread', format: 'Comics', issues_remaining: 5, total_issues: 10 },
    });
    const thread = await threadResponse.json();
    await request.post(`/api/v1/threads/${thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-10' },
    });

    // Create reading order
    const orderResponse = await request.post('/api/reading-orders/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { name: 'Cycle Order', thread_ids: [thread.id] },
    });
    const readingOrder = await orderResponse.json();

    const issueIds = (await request.get(`/api/v1/threads/${thread.id}/issues`, { headers: { Authorization: `Bearer ${token}` } })).then(r => r.json()).then(d => d.issues.map((i: { id: number }) => i.id));
    const issueIdsResolved = await issueIds;
    await request.post(`/api/reading-orders/${readingOrder.id}/items`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_ids: issueIdsResolved },
    });

    // Set thread as pending
    await request.post(`/api/threads/${thread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 10000 });

    // Click Explain route
    const explainButton = page.getByRole('button', { name: new RegExp(`Explain route.*${readingOrder.name}`) });
    await expect(explainButton).toBeVisible({ timeout: 5000 });
    await explainButton.click();

    // Verify modal opens (even if no cyclic diagnostic is present, it should not crash)
    const modal = page.getByRole('dialog', { name: new RegExp(`Cycle Test Thread.*#\\d+`) });
    await expect(modal).toBeVisible();

    // Check for continuity eligibility section
    await expect(page.getByText('Continuity eligibility')).toBeVisible();

    // Close modal
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();

    // Verify rating view preserved
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
  });

  test('preserves scroll position and focus when closing on mobile viewport', async ({ authenticatedWithThreadsPage, request }) => {
    const page = authenticatedWithThreadsPage;
    await page.setViewportSize({ width: 375, height: 667 });

    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    const threadResponse = await request.post('/api/threads/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { title: 'Mobile Route Thread', format: 'Comics', issues_remaining: 5, total_issues: 10 },
    });
    const thread = await threadResponse.json();
    await request.post(`/api/v1/threads/${thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_range: '1-10' },
    });

    const orderResponse = await request.post('/api/reading-orders/', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { name: 'Mobile Order', thread_ids: [thread.id] },
    });
    const readingOrder = await orderResponse.json();

    const issueIds = (await request.get(`/api/v1/threads/${thread.id}/issues`, { headers: { Authorization: `Bearer ${token}` } })).then(r => r.json()).then(d => d.issues.map((i: { id: number }) => i.id));
    const issueIdsResolved = await issueIds;
    await request.post(`/api/reading-orders/${readingOrder.id}/items`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { issue_ids: issueIdsResolved },
    });

    await request.post(`/api/threads/${thread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 10000 });

    // Scroll the rating view slightly
    await page.evaluate(() => window.scrollTo(0, 100));

    // Click Explain route
    const explainButton = page.getByRole('button', { name: new RegExp(`Explain route.*${readingOrder.name}`) });
    await expect(explainButton).toBeVisible({ timeout: 5000 });
    await explainButton.click();

    // Verify modal opens
    const modal = page.getByRole('dialog', { name: new RegExp(`Mobile Route Thread.*#\\d+`) });
    await expect(modal).toBeVisible();

    // Close with backdrop click
    await page.locator('.fixed.inset-0.bg-\\[\\#110e0a\\]/60').first().click();

    await expect(modal).toBeHidden();

    // Verify rating view preserved and focus restored
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    // The explain button should have focus restored
    await expect(explainButton).toBeFocused();
  });
});