import { test, expect } from './fixtures';

test.describe('Retired Analytics feature', () => {
  test('retired analytics route redirects to the root page', async ({ authenticatedPage }) => {
    const baseUrl = process.env.BASE_URL || 'http://localhost:9000';
    await authenticatedPage.goto('/analytics');

    await expect(authenticatedPage).toHaveURL(`${baseUrl}/`);
  });

  test('does not expose analytics in primary navigation', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const analyticsLink = authenticatedPage.locator('a[href*="analytics"]');
    expect(await analyticsLink.count()).toBe(0);
  });
});
