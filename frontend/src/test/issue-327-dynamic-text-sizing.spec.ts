import { test, expect } from './fixtures';

test.describe('Issue #327: Dynamic Text Sizing for Long Titles', () => {
  test('queue page thread titles wrap to 2 lines for long titles', async ({ authenticatedPage }) => {
    const threadTitles = [
      'Black Panther: A Nation Under Our Feet Vol. 1',
      'Black Panther: 2016 Marvel Legacy',
      'Black Panther Vol. 5: The Intergalactic Empire',
    ];

    for (const title of threadTitles) {
      const response = await authenticatedPage.request.post('/api/threads/', {
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
      const issuesResponse = await authenticatedPage.request.post(`/api/v1/threads/${threadData.id}/issues`, {
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

  test('rating view title wraps to 2 lines after rolling', async ({ authenticatedPage }) => {
    const response = await authenticatedPage.request.post('/api/threads/', {
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
    const issuesResponse = await authenticatedPage.request.post(`/api/v1/threads/${threadData.id}/issues`, {
      data: { issue_range: '1-5' },
    });
    expect(issuesResponse.ok()).toBeTruthy();

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const rollButton = authenticatedPage.getByTestId('roll-button');
    await expect(rollButton).toBeVisible();
    await rollButton.click();

    await authenticatedPage.waitForTimeout(2000);

    const threadInfo = authenticatedPage.locator('#thread-info h2');
    await expect(threadInfo).toBeVisible();
    await expect(threadInfo).toContainText('Black Panther: A Nation Under Our Feet Vol. 1');

    const className = await threadInfo.getAttribute('class');
    expect(className).toContain('line-clamp-2');
  });

  test('short titles display normally with line-clamp', async ({ authenticatedPage }) => {
    const response = await authenticatedPage.request.post('/api/threads/', {
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
