import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

const isCI = !!process.env.CI
const baseURL = process.env.PROD_BASE_URL ?? process.env.BASE_URL
const storageStatePath = process.env.PROD_PROFILE_STORAGE_STATE

if (!baseURL) {
  throw new Error('Set PROD_BASE_URL (or BASE_URL) to run the production performance probe.')
}

if (!storageStatePath || !existsSync(storageStatePath)) {
  throw new Error(
    'Set PROD_PROFILE_STORAGE_STATE to the disposable-account storage state created by ' +
      'scripts/create-production-e2e-account.mjs. The probe never runs unauthenticated.',
  )
}

// Production performance probe (issue #1664), re-added on top of the rebuilt
// browser-test foundation (#1480).
//
// A single authenticated Chromium session against the live production URL,
// using the per-run disposable account's Playwright storage state. It records
// startup/queue milestones to PROD_PERFORMANCE_OUTPUT; the dispatch-only
// .github/workflows/production-performance.yml owns the disposable account
// lifecycle (create before, delete after) and the bounded history cache.
//
// No retries: the probe must record one honest measurement per run, and a
// retry would replace a failed production observation with a second sample
// instead of surfacing the failure.
export default defineConfig({
  testDir: './src/test',
  testMatch: '**/production-performance.spec.ts',
  fullyParallel: false,
  forbidOnly: isCI,
  retries: 0,
  workers: 1,
  timeout: 3 * 60 * 1000,
  outputDir: 'test-results/prod-performance',
  reporter: isCI
    ? [
        ['list'],
        ['html', { outputFolder: '../playwright-report-prod-performance', open: 'never' }],
        ['json', { outputFile: 'test-results/prod-performance/results.json' }],
      ]
    : [['list']],
  use: {
    baseURL,
    storageState: storageStatePath,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  expect: {
    timeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
