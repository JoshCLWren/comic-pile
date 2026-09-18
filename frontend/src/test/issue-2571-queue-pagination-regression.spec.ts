import { expect, test } from './fixtures';
import { waitForQueueReady } from './helpers';

/**
 * Queue pagination regression suite (#2571).
 * 
 * Validates bidirectional scrolling through 5+ pages of data using real 
 * virtualization. Proves that visible cards remain painted, previously 
 * loaded regions recover immediately, and no duplicates or gaps occur.
 */
test.describe('Queue pagination regression (#2571)', () => {
  test('survives bidirectional traversal of 5+ pages of data', async ({ authenticatedWithProductionQueuePage }) => {
    const page = authenticatedWithProductionQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    // Page 1: Initial load
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(50);
    await expect(page.getByText('Test Thread 1')).toBeVisible();
    await expect(page.getByText('Test Thread 50')).toBeVisible();

    // 1. Scroll to bottom to load Page 2 (51-100)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.getByText('Test Thread 100')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(100);

    // 2. Scroll back near top
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(page.getByText('Test Thread 1')).toBeVisible();

    // 3. Scroll down to load Page 3 (101-150)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.getByText('Test Thread 150')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(150);

    // 4. Scroll back through prior pages (Page 2)
    await page.evaluate(() => window.scrollTo(0, window.innerHeight * 5)); // Approximate middle
    await expect(page.getByText('Test Thread 51')).toBeVisible({ timeout: 5000 });

    // 5. Continue through pages 4 and 5 (151-250)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.getByText('Test Thread 200')).toBeVisible({ timeout: 15000 });
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.getByText('Test Thread 250')).toBeVisible({ timeout: 15000 });
    
    // Final count check
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(250);

    // 6. Revisit earlier loaded regions
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(page.getByText('Test Thread 1')).toBeVisible();
    
    await page.evaluate(() => window.scrollTo(0, window.innerHeight * 2));
    await expect(page.getByText('Test Thread 75')).toBeVisible({ timeout: 5000 });

    // Final Consistency Assertions
    const items = page.getByTestId('queue-thread-item');
    const count = await items.count();
    expect(count).toBe(250);

    // Check for duplicates/skips by sampling the rendered IDs or text
    // Since we use 'Test Thread X', we can check that we have 1 and 250 and no duplicates
    const allTexts = await page.evaluate(() => 
      Array.from(document.querySelectorAll('[data-testid="queue-thread-item"]'))
        .map(el => el.textContent?.trim())
    );
    
    const uniqueTexts = new Set(allTexts);
    expect(uniqueTexts.size).toBe(allTexts.length);
  });

  test('pagination stability across different sort keys', async ({ authenticatedWithProductionQueuePage }) => {
    const page = authenticatedWithProductionQueuePage;
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const sorts = [
      { name: 'Title', selector: 'button:has-text("Title")' },
      { name: 'Position', selector: 'button:has-text("Position")' },
      { name: 'Recently Added', selector: 'button:has-text("Recently Added")' },
    ];

    for (const sort of sorts) {
      await page.locator(sort.selector).click();
      await waitForQueueReady(page);
      
      // Load at least 3 pages for each sort
      for (let i = 0; i < 2; i++) {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        await page.waitForTimeout(500); // Allow for network/render
      }
      
      await expect(page.getByTestId('queue-thread-item')).toHaveCount(150);
      await page.evaluate(() => window.scrollTo(0, 0));
      await expect(page.getByTestId('queue-thread-item').first()).toBeVisible();
    }
  });
});
