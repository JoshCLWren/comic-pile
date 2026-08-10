import { expect, test } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Blocked roll recovery mobile layout (#849)', () => {
  test('keeps the preserved roll and ordered prerequisites readable at 390px', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;

    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();

    const firstThreadCard = page.locator('[role="button"]').filter({
      has: page.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    await page.getByText('Read Now', { exact: true }).click();
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    await page.route('**/api/v1/roll/bootstrap', async (route) => {
      const response = await route.fetch();
      const bootstrap = await response.json();
      await route.fulfill({
        response,
        json: {
          ...bootstrap,
          roll_recovery: {
            original_thread_id: bootstrap.pending_thread_id ?? bootstrap.active_thread?.id ?? 1,
            original_thread_title: 'Original blocked roll',
            direct_blockers: [
              {
                rule_id: 101,
                source_type: 'issue',
                source_id: 201,
                source_label: 'Direct blocker',
                satisfaction_type: 'item_read',
                satisfied: false,
                causing_issue_ids: [201],
                causing_member_issue_ids: [],
                note: null,
              },
            ],
            readable_prerequisites: [
              { node_type: 'issue', node_id: 301, label: 'First readable prerequisite' },
              { node_type: 'issue', node_id: 302, label: 'Second readable prerequisite' },
            ],
          },
        },
      });
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const recovery = page.getByRole('region', { name: 'Blocked roll recovery' });
    await expect(recovery).toBeVisible();
    await expect(recovery.getByText('Original blocked roll')).toBeVisible();
    await expect(recovery.getByText('Direct blocker')).toBeVisible();
    await expect(recovery.getByText('First readable prerequisite')).toBeVisible();
    await expect(recovery.getByText('Second readable prerequisite')).toBeVisible();
    await expect(recovery.getByText('Recommended first')).toBeVisible();
    await expect(recovery.getByText('Read now')).toHaveCount(2);

    const recoveryBox = await recovery.boundingBox();
    expect(recoveryBox).not.toBeNull();
    expect(recoveryBox!.x).toBeGreaterThanOrEqual(0);
    expect(recoveryBox!.x + recoveryBox!.width).toBeLessThanOrEqual(390);

    const recommendationRows = recovery.locator('.rounded-xl').filter({ hasText: 'Read now' });
    await expect(recommendationRows).toHaveCount(2);
    for (let index = 0; index < 2; index += 1) {
      const row = recommendationRows.nth(index);
      await expect(row).toBeVisible();
      const box = await row.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    }
  });
});
