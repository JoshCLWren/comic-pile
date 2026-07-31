import { defineConfig, devices } from '@playwright/test'

const prodBaseUrl = process.env.PROD_BASE_URL ?? process.env.BASE_URL

if (!prodBaseUrl) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run the small-account production smoke profile.')
}

export default defineConfig({
  metadata: { productionProfile: true, smallAccountSmokeProfile: true },
  testDir: './src/test',
  testMatch: 'production-profile.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 5 * 60 * 1000,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: '../playwright-report-prod-profile-small' }],
  ],
  use: {
    baseURL: prodBaseUrl,
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
      name: 'chromium-small-account-smoke',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
