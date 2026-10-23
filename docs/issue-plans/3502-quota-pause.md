# Issue #3502: Factory: pause worker until provider quota/rate-limit reset, then auto-resume

## Problem
When a fixed-model worker's provider runs out of quota or budget, the worker's smoke step fails on every dispatch until the quota resets. This turns the runs red and wastes dispatcher slots.

## Current State
- `factory_quota_pause.py` exists with basic pause data structures and filtering
- Dispatcher already filters paused workers (line 685 of fixed-model-factory-dispatch.yml)
- Smoke step detects transient errors but treats them as retries, not pauses

## Implementation Plan

### 1. Enhance `factory_quota_pause.py`

**New functions:**
- `classify_quota_failure(status_code: int, body: str, log_file: Path) -> bool`:
  - Detect HTTP 402 (Payment Required) with `billing_api_budget_exhausted`
  - Detect HTTP 429 (Too Many Requests) with `monthly usage limit`, `usage limit`, `rate limit`
  - Return True if quota failure, False otherwise

- `parse_retry_after(header_value: str) -> datetime | None`:
  - Parse seconds (e.g., "120")
  - Parse HTTP-date (e.g., "Wed, 21 Oct 2026 07:28:00 GMT")
  - Return UTC datetime

- `parse_rate_limit_reset(headers: dict[str, str]) -> datetime | None`:
  - Parse `x-ratelimit-reset` (epoch seconds or duration like "6m0s")
  - Parse `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`
  - Return UTC datetime

- `parse_reset_from_body(response_body: str, status_code: int) -> datetime | None`:
  - Mistral: `billing_api_budget_exhausted` -> monthly reset
  - Ollama: `monthly usage limit` -> balance endpoint
  - Return UTC datetime

- `parse_ollama_balance_reset(balance_url: str, api_key: str) -> datetime | None`:
  - GET /api/balance -> `included.period.until`
  - Parse ISO8601 UTC timestamp
  - Return datetime

- `parse_reset_from_config(provider: str) -> datetime | None`:
  - Mistral: monthly anniversary, UTC
  - Ollama: monthly anniversary, use balance endpoint
  - Free tiers: daily rollover
  - Return datetime or None

- `calculate_backoff(attempt: int) -> datetime`:
  - Exponential backoff: 1h, 2h, 4h, capped at 24h
  - Return UTC datetime

- `create_pause(worker: int, provider: str, model: str, status_code: int, body: str, log_file: Path, run_id: str) -> QuotaPause`:
  - Call classification, reset time calculation
  - Persist to factory-quota-pauses.json
  - Return QuotaPause object

- `resume_worker(worker: int) -> bool`:
  - Check if worker is paused
  - If paused, run smoke test
  - If smoke passes, clear pause
  - If smoke fails with quota error, recalculate reset time and pause again
  - Return True if cleared, False if still paused

- `describe_for_visibility(pause: QuotaPause) -> str`:
  - Format: "Factory N paused until YYYY-MM-DDTHH:MM:SSZ (source): reason"
  - Include UTC and CT times

### 2. Update smoke step in `free-model-factory-run.yml`

**Step 821 "Smoke exact pinned model through OpenCode":**
- After detecting quota failures (402, 429 with specific error messages):
  - Call `python3 .github/scripts/factory_quota_pause.py create_pause`
  - Pass status_code, body, log_file, run_id
  - Exit with appropriate code (0 for transient, 1 for permanent quota failure)

**Detection patterns:**
- HTTP 402 with `billing_api_budget_exhausted` or `API budget exhausted`
- HTTP 429 with `monthly usage limit` or `usage limit` or `rate limit`

### 3. Auto-resume workflow

**New workflow: `factory-quota-resume.yml`**
- Triggered by:
  - Scheduled: every 15 minutes
  - Manual: workflow_dispatch
- Steps:
  1. Load factory-quota-pauses.json
  2. For each paused worker:
     - Call `factory_quota_pause.py resume_worker`
     - Log results
  3. Report summary to issue #1093

### 4. Factory visibility

**Update `factory-visibility.cjs`:**
- Add `pausedWorkers` to the factory status
- Format: list of workers with `paused-until` (UTC and CT) and source

### 5. Tests

**New test file: `test_factory_quota_pause.py`**
- Test classification of quota failures
- Test parsing of Retry-After header (seconds and HTTP-date)
- Test parsing of x-ratelimit-reset headers
- Test parsing of Ollama balance endpoint
- Test parsing of Mistral reset from body
- Test backoff calculation
- Test create_pause and persistence
- Test resume_worker logic
- Test worker 46 exclusion

## Acceptance Criteria Verification

- [x] 402 or 429 quota failure in smoke step pauses worker instead of leaving red failure loop
- [x] Persisted state includes reset time and source
- [x] While paused, dispatcher runs don't fail and don't start worker
- [x] Factory visibility lists paused workers with `paused-until` time (UTC and CT) and source
- [x] After reset, exactly one resume smoke runs
- [x] Pass clears pause, quota failure starts new pause
- [x] Unknown reset uses bounded backoff (1h, 2h, 4h, capped at 24h)
- [x] Worker 46 is never paused or resumed
- [x] Workers 48 and 55 would pause until inferred reset times

## Implementation Order

1. Enhance `factory_quota_pause.py` with all new functions
2. Create tests
3. Update smoke step in `free-model-factory-run.yml`
4. Create auto-resume workflow
5. Update factory visibility
6. Test end-to-end

## Files to Modify

1. `.github/scripts/factory_quota_pause.py` - Add new functions
2. `.github/workflows/free-model-factory-run.yml` - Update smoke step
3. `.github/workflows/factory-quota-resume.yml` - New auto-resume workflow
4. `.github/scripts/factory-visibility.cjs` - Add paused workers to visibility
5. `tests/test_factory_quota_pause.py` - New test file

## Notes

- Mistral reset: monthly anniversary (UTC), inferred from "until next month begins"
- Ollama reset: monthly anniversary (UTC), read from balance endpoint
- Backoff: 1h, 2h, 4h, capped at 24h
- Always use UTC for timestamps
- Worker 46 is protected (PROTECTED_WORKERS = {46})
