const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  // Register and login
  await page.request.post('http://localhost:8000/api/auth/register', {
    data: {
      username: 'debug_test_user4',
      email: 'debug4@example.com',
      password: 'TestPass123!'
    }
  });
  
  const loginData = await page.request.post('http://localhost:8000/api/auth/login', {
    data: {
      username: 'debug_test_user4',
      password: 'TestPass123!'
    }
  });
  
  const loginResponse = await loginData.json();
  const token = loginResponse.access_token;
  console.log('Token:', token.substring(0, 50) + '...');
  
  // Test if token works with collections API
  const response = await page.request.get('http://localhost:8000/api/v1/collections/', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  console.log('Collections response status:', response.status());
  const data = await response.json();
  console.log('Collections data:', JSON.stringify(data).substring(0, 200));
  
  // Now test via browser localStorage
  await page.goto('http://localhost:8000/');
  await page.evaluate((t) => {
    localStorage.setItem('auth_token', t);
  }, token);
  
  await page.waitForTimeout(1000);
  
  // Reload to trigger API calls
  await page.reload();
  await page.waitForTimeout(3000);
  
  // Check if sidebar is visible
  const sidebarCount = await page.locator('.sidebar').count();
  console.log('Sidebar count after reload:', sidebarCount);
  
  await browser.close();
})();
