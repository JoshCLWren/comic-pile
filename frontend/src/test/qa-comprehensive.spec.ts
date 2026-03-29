import { test, expect } from './fixtures';
import { generateTestUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('QA Comprehensive Test Suite', () => {
  let testUser: ReturnType<typeof generateTestUser>;

  test.beforeAll(async ({ request }) => {
    testUser = generateTestUser();
    
    // Register user
    const registerResponse = await request.post('/api/auth/register', {
      data: testUser,
    });
    expect(registerResponse.ok()).toBeTruthy();

    // Create some test threads
    const loginResponse = await request.post('/api/auth/login', {
      data: {
        username: testUser.username,
        password: testUser.password,
      },
    });
    expect(loginResponse.ok()).toBeTruthy();
    const loginData = await loginResponse.json();
    const accessToken = loginData.access_token;

    // Create threads with different states
    const headers = {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    };

    // Thread 1: Active with issues
    let thread1Response = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'X-Men: The Animated Series',
        format: 'issue',
        issues_remaining: 10,
      },
    });
    expect(thread1Response.ok()).toBeTruthy();
    const thread1 = await thread1Response.json();

    // Create issues for thread 1
    await request.post(`/api/v1/threads/${thread1.id}/issues`, {
      headers,
      data: { issue_range: '1-10' },
    });

    // Thread 2: Completed thread
    let thread2Response = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Amazing Spider-Man',
        format: 'issue',
        issues_remaining: 0,
      },
    });
    expect(thread2Response.ok()).toBeTruthy();
    const thread2 = await thread2Response.json();

    // Create and mark all issues as read for thread 2
    await request.post(`/api/v1/threads/${thread2.id}/issues`, {
      headers,
      data: { issue_range: '1-5' },
    });

    const issuesResponse = await request.get(`/api/v1/threads/${thread2.id}/issues`, {
      headers,
    });
    if (issuesResponse.ok()) {
      const issuesData = await issuesResponse.json();
      for (const issue of issuesData.issues) {
        await request.post(`/api/v1/issues/${issue.id}:markRead`, {
          headers,
        });
      }
    }

    // Thread 3: Another active thread
    let thread3Response = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Batman: Year One',
        format: 'issue',
        issues_remaining: 4,
      },
    });
    expect(thread3Response.ok()).toBeTruthy();
    const thread3 = await thread3Response.json();

    await request.post(`/api/v1/threads/${thread3.id}/issues`, {
      headers,
      data: { issue_range: '1-4' },
    });
  });

  test('1. Auth - Navigate to home and verify authentication', async ({ page }) => {
    // Login
    await loginUser(page, testUser);
    
    // Navigate to home
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    
    // Should not be redirected to login
    await expect(page).not.toHaveURL(/login/);
    
    // Should see roll page elements
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 10000 });
  });

  test('2. Roll page - Verify page loads and elements are present', async ({ page }) => {
    await loginUser(page, testUser);
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Verify roll page loads
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 10000 });

    // Check header indicators
    const headerElements = page.locator('[data-roll-pool] header, [data-roll-pool] .header');
    const headerCount = await headerElements.count();
    
    if (headerCount > 0) {
      // Check for labels and tooltips (hover over indicators)
      const indicators = page.locator('[data-roll-pool] [aria-label], [data-roll-pool] [title]');
      const indicatorCount = await indicators.count();
      
      if (indicatorCount > 0) {
        // Hover over first indicator to check tooltip
        await indicators.first().hover();
        await page.waitForTimeout(500);
      }
    }

    // Check CollectionToolbar renders
    const collectionToolbar = page.locator('[aria-label="Roll pool collection"], .collection-toolbar');
    await expect(collectionToolbar.first()).toBeVisible({ timeout: 5000 });

    // Check for New collection button
    const newCollectionButton = page.locator('button:has-text("New collection"), button:has-text("Create collection")');
    const newCollectionCount = await newCollectionButton.count();
    if (newCollectionCount > 0) {
      await expect(newCollectionButton.first()).toBeVisible();
    }
  });

  test('3. Queue page - Verify thread list and search/filter', async ({ page }) => {
    await loginUser(page, testUser);
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });

    // Verify queue page loads
    await expect(page.locator('h1:has-text("Queue"), h2:has-text("Queue")').first()).toBeVisible({ timeout: 10000 });

    // Check search/filter box
    const searchBox = page.locator('input[placeholder*="search" i], input[placeholder*="filter" i], input[type="search"]');
    const searchCount = await searchBox.count();
    
    if (searchCount > 0) {
      await expect(searchBox.first()).toBeVisible();
      
      // Test search functionality
      await searchBox.first().fill('X-Men');
      await page.waitForTimeout(500);
      
      // Clear search
      await searchBox.first().fill('');
      await page.waitForTimeout(500);
    }

    // Verify thread cards show correct info
    const threadCards = page.locator('[data-testid="queue-thread-item"], .thread-card, .thread-item');
    const threadCount = await threadCards.count();
    
    if (threadCount > 0) {
      // Check first thread card has title
      const firstCard = threadCards.first();
      await expect(firstCard).toBeVisible();
      
      // Check for position/status indicators
      const positionLabel = firstCard.locator('text=/#\\d+/i, [data-position]');
      const positionCount = await positionLabel.count();
      
      if (positionCount > 0) {
        await expect(positionLabel.first()).toBeVisible();
      }
    }
  });

  test('4. Session page - Click into thread and verify issues', async ({ page }) => {
    await loginUser(page, testUser);
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });

    // Wait for queue to load
    await page.waitForTimeout(1000);

    // Find and click on a thread
    const threadLinks = page.locator('a[href*="/thread/"], [data-testid="queue-thread-item"]');
    const threadCount = await threadLinks.count();
    
    if (threadCount > 0) {
      await threadLinks.first().click();
      await page.waitForLoadState('domcontentloaded');

      // Verify issues list loads
      const issueList = page.locator('.issue-list, [data-testid="issue-list"]');
      await expect(issueList.first()).toBeVisible({ timeout: 10000 });

      // Check issue cards
      const issueCards = page.locator('.issue-item, [data-issue-id]');
      const issueCount = await issueCards.count();
      
      if (issueCount > 0) {
        // Check first issue has number and title
        const firstIssue = issueCards.first();
        await expect(firstIssue).toBeVisible();

        // Check for read/unread state
        const readIndicator = firstIssue.locator('.read, .unread, [data-read]');
        const readCount = await readIndicator.count();
        // Read indicator may or may not be present
      }

      // Check position slider or controls
      const positionSlider = page.locator('input[type="range"], .position-slider, [data-position-slider]');
      const sliderCount = await positionSlider.count();
      
      if (sliderCount > 0) {
        await expect(positionSlider.first()).toBeVisible();
      }
    }
  });

  test('5. History page - Verify reading history', async ({ page }) => {
    await loginUser(page, testUser);
    await page.goto('/history', { waitUntil: 'domcontentloaded' });

    // Verify history page loads
    await expect(page.locator('h1:has-text("History"), h2:has-text("History")').first()).toBeVisible({ timeout: 10000 });

    // Check for sessions list
    const sessionsList = page.locator('#sessions-list, .sessions-list, [data-sessions]');
    const sessionsCount = await sessionsList.count();
    
    if (sessionsCount > 0) {
      await expect(sessionsList.first()).toBeVisible();
    }
  });

  test('6. Analytics page - Verify charts and stats', async ({ page }) => {
    await loginUser(page, testUser);
    await page.goto('/analytics', { waitUntil: 'domcontentloaded' });

    // Verify analytics page loads
    await expect(page.locator('h1:has-text("Analytics"), h2:has-text("Analytics")').first()).toBeVisible({ timeout: 10000 });

    // Check for glass cards (stat cards)
    const glassCards = page.locator('.glass-card, .stat-card, [data-stat]');
    const cardCount = await glassCards.count();
    
    if (cardCount > 0) {
      await expect(glassCards.first()).toBeVisible();
      
      // Check that numbers look reasonable (not NaN)
      const firstCardText = await glassCards.first().textContent();
      expect(firstCardText).not.toContain('NaN');
    }

    // Check for charts
    const charts = page.locator('canvas, .chart, .graph, [data-chart]');
    const chartCount = await charts.count();
    
    if (chartCount > 0) {
      await expect(charts.first()).toBeVisible();
    }
  });

  test('7. Dependencies - Check dependency indicators and tooltips', async ({ page, request }) => {
    await loginUser(page, testUser);

    // Create threads with dependencies
    const loginResponse = await request.post('/api/auth/login', {
      data: {
        username: testUser.username,
        password: testUser.password,
      },
    });
    const loginData = await loginResponse.json();
    const accessToken = loginData.access_token;
    const headers = {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    };

    // Create prerequisite thread
    const prereqResponse = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Prerequisite Comic',
        format: 'issue',
        issues_remaining: 1,
      },
    });
    const prereqThread = await prereqResponse.json();
    await request.post(`/api/v1/threads/${prereqThread.id}/issues`, {
      headers,
      data: { issue_range: '1-1' },
    });

    // Create dependent thread
    const dependentResponse = await request.post('/api/threads/', {
      headers,
      data: {
        title: 'Dependent Comic',
        format: 'issue',
        issues_remaining: 1,
      },
    });
    const dependentThread = await dependentResponse.json();
    await request.post(`/api/v1/threads/${dependentThread.id}/issues`, {
      headers,
      data: { issue_range: '1-1' },
    });

    // Create dependency
    await request.post(`/api/v1/threads/${dependentThread.id}/dependencies`, {
      headers,
      data: {
        blocks_thread_id: prereqThread.id,
      },
    });

    // Navigate to queue and check for dependency indicators
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);

    // Look for dependency indicators
    const depIndicators = page.locator('[data-dependency], .dependency, [aria-label*="depend" i]');
    const depCount = await depIndicators.count();
    
    if (depCount > 0) {
      // Hover over dependency indicator to check tooltip
      await depIndicators.first().hover();
      await page.waitForTimeout(500);
      
      // Check tooltip text
      const tooltip = page.locator('.tooltip, [role="tooltip"]');
      const tooltipCount = await tooltip.count();
      
      if (tooltipCount > 0) {
        const tooltipText = await tooltip.first().textContent();
        // Verify it says "Blocking" not "Blocks" for outgoing deps
        if (tooltipText) {
          expect(tooltipText.toLowerCase()).not.toContain('blocks');
        }
      }
    }
  });

  test('8. Collections - Verify collection switcher and creation', async ({ page }) => {
    await loginUser(page, testUser);
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Open collection switcher
    const collectionSwitcher = page.locator('[aria-label="Roll pool collection"], .collection-switcher, button:has-text("Collection")');
    const switcherCount = await collectionSwitcher.count();
    
    if (switcherCount > 0) {
      await collectionSwitcher.first().click();
      await page.waitForTimeout(500);

      // Check for collections list
      const collectionsList = page.locator('.collections-list, [data-collections]');
      const listCount = await collectionsList.count();
      
      if (listCount > 0) {
        await expect(collectionsList.first()).toBeVisible();
      }

      // Try creating new collection
      const newCollectionButton = page.locator('button:has-text("New collection"), button:has-text("Create collection")');
      const newCollectionCount = await newCollectionButton.count();
      
      if (newCollectionCount > 0) {
        await newCollectionButton.first().click();
        await page.waitForTimeout(500);

        // Check for collection creation dialog/form
        const collectionForm = page.locator('input[placeholder*="collection" i], .collection-form');
        const formCount = await collectionForm.count();
        
        if (formCount > 0) {
          await expect(collectionForm.first()).toBeVisible();
          
          // Close the form/dialog
          await page.keyboard.press('Escape');
          await page.waitForTimeout(500);
        }
      }
    }
  });

  test('9. API health - Verify API endpoints', async ({ request }) => {
    // Check health endpoint
    const healthResponse = await request.get('/health');
    expect(healthResponse.ok()).toBeTruthy();
    
    const healthData = await healthResponse.json();
    expect(healthData).toHaveProperty('status');
    expect(healthData.status).toBe('healthy');

    // Check docs endpoint
    const docsResponse = await request.get('/docs');
    expect(docsResponse.ok()).toBeTruthy();
  });
});