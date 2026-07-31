import { defineConfig, devices } from '@playwright/test'

const prodBaseUrl = process.env.PROD_BASE_URL ?? process.env.BASE_URL

if (!prodBaseUrl) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run the production profile.')
}

export default defineConfig({
  metadata: { productionProfile: true },
  testDir: './src/test',
  testMatch: 'production-profile.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  // The journey may take longer during production cold starts, while the
  // individual request budget remains capped separately at five seconds.
  timeout: 300 * 1000,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: '../playwright-report-prod-profile' }],
  ],
  use: {
    baseURL: prodBaseUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 30000,
    navigationTimeout: 30000,
  },
  expect: {
    timeout: 15000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
