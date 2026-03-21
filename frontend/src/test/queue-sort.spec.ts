import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Queue Sorting', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
  });

  test('should sort threads alphabetically (A-Z)', async ({ authenticatedPage }) => {
    const threadTitles = ['Zebra Comics', 'Alpha Series', 'Mega Man', 'Batman Adventures'];
    
    for (const title of threadTitles) {
      await createThread(authenticatedPage, {
        title,
        format: 'Comics',
        issues_remaining: 5,
      });
    }

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'title-asc');
    await authenticatedPage.waitForTimeout(500);

    const threadElements = authenticatedPage.locator('#queue-container h3');
    const count = await threadElements.count();

    expect(count).toBeGreaterThanOrEqual(threadTitles.length);

    const titles: string[] = [];
    for (let i = 0; i < Math.min(count, threadTitles.length); i++) {
      const text = await threadElements.nth(i).textContent();
      if (text) titles.push(text);
    }

    const sortedTitles = [...titles].sort((a, b) => a.localeCompare(b));
    expect(titles).toEqual(sortedTitles);
  });

  test('should sort threads alphabetically (Z-A)', async ({ authenticatedPage }) => {
    const threadTitles = ['Apple Comics', 'Zero Hour', 'Mystery Tales', 'Super Stories'];
    
    for (const title of threadTitles) {
      await createThread(authenticatedPage, {
        title,
        format: 'Comics',
        issues_remaining: 5,
      });
    }

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'title-desc');
    await authenticatedPage.waitForTimeout(500);

    const threadElements = authenticatedPage.locator('#queue-container h3');
    const count = await threadElements.count();

    expect(count).toBeGreaterThanOrEqual(threadTitles.length);

    const titles: string[] = [];
    for (let i = 0; i < Math.min(count, threadTitles.length); i++) {
      const text = await threadElements.nth(i).textContent();
      if (text) titles.push(text);
    }

    const sortedTitles = [...titles].sort((a, b) => b.localeCompare(a));
    expect(titles).toEqual(sortedTitles);
  });

  test('should sort threads by recently added', async ({ authenticatedPage }) => {
    const firstThread = await createThread(authenticatedPage, {
      title: 'First Thread',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.waitForTimeout(1100);

    await createThread(authenticatedPage, {
      title: 'Second Thread',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'created-desc');
    await authenticatedPage.waitForTimeout(500);

    const threadElements = authenticatedPage.locator('#queue-container h3');
    const firstTitle = await threadElements.nth(0).textContent();
    const secondTitle = await threadElements.nth(1).textContent();

    expect(firstTitle).toContain('Second Thread');
    expect(secondTitle).toContain('First Thread');
  });

  test('should sort threads by format', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Batman',
      format: 'Comics',
      issues_remaining: 5,
    });

    await createThread(authenticatedPage, {
      title: 'Saga',
      format: 'Trade',
      issues_remaining: 3,
    });

    await createThread(authenticatedPage, {
      title: 'Watchmen',
      format: 'Omnibus',
      issues_remaining: 1,
    });

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'format');
    await authenticatedPage.waitForTimeout(500);

    const formatElements = authenticatedPage.locator('#queue-container .glass-card p.text-xs.uppercase');
    const count = await formatElements.count();

    expect(count).toBeGreaterThanOrEqual(3);

    const formats: string[] = [];
    for (let i = 0; i < Math.min(count, 3); i++) {
      const text = await formatElements.nth(i).textContent();
      if (text) formats.push(text);
    }

    const sortedFormats = [...formats].sort((a, b) => a.localeCompare(b));
    expect(formats).toEqual(sortedFormats);
  });

  test('should display in queue order by default', async ({ authenticatedPage }) => {
    const threadTitles = ['Third Thread', 'First Thread', 'Second Thread'];

    for (const title of threadTitles) {
      await createThread(authenticatedPage, {
        title,
        format: 'Comics',
        issues_remaining: 5,
      });
    }

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    const threadElements = authenticatedPage.locator('#queue-container h3');
    const count = await threadElements.count();

    expect(count).toBeGreaterThanOrEqual(threadTitles.length);

    for (let i = 0; i < Math.min(count, threadTitles.length); i++) {
      const text = await threadElements.nth(i).textContent();
      expect(text).toContain(threadTitles[i]);
    }
  });

  test('should not mutate queue positions when sorting', async ({ authenticatedPage }) => {
    const firstThread = await createThread(authenticatedPage, {
      title: 'Alpha',
      format: 'Comics',
      issues_remaining: 5,
    });

    await createThread(authenticatedPage, {
      title: 'Zeta',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    const getQueuePositions = async () => {
      await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'queue');
      await authenticatedPage.waitForTimeout(500);
      const threadElements = authenticatedPage.locator('#queue-container h3');
      const titles: string[] = [];
      const count = await threadElements.count();
      for (let i = 0; i < Math.min(count, 2); i++) {
        const text = await threadElements.nth(i).textContent();
        if (text) titles.push(text);
      }
      return titles;
    };

    const originalOrder = await getQueuePositions();
    expect(originalOrder[0]).toContain('Alpha');

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'title-desc');
    await authenticatedPage.waitForTimeout(500);

    const sortedOrder = await getQueuePositions();
    expect(sortedOrder).toEqual(originalOrder);
  });

  test('should switch between sort options', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Amazing Spider-Man',
      format: 'Comics',
      issues_remaining: 10,
    });

    await createThread(authenticatedPage, {
      title: 'Batman',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'title-asc');
    await authenticatedPage.waitForTimeout(500);
    let firstTitle = await authenticatedPage.locator('#queue-container h3').first().textContent();
    expect(firstTitle).toContain('Amazing');

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'title-desc');
    await authenticatedPage.waitForTimeout(500);
    firstTitle = await authenticatedPage.locator('#queue-container h3').first().textContent();
    expect(firstTitle).toContain('Batman');

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'queue');
    await authenticatedPage.waitForTimeout(500);
    firstTitle = await authenticatedPage.locator('#queue-container h3').first().textContent();
    expect(firstTitle).toContain('Amazing');
  });

  test('should show sort dropdown on mobile', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 375, height: 667 });
    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    const sortDropdown = authenticatedPage.locator('select[aria-label="Sort threads"]');
    await expect(sortDropdown).toBeVisible();
  });

  test('should persist sort option across page reloads', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'X-Men',
      format: 'Comics',
      issues_remaining: 5,
    });

    await createThread(authenticatedPage, {
      title: 'Avengers',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    await authenticatedPage.selectOption('select[aria-label="Sort threads"]', 'title-desc');
    await authenticatedPage.waitForTimeout(500);

    let firstTitle = await authenticatedPage.locator('#queue-container h3').first().textContent();
    expect(firstTitle).toContain('X-Men');

    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    firstTitle = await authenticatedPage.locator('#queue-container h3').first().textContent();
    expect(firstTitle).toContain('X-Men');
  });
});
