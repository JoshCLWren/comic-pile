import { chromium } from '@playwright/test';
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] });
const files = ['index.html','roll.html','queue.html','login.html','forgot-password.html','reset-password.html','reading-lists.html','analytics.html'];
for (const f of files) {
  const page = await browser.newPage();
  const msgs = [];
  page.on('console', m => { if (m.type()==='error' || /CSP|Content Security|eval/i.test(m.text())) msgs.push(m.type()+': '+m.text()); });
  page.on('pageerror', e => msgs.push('PAGEERROR: '+e.message));
  try {
    await page.goto('http://127.0.0.1:8125/'+f, { waitUntil: 'domcontentloaded', timeout: 15000 });
  } catch(e) { msgs.push('NAV: '+e.message); }
  await page.waitForTimeout(1500);
  console.log(f, '=>', msgs.length ? msgs.join(' | ') : 'OK');
  await page.close();
}
await browser.close();
console.log('done');
