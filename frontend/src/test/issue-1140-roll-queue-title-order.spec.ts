import { expect, test } from './fixtures';

test.describe('Roll queue issue-below-title order (#1140)', () => {
  test('renders the series title above the issue number on mobile', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');

    const pool = page.getByLabel(/Eligible now, \d+ mapped results?/i);
    await expect(pool).toBeVisible();

    const firstMapping = pool.getByRole('button', { name: /Die face 1: .+, issue \d+,/i }).first();
    await expect(firstMapping).toBeVisible();

    const titleText = firstMapping.locator('p').nth(0);
    const issueText = firstMapping.locator('p').nth(1);
    await expect(titleText).not.toHaveText(/^Issue \d+$/);
    await expect(titleText).not.toHaveText(/^Next unread issue$/);
    await expect(issueText).toHaveText(/^Issue \d+$/);

    const titleBox = await titleText.boundingBox();
    const issueBox = await issueText.boundingBox();
    expect(titleBox).not.toBeNull();
    expect(issueBox).not.toBeNull();
    if (titleBox && issueBox) {
      expect(titleBox.y + titleBox.height).toBeLessThanOrEqual(issueBox.y + 0.5);
    }
  });
});
