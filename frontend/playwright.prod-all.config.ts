import { defineConfig, devices } from '@playwright/test';

const prodBaseUrl = process.env.PROD_BASE_URL ?? process.env.BASE_URL;

if (!prodBaseUrl) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run all E2E tests against production.');
}

export default defineConfig({
  testDir: './src/test',
  testMatch: '**/*.spec.ts',
  // Same ignore patterns as main config (playwright.config.ts)
  testIgnore: [
    '**/*.test.{js,jsx,ts,tsx}', // Test utility files
    '**/prod-smoke.spec.ts', // Use playwright.prod.config.ts for prod smoke tests
    '**/thread-repositioning-fix.spec.ts', // Requires TEST_USERNAME and TEST_PASSWORD env vars
  ],
  fullyParallel: false,
  retries: 10,
  workers: process.env.WORKERS ? parseInt(process.env.WORKERS) : 10,
  timeout: 45 * 1000,
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../playwright-report-prod-all' }]],
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
