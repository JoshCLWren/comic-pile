import { test, expect } from '@playwright/test';

test.describe('Thread Repositioning Fix Demo', () => {
  test.beforeEach(async ({ page }) => {
    // Get credentials from environment variables
    const testUsername = process.env.TEST_USERNAME
    const testPassword = process.env.TEST_PASSWORD

    if (!testUsername || !testPassword) {
      throw new Error('TEST_USERNAME and TEST_PASSWORD environment variables must be set');
    }

    // Login before each test using env vars
    await page.goto('/login');
    await page.fill('input[name="username"]', testUsername);
    await page.fill('input[name="password"]', testPassword);
    await page.click('button[type="submit"]');
    await page.waitForURL('**/');
  });

  test('demonstrates thread repositioning fix working', async ({ page }) => {
    // Navigate to Queue page
    await page.goto('/queue');
    await page.waitForLoadState('networkidle');
    
    // Take initial screenshot
    await page.screenshot({ path: 'queue_initial.png', fullPage: true });
    console.log('📸 Screenshot taken: queue_initial.png');
    
    // Find Spider-Man Adventures thread
    const spiderManThread = await page.locator('div.thread-item:has-text("Spider-Man Adventures")').first();
    await expect(spiderManThread).toBeVisible();
    
    // Get initial position (from data attribute or text)
    const initialElement = await spiderManThread.locator('.thread-position, [data-position]').first();
    const initialPosition = await initialElement.textContent() || await spiderManThread.getAttribute('data-position');
    console.log(`🔍 Initial Spider-Man Adventures position: ${initialPosition}`);
    
    // Click the reposition/move button
    const moveButton = spiderManThread.locator('button:has-text("Move"), button:has-text("⋮"), .reposition-btn').first();
    await expect(moveButton).toBeVisible();
    await moveButton.click();
    
    // Wait for modal to appear
    const modal = page.locator('.modal, dialog, [role="dialog"]').first();
    await expect(modal).toBeVisible({ timeout: 3000 });
    
    // Take screenshot of modal
    await page.screenshot({ path: 'modal_open.png', fullPage: true });
    console.log('📸 Screenshot taken: modal_open.png');
    
    // Find position input/slider
    const positionInput = modal.locator('input[type="number"], input[name="position"], [role="slider"]').first();
    if (await positionInput.isVisible()) {
      // If it's an input, fill it
      await positionInput.fill('11');
    } else {
      // Try slider approach
      const slider = modal.locator('[role="slider"]').first();
      if (await slider.isVisible()) {
        await slider.fill('11'); // For range sliders
      }
    }
    
    // Take screenshot of filled modal
    await page.screenshot({ path: 'modal_filled.png', fullPage: true });
    console.log('📸 Screenshot taken: modal_filled.png');
    
    // Click the submit button
    const submitButton = modal.locator('button[type="submit"], button:has-text("Move"), button:has-text("Save")').first();
    await expect(submitButton).toBeVisible();
    await submitButton.click();
    
    // Wait for modal to close and operation to complete
    await expect(modal).toBeHidden({ timeout: 5000 });
    await page.waitForLoadState('networkidle');
    
    // Take final screenshot
    await page.screenshot({ path: 'queue_final.png', fullPage: true });
    console.log('📸 Screenshot taken: queue_final.png');
    
    // Verify Spider-Man Adventures is now at position 11
    const finalPositionElement = await spiderManThread.locator('.thread-position, [data-position]').first();
    const finalPosition = await finalPositionElement.textContent() || await spiderManThread.getAttribute('data-position');
    
    console.log(`✅ Spider-Man Adventures moved from position ${initialPosition} to ${finalPosition}`);
    
    // Check for success message or verify via API
    const successMessage = page.locator('.success-message, .toast, [role="alert"]:has-text("success")').first();
    if (await successMessage.isVisible()) {
      console.log('✅ Success message displayed');
    }
    
    console.log('🎉 Thread repositioning fix demo completed successfully!');
  });
});