import { chromium } from '@playwright/test'

const baseUrl = process.env.PROD_BASE_URL
const username = process.env.PROD_E2E_ACCOUNT_USERNAME
const email = process.env.PROD_E2E_ACCOUNT_EMAIL
const password = process.env.PROD_E2E_ACCOUNT_PASSWORD
const output = process.env.PROD_PROFILE_STORAGE_STATE

for (const [name, value] of Object.entries({
  PROD_BASE_URL: baseUrl,
  PROD_E2E_ACCOUNT_USERNAME: username,
  PROD_E2E_ACCOUNT_EMAIL: email,
  PROD_E2E_ACCOUNT_PASSWORD: password,
  PROD_PROFILE_STORAGE_STATE: output,
})) {
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`)
  }
}

const browser = await chromium.launch()
try {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(`${baseUrl}/register`, { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByLabel('Confirm Password').fill(password)
  await page.getByRole('button', { name: 'Create Account' }).click()
  await page.waitForURL((url) => url.pathname === '/', { timeout: 30_000 })
  await page.locator('[data-app-shell-ready="true"]').waitFor({ state: 'visible', timeout: 30_000 })
  await context.storageState({ path: output })
} finally {
  await browser.close()
}
