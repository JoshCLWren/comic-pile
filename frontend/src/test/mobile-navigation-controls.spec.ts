import { expect, test } from './fixtures';

test.describe('Mobile navigation and Roll controls (#1091)', () => {
  test('labels every destination and keeps actions above the fixed navigation', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;
    await page.setViewportSize({ width: 430, height: 932 });
    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();

    const navigation = page.getByRole('navigation', { name: 'Main navigation' });
    for (const label of ['Roll', 'Queue', 'History', 'Crossovers', 'More']) {
      await expect(navigation.getByText(label, { exact: true })).toBeVisible();
    }

    const activeItems = navigation.locator('.nav-item.active');
    await expect(activeItems).toHaveCount(1);
    await expect(page.getByRole('button', { name: /current die d\d+, automatic mode/i })).toBeVisible();

    await navigation.getByRole('button', { name: 'More pages' }).click();
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(page.getByText('Submit Feedback', { exact: true })).toBeVisible();

    const shellSpacing = await page.locator('[data-app-shell-ready] > main').evaluate((main) => {
      const style = window.getComputedStyle(main);
      const nav = document.querySelector<HTMLElement>('.nav-container');
      return {
        paddingBottom: Number.parseFloat(style.paddingBottom),
        navHeight: nav?.getBoundingClientRect().height ?? 0,
      };
    });
    expect(shellSpacing.paddingBottom).toBeGreaterThan(shellSpacing.navHeight);
  });

  test('uses plain language for manual selection and die mode', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;
    await page.setViewportSize({ width: 430, height: 932 });
    await page.goto('/');

    await page.getByRole('button', { name: 'Pick manually' }).click();
    await expect(page.getByRole('dialog', { name: 'Pick manually' })).toBeVisible();
    await expect(page.getByText('Choose the eligible thread you want to read next.')).toBeVisible();
    await page.getByRole('button', { name: 'Close' }).click();

    await page.getByRole('button', { name: /current die d\d+, automatic mode/i }).click();
    await expect(page.getByText(/Automatic mode is active at d\d+/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use automatic' })).toBeVisible();
  });
});
