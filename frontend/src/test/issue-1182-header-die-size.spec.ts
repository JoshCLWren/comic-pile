import { test, expect } from './fixtures';
import { setRangeInput } from './helpers';

test.describe('Issue #1182: duplicate full-size die after rating', () => {
  test('header die preview keeps its 40px size when the 3D chunk loads during the rating view', async ({ page }) => {
    test.setTimeout(60000);
    const timestamp = Date.now();
    const username = `issue1182_${timestamp}_${Math.random().toString(36).slice(2, 8)}@example.com`;
    const password = 'TestPass123!';

    const registerResponse = await page.request.post('/api/auth/register', {
      data: { username, email: username, password },
    });
    expect(registerResponse.ok()).toBeTruthy();

    const loginResponse = await page.request.post('/api/auth/login', {
      data: { username, password },
    });
    expect(loginResponse.ok()).toBeTruthy();
    const loginData = (await loginResponse.json()) as { access_token: string };
    const token = loginData.access_token;

    const csrfResponse = await page.request.get('/api/auth/csrf', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(csrfResponse.ok()).toBeTruthy();
    const csrfData = (await csrfResponse.json()) as { csrf_token: string };
    const authHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-CSRF-Token': csrfData.csrf_token,
    };

    const threadResponse = await page.request.post('/api/threads/', {
      data: { title: `Issue 1182 thread ${timestamp}`, format: 'comic', issues_remaining: 5 },
      headers: authHeaders,
    });
    expect(threadResponse.ok()).toBeTruthy();
    const threadData = (await threadResponse.json()) as { id: number };
    const issuesResponse = await page.request.post(`/api/v1/threads/${threadData.id}/issues`, {
      data: { issue_range: '1-10' },
      headers: authHeaders,
    });
    expect(issuesResponse.ok()).toBeTruthy();

    await page.addInitScript((t) => localStorage.setItem('auth_token', t), token);

    // Delay the lazy Dice3D chunk so it resolves while the rating view is open
    // and the header die preview is hidden. Without the resize fix it would mount
    // at 0x0, fall back to 200x200, and render a full-size die once revealed.
    await page.route('**/assets/Dice3D-*.js', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      await route.continue();
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
    await page.click('#main-die-3d');
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Let the delayed Dice3D chunk resolve while the header die is hidden.
    // Wait for the header canvas to be attached to the DOM (present) instead of a fixed timeout,
    // which directly proves the chunk loaded and the header Dice3D mounted.
    // The canvas will be hidden while the rating view is open, so we wait for 'attached' state.
    await page.waitForSelector('header canvas', { state: 'attached', timeout: 10000 });

    await setRangeInput(page, '#rating-input', '4');
    const rateResponse = page.waitForResponse(
      (response) => response.url().includes('/api/rate/') && response.request().method() === 'POST',
    );
    await page.click('button[data-testid="save-and-continue"]');
    await rateResponse;

    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
    // Wait for header die to settle at 40x40 instead of a fixed timeout
    await page.waitForFunction(() => {
      const canvases = Array.from(document.querySelectorAll('header canvas'));
      return canvases.length > 0 && canvases.every((canvas) => {
        const rect = canvas.getBoundingClientRect();
        return Math.round(rect.width) === 40 && Math.round(rect.height) === 40;
      });
    }, { timeout: 5000 });

    const headerCanvasSizes = await page.evaluate(() => {
      const canvases = Array.from(document.querySelectorAll('header canvas'));
      return canvases.map((canvas) => {
        const rect = canvas.getBoundingClientRect();
        return { w: Math.round(rect.width), h: Math.round(rect.height) };
      });
    });

    // The header "Ladder" preview die must be sized to its 40x40 container,
    // never the mount-time 200x200 fallback.
    expect(headerCanvasSizes).toEqual([{ w: 40, h: 40 }]);
  });
});
