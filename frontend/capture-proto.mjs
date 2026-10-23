import { chromium } from '@playwright/test'

const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 })
const res = await page.request.post('http://127.0.0.1:8000/api/v1/auth/login', {
  data: { username: 'testuser', password: 'testpass123' },
})
const body = await res.json()
await page.addInitScript((token) => {
  localStorage.setItem('auth_token', token)
}, body.access_token)
await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })
await page.getByTestId('main-die-3d').click()
await page.waitForTimeout(4000)
console.log('url', page.url())
console.log((await page.locator('body').innerText()).slice(0, 2200))
await page.screenshot({ path: '/tmp/opencode/proto-rolled.png', fullPage: false })
await browser.close()
