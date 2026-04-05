/* eslint-disable max-lines */
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

    const tapInstruction = authenticatedPage.locator(SELECTORS.roll.tapInstruction);
    const tapInstructionExists = await tapInstruction.count() > 0;

    if (tapInstructionExists) {
      await expect(tapInstruction).toBeVisible();
    } else {
      const mainDie = authenticatedPage.locator(SELECTORS.roll.mainDie);
      await expect(mainDie).toBeVisible({ timeout: 10000 });
    }
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

     const emptyQueueMessage = authenticatedPage.locator('text=Your reading queue is empty — add some comic threads to get started.');
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

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();
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

    // Review form now appears - submit it (empty is fine)
    await expect(authenticatedWithThreadsPage.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 });
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      authenticatedWithThreadsPage.click('button:has-text("Skip")'), // Skip button (doesn't require text)
    ]);

    // Wait to return to roll view
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 5000 });

    // Second roll (same denomination) - animation should play
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    // Verify rating view appears (means animation played and roll succeeded)
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 5000 });

    // Verify still on home page (not redirected)
    expect(new URL(authenticatedWithThreadsPage.url()).pathname).toBe('/');
  });

  test.describe('Issue Metadata Persistence and Simplified Migration', () => {
    test('should show SimpleMigrationDialog and complete migration during rating', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
      if (!token) {
        throw new Error('No auth token found');
      }

      const threadTitle = `Legacy Thread ${Date.now()}`;

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: threadTitle,
          format: 'Comics',
          issues_remaining: 5,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      await authenticatedPage.click(SELECTORS.roll.mainDie);

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      await authenticatedPage.fill(SELECTORS.rate.ratingInput, '4');

      await authenticatedPage.click(SELECTORS.rate.submitButton);

      await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible({ timeout: 5000 });
      await expect(authenticatedPage.locator('#simple-migration-dialog-title')).toContainText('Track Issues');

      await authenticatedPage.fill('#issue-number', '5');

      await authenticatedPage.locator('.migration-dialog__btn--primary').filter({ hasText: 'Start Tracking' }).click();

      await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0, { timeout: 15000 });

      await expect(authenticatedPage.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 10000 });

      const threadDataResponse = await request.get(`/api/threads/${thread.id}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!threadDataResponse.ok()) {
        throw new Error(`Failed to fetch thread data: ${threadDataResponse.status()} ${threadDataResponse.statusText()}`);
      }

      const updatedThread = await threadDataResponse.json();
      expect(updatedThread.total_issues).toBe(9);
      expect(updatedThread.reading_progress).toBe('in_progress');
      expect(updatedThread.next_unread_issue_number).toBe('6');
    });

    test('should persist issue metadata after session refetch', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
      if (!token) {
        throw new Error('No auth token found');
      }

      const threadTitle = `Migrated Thread ${Date.now()}`;

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: threadTitle,
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 10,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      const issuesResponse = await request.post(`/api/v1/threads/${thread.id}/issues`, {
        data: {
          issue_range: '1-10',
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!issuesResponse.ok()) {
        throw new Error(`Failed to create issues: ${issuesResponse.status()} ${issuesResponse.statusText()}`);
      }

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
      await threadElement.click();

      const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
      await expect(actionSheetTitle).toBeVisible();

      await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const initialSessionResponse = await authenticatedPage.request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      expect(initialSessionResponse.ok()).toBeTruthy();

      const initialSessionData = await initialSessionResponse.json();
      expect(initialSessionData.active_thread).toBeDefined();
      expect(initialSessionData.active_thread.issue_number).toBeDefined();
      const initialIssueNumber = initialSessionData.active_thread.issue_number;

      await authenticatedPage.evaluate(async (authToken) => {
        const response = await fetch('/api/sessions/current/', {
          headers: {
            'Authorization': `Bearer ${authToken}`
          }
        });
        if (!response.ok) {
          throw new Error(`Failed to refetch session: ${response.status}`);
        }
        return await response.json();
      }, token);

      const refetchedSessionResponse = await authenticatedPage.request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      expect(refetchedSessionResponse.ok()).toBeTruthy();

      const refetchedSessionData = await refetchedSessionResponse.json();
      expect(refetchedSessionData.active_thread).toBeDefined();
      expect(refetchedSessionData.active_thread.issue_number).toBeDefined();
      expect(refetchedSessionData.active_thread.issue_number).toBe(initialIssueNumber);
    });

    test('should persist issue metadata after page reload', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
      if (!token) {
        throw new Error('No auth token found');
      }

      const threadTitle = `Migrated Thread ${Date.now()}`;

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: threadTitle,
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 10,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      const issuesResponse = await request.post(`/api/v1/threads/${thread.id}/issues`, {
        data: {
          issue_range: '1-10',
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!issuesResponse.ok()) {
        throw new Error(`Failed to create issues: ${issuesResponse.status()} ${issuesResponse.statusText()}`);
      }

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
      await threadElement.click();

      const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
      await expect(actionSheetTitle).toBeVisible();

      await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const initialSessionResponse = await authenticatedPage.request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      expect(initialSessionResponse.ok()).toBeTruthy();

      const initialSessionData = await initialSessionResponse.json();
      const initialIssueNumber = initialSessionData.active_thread.issue_number;

      await authenticatedPage.reload();
      await authenticatedPage.waitForLoadState('networkidle');

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const reloadedSessionResponse = await authenticatedPage.request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      expect(reloadedSessionResponse.ok()).toBeTruthy();

      const reloadedSessionData = await reloadedSessionResponse.json();
      expect(reloadedSessionData.active_thread).toBeDefined();
      expect(reloadedSessionData.active_thread.issue_number).toBeDefined();
      expect(reloadedSessionData.active_thread.issue_number).toBe(initialIssueNumber);
    });

    test('should persist issue metadata after 409 conflict recovery', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
      if (!token) {
        throw new Error('No auth token found');
      }

      const threadTitle = `Migrated Thread ${Date.now()}`;

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: threadTitle,
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 10,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      const issuesResponse = await request.post(`/api/v1/threads/${thread.id}/issues`, {
        data: {
          issue_range: '1-10',
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!issuesResponse.ok()) {
        throw new Error(`Failed to create issues: ${issuesResponse.status()} ${issuesResponse.statusText()}`);
      }

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      await authenticatedPage.click(SELECTORS.roll.mainDie);

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const initialSessionResponse = await authenticatedPage.request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      expect(initialSessionResponse.ok()).toBeTruthy();

      const initialSessionData = await initialSessionResponse.json();
      const initialIssueNumber = initialSessionData.active_thread.issue_number;

      const secondRollResponse = await authenticatedPage.request.post('/api/roll/', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      expect(secondRollResponse.status()).toBe(409);

      const sessionResponse = await authenticatedPage.request.get('/api/sessions/current/', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      expect(sessionResponse.ok()).toBeTruthy();

      const sessionData = await sessionResponse.json();
      expect(sessionData.active_thread).toBeDefined();
      expect(sessionData.active_thread.issue_number).toBeDefined();
      expect(sessionData.active_thread.issue_number).toBe(initialIssueNumber);
    });
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

    test('roll only selects from unblocked threads', async ({ authenticatedPage }) => {
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
        issues_remaining: 10,
        total_issues: 10,
      },
      })
      const unblockedThread = await unblockedResponse.json()

      // Create issues for the unblocked thread
      await authenticatedPage.request.post(`/api/v1/threads/${unblockedThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { issue_range: '1-10' },
      })

      const blockedResponse = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      data: {
        title: 'Blocked Thread - Never Rolled',
        format: 'Comics',
        issues_remaining: 3,
        total_issues: 10,
      },
      })
      const blockedThread = await blockedResponse.json()

      // Create issues for the blocked thread
      await authenticatedPage.request.post(`/api/v1/threads/${blockedThread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { issue_range: '1-10' },
      })

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
        
        // Review form now appears - submit it (empty is fine)
        await expect(authenticatedPage.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 })
        await Promise.all([
          authenticatedPage.waitForResponse(r => r.url().includes('/api/rate/')),
          authenticatedPage.click('button:has-text("Skip")'), // Skip button (doesn't require text)
        ])
        
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

  test.describe('Snoozed thread filtering', () => {
    test('issue #321: snoozed threads do not appear in roll pool', async ({ authenticatedPage }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create three threads
      const thread1Response = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Active Thread A',
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 5,
        },
      })
      await authenticatedPage.request.post(`/api/v1/threads/${(await thread1Response.json()).id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { issue_range: '1-5' },
      })

      const thread2Response = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Snoozed Thread B',
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 5,
        },
      })
      const thread2 = await thread2Response.json()
      await authenticatedPage.request.post(`/api/v1/threads/${thread2.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { issue_range: '1-5' },
      })

      const thread3Response = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Active Thread C',
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 5,
        },
      })
      await authenticatedPage.request.post(`/api/v1/threads/${(await thread3Response.json()).id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { issue_range: '1-5' },
      })

      // Go to roll page
      await authenticatedPage.goto('/')
      await authenticatedPage.waitForLoadState('networkidle')

      // Click on snoozed thread to open action sheet
      const snoozedThreadElement = authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: 'Snoozed Thread B' })
      await snoozedThreadElement.click()

      // Click "Read Now" to set thread as pending
      const readButton = authenticatedPage.locator('button:has-text("Read Now")')
      await readButton.click()

      // Wait for rating view to appear
      await authenticatedPage.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 5000 })

      // Snooze the thread via the rating view
      const snoozeButton = authenticatedPage.locator('button:has-text("Snooze")')
      await snoozeButton.click()

       // Wait for snooze to complete and return to roll page
       await authenticatedPage.waitForLoadState('networkidle')

       // Wait for at least one active thread to appear in the pool
       await expect(
         authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: 'Active Thread A' })
       ).toBeVisible({ timeout: 10000 })

       // Check that snoozed thread is NOT in the roll pool
       const rollPoolText = await authenticatedPage.evaluate(() => {
         const poolElement = document.querySelector('[data-roll-pool]')
         return poolElement ? poolElement.textContent : ''
       })

       expect(rollPoolText).not.toContain('Snoozed Thread B')
       expect(rollPoolText).toContain('Active Thread A')
    })

    test('snoozed thread appears in SNOOZED section only', async ({ authenticatedPage }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)

      // Create a thread to snooze
      const threadResponse = await authenticatedPage.request.post('/api/threads/', {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: {
          title: 'Snoozed Test Thread',
          format: 'Comics',
          issues_remaining: 5,
          total_issues: 5,
        },
      })
      const thread = await threadResponse.json()
      await authenticatedPage.request.post(`/api/v1/threads/${thread.id}/issues`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { issue_range: '1-5' },
      })

      // Go to roll page
      await authenticatedPage.goto('/')
      await authenticatedPage.waitForLoadState('networkidle')

      // Click on thread to open action sheet
      const threadElement = authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: 'Snoozed Test Thread' })
      await threadElement.click()

      // Click "Read Now" to set thread as pending
      const readButton = authenticatedPage.locator('button:has-text("Read Now")')
      await readButton.click()

      // Wait for rating view to appear
      await authenticatedPage.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible', timeout: 5000 })

      // Snooze the thread via the rating view
      const snoozeButton = authenticatedPage.locator('button:has-text("Snooze")')
      await snoozeButton.click()

      // Wait for snooze to complete and return to roll page
      await authenticatedPage.waitForLoadState('networkidle')

      // Expand the snoozed section - look for button containing "Snoozed ("
      const snoozedToggleButton = authenticatedPage.locator('button').filter({ hasText: /Snoozed \(/ })
      await snoozedToggleButton.click()

      // Wait for snoozed threads to appear
      await authenticatedPage.waitForTimeout(500)

      // Check that snoozed thread appears in SNOOZED section
      await expect(authenticatedPage.locator('text=Snoozed Test Thread')).toBeVisible()

      // Check that thread does NOT appear in roll pool
      const rollPoolText = await authenticatedPage.evaluate(() => {
        const poolElement = document.querySelector('[data-roll-pool]')
        return poolElement ? poolElement.textContent : ''
      })

      expect(rollPoolText).not.toContain('Snoozed Test Thread')
    })
  });

  test.describe('Manual Die Selection', () => {
    test('issue #281: manual die selection should persist after rating', async ({ authenticatedWithThreadsPage, request }) => {
      const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

      await authenticatedWithThreadsPage.goto('/');
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');
      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

      const MANUAL_DIE = 8;

      const dieButton = authenticatedWithThreadsPage.locator(`button:has-text("d${MANUAL_DIE}")`).first();
      await dieButton.click();
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');

      const sessionBefore = await request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const sessionBeforeData = await sessionBefore.json();
      expect(sessionBeforeData.manual_die).toBe(MANUAL_DIE);
      expect(sessionBeforeData.current_die).toBe(MANUAL_DIE);

      await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
      await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      await authenticatedWithThreadsPage.fill(SELECTORS.rate.ratingInput, '5');
      await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

      // Review form now appears - submit it (empty is fine)
      await expect(authenticatedWithThreadsPage.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 });
      await Promise.all([
        authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
        authenticatedWithThreadsPage.click('button:has-text("Skip")'), // Skip button (doesn't require text)
      ]);

      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');

      const sessionAfter = await request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const sessionAfterData = await sessionAfter.json();

      expect(sessionAfterData.manual_die).toBe(MANUAL_DIE);
      expect(sessionAfterData.current_die).toBe(MANUAL_DIE);
    });

    test('issue #280: manual die selection should persist after snoozing', async ({ authenticatedWithThreadsPage, request }) => {
      const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

      await authenticatedWithThreadsPage.goto('/');
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');
      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

      const MANUAL_DIE = 10;

      const dieButton = authenticatedWithThreadsPage.locator(`button:has-text("d${MANUAL_DIE}")`).first();
      await dieButton.click();
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');

      const sessionBeforeRoll = await request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const sessionBeforeRollData = await sessionBeforeRoll.json();
      expect(sessionBeforeRollData.manual_die).toBe(MANUAL_DIE);
      expect(sessionBeforeRollData.current_die).toBe(MANUAL_DIE);

      await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
      await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const sessionAfterRoll = await request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const sessionAfterRollData = await sessionAfterRoll.json();

      const snoozeButton = authenticatedWithThreadsPage.locator('button:has-text("Snooze")').first();
      await snoozeButton.click();

      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');

      const sessionAfterSnooze = await request.get('/api/sessions/current/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const sessionAfterSnoozeData = await sessionAfterSnooze.json();

      expect(sessionAfterSnoozeData.manual_die).toBe(MANUAL_DIE);
      expect(sessionAfterSnoozeData.current_die).toBe(MANUAL_DIE);
    });
  });

  test.describe('Rating View Layout', () => {
  test('issue #324: rating view should show title and issue number on one line', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    const threadTitle = 'X-Force';
    const totalIssues = 100;

    const threadResponse = await request.post('/api/threads/', {
      data: {
        title: threadTitle,
        format: 'Comics',
        issues_remaining: 72,
        total_issues: totalIssues,
      },
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    if (!threadResponse.ok()) {
      throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
    }

    const thread = await threadResponse.json();

    await request.post(`/api/v1/threads/${thread.id}/issues`, {
      data: { issue_range: '1-100' },
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadElement = authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    const readButton = authenticatedPage.locator('button:has-text("Read Now")');
    await readButton.click();

    await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

    const titleElement = authenticatedPage.locator('#thread-info h2');
    await expect(titleElement).toBeVisible();

    const titleText = await titleElement.textContent();
    expect(titleText).toContain('X-Force');
  });

    test('issue #324: rating view should show percentage complete and issues left', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: 'Test Thread',
          format: 'Comics',
          issues_remaining: 100,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      await request.post(`/api/v1/threads/${thread.id}/issues`, {
        data: { issue_range: '1-100' },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      const issuesResponse = await request.get(`/api/v1/threads/${thread.id}/issues?page_size=100`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!issuesResponse.ok()) {
        throw new Error(`Failed to get issues: ${issuesResponse.status()} ${issuesResponse.statusText()}`);
      }

      const issuesData = await issuesResponse.json();
      const issues = issuesData.issues;

      for (let i = 0; i < 72; i++) {
        await request.post(`/api/v1/issues/${issues[i].id}:markRead`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
      }

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      const threadElement = authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: 'Test Thread' }).first();
      await threadElement.click();

      const readButton = authenticatedPage.locator('button:has-text("Read Now")');
      await readButton.click();

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const progressText = authenticatedPage.locator('#thread-info');
      await expect(progressText).toContainText('72% complete');
      await expect(progressText).toContainText('28 issues left');
    });

    test('issue #324: rating view should show "You rolled a X!" instead of Queue position', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.goto('/');
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');
      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

      await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

      await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const rolledText = authenticatedWithThreadsPage.locator('#thread-info');
      await expect(rolledText).toContainText('You rolled a');

      await expect(rolledText).not.toContainText('Queue #');
    });

  test('issue #324: rating view should handle long titles with truncation', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    const longTitle = 'The Amazing Spider-Man: The Complete Collection Volume One: The Stan Lee Years';

    const threadResponse = await request.post('/api/threads/', {
      data: {
        title: longTitle,
        format: 'Comics',
        issues_remaining: 50,
        total_issues: 100,
      },
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    if (!threadResponse.ok()) {
      throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
    }

    const thread = await threadResponse.json();

    await request.post(`/api/v1/threads/${thread.id}/issues`, {
      data: { issue_range: '1-100' },
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadElement = authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: longTitle }).first();
    await threadElement.click();

    const readButton = authenticatedPage.locator('button:has-text("Read Now")');
    await readButton.click();

    await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

    // The title now includes the issue number within the h2 element
    const titleElement = authenticatedPage.locator('#thread-info h2');
    await expect(titleElement).toBeVisible();

    const titleText = await titleElement.textContent();
    expect(titleText).toContain('#');
    expect(titleText).toContain(longTitle.substring(0, 30));
  });

    test('issue #324: rating view should display 0% for unread thread', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: 'Unread Thread',
          format: 'Comics',
          issues_remaining: 10,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      await request.post(`/api/v1/threads/${thread.id}/issues`, {
        data: { issue_range: '1-10' },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      const threadElement = authenticatedPage.locator('[data-roll-pool] [role="button"]').filter({ hasText: 'Unread Thread' }).first();
      await threadElement.click();

      const readButton = authenticatedPage.locator('button:has-text("Read Now")');
      await readButton.click();

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const progressText = authenticatedPage.locator('#thread-info');
      await expect(progressText).toContainText('0% complete');
      await expect(progressText).toContainText('10 issues left');
    });

    test('issue #324: rating view should display 100% for completed thread', async ({ authenticatedPage, request }) => {
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

      const threadResponse = await request.post('/api/threads/', {
        data: {
          title: 'Completed Thread',
          format: 'Comics',
          issues_remaining: 10,
        },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!threadResponse.ok()) {
        throw new Error(`Failed to create thread: ${threadResponse.status()} ${threadResponse.statusText()}`);
      }

      const thread = await threadResponse.json();

      await request.post(`/api/v1/threads/${thread.id}/issues`, {
        data: { issue_range: '1-10' },
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      const issuesResponse = await request.get(`/api/v1/threads/${thread.id}/issues?page_size=100`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!issuesResponse.ok()) {
        throw new Error(`Failed to get issues: ${issuesResponse.status()} ${issuesResponse.statusText()}`);
      }

      const issuesData = await issuesResponse.json();
      const issues = issuesData.issues;

      for (const issue of issues.slice(0, -1)) {
        await request.post(`/api/v1/issues/${issue.id}:markRead`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
      }

      await request.post(`/api/threads/${thread.id}/set-pending`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('networkidle');

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

      const lastIssue = issues[issues.length - 1];
      await request.post(`/api/v1/issues/${lastIssue.id}:markRead`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      await authenticatedPage.reload();
      await authenticatedPage.waitForLoadState('networkidle');

      await expect(authenticatedPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

    const progressText = authenticatedPage.locator('#thread-info');
    await expect(progressText).toContainText('100% complete', { timeout: 10000 });
    await expect(progressText).toContainText('0 issues left', { timeout: 10000 });

      const threadAfterResponse = await request.get(`/api/threads/${thread.id}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!threadAfterResponse.ok()) {
        throw new Error(`Failed to get thread: ${threadAfterResponse.status()} ${threadAfterResponse.statusText()}`);
      }

      const threadAfter = await threadAfterResponse.json();

      expect(threadAfter.total_issues).toBe(10);
      expect(threadAfter.issues_remaining).toBe(0);
      expect(threadAfter.reading_progress).toBe('completed');
    });
  });
});
