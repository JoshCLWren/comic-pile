import { test, expect } from '@playwright/test';

test('CSP no violations', async ({ page }) => {
  const msgs: string[] = [];
  page.on('console', (m) => {
    const t = m.text();
    if (m.type() === 'error' || /CSP|Content Security|violat/i.test(t)) msgs.push(t);
  });
  page.on('pageerror', (e) => msgs.push('PAGEERROR: ' + e.message));
  await page.goto('/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  for (const r of ['/login', '/roll', '/queue', '/reading-lists']) {
    await page.goto(r, { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForTimeout(1000);
  }
  console.log('COLLECTED:', JSON.stringify(msgs));
  const violations = msgs.filter((m) => /CSP|Content Security|violat/i.test(m));
  expect(violations.length).toBe(0);
});
