import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

test('debug 4350 reload state', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  page.on('console', (msg) => console.log('CONSOLE', msg.type(), msg.text().slice(0, 300)))
  page.on('pageerror', (err) => console.log('PAGEERROR', err.message.slice(0, 300)))
  page.on('response', (res) => {
    if (res.url().includes('/api/v2/threads') || res.url().includes('/api/v2/roll')) {
      console.log('RESP', res.status(), res.request().method(), res.url().replace(/^.*\/api/, '/api'))
    }
  })
  await createThread(page, {
    title: 'Debug Series',
    format: 'Comic',
    issues_remaining: 3,
    total_issues: 3,
  })
  await gotoRollPage(page)
  console.log('BEFORE CLICK', (await page.locator('body').innerText()).slice(0, 600))
  await page.locator('#main-die-3d').click()
  await page.waitForTimeout(3000)
  console.log('AFTER CLICK', (await page.locator('body').innerText()).slice(0, 900))
  console.log('STORAGE', await page.evaluate(() => JSON.stringify(localStorage)))
  await page.reload()
  await page.waitForTimeout(5000)
  console.log('AFTER RELOAD', (await page.locator('body').innerText()).slice(0, 900))
  console.log('STORAGE2', await page.evaluate(() => JSON.stringify(localStorage)))
})
