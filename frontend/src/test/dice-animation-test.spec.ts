import { test, expect } from '@playwright/test';

/**
 * Test to observe dice animation on second consecutive roll
 * This reproduces the reported issue where the dice animation 
 * doesn't play on the second consecutive roll in production.
 */

test.describe('Dice Animation Second Roll Issue', () => {
  const PROD_URL = process.env.PROD_BASE_URL || 'https://app-production-72b9.up.railway.app';

  test('observe dice animation on first and second roll', async ({ page }) => {
    // Create a new user for this test
    const nonce = `${Date.now()}_${Math.floor(Math.random() * 1_000_000)}`;
    const user = {
      username: `anim_test_${nonce}`,
      email: `anim_test_${nonce}@example.com`,
      password: 'TestPass123!',
    };

    console.log('Creating test user...');
    const registerResponse = await page.request.post(`${PROD_URL}/api/auth/register`, {
      data: user,
      timeout: 15000,
    });
    expect(registerResponse.ok()).toBeTruthy();

    const loginResponse = await page.request.post(`${PROD_URL}/api/auth/login`, {
      data: { username: user.username, password: user.password },
      timeout: 15000,
    });
    expect(loginResponse.ok()).toBeTruthy();

    const loginData = await loginResponse.json();
    const token = loginData.access_token;

    // Seed threads
    console.log('Seeding threads...');
    for (const title of ['Animation Test A', 'Animation Test B', 'Animation Test C']) {
      const response = await page.request.post(`${PROD_URL}/api/threads/`, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        data: { title, format: 'Comic', issues_remaining: 5 },
      });
      expect(response.ok()).toBeTruthy();
    }

    // Navigate to roll page with auth
    await page.addInitScript((authToken) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    console.log('Navigating to roll page...');
    await page.goto(PROD_URL);
    await page.waitForLoadState('networkidle');

    // Wait for the main die to be visible
    const mainDie = page.locator('#main-die-3d');
    await expect(mainDie).toBeVisible();
    console.log('Main die is visible');

    // Add console listener to catch any errors
    page.on('console', (msg) => {
      console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`);
    });

    // Add page error listener
    page.on('pageerror', (error) => {
      console.log(`[Browser Error] ${error.message}`);
    });

    // FIRST ROLL
    console.log('\n=== FIRST ROLL ===');
    console.log('Clicking die for first roll...');
    
    // Capture animation state before first click
    const beforeFirstClick = await mainDie.evaluate((el) => {
      return {
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      };
    });
    console.log('Before first click:', beforeFirstClick);

    await mainDie.click();
    
    // Wait a moment for animation to start
    await page.waitForTimeout(100);
    
    const afterFirstClick = await mainDie.evaluate((el) => {
      return {
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      };
    });
    console.log('After first click (100ms):', afterFirstClick);

    // Wait for rating view to appear (first roll complete)
    const ratingInput = page.locator('#rating-input');
    await ratingInput.waitFor({ timeout: 15000 });
    console.log('Rating view visible after first roll');

    // Submit rating to go back to roll view
    console.log('Submitting rating...');
    await page.click('button:has-text("Save & Continue")');
    
    // Wait to return to roll view
    await expect(mainDie).toBeVisible({ timeout: 10000 });
    console.log('Back to roll view');
    
    // Wait a moment for state to settle
    await page.waitForTimeout(500);

    // SECOND ROLL - This is where the issue reportedly occurs
    console.log('\n=== SECOND ROLL ===');
    console.log('Clicking die for second roll...');
    
    const beforeSecondClick = await mainDie.evaluate((el) => {
      return {
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      };
    });
    console.log('Before second click:', beforeSecondClick);

    await mainDie.click();
    
    // Wait a moment for animation to potentially start
    await page.waitForTimeout(100);
    
    const afterSecondClick = await mainDie.evaluate((el) => {
      return {
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      };
    });
    console.log('After second click (100ms):', afterSecondClick);

    // Check if animation class was applied
    if (!afterSecondClick.hasRollingClass) {
      console.error('ERROR: dice-state-rolling class NOT applied on second roll!');
    } else {
      console.log('SUCCESS: dice-state-rolling class applied on second roll');
    }

    // Wait for rating view (second roll complete)
    try {
      await ratingInput.waitFor({ timeout: 15000 });
      console.log('Rating view visible after second roll');
    } catch (e) {
      console.error('ERROR: Rating view did not appear after second roll');
      throw e;
    }

    // THIRD ROLL - Test one more time
    console.log('\n=== THIRD ROLL ===');
    console.log('Clicking die for third roll...');
    
    await page.click('button:has-text("Save & Continue")');
    await expect(mainDie).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(500);

    const beforeThirdClick = await mainDie.evaluate((el) => {
      return {
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      };
    });
    console.log('Before third click:', beforeThirdClick);

    await mainDie.click();
    await page.waitForTimeout(100);
    
    const afterThirdClick = await mainDie.evaluate((el) => {
      return {
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      };
    });
    console.log('After third click (100ms):', afterThirdClick);

    if (!afterThirdClick.hasRollingClass) {
      console.error('ERROR: dice-state-rolling class NOT applied on third roll!');
    } else {
      console.log('SUCCESS: dice-state-rolling class applied on third roll');
    }
  });
});
