const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Capture console messages
  page.on('console', msg => {
    console.log(`Console [${msg.type()}]:`, msg.text());
  });
  
  // Capture network errors
  page.on('response', response => {
    if (response.status() >= 400) {
      console.log(`Network Error: ${response.url()} - ${response.status()}`);
    }
  });
  
  // Simulate what the fixture does
  await page.goto('http://localhost:8000/login');
  await page.evaluate(() => localStorage.clear());
  
  // Register and login
  await page.request.post('http://localhost:8000/api/auth/register', {
    data: {
      username: 'debug_test_user3',
      email: 'debug3@example.com',
      password: 'TestPass123!'
    }
  });
  
  const loginData = await page.request.post('http://localhost:8000/api/auth/login', {
    data: {
      username: 'debug_test_user3',
      password: 'TestPass123!'
    }
  });
  
  const loginResponse = await loginData.json();
  console.log('Got token, setting in localStorage');
  
  await page.addInitScript((token) => {
    localStorage.setItem('auth_token', token);
  }, loginResponse.access_token);
  
  console.log('Navigating to home page...');
  await page.goto('http://localhost:8000/');
  
  console.log('Waiting 5 seconds for page to load...');
  await page.waitForTimeout(5000);
  
  // Check page state
  const url = page.url();
  const title = await page.title();
  console.log('Final URL:', url);
  console.log('Page title:', title);
  
  const hasRoot = await page.locator('#root').count();
  const hasChildren = await page.locator('#root > *').count();
  console.log('Root element count:', hasRoot);
  console.log('Root children count:', hasChildren);
  
  await browser.close();
})();
