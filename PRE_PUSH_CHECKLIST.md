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

### 4. Python E2E Tests ✅
```bash
uv run pytest tests_e2e/ --no-cov -q
```
- Integration tests must pass
- Located in `tests_e2e/` directory
- **Files:**
  - `test_api_workflows.py` - API endpoint integration tests
  - `test_dice_ladder_e2e.py` - Dice ladder workflow tests
- **NOT including** Playwright tests (those are TypeScript in frontend/)

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

| Suite | Command | Location | Pre-Push | CI |
|-------|---------|----------|----------|-----|
| **Unit Tests** | `pytest tests/` | `tests/` | ✅ Required | ✅ Always |
| **Python E2E** | `pytest tests_e2e/` | `tests_e2e/` | ✅ Required | ✅ Always |
| - test_api_workflows.py | | | | |
| - test_dice_ladder_e2e.py | | | | |
| **Playwright E2E** | `npm run test:e2e` | `frontend/src/test/` | ⏭️ Too slow | ✅ Sharded |
| - accessibility.spec.ts | | | | |
| - auth.spec.ts | | | | |
| - roll.spec.ts | | | | |
| - rate.spec.ts | | | | |
| - (11 more spec files) | | | | |

**Why Playwright is CI-only:**
- Requires frontend build (`npm run build`)
- Requires backend server running
- Takes 8-10 minutes even with 4 shards
- Too slow for pre-push verification

**Pre-push Strategy:**
- ✅ Unit tests (333 tests, ~75 seconds)
- ✅ Python E2E tests (10 tests, ~5 seconds)
- ⏭️ Playwright tests (run in CI with proper backend/frontend setup)

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
