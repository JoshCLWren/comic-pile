import { defineConfig, devices } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const isCI = !!process.env.CI;

// Inventory-driven Chromium regression config (issue #1483).
//
// Coverage is selected from the canonical behavior inventory
// (docs/e2e-behavior-inventory.yaml) by scripts/e2e_regression_select.py,
// which writes a JSON manifest consumed here. The config fails closed when
// the manifest is missing or empty so a scheduled run can never silently
// execute zero specs and report success.
//
// Only Chromium runs here. Firefox/WebKit remain optional diagnostics, and
// nothing in this pipeline creates GitHub issues or labels from failures —
// defect reconciliation is documented in docs/E2E_CHROMIUM_REGRESSION.md.

type SelectionManifest = {
  schema?: unknown;
  scope?: unknown;
  specs?: unknown;
};

function loadSelectionSpecs(): string[] {
  const candidate =
    process.env.E2E_REGRESSION_SELECTION ?? 'test-results/regression/selection.json';
  const resolved = path.resolve(candidate);
  if (!existsSync(resolved)) {
    throw new Error(
      `Missing regression selection manifest at ${resolved}. ` +
        'Run `pnpm run test:e2e:regression` (or scripts/e2e_regression_select.py) first.',
    );
  }
  // SAFETY: JSON.parse of a manifest file validated by schema in scripts/e2e_regression_select.py
  const manifest = JSON.parse(readFileSync(resolved, 'utf-8')) as SelectionManifest;
  const specs: string[] = [];
  if (Array.isArray(manifest.specs)) {
    for (const entry of manifest.specs) {
      // Domain values after I/O boundary parsing
      const entrySpec = String(entry)
      if (entrySpec.length === 0) {
        throw new Error('Invalid spec entry in selection manifest: empty string');
      }
      specs.push(entry);
    }
  }
  if (specs.length === 0) {
    throw new Error(
      `Selection manifest ${resolved} lists no specs; refusing to run an empty regression suite.`,
    );
  }
  return specs;
}

const selectionSpecs = loadSelectionSpecs();

export default defineConfig({
  testDir: './src/test',
  testMatch: selectionSpecs,
  testIgnore: ['**/*.test.{js,jsx,ts,tsx}', '**/*.audit.ts'],
  fullyParallel: true,
  forbidOnly: isCI,
  retries: 0,
  workers: Number(process.env.REGRESSION_WORKERS ?? (isCI ? 2 : 4)),
  timeout: 90 * 1000,
  // Structured JSON plus HTML with traces/screenshots/video retained on
  // failure so triage has evidence without manufacturing tickets.
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report/regression', open: 'never' }],
    ['json', { outputFile: 'test-results/regression/results.json' }],
  ],
  outputDir: 'test-results/regression/artifacts',
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
      name: 'chromium-regression',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
