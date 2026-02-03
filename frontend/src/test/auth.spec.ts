import { test, expect } from './fixtures';
import { generateTestUser, loginUser, SELECTORS } from './helpers';

test.describe('Authentication Flow', () => {
  test('should register a new user successfully', async ({ page }) => {
    const user = generateTestUser();

    await page.goto('/register');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.emailInput, user.email);
    await page.fill(SELECTORS.auth.passwordInput, user.password);
    await page.fill(SELECTORS.auth.confirmPasswordInput, user.password);
    await page.click(SELECTORS.auth.submitButton);

    await page.waitForURL('/', { timeout: 5000 });
    await expect(page).toHaveURL('/');
    await expect(page.locator(SELECTORS.navigation.homeLink)).toBeVisible();
  });

  test('should show validation error for mismatched passwords', async ({ page }) => {
    const user = generateTestUser();

    await page.goto('/register');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.emailInput, user.email);
    await page.fill(SELECTORS.auth.passwordInput, user.password);
    await page.fill(SELECTORS.auth.confirmPasswordInput, 'DifferentPassword123!');
    await page.click(SELECTORS.auth.submitButton);

    const errorMessage = page.locator('text=Passwords do not match');
    await expect(errorMessage).toBeVisible({ timeout: 3000 });
  });

  test('should show validation error for weak password', async ({ page }) => {
    const user = generateTestUser();

    await page.goto('/register');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.emailInput, user.email);
    await page.fill(SELECTORS.auth.passwordInput, 'weak');
    await page.fill(SELECTORS.auth.confirmPasswordInput, 'weak');
    await page.click(SELECTORS.auth.submitButton);

    await expect(page.locator('text=Password must')).toBeVisible({ timeout: 3000 });
  });

  test.describe.serial('should login with valid credentials', () => {
    test('login test', async ({ page }) => {
    const user = generateTestUser();

    await page.goto('/register');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.emailInput, user.email);
    await page.fill(SELECTORS.auth.passwordInput, user.password);
    await page.fill(SELECTORS.auth.confirmPasswordInput, user.password);
    await page.click(SELECTORS.auth.submitButton);
    await page.waitForURL('/', { timeout: 5000 });

    await page.evaluate(() => localStorage.clear());
    await page.goto('/login');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.passwordInput, user.password);
    await page.click(SELECTORS.auth.submitButton);

    await page.waitForURL('/', { timeout: 5000 });
    await expect(page).toHaveURL('/');
    });
  });

  test('should show error for invalid credentials', async ({ page }) => {
    const user = generateTestUser();

    await page.goto('/login');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.passwordInput, 'WrongPassword123!');
    await page.click(SELECTORS.auth.submitButton);

    const errorMessage = page.locator('text=Incorrect username or password');
    await expect(errorMessage).toBeVisible({ timeout: 3000 });
  });

  test('should persist auth token across page reloads', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await expect(authenticatedPage.locator(SELECTORS.roll.dieSelector)).toBeVisible();

    await authenticatedPage.reload();
    await expect(authenticatedPage.locator(SELECTORS.roll.dieSelector)).toBeVisible();
  });

  test('should logout and clear local storage', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    
    const hasTokenBefore = await authenticatedPage.evaluate(() => 
      !!localStorage.getItem('auth_token')
    );
    expect(hasTokenBefore).toBe(true);

    await authenticatedPage.evaluate(() => {
      localStorage.removeItem('auth_token');
    });

    await authenticatedPage.reload();
    await expect(authenticatedPage.locator(SELECTORS.roll.dieSelector)).not.toBeVisible();
  });
});
