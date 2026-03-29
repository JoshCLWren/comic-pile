## Failing CI Checks

- **Frontend Lint + Typecheck**: Likely due to new syntax or missing dependencies in the help/glossary page.

- **E2E Playwright Tests (All Shards 1-8)**:
    - Multiple shards failing indicate flakiness or logical errors likely related to:
        - Possible misbehavior under the new navigation overlays or components.
        - Incorrect selectors or DOM structure changes after navigating to the **Glossary** or **Help** pages.
    - Need deeper investigation into each log to identify if multiple types of regressions or pattern mismatches.

## Acceptance Criteria to Fix
1. **Fix Typechecking Lint Errors**: Add missing TypeScript definitions or import statements.
2. **E2E Playwright Tests**:
    - Review CI logs for specific failures to identify failing selectors/pages.
    - Ensure new glossary/help pages load properly without breaking existing flows.
    - Update integration test logic if necessary.

- **CodeRabbit Issues**: None detected. CI indicates **no CodeRabbit-specific issues**.
