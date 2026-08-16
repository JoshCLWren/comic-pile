import { defineConfig } from 'vitest/config';
import TestDriver from 'testdriverai/vitest';

// Note: dotenv is loaded automatically by the TestDriver SDK
export default defineConfig({
  test: {
    // Scope to the TestDriver computer-use tests only, so this config does not
    // sweep in the repo's other suites (Python-adjacent tests, the frontend's
    // own Vitest unit tests, and the Playwright E2E specs under frontend/).
    include: ['testdriver/**/*.test.{js,mjs,ts}'],
    testTimeout: 300000,
    hookTimeout: 300000,
    reporters: [
      'default',
      TestDriver(),
    ],
    setupFiles: ['testdriverai/vitest/setup'],
  },
});
