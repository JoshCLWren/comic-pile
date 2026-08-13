import { expect, test } from './fixtures';

test.describe('Eligible Roll pool mappings (#1089)', () => {
  test('shows truthful issue mappings and explains full-queue shuffle on mobile', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;
    await page.setViewportSize({ width: 430, height: 932 });
    await page.goto('/');

    const pool = page.getByLabel(/Eligible now, \d+ mapped results?/i);
    await expect(pool).toBeVisible();

    const mappings = pool.getByRole('button', { name: /Die face \d+: issue \d+,/i });
    await expect(mappings).toHaveCount(3);
    await expect(mappings.first()).toBeVisible();

    const shuffle = page.getByRole('button', { name: 'Shuffle queue' });
    await expect(shuffle).toHaveAccessibleDescription(/complete active queue/i);
    await shuffle.click();

    await expect(page.getByLabel(/Eligible now, \d+ mapped results?/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Die face 1: issue \d+,/i })).toBeVisible();
  });
});
