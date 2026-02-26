const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  // Register and login
  await page.request.post('http://localhost:8000/api/auth/register', {
    data: {
      username: 'debug_test_user5',
      email: 'debug5@example.com',
      password: 'TestPass123!'
    }
  });
  
  const loginData = await page.request.post('http://localhost:8000/api/auth/login', {
    data: {
      username: 'debug_test_user5',
      password: 'TestPass123!'
    }
  });
  
  const loginResponse = await loginData.json();
  const token = loginResponse.access_token;
  console.log('Got token:', token.substring(0, 30) + '...');
  
  // Use addInitScript like the fixture
  await page.addInitScript((t) => {
    console.log('Init script running!');
    localStorage.setItem('auth_token', t);
    console.log('Token set in localStorage');
  }, token);
  
  console.log('Navigating to home page...');
  await page.goto('http://localhost:8000/');
  
  console.log('Waiting for page to load...');
  await page.waitForTimeout(5000);
  
  // Check page state
  const sidebarCount = await page.locator('.sidebar').count();
  const rootChildren = await page.locator('#root > *').count();
  const navCount = await page.locator('nav').count();
  
  console.log('Sidebar count:', sidebarCount);
  console.log('Root children:', rootChildren);
  console.log('Nav count:', navCount);
  
  // Get body text
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('Body text (first 200 chars):', bodyText.substring(0, 200));
  
  await browser.close();
})();
