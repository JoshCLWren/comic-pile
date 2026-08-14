import { chromium } from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 960, height: 926 } });
page.on('console', (m) => console.log('[console]', m.type(), m.text().slice(0, 200)));
page.on('pageerror', (e) => console.log('[pageerror]', e.message));

const loginRes = await page.request.post('http://127.0.0.1:8000/api/auth/login', {
  data: { username: 'test@example.com', password: 'testpass123' },
});
console.log('login status', loginRes.status());
const token = (await loginRes.json()).access_token;
await page.addInitScript((t) => localStorage.setItem('auth_token', t), token);

await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 15000 });
await page.waitForTimeout(3000);

const dieInfo = () => page.evaluate(() => {
  const canvases = Array.from(document.querySelectorAll('canvas'));
  const info = canvases.map((c) => {
    const r = c.getBoundingClientRect();
    const parent = c.parentElement;
    return {
      w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y),
      parentClass: parent?.className?.slice?.(0, 60) ?? null,
      insideMain: !!parent?.closest?.('#main-die-3d'),
      insideHeader: !!parent?.closest?.('#die-selector'),
    };
  });
  return { totalCanvases: canvases.length, dice3dContainers: document.querySelectorAll('.dice-3d').length, info };
});

console.log('BEFORE roll:', JSON.stringify(await dieInfo(), null, 1));

await page.click('#main-die-3d');
await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });
await page.waitForTimeout(500);
console.log('DURING rating:', JSON.stringify(await dieInfo(), null, 1));
console.log('rating view title:', await page.locator('#selected-issue-heading').textContent().catch(() => 'n/a'));

// save & continue with a rating
await page.evaluate(() => {
  const input = document.querySelector('#rating-input');
  input.value = '3';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
});

const rateResp = page.waitForResponse((r) => r.url().includes('/api/v1/rate/') && r.request().method() === 'POST', { timeout: 8000 }).catch(() => null);
await page.click('button[data-testid="save-and-continue"]');
const resp = await rateResp;
console.log('rate response:', resp ? `${resp.status()} ${(await resp.text()).slice(0, 120)}` : 'none');

await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 }).catch(() => console.log('main die not visible after rating'));
await page.waitForTimeout(3000);
console.log('AFTER rating:', JSON.stringify(await dieInfo(), null, 1));

await browser.close();
