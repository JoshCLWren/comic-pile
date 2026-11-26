# E2E test pointer

The legacy Python pytest/Playwright suite was removed with the Python application. This directory intentionally contains only this pointer.

Maintained browser coverage lives in `frontend/src/test/` and uses TypeScript Playwright with the Chromium project. Read [`frontend/src/test/README.md`](../frontend/src/test/README.md) and [`docs/E2E_CHROMIUM_REGRESSION.md`](../docs/E2E_CHROMIUM_REGRESSION.md) for current setup, commands, inventory scopes, and failure policy.

Never skip or weaken a failing browser test. Reproduce it with focused evidence, repair the product or test, and preserve traces/screenshots/results for the existing issue or PR.
