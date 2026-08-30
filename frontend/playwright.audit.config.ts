import { defineConfig, devices } from '@playwright/test'

const isCI = !!process.env.CI

export default defineConfig({
  testDir: './src/test',
  testMatch: '**/*.audit.ts',
  fullyParallel: false,
  forbidOnly: isCI,
  retries: 0,
  workers: 1,
  timeout: 6 * 60 * 1000,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: process.env.BASE_URL || 'http://localhost:9000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 30000,
    navigationTimeout: 30000,
    reducedMotion: 'reduce',
  },
  expect: {
    timeout: 15000,
  },
  projects: [
    {
      name: 'chromium-ui-audit',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
