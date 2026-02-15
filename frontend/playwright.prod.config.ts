import { defineConfig, devices } from '@playwright/test';

const prodBaseUrl = process.env.PROD_BASE_URL ?? process.env.BASE_URL;

if (!prodBaseUrl) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run prod smoke tests.');
}

export default defineConfig({
  testDir: './src/test',
  testMatch: 'prod-smoke.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 45 * 1000,
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../playwright-report-prod' }]],
  use: {
    baseURL: prodBaseUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 30000,
    navigationTimeout: 30000,
  },
  expect: {
    timeout: 10000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

