import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Visual Regression Tests', () => {
  test('should match screenshot of home page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.dieSelector);

    await expect(authenticatedPage).toHaveScreenshot('home-page.png', {
      maxDiffPixels: 100,
      threshold: 0.2,
    });
  });

  test('should match screenshot of register page', async ({ page }) => {
    await page.goto('/register');

    await expect(page).toHaveScreenshot('register-page.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of login page', async ({ page }) => {
    await page.goto('/login');

    await expect(page).toHaveScreenshot('login-page.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of threads/queue page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/threads');

    await expect(authenticatedPage).toHaveScreenshot('threads-page.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of rate page', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Visual Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    await expect(page).toHaveScreenshot('rate-page.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of analytics page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    await expect(authenticatedPage).toHaveScreenshot('analytics-page.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of history page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    await expect(authenticatedPage).toHaveScreenshot('history-page.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of die selector with d10', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.dieSelector);

    const d10Button = authenticatedPage.locator('button:has-text("d10")').first();
    await d10Button.click();
    await authenticatedPage.waitForTimeout(500);

    await expect(authenticatedPage).toHaveScreenshot('die-selector-d10.png', {
      maxDiffPixels: 150,
      clip: { x: 0, y: 0, width: 400, height: 400 },
    });
  });

  test('should match screenshot of die selector with different sizes', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.dieSelector);

    const dieSizes = ['d4', 'd6', 'd8', 'd12', 'd20'];

    for (const dieSize of dieSizes) {
      const button = authenticatedPage.locator(`button:has-text("${dieSize}")`).first();
      if (await button.isVisible()) {
        await button.click();
        await authenticatedPage.waitForTimeout(500);

        await expect(authenticatedPage).toHaveScreenshot(`die-selector-${dieSize}.png`, {
          maxDiffPixels: 150,
          clip: { x: 0, y: 0, width: 400, height: 400 },
        });
      }
    }
  });

  test('should match screenshot of 3D dice animation', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Dice Animation Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(1000);

    await expect(page.locator(SELECTORS.roll.mainDie)).toHaveScreenshot('dice-rolling.png', {
      maxDiffPixels: 200,
    });
  });

  test('should match screenshot of thread list with multiple threads', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    for (let i = 1; i <= 5; i++) {
      await createThread(page, {
        title: `Comic ${i}`,
        format: 'Comic',
        issues_remaining: i * 2,
      });
    }

    await page.goto('/queue');

    await expect(page).toHaveScreenshot('thread-list-multiple.png', {
      maxDiffPixels: 100,
      fullPage: true,
    });
  });

  test('should match screenshot of rating form', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Rating Form Test',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    await expect(page.locator(SELECTORS.rate.ratingInput)).toHaveScreenshot('rating-form.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot on mobile viewport', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 375, height: 667 });
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.dieSelector);

    await expect(authenticatedPage).toHaveScreenshot('home-mobile.png', {
      maxDiffPixels: 150,
    });
  });

  test('should match screenshot on tablet viewport', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 768, height: 1024 });
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.dieSelector);

    await expect(authenticatedPage).toHaveScreenshot('home-tablet.png', {
      maxDiffPixels: 150,
    });
  });

  test('should match screenshot of error state', async ({ page }) => {
    await page.route('**/api/threads/**', route => route.abort());

    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/threads');

    const errorElement = page.locator('text=error|failed|try again');
    const hasError = await errorElement.count() > 0;

    if (hasError) {
      await expect(page).toHaveScreenshot('error-state.png', {
        maxDiffPixels: 100,
      });
    }
  });

  test('should match screenshot of empty state', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');

    await expect(authenticatedPage).toHaveScreenshot('empty-queue.png', {
      maxDiffPixels: 100,
    });
  });

  test('should match screenshot of loading state', async ({ page }) => {
    await page.route('**/api/threads/**', async route => {
      await new Promise(resolve => setTimeout(resolve, 2000));
      route.continue();
    });

    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/threads');

    const loadingElement = page.locator('.loading, .spinner, [aria-busy="true"]');
    const hasLoading = await loadingElement.count() > 0;

    if (hasLoading) {
      await expect(page).toHaveScreenshot('loading-state.png', {
        maxDiffPixels: 150,
      });
    }
  });

  test('should match screenshot of dark mode if supported', async ({ authenticatedPage }) => {
    const darkModeToggle = authenticatedPage.locator(
      'button:has-text("Dark"), button:has-text("Theme"), [aria-label*="dark"]'
    );
    const hasDarkMode = await darkModeToggle.count() > 0;

    if (hasDarkMode) {
      await darkModeToggle.first().click();
      await authenticatedPage.waitForTimeout(500);

      await expect(authenticatedPage).toHaveScreenshot('dark-mode.png', {
        maxDiffPixels: 100,
      });
    }
  });
});
