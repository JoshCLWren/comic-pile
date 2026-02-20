import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './src/test',
  testMatch: '**/*.spec.ts',
  testIgnore: ['**/*.test.{js,jsx,ts,tsx}', '**/prod-smoke.spec.ts'],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 4,
  timeout: 30 * 1000,
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
  webServer: {
    command: process.env.CI
      ? 'echo "CI mode - reusing existing server"'
      : 'bash -c "cd .. && set -a && source .env.test && set +a && .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"',
    port: parseInt(process.env.API_PORT || '8000'),
    reuseExistingServer: true,
    timeout: 120000,
  },
});
