const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  // Capture ALL console messages
  page.on('console', msg => {
    const type = msg.type();
    const text = msg.text();
    if (type === 'error' || type === 'warn' || text.includes('Init') || text.includes('Token')) {
      console.log(`Browser Console [${type}]:`, text);
    }
  });
  
  // Also capture page errors
  page.on('pageerror', error => {
    console.log('Page Error:', error.message);
    console.log('Stack:', error.stack);
  });
  
  // Register and login
  await page.request.post('http://localhost:8000/api/auth/register', {
    data: {
      username: 'debug_test_user6',
      email: 'debug6@example.com',
      password: 'TestPass123!'
    }
  });
  
  const loginData = await page.request.post('http://localhost:8000/api/auth/login', {
    data: {
      username: 'debug_test_user6',
      password: 'TestPass123!'
    }
  });
  
  const loginResponse = await loginData.json();
  
  // Use addInitScript
  await page.addInitScript((token) => {
    console.log('=== INIT SCRIPT START ===');
    try {
      localStorage.setItem('auth_token', token);
      console.log('Token successfully set in localStorage');
    } catch (e) {
      console.error('Error setting localStorage:', e);
    }
    console.log('=== INIT SCRIPT END ===');
  }, loginResponse.access_token);
  
  console.log('Navigating to http://localhost:8000/');
  await page.goto('http://localhost:8000/', { waitUntil: 'networkidle' });
  
  console.log('Waiting 5 seconds...');
  await page.waitForTimeout(5000);
  
  // Check what's in the DOM
  const rootHTML = await page.locator('#root').innerHTML();
  console.log('Root HTML length:', rootHTML.length);
  console.log('Root HTML content:', rootHTML.substring(0, 500));
  
  await browser.close();
})();
