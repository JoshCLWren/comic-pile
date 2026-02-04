import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './src/test',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 4 : undefined,
  reporter: [
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
    command: 'bash -c "cd .. && export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5437/comic_pile_test && export SECRET_KEY=test-secret-key-for-testing-only && export AUTO_BACKUP_ENABLED=false && export SKIP_WORKTREE_CHECK=true && export TEST_ENVIRONMENT=true && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"',
    port: parseInt(process.env.API_PORT || '8000'),
    reuseExistingServer: !!process.env.REUSE_EXISTING_SERVER,
    timeout: 120000,
  },
});
