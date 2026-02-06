import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './src/test',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 6 : 4,
  workers: process.env.CI ? 2 : 4,  // Reduced from 6 to 4 to reduce rate limiting pressure
  timeout: 60 * 1000, // 60 seconds per test (increased from default 30s for CI)
  reporter: process.env.CI
    ? [
        ['github'],
        ['list', { printSteps: true }],
        ['html', { open: 'never', outputFolder: '../playwright-report' }],
        ['json', { outputFile: '../test-results/results.json' }],
      ]
    : [
        ['html', { open: 'never', outputFolder: '../playwright-report' }],
        ['json', { outputFile: '../test-results/results.json' }],
        ['list'],
      ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 60000,
    navigationTimeout: 60000,
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
  webServer: {
    command: process.env.CI
      ? 'echo "CI mode - reusing existing server"'
      : 'bash -c "cd .. && set -a && source .env.test && set +a && .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"',
    port: parseInt(process.env.API_PORT || '8000'),
    reuseExistingServer: !!process.env.REUSE_EXISTING_SERVER,
    timeout: 120000,
  },
});
