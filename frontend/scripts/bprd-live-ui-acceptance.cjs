const { chromium } = require('@playwright/test')
const fs = require('node:fs')

const baseUrl = process.env.BASE_URL
const token = process.env.ACCESS_TOKEN
const planId = process.env.PLAN_ID
const planUrl = `${baseUrl}/continuity-plans/${planId}`

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } })
  const failures = []

  page.on('pageerror', error => failures.push(`pageerror: ${error.message}`))
  page.on('console', msg => {
    if (msg.type() === 'error') failures.push(`console: ${msg.text()}`)
  })

  await page.addInitScript(accessToken => {
    localStorage.setItem('auth_token', accessToken)
    window.__COMIC_PILE_ACCESS_TOKEN = accessToken
  }, token)

  await page.goto(planUrl, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByRole('button', { name: 'Browse sources' }).waitFor({ state: 'visible', timeout: 30000 })
  await page.screenshot({ path: '../bprd-live-ui-v3-before.png', fullPage: true })

  await page.getByRole('button', { name: 'Browse sources' }).click()
  const source = page.getByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Omnibus Vol\. 3/i })
  await source.waitFor({ state: 'visible', timeout: 30000 })
  await source.click()
  await page.getByText('Missing · choose whether to add').first().waitFor({ state: 'visible', timeout: 30000 })

  const addBoxes = page.getByRole('checkbox', { name: 'Add' })
  if (await addBoxes.count() !== 15) throw new Error(`Expected 15 Add choices, got ${await addBoxes.count()}`)

  for (let i = 0; i < 15; i++) {
    const unchecked = page.locator('input[type="checkbox"]:not(:checked)')
    const expectedUnchecked = 15 - i
    if (await unchecked.count() !== expectedUnchecked) {
      throw new Error(`Expected ${expectedUnchecked} unchecked choices before click ${i + 1}, got ${await unchecked.count()}`)
    }
    const responsePromise = page.waitForResponse(
      response => response.url().includes('/adoption-plan') && response.request().method() === 'POST',
      { timeout: 30000 },
    )
    await unchecked.first().click()
    const response = await responsePromise
    if (!response.ok()) throw new Error(`adoption-plan failed with status ${response.status()}`)
    await page.waitForFunction(
      expected => document.querySelectorAll('input[type="checkbox"]:checked').length === expected,
      i + 1,
      { timeout: 30000 },
    )
  }

  const commitButton = page.getByRole('button', { name: 'Add selected material' })
  await commitButton.waitFor({ state: 'visible' })
  if (await commitButton.isDisabled()) throw new Error('Add selected material stayed disabled after all 15 opt-ins')

  const reloadPromise = page.waitForEvent('framenavigated', {
    predicate: frame => frame === page.mainFrame() && frame.url() === planUrl,
    timeout: 30000,
  })
  const commitResponsePromise = page.waitForResponse(
    response => response.url().includes('/adoption-commit') && response.request().method() === 'POST',
    { timeout: 30000 },
  )
  await commitButton.click()
  const commitResponse = await commitResponsePromise
  if (!commitResponse.ok()) throw new Error(`adoption-commit failed with status ${commitResponse.status()}`)
  await reloadPromise

  if (page.url() !== planUrl) throw new Error(`Post-adoption reload left the plan: ${page.url()}`)
  await page.getByRole('button', { name: 'Browse sources' }).waitFor({ state: 'visible', timeout: 30000 })
  await page.screenshot({ path: '../bprd-live-ui-v3-committed.png', fullPage: true })

  await page.getByRole('button', { name: 'Browse sources' }).click()
  const sourceAgain = page.getByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Omnibus Vol\. 3/i })
  await sourceAgain.waitFor({ state: 'visible', timeout: 30000 })
  await sourceAgain.click()
  await page.getByText('Already in ComicPile').first().waitFor({ state: 'visible', timeout: 30000 })

  const existingCount = await page.getByText('Already in ComicPile').count()
  if (existingCount !== 15) throw new Error(`Expected 15 existing entries after reload, got ${existingCount}`)
  if (await page.getByRole('checkbox', { name: 'Add' }).count() !== 0) throw new Error('Add choices remained after reload')
  await page.screenshot({ path: '../bprd-live-ui-v3-reloaded.png', fullPage: true })

  fs.writeFileSync('../bprd-live-ui-v3-browser.json', JSON.stringify({
    plan_id: Number(planId),
    existing_after_reload: existingCount,
    browser_failures: failures,
  }, null, 2))

  if (failures.length) throw new Error(`Browser console/page failures: ${failures.join(' | ')}`)
  await browser.close()
}

main().catch(error => {
  console.error(error)
  process.exit(1)
})
