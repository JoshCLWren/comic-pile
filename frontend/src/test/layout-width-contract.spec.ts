import { test, expect } from './fixtures';

test.describe('Layout width contract (#1400)', () => {
  test('Roll (/ ) receives wide width contract with ~1536px cap', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await expect(authenticatedPage.locator('#root')).toBeVisible();

    const mainClass = await authenticatedPage.locator('main').evaluate((el) => (el as HTMLElement).className);
    expect(mainClass).toContain('xl:max-w-[1536px]');
    expect(mainClass).not.toContain('xl:max-w-5xl');
  });

  test('Queue (/queue) retains default narrow width contract', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await expect(authenticatedPage.locator('#root')).toBeVisible();

    const mainClass = await authenticatedPage.locator('main').evaluate((el) => (el as HTMLElement).className);
    expect(mainClass).toContain('xl:max-w-5xl');
    expect(mainClass).not.toContain('xl:max-w-[1536px]');
  });
});