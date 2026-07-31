import { defineConfig, devices } from '@playwright/test'

const prodBaseUrl = process.env.PROD_BASE_URL ?? process.env.BASE_URL
const storageState = process.env.PROD_PROFILE_STORAGE_STATE

if (!prodBaseUrl) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run the real-user production profile.')
}

export default defineConfig({
  metadata: { productionRealUserProfile: true },
  testDir: './src/test',
  testMatch: 'production-profile-real-user.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 20 * 60 * 1000,
  outputDir: '../test-results-prod-profile',
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: '../playwright-report-prod-profile' }],
  ],
  use: {
    baseURL: prodBaseUrl,
    ...(storageState ? { storageState } : {}),
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
      name: 'chromium-real-user-profile',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
