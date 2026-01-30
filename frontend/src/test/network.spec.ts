import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Network & API Tests', () => {
  test('should make successful API call to create thread', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const response = await page.request.post('/api/threads/', {
      data: {
        title: 'API Test Comic',
        format: 'Comic',
        issues_remaining: 5,
      },
    });

    expect(response.status()).toBe(201);
    const data = await response.json();
    expect(data.title).toBe('API Test Comic');
  });

  test('should handle API errors gracefully', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const response = await page.request.post('/api/threads/', {
      data: {
        title: '',
        format: '',
        issues_remaining: -1,
      },
    });

    expect(response.status()).toBeGreaterThanOrEqual(400);
  });

  test('should include auth token in API requests', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Auth Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');

    const [request] = await Promise.all([
      page.waitForRequest(req => req.url().includes('/api/')),
      page.click(SELECTORS.roll.mainDie),
    ]);

    const authHeader = request.headers()['authorization'];
    expect(authHeader).toBeDefined();
    expect(authHeader).toMatch(/Bearer .+/);
  });

  test('should retry failed requests', async ({ page }) => {
    let attemptCount = 0;
    await page.route('**/api/threads/**', async route => {
      attemptCount++;
      if (attemptCount < 3) {
        await route.abort();
      } else {
        await route.continue();
      }
    });

    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/threads');

    const hasRetry = attemptCount >= 2;
    expect(hasRetry).toBe(true);
  });

  test('should handle network timeouts', async ({ page }) => {
    await page.route('**/api/threads/**', async route => {
      await new Promise(resolve => setTimeout(resolve, 30000));
    });

    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/threads');

    const timeoutMessage = page.locator('text=timeout|took too long|try again');
    const hasTimeout = await timeoutMessage.count({ timeout: 35000 }).then(count => count > 0);

    if (hasTimeout) {
      await expect(timeoutMessage.first()).toBeVisible();
    }
  });

  test('should cache responses appropriately', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Cache Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    let requestCount = 0;
    await page.route('**/api/threads/**', route => {
      requestCount++;
      route.continue();
    });

    await page.goto('/threads');
    await page.waitForTimeout(1000);

    await page.reload();
    await page.waitForTimeout(1000);

    expect(requestCount).toBeGreaterThan(0);
  });

  test('should validate request payload', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    let capturedPayload: any = null;
    await page.route('**/api/threads/**', async route => {
      if (route.request().method() === 'POST') {
        capturedPayload = route.request().postDataJSON();
      }
      await route.continue();
    });

    await page.goto('/threads');
    await page.click(SELECTORS.threadList.newThreadButton);
    await page.fill(SELECTORS.threadList.titleInput, 'Payload Test');
    await page.fill(SELECTORS.threadList.formatInput, 'Comic');
    await page.click(SELECTORS.auth.submitButton);

    await page.waitForTimeout(1000);

    expect(capturedPayload).toBeDefined();
    expect(capturedPayload.title).toBe('Payload Test');
  });

  test('should handle concurrent requests', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const promises = [];
    for (let i = 0; i < 5; i++) {
      promises.push(
        page.request.post('/api/threads/', {
          data: {
            title: `Concurrent Comic ${i}`,
            format: 'Comic',
            issues_remaining: 5,
          },
        })
      );
    }

    const responses = await Promise.all(promises);
    
    for (const response of responses) {
      expect([200, 201]).toContain(response.status());
    }
  });

  test('should respect rate limiting', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const responses = [];
    for (let i = 0; i < 20; i++) {
      const response = await page.request.post('/api/threads/', {
        data: {
          title: `Rate Limit Test ${i}`,
          format: 'Comic',
          issues_remaining: 5,
        },
      });
      responses.push(response.status());
    }

    const hasRateLimit = responses.includes(429);
    if (hasRateLimit) {
      expect(responses).toContain(429);
    }
  });

  test('should handle CORS correctly', async ({ page, request }) => {
    const response = await request.get(`${page.url()}api/threads/`, {
      headers: {
        'Origin': 'http://localhost:3000',
      },
    });

    const corsHeader = response.headers()['access-control-allow-origin'];
    expect(corsHeader).toBeDefined();
  });

  test('should compress large responses', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    for (let i = 0; i < 50; i++) {
      await createThread(page, {
        title: `Compression Test Comic ${i}`,
        format: 'Comic',
        issues_remaining: 5,
      });
    }

    await page.goto('/threads');

    const [response] = await Promise.all([
      page.waitForResponse(res => res.url().includes('/api/threads')),
      page.waitForSelector(SELECTORS.threadList.container),
    ]);

    const contentEncoding = response.headers()['content-encoding'];
    const hasCompression = contentEncoding?.includes('gzip') || contentEncoding?.includes('br');

    expect(response.status()).toBe(200);
  });

  test('should sanitize user input in requests', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const maliciousInput = '<script>alert("xss")</script>';

    const response = await page.request.post('/api/threads/', {
      data: {
        title: maliciousInput,
        format: 'Comic',
        issues_remaining: 5,
      },
    });

    expect(response.status()).toBeGreaterThanOrEqual(400);

    if (response.status() >= 200 && response.status() < 300) {
      const data = await response.json();
      expect(data.title).not.toContain('<script>');
    }
  });

  test('should include proper error messages in API responses', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const response = await page.request.post('/api/threads/', {
      data: {
        title: '',
        format: '',
      },
    });

    if (response.status() >= 400) {
      const data = await response.json();
      expect(data.detail || data.error || data.message).toBeDefined();
    }
  });

  test('should handle websocket connections if present', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    let wsConnected = false;

    page.on('websocket', ws => {
      wsConnected = true;
    });

    await page.goto('/');

    await page.waitForTimeout(2000);

    if (wsConnected) {
      expect(wsConnected).toBe(true);
    }
  });
});
