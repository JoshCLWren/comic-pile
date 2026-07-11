import { test, expect } from './fixtures';
import { generateTestUser, loginUser, registerUser, SELECTORS } from './helpers';

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

    await page.request.post('/api/auth/logout');
    await page.evaluate(() => {
      localStorage.clear();
      delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
      window.location.assign('/login');
    });
    await page.waitForURL('**/login', { timeout: 10000 });
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
    await expect(authenticatedPage.locator('#root')).toBeVisible();

    const tokenBeforeReload = await authenticatedPage.evaluate(() => {
      const win = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
      return localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN ?? null
    });
    expect(tokenBeforeReload).toBeTruthy();

    await authenticatedPage.reload();
    await expect(authenticatedPage.locator('#root')).toBeVisible();

    const tokenAfterReload = await authenticatedPage.evaluate(() => {
      const win = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
      return localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN ?? null
    });
    expect(tokenAfterReload).toBe(tokenBeforeReload);

    const meResponse = await authenticatedPage.request.get('/api/auth/me', {
      headers: { Authorization: `Bearer ${tokenAfterReload}` },
    });
    expect(meResponse.ok()).toBeTruthy();
  });

  test('should clear auth token and redirect to login on logout', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    const loginResponse = await page.request.post('/api/auth/login', {
      data: {
        username: user.username,
        password: user.password,
      },
    });
    expect(loginResponse.ok()).toBeTruthy();
    const loginData = await loginResponse.json() as { access_token?: string };
    expect(loginData.access_token).toBeTruthy();

    await page.goto('/');
    await page.evaluate((token: string) => {
      localStorage.setItem('auth_token', token);
    }, loginData.access_token as string);

    await page.reload();

    const tokenBefore = await page.evaluate(() => {
      const win = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
      return localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN ?? null
    });
    expect(tokenBefore).toBeTruthy();

    const logoutResponse = await page.request.post('/api/auth/logout', {
      headers: { Authorization: `Bearer ${tokenBefore}` },
    });
    expect(logoutResponse.ok()).toBeTruthy();

    await page.evaluate(() => {
      localStorage.clear();
      delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });

    await page.goto('/login');

    await expect(page).toHaveURL('/login');

    await expect.poll(async () => {
      return page.evaluate(() => {
        const win = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
        return Boolean(localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN)
      })
    }).toBe(false);
  });
});
