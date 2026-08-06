import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PROD_BASE_URL ?? process.env.BASE_URL
const storageState = process.env.PROD_PROFILE_STORAGE_STATE

if (!baseURL) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run the production performance probe.')
}

if (!storageState || !existsSync(storageState)) {
  throw new Error('Set PROD_PROFILE_STORAGE_STATE to an existing Playwright storage-state file.')
}

export default defineConfig({
  testDir: './src/test',
  testMatch: 'production-performance.spec.ts',
  fullyParallel: false,
  retries: 1,
  workers: 1,
  timeout: 2 * 60 * 1000,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: '../playwright-report-prod-performance' }],
  ],
  use: {
    baseURL,
    storageState,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  expect: {
    timeout: 60_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
