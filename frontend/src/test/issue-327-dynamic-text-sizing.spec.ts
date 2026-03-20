import { test, expect } from './fixtures';

test.describe('Issue #327: Dynamic Text Sizing for Long Titles', () => {
  test('queue page thread titles wrap to 2 lines for long titles', async ({ authenticatedPage, request }) => {
    // Create threads with long similar titles via API
    const accessToken = await authenticatedPage.evaluate(() => {
      return (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });

    const headers = {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    };

    // Create three threads with long similar Black Panther titles
    await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Black Panther: A Nation Under Our Feet Vol. 1',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 5,
      },
    });

    await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Black Panther: 2016 Marvel Legacy',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 3,
      },
    });

    await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Black Panther Vol. 5: The Intergalactic Empire',
        format: 'Comic',
        issues_remaining: 4,
        total_issues: 4,
      },
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCards = authenticatedPage.locator('[data-testid="queue-thread-item"]');
    await expect(threadCards).toHaveCount(3);

    // Check that first title is displayed with line-clamp-2
    const firstTitle = threadCards.first().locator('h3');
    await expect(firstTitle).toContainText('Black Panther: A Nation Under Our Feet Vol. 1');
    
    // Verify the element has line-clamp-2 class
    const className = await firstTitle.getAttribute('class');
    expect(className).toContain('line-clamp-2');
  });

  test('rating view title wraps to 2 lines after rolling', async ({ authenticatedPage, request }) => {
    const accessToken = await authenticatedPage.evaluate(() => {
      return (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });

    const headers = {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    };

    // Create thread with long title
    const threadResponse = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Black Panther: A Nation Under Our Feet Vol. 1',
        format: 'Comic',
        issues_remaining: 5,
        total_issues: 5,
      },
    });
    
    expect(threadResponse.ok()).toBeTruthy();

    // Create issues
    const threadData = await threadResponse.json();
    await request.post(`/api/v1/threads/${threadData.id}/issues`, {
      headers,
      data: { issue_range: '1-5' },
    });

    // Navigate to roll page
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Roll the die
    const rollButton = authenticatedPage.getByTestId('roll-button');
    await expect(rollButton).toBeVisible();
    await rollButton.click();

    // Wait for roll to complete
    await authenticatedPage.waitForTimeout(2000);

    // The rating view should show the thread title
    const threadInfo = authenticatedPage.locator('#thread-info h2');
    await expect(threadInfo).toBeVisible();
    await expect(threadInfo).toContainText('Black Panther: A Nation Under Our Feet Vol. 1');

    // Verify the element has line-clamp-2 class
    const className = await threadInfo.getAttribute('class');
    expect(className).toContain('line-clamp-2');
  });

  test('short titles display normally with line-clamp', async ({ authenticatedPage, request }) => {
    const accessToken = await authenticatedPage.evaluate(() => {
      return (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });

    const headers = {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    };

    // Create thread with short title
    await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Batman',
        format: 'Comic',
        issues_remaining: 1,
        total_issues: 1,
      },
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCards = authenticatedPage.locator('[data-testid="queue-thread-item"]');
    const batmanCard = threadCards.filter({ hasText: 'Batman' });
    
    const title = batmanCard.locator('h3');
    await expect(title).toContainText('Batman');
    
    // Should still have line-clamp-2 class
    const className = await title.getAttribute('class');
    expect(className).toContain('line-clamp-2');
  });
});
