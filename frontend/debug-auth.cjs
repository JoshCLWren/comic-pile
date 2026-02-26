const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Simulate what the fixture does
  await page.goto('http://localhost:8000/login');
  await page.evaluate(() => localStorage.clear());
  
  // Register and login
  await page.request.post('http://localhost:8000/api/auth/register', {
    data: {
      username: 'debug_test_user2',
      email: 'debug2@example.com',
      password: 'TestPass123!'
    }
  });
  
  const loginData = await page.request.post('http://localhost:8000/api/auth/login', {
    data: {
      username: 'debug_test_user2',
      password: 'TestPass123!'
    }
  });
  
  const loginResponse = await loginData.json();
  
  await page.addInitScript((token) => {
    localStorage.setItem('auth_token', token);
  }, loginResponse.access_token);
  
  await page.goto('http://localhost:8000/');
  await page.waitForTimeout(3000);
  
  // Get page HTML
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('Page text (first 500 chars):', bodyText.substring(0, 500));
  
  // Check for navigation elements
  const hasNav = await page.locator('nav').count();
  const hasMain = await page.locator('main').count();
  const hasSidebar = await page.locator('.sidebar').count();
  
  console.log('Elements - nav:', hasNav, 'main:', hasMain, '.sidebar:', hasSidebar);
  
  // Check console errors
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log('Console error:', msg.text());
    }
  });
  
  await browser.close();
})();
