import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './src/test',
  testMatch: '**/*.spec.ts',
  testIgnore: ['**/*.test.{js,jsx,ts,tsx}'],
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 1 : 4,
  timeout: 60 * 1000,
  reporter: isCI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:9000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
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
