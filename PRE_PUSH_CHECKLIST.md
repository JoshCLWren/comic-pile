# Pre-Push Checklist - MANDATORY

## CRITICAL: These checks MUST pass before pushing

Running: `bash scripts/pre-push-check.sh`

### 1. Type Checking ✅
```bash
uv run ty check --error-on-warning
```
- Must pass with no errors
- No type ignores in staged files

### 2. Linting ✅
```bash
uv run ruff check .
```
- Must pass with no errors
- No noqa comments in new code

### 3. Unit Tests ✅
```bash
uv run pytest tests/ --no-cov -q
```
- **ALL 333+ unit tests must pass**
- Located in `tests/` directory
- No failures, no errors

### 4. E2E API Tests ✅
```bash
uv run pytest tests_e2e/test_api.py --no-cov -q
```
- Integration tests must pass
- Located in `tests_e2e/` directory
- Tests API endpoints end-to-end

### 5. Frontend Build Check (if frontend changed) ✅
```bash
cd frontend && npm run build
```
- **Only runs if frontend/ files were modified**
- Ensures `static/react/` directory is populated
- Required for E2E Playwright tests

### 6. Git Status ✅
- Working tree must be clean
- All changes committed

## Test Suites

| Suite | Command | Location | Required |
|-------|---------|----------|----------|
| Unit Tests | `pytest tests/` | `tests/` | ✅ Always |
| E2E API | `pytest tests_e2e/test_api.py` | `tests_e2e/` | ✅ Always |
| E2E Playwright | `npm run test:e2e` | `frontend/` | ⏭️ CI only (slow) |
| E2E Dice Ladder | Specialized | `tests_e2e/` | ⏭️ CI only |

**Note**: Playwright and Dice Ladder E2E tests are run in CI only due to complexity and execution time.

## Only After ALL Checks Pass:
```bash
git push
```

## If Any Check Fails:
1. Fix the issues
2. Run `bash scripts/pre-push-check.sh` again
3. ONLY push when all 6 checks pass

## NO EXCEPTIONS
This prevents wasted CI cycles and ensures code quality.
