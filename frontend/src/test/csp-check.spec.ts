import { test, expect } from '@playwright/test';

test('CSP no violations', async ({ page }) => {
  const msgs: string[] = [];
  page.on('console', m => { if (m.type() === 'error' || /CSP|Content Security/i.test(m.text())) msgs.push(m.text()); });
  page.on('pageerror', e => msgs.push('PAGEERROR: ' + e.message));
  await page.goto('/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  console.log('COLLECTED:', JSON.stringify(msgs));
  // also navigate to a few routes
  for (const r of ['/login', '/roll', '/queue']) {
    await page.goto(r, { waitUntil: 'networkidle' }).catch(()=>{});
    await page.waitForTimeout(1000);
  }
  console.log('FINAL:', JSON.stringify(msgs));
  expect(msgs.filter(m=>/CSP|Content Security|violat/i.test(m))).length).toBe(0);
});
