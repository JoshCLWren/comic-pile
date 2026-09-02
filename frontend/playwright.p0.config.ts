import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

// Shadow P0 browser config (issue #1481).
//
// Runs ONLY the fresh rebuilt P0 Chromium suite committed by the E2E rebuild
// (#1480). It intentionally excludes every retired legacy spec so shadow CI
// never executes coverage that is no longer part of the canonical P0 contract.
//
// Runtime and sharding stay bounded for the deliberately small P0 suite, and
// only Chromium is exercised. Firefox/WebKit are not part of this shadow gate.
export default defineConfig({
  testDir: './src/test',
  testMatch: '**/p0-*.spec.ts',
  testIgnore: ['**/*.test.{js,jsx,ts,tsx}', '**/*.audit.ts'],
  fullyParallel: false,
  forbidOnly: isCI,
  retries: 0,
  workers: Number(process.env.P0_WORKERS ?? 2),
  timeout: 90 * 1000,
  // Emit structured JSON plus an HTML report so failures retain enough evidence
  // to debug without manufacturing tickets.
  reporter: isCI
    ? [
        ['list'],
        ['html', { outputFolder: 'playwright-report/p0', open: 'never' }],
        ['json', { outputFile: 'test-results/p0/results.json' }],
      ]
    : [['list']],
  outputDir: 'test-results/p0',
  use: {
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:9000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 30000,
    navigationTimeout: 30000,
  },
  expect: {
    timeout: 15000,
  },
  projects: [
    {
      name: 'chromium-p0',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
