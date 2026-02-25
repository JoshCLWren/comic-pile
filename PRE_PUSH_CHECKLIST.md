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

### 3. Tests ✅
```bash
uv run pytest tests/ --no-cov -q
```
- **ALL 333 tests must pass**
- No failures, no errors

### 4. Git Status ✅
- Working tree must be clean
- All changes committed

## Only After ALL Checks Pass:
```bash
git push
```

## If Any Check Fails:
1. Fix the issues
2. Run the failed check again
3. ONLY push when all 4 checks pass

## NO EXCEPTIONS
This prevents wasted CI cycles and ensures code quality.
