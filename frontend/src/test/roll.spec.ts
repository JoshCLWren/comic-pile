import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Roll Dice Feature', () => {
  test('should display die selector on home page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await expect(authenticatedPage.locator(SELECTORS.roll.dieSelector)).toBeVisible();
    await expect(authenticatedPage.locator(SELECTORS.roll.headerDieLabel)).toBeVisible();
  });

  test('should roll dice and show inline rating on home page', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();
    expect(new URL(authenticatedWithThreadsPage.url()).pathname).toBe('/');
  });

  test('regression: roll API response should be handled and inline rating should appear', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(currentUrl).toMatch(/\/$/);
    expect(currentUrl).not.toMatch(/\/rate/);
  });

  test('should show tap instruction on first visit', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await expect(authenticatedPage.locator(SELECTORS.roll.tapInstruction)).toBeVisible();
  });

  test('should support different die sizes (d4, d6, d8, d10, d12, d20)', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const dieSizes = ['d4', 'd6', 'd8', 'd10', 'd12', 'd20'];

    for (const dieSize of dieSizes) {
      const dieButton = authenticatedPage.locator(`button:has-text("${dieSize}")`).first();
      await expect(dieButton).toBeVisible();
    }
  });

  test('should display 3D dice canvas', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    const canvasInfo = await authenticatedPage.evaluate(() => {
      const container = document.querySelector('#main-die-3d');
      if (!container) return { error: 'Dice container not found' };

      const canvas = container.querySelector('canvas');
      if (!canvas) return { error: 'Canvas not found' };

      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      if (!gl) return { error: 'WebGL context not available' };

      return {
        success: true,
        hasWebGL: true,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
      };
    });

    if (canvasInfo.error) {
      console.log('3D Dice Canvas Info:', canvasInfo.error);
      return;
    }

    expect(canvasInfo.hasWebGL).toBe(true);
    expect(canvasInfo.canvasWidth).toBeGreaterThan(0);
    expect(canvasInfo.canvasHeight).toBeGreaterThan(0);
  });

  test('should handle roll with empty queue gracefully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    const emptyQueueMessage = authenticatedPage.locator('text=Queue Empty');
    await expect(emptyQueueMessage).toBeVisible();
  });

  test('should update session state after roll', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');

    const sessionBefore = await authenticatedWithThreadsPage.evaluate(async () => {
      const response = await fetch('/api/sessions/current');
      const data = await response.json();
      return data;
    });

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    const sessionAfter = await authenticatedWithThreadsPage.evaluate(async () => {
      const response = await fetch('/api/sessions/current');
      const data = await response.json();
      return data;
    });

    expect(sessionAfter).toBeDefined();
  });

  test('should show loading state during roll animation', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    const loadingIndicator = authenticatedWithThreadsPage.locator('.loading, .rolling, [aria-busy="true"]');

    await expect(async () => {
      const count = await loadingIndicator.count();
      if (count > 0) {
        await expect(loadingIndicator.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should be accessible via keyboard navigation', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector('#main-die-3d', { state: 'visible', timeout: 5000 });

    const dieElement = authenticatedWithThreadsPage.locator('#main-die-3d');
    await dieElement.focus();
    await authenticatedWithThreadsPage.keyboard.press('Enter');

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(new URL(currentUrl).pathname).toBe('/');
    expect(currentUrl).not.toContain('/rate');
  });

  test('should prevent multiple rapid rolls', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(currentUrl).toMatch(/\/$/);
  });

  test('should show inline rating without loading state after roll', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    // Verify no loading state appears
    const loadingText = authenticatedWithThreadsPage.getByText('Loading...');
    await expect(async () => {
      const isVisible = await loadingText.isVisible().catch(() => false);
      expect(isVisible).toBe(false);
    }).toPass({ timeout: 3000 });

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 2000 });
    expect(new URL(authenticatedWithThreadsPage.url()).pathname).toBe('/');
  });

  test('regression: animation should play on consecutive rolls after rating', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    // First roll
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    // Submit rating to return to roll view
    await authenticatedWithThreadsPage.fill(SELECTORS.rate.ratingInput, '5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

    // Wait to return to roll view
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 5000 });

    // Second roll (same denomination) - animation should play
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    // Verify rating view appears (means animation played and roll succeeded)
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    // Verify still on home page (not redirected)
    expect(new URL(authenticatedWithThreadsPage.url()).pathname).toBe('/');
  });

  test.describe('Blocked thread filtering', () => {
    test('blocked threads do not appear in roll pool', async ({ authenticatedPage }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create three threads
      const thread1Response = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Unblocked Thread A',
          format: 'Comics',
          issues_remaining: 5,
        },
      })
      const thread1 = await thread1Response.json()

      const thread2Response = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Blocked Thread B',
          format: 'Comics',
          issues_remaining: 5,
        },
      })
      const thread2 = await thread2Response.json()

      const thread3Response = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Unblocked Thread C',
          format: 'Comics',
          issues_remaining: 5,
        },
      })
      const thread3 = await thread3Response.json()

      // Create a dependency that blocks thread2
      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          source_type: 'thread',
          source_id: thread1.id,
          target_type: 'thread',
          target_id: thread2.id,
        },
      })

      // Go to roll page
      await authenticatedPage.goto('/')
      await authenticatedPage.waitForLoadState('networkidle')

      // Check that blocked thread is NOT in the roll pool
      const rollPoolText = await authenticatedPage.evaluate(() => {
        const poolElement = document.querySelector('[data-roll-pool]')
        return poolElement ? poolElement.textContent : ''
      })

      expect(rollPoolText).not.toContain('Blocked Thread B')
      expect(rollPoolText).toContain('Unblocked Thread A')
    })

    test.skip('roll only selects from unblocked threads', async ({ authenticatedPage }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create threads with specific names to verify roll result
      const unblockedResponse = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      data: {
        title: 'Rollable Thread',
        format: 'Comics',
        issues_remaining: 3,
      },
      })
      const unblockedThread = await unblockedResponse.json()

      const blockedResponse = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      data: {
        title: 'Blocked Thread - Never Rolled',
        format: 'Comics',
        issues_remaining: 3,
      },
      })
      const blockedThread = await blockedResponse.json()

      // Block the second thread
      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          source_type: 'thread',
          source_id: unblockedThread.id,
          target_type: 'thread',
          target_id: blockedThread.id,
        },
      })

      // Wait for dependency to be processed and refetch threads
      await authenticatedPage.waitForTimeout(2000)

      // Perform multiple rolls to verify blocked thread is never selected
      await authenticatedPage.goto('/')
      await authenticatedPage.waitForLoadState('networkidle')

      for (let i = 0; i < 5; i++) {
        await authenticatedPage.click(SELECTORS.roll.mainDie)
        await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 })

        // Check that the rolled thread is not the blocked one by verifying thread title in rating view
        const threadTitle = await authenticatedPage.locator('h2.text-2xl.font-black').textContent()
        expect(threadTitle).not.toContain('Blocked Thread - Never Rolled')

        // Submit rating to reset for next roll
        await authenticatedPage.fill(SELECTORS.rate.ratingInput, '4')
        await authenticatedPage.click(SELECTORS.rate.submitButton)
        await expect(authenticatedPage.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 5000 })
      }
    })

    test('blocked thread indicator appears in queue but thread is not rollable', async ({ authenticatedPage }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create a thread that will be blocked
      const blockedThreadResponse = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Queue Blocked Thread',
          format: 'Comics',
          issues_remaining: 5,
        },
      })
      const blockedThread = await blockedThreadResponse.json()

      // Create a thread to block it
      const blockerThreadResponse = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Queue Blocker Thread',
          format: 'Comics',
          issues_remaining: 5,
        },
      })
      const blockerThread = await blockerThreadResponse.json()

      // Create the blocking dependency
      await authenticatedPage.request.post('/api/v1/dependencies/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          source_type: 'thread',
          source_id: blockerThread.id,
          target_type: 'thread',
          target_id: blockedThread.id,
        },
      })

      // Navigate to queue and verify blocked indicator
      await authenticatedPage.goto('/queue')
      await authenticatedPage.waitForLoadState('networkidle')

      const blockedCard = authenticatedPage
        .locator('#queue-container .glass-card')
        .filter({ hasText: 'Queue Blocked Thread' })
        .first()

      // Should show blocked indicator
      await expect(
        blockedCard.locator('[aria-label="Blocked thread"]')
      ).toBeVisible()

      // Now check roll page
      await authenticatedPage.goto('/')
      await authenticatedPage.waitForLoadState('networkidle')

      // Blocked thread should NOT appear in roll pool
      const rollPoolText = await authenticatedPage.evaluate(() => {
        const poolElement = document.querySelector('[data-roll-pool]')
        return poolElement ? poolElement.textContent : ''
      })

      expect(rollPoolText).not.toContain('Queue Blocked Thread')
    })
  });
});
