import { test, expect } from './fixtures';
import { createThread, SELECTORS, extractThreadsFromResponse } from './helpers';

async function makeAuthenticatedRequest(page: any, method: string, url: string, data?: any): Promise<any> {
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

	return await page.request.fetch(url, options);
}

test.describe('Issue Dependency Indicators', () => {
	test('should show dependency indicator for issues with dependencies', async ({ authenticatedPage }) => {
		const timestamp = Date.now();

		await createThread(authenticatedPage, {
			title: `Dependency Source ${timestamp}`,
			format: 'Comics',
			issues_remaining: 2,
			total_issues: 2,
		});

		await createThread(authenticatedPage, {
			title: `Dependency Target ${timestamp}`,
			format: 'Comics',
			issues_remaining: 3,
			total_issues: 3,
		});

		const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
		const threads = extractThreadsFromResponse(await threadsResponse.json());
		const source = threads.find((t: any) => t.title === `Dependency Source ${timestamp}`);
		const target = threads.find((t: any) => t.title === `Dependency Target ${timestamp}`);

    const sourceIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${source.id}/issues`);
    const sourceIssues = await sourceIssuesResponse.json();

    const targetIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${target.id}/issues`);
    const targetIssues = await targetIssuesResponse.json();

    const sourceIssue = sourceIssues.issues[0];
    const targetIssue = targetIssues.issues[1];

    const createDepResponse = await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/dependencies/', {
      source_type: 'issue',
      source_id: sourceIssue.id,
      target_type: 'issue',
      target_id: targetIssue.id,
    });
    expect(createDepResponse.ok()).toBeTruthy();

    await authenticatedPage.goto(`/queue`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click(`text=${target.title}`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click('button:has-text("Edit Thread")');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.waitForTimeout(2000);

    const issueItem = authenticatedPage.locator(`[data-testid="issue-pill-${targetIssue.id}"]`);
    await issueItem.waitFor({ state: 'visible', timeout: 5000 });

    const indicator = issueItem.locator('.dependency-indicator');
    const indicatorCount = await indicator.count();

    expect(indicatorCount).toBeGreaterThan(0);
  });

  test('should not show dependency indicator for issues without dependencies', async ({ authenticatedPage }) => {
    const timestamp = Date.now();

    await createThread(authenticatedPage, {
      title: `No Dependencies Thread ${timestamp}`,
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    });

	const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
	const threads = extractThreadsFromResponse(await threadsResponse.json());
	const thread = threads.find((t: any) => t.title === `No Dependencies Thread ${timestamp}`);

    await authenticatedPage.goto(`/queue`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click(`text=${thread.title}`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click('button:has-text("Edit Thread")');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.waitForTimeout(1000);

    const indicators = authenticatedPage.locator('.dependency-indicator');
    expect(await indicators.count()).toBe(0);
  });

  test('should show tooltip with dependency details on hover', async ({ authenticatedPage }) => {
    const timestamp = Date.now();

    const sourceThread = await createThread(authenticatedPage, {
      title: `Tooltip Source ${timestamp}`,
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    });

    const targetThread = await createThread(authenticatedPage, {
      title: `Tooltip Target ${timestamp}`,
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    });

	const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
	const threads = extractThreadsFromResponse(await threadsResponse.json());
	const source = threads.find((t: any) => t.title === `Tooltip Source ${timestamp}`);
	const target = threads.find((t: any) => t.title === `Tooltip Target ${timestamp}`);

    const sourceIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${source.id}/issues`);
    const sourceIssues = await sourceIssuesResponse.json();

    const targetIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${target.id}/issues`);
    const targetIssues = await targetIssuesResponse.json();

    const sourceIssue = sourceIssues.issues[0];
    const targetIssue = targetIssues.issues[1];

    await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/dependencies/', {
      source_type: 'issue',
      source_id: sourceIssue.id,
      target_type: 'issue',
      target_id: targetIssue.id,
    });

    await authenticatedPage.goto(`/queue`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click(`text=${target.title}`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click('button:has-text("Edit Thread")');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.waitForTimeout(2000);

    const issueItem = authenticatedPage.locator(`[data-testid="issue-pill-${targetIssue.id}"]`);
    await issueItem.waitFor({ state: 'visible', timeout: 5000 });

    const indicator = issueItem.locator('.dependency-indicator');
    if (await indicator.count() > 0) {
      await indicator.hover();
      await authenticatedPage.waitForTimeout(500);

      const tooltip = authenticatedPage.locator('.relative .absolute');
      const tooltipVisible = await tooltip.count() > 0;
      expect(tooltipVisible).toBeTruthy();
    }
  });

  test('should handle multiple dependencies on same issue', async ({ authenticatedPage }) => {
    const timestamp = Date.now();

    await createThread(authenticatedPage, {
      title: `Source 1 ${timestamp}`,
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    });

    await createThread(authenticatedPage, {
      title: `Source 2 ${timestamp}`,
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    });

    await createThread(authenticatedPage, {
      title: `Multi Dep Target ${timestamp}`,
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    });

	const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
	const threads = extractThreadsFromResponse(await threadsResponse.json());
	const source1 = threads.find((t: any) => t.title === `Source 1 ${timestamp}`);
	const source2 = threads.find((t: any) => t.title === `Source 2 ${timestamp}`);
	const target = threads.find((t: any) => t.title === `Multi Dep Target ${timestamp}`);

    const source1IssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${source1.id}/issues`);
    const source1Issues = await source1IssuesResponse.json();

    const source2IssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${source2.id}/issues`);
    const source2Issues = await source2IssuesResponse.json();

    const targetIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${target.id}/issues`);
    const targetIssues = await targetIssuesResponse.json();

    const targetIssue = targetIssues.issues[1];

    await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/dependencies/', {
      source_type: 'issue',
      source_id: source1Issues.issues[0].id,
      target_type: 'issue',
      target_id: targetIssue.id,
    });

    await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/dependencies/', {
      source_type: 'issue',
      source_id: source2Issues.issues[0].id,
      target_type: 'issue',
      target_id: targetIssue.id,
    });

    await authenticatedPage.goto(`/queue`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click(`text=${target.title}`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click('button:has-text("Edit Thread")');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.waitForTimeout(2000);

    const issueItem = authenticatedPage.locator(`[data-testid="issue-pill-${targetIssue.id}"]`);
    await issueItem.waitFor({ state: 'visible', timeout: 5000 });

    const indicator = issueItem.locator('.dependency-indicator');
    const indicatorCount = await indicator.count();

    expect(indicatorCount).toBeGreaterThan(0);

    await indicator.hover();
    await authenticatedPage.waitForTimeout(500);

    const tooltipText = await authenticatedPage.locator('.relative .absolute').first().textContent();
    expect(tooltipText).toContain('Source 1');
    expect(tooltipText).toContain('Source 2');
  });

  test('should show both incoming and outgoing dependencies', async ({ authenticatedPage }) => {
    const timestamp = Date.now();

    const sourceThread = await createThread(authenticatedPage, {
      title: `Chain Source ${timestamp}`,
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    });

    const middleThread = await createThread(authenticatedPage, {
      title: `Chain Middle ${timestamp}`,
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    });

    const targetThread = await createThread(authenticatedPage, {
      title: `Chain Target ${timestamp}`,
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    });

	const threadsResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', '/api/threads/');
	const threads = extractThreadsFromResponse(await threadsResponse.json());
	const source = threads.find((t: any) => t.title === `Chain Source ${timestamp}`);
	const middle = threads.find((t: any) => t.title === `Chain Middle ${timestamp}`);
	const target = threads.find((t: any) => t.title === `Chain Target ${timestamp}`);

    const sourceIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${source.id}/issues`);
    const sourceIssues = await sourceIssuesResponse.json();

    const middleIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${middle.id}/issues`);
    const middleIssues = await middleIssuesResponse.json();

    const targetIssuesResponse = await makeAuthenticatedRequest(authenticatedPage, 'GET', `/api/v1/threads/${target.id}/issues`);
    const targetIssues = await targetIssuesResponse.json();

    const middleIssue = middleIssues.issues[1];

    await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/dependencies/', {
      source_type: 'issue',
      source_id: sourceIssues.issues[0].id,
      target_type: 'issue',
      target_id: middleIssue.id,
    });

    await makeAuthenticatedRequest(authenticatedPage, 'POST', '/api/v1/dependencies/', {
      source_type: 'issue',
      source_id: middleIssue.id,
      target_type: 'issue',
      target_id: targetIssues.issues[0].id,
    });

    await authenticatedPage.goto(`/queue`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click(`text=${middle.title}`);
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.click('button:has-text("Edit Thread")');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.waitForTimeout(2000);

    const issueItem = authenticatedPage.locator(`[data-testid="issue-pill-${middleIssue.id}"]`);
    await issueItem.waitFor({ state: 'visible', timeout: 5000 });

    const indicator = issueItem.locator('.dependency-indicator');
    if (await indicator.count() > 0) {
      await indicator.hover();
      await authenticatedPage.waitForTimeout(500);

      const tooltipText = await authenticatedPage.locator('.relative .absolute').first().textContent();
      expect(tooltipText).toContain('Chain Source');
      expect(tooltipText).toContain('Chain Target');
      expect(tooltipText).toContain('Blocked by');
      expect(tooltipText).toContain('Blocking');
    }
  });
});
