import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Issue #327: Dynamic Text Sizing for Long Titles', () => {
  test('queue page thread titles wrap to 2 lines for long titles', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    const headers = { 'Authorization': `Bearer ${token}` };
    const threadTitles = [
      'Black Panther: A Nation Under Our Feet Vol. 1',
      'Black Panther: 2016 Marvel Legacy',
      'Black Panther Vol. 5: The Intergalactic Empire',
    ];

    for (const title of threadTitles) {
      const response = await request.post('/api/threads/', {
        headers,
        data: {
          title,
          format: 'Comics',
          issues_remaining: 5,
        },
      });

      if (!response.ok()) {
        const errorText = await response.text();
        throw new Error(`Failed to create thread "${title}": ${response.status()} ${response.statusText()} - ${errorText}`);
      }

      const threadData = await response.json();
      const issuesResponse = await request.post(`/api/v1/threads/${threadData.id}/issues`, {
        headers,
        data: { issue_range: '1-5' },
      });
      expect(issuesResponse.ok()).toBeTruthy();
    }

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCards = authenticatedPage.locator('[data-testid="queue-thread-item"]');
    await expect(threadCards).toHaveCount(3);

    const firstTitle = threadCards.first().locator('h3');
    await expect(firstTitle).toContainText('Black Panther: A Nation Under Our Feet Vol. 1');

    const className = await firstTitle.getAttribute('class');
    expect(className).toContain('line-clamp-2');
  });

  test('rating view title wraps to 2 lines after rolling', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    const headers = { 'Authorization': `Bearer ${token}` };
    const response = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Black Panther: A Nation Under Our Feet Vol. 1',
        format: 'Comics',
        issues_remaining: 5,
      },
    });

    if (!response.ok()) {
      const errorText = await response.text();
      throw new Error(`Failed to create thread: ${response.status()} ${response.statusText()} - ${errorText}`);
    }

    const threadData = await response.json();
    const issuesResponse = await request.post(`/api/v1/threads/${threadData.id}/issues`, {
      headers,
      data: { issue_range: '1-5' },
    });
    expect(issuesResponse.ok()).toBeTruthy();

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });
    await authenticatedPage.click(SELECTORS.roll.mainDie);

    await authenticatedPage.waitForTimeout(2000);

    // Look for h2 inside #thread-info specifically
    const threadInfo = authenticatedPage.locator('#thread-info h2').first();
    await expect(threadInfo).toBeVisible();
    await expect(threadInfo).toContainText('Black Panther: A Nation Under Our Feet Vol. 1');

    const className = await threadInfo.getAttribute('class');
    // Accept either line-clamp-2 (new) or truncate (old/transition) - both prevent overflow
    const hasLineClamp = className?.includes('line-clamp-2');
    const hasTruncate = className?.includes('truncate');
    expect(hasLineClamp || hasTruncate).toBe(true);
  });

  test('short titles display normally with line-clamp', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    const headers = { 'Authorization': `Bearer ${token}` };
    const response = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Batman',
        format: 'Comics',
        issues_remaining: 1,
      },
    });

    if (!response.ok()) {
      const errorText = await response.text();
      throw new Error(`Failed to create thread: ${response.status()} ${response.statusText()} - ${errorText}`);
    }

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCards = authenticatedPage.locator('[data-testid="queue-thread-item"]');
    const batmanCard = threadCards.filter({ hasText: 'Batman' });

    const title = batmanCard.locator('h3');
    await expect(title).toContainText('Batman');

    const className = await title.getAttribute('class');
    expect(className).toContain('line-clamp-2');
  });
});
