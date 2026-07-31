import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

const prodBaseUrl = process.env.PROD_BASE_URL ?? process.env.BASE_URL
const storageState = process.env.PROD_PROFILE_STORAGE_STATE

if (!prodBaseUrl) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run the production profile.')
}

if (!storageState) {
  throw new Error(
    'Set PROD_PROFILE_STORAGE_STATE to a Playwright storage-state JSON file for the full production account.',
  )
}

if (!existsSync(storageState)) {
  throw new Error(`PROD_PROFILE_STORAGE_STATE does not exist: ${storageState}`)
}

export default defineConfig({
  metadata: {
    productionProfile: true,
    sourceHarApiRequests: 198,
    sourceHarCapturedAt: '2026-07-30T15:25:46.699-05:00',
  },
  testDir: './src/test',
  testMatch: 'production-profile.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 10 * 60 * 1000,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: '../playwright-report-prod-profile' }],
  ],
  use: {
    baseURL: prodBaseUrl,
    storageState,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },
  expect: {
    timeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
