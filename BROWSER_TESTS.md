# Browser UI Testing Status

## TypeScript Playwright Tests

**Location**: `frontend/src/test/`

**Status**: ❌ **DISABLED IN CI**

**Reason**: Frontend infrastructure issues (vitest conflicts, babel decorator syntax)

### Test Coverage

The following TypeScript Playwright test files exist but are **not run in CI**:

- `auth.spec.ts` - Authentication flow (register, login, logout)
- `roll.spec.ts` - Roll dice feature, 3D dice rendering, navigation
- `rate.spec.ts` - Rate thread feature, form validation
- `threads.spec.ts` - Thread management (create, edit, delete)
- `history.spec.ts` - History view and filtering
- `edge-cases.spec.ts` - Error handling and edge cases
- `accessibility.spec.ts` - A11y compliance
- `visual.spec.ts` - Visual regression tests
- `network.spec.ts` - Network resilience
- `analytics.spec.ts` - Analytics tracking

### Running TypeScript Playwright Tests Locally

**Manual testing only** - not currently supported in CI due to infrastructure issues:

```bash
cd frontend
npx playwright test --project=chromium
npx playwright test --ui  # Interactive mode
npx playwright show-report  # View test results
```

## Python Backend Test Coverage

**Status**: ✅ **FULLY FUNCTIONAL IN CI**

All business logic tested via Python API tests:

| Feature | Python Test | Coverage |
|---------|-------------|----------|
| Authentication | `tests/test_auth.py` | ✅ Full |
| Roll API | `tests/test_roll_api.py` | ✅ Full |
| Rate API | `tests/test_rate_api.py` | ✅ Full |
| Sessions | `tests/test_session.py` | ✅ Full |
| Queue | `tests/test_queue_api.py`, `tests/test_queue_edge_cases.py` | ✅ Full |
| History | `tests/test_history.py`, `tests/test_history_events.py` | ✅ Full |
| E2E Workflows | `tests_e2e/test_api_workflows.py` | ✅ Full |
| Dice Ladder | `tests_e2e/test_dice_ladder_e2e.py` | ✅ Full |

## Why No Browser UI Tests in CI?

### Attempted Solutions

1. **Python Playwright** (2025-01) - Failed due to event loop conflicts with pytest-asyncio
   - 9+ commits attempting fixes
   - All reverted due to fundamental incompatibility

2. **TypeScript Playwright** (2025-02) - CI infrastructure issues
   - vitest/jest matcher conflicts
   - babel decorator syntax errors
   - Pre-existing frontend configuration problems

### Current Situation

- **Backend API testing**: 100% covered by Python tests (260 passing)
- **Frontend unit tests**: Disabled (see `*.test.jsx` files in `frontend/src/`)
- **Browser UI tests**: Disabled in CI (manual only)

### Recommendation

For now, rely on:
1. **Python API tests** for CI coverage (96.30% coverage, 260 tests passing)
2. **Manual browser testing** for UI interactions
3. **Code review** for frontend changes

Future work to fix frontend test infrastructure is welcome but not blocking.

## Docker Test Infrastructure

Docker infrastructure for manual testing is available:

```bash
make docker-test-up    # Start PostgreSQL + API server
make docker-test-health  # Check services
make docker-test-logs   # View logs
make docker-test-down   # Stop services
```

See `docker-compose.test.yml` for configuration.

## Related Documentation

- `AGENTS.md` - Testing patterns and guidelines
- `TASKS_DOCKER_BROWSER_TESTS.md` - Docker infrastructure attempt
- `TASKS_DOCKER_BROWSER_TESTS_SUMMARY.md` - Lessons learned from Python Playwright attempts
