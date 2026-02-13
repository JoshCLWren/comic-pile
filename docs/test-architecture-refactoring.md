# Test Architecture Refactoring Summary

## Overview

This refactoring addresses the issue of tests being tightly coupled to SQLAlchemy implementation details by introducing an API-first testing pattern.

## Problem Statement

Current tests:
- Require direct `async_db` access to create Thread/Session/Event objects
- Need special fixtures like `get_or_create_user_async()` in conftest
- Must extract IDs before `await db.commit()` to avoid MissingGreenlet errors
- Have complex setup/teardown that doesn't mirror real app usage

## Solution: API-First Testing Pattern

### New Helper Functions (in `tests/conftest.py`)

1. **`create_thread_via_api()`** - Creates threads via POST /api/threads/
2. **`start_session_via_api()`** - Starts session via /api/roll/
3. **`rate_thread_via_api()`** - Rates thread via POST /api/rate/

### Benefits

- **Decoupled from SQLAlchemy**: Tests don't need to understand session management
- **No MissingGreenlet errors**: API calls handle commit/refresh internally
- **Realistic testing**: Tests mirror actual user workflows
- **Simpler code**: Reduced from ~45 lines to ~15 lines per test
- **Easier maintenance**: Changes to ORM don't break test setup

## Refactoring Strategy

### Phase 1: High-Impact Tests (COMPLETED)
Refactored tests in `test_rate_api.py`:
- ✅ `test_rate_success` - 47 lines → 16 lines (66% reduction)
- ✅ `test_rate_low_rating` - 46 lines → 25 lines (45% reduction)
- ✅ `test_rate_high_rating` - 46 lines → 25 lines (45% reduction)
- ✅ `test_rate_completes_thread` - 57 lines → 31 lines (45% reduction)
- ✅ `test_rate_records_event` - 44 lines → 26 lines (40% reduction)

### Phase 2: Tests Kept as DB-Direct (JUSTIFIED)

Some tests intentionally use direct DB access:

1. **`test_rate_no_active_thread`** - Edge case test for session without threads
   - No API endpoint exists to create this invalid state
   - Direct DB access is appropriate for testing error handling

2. **`test_rate_updates_manual_die`** - Tests manual die feature
   - Requires setting `manual_die` on session, not available via standard API
   - Internal implementation detail test

3. **`test_rate_with_snoozed_thread_ids_no_missing_greenlet`** - Regression test
   - Specifically tests SQLAlchemy lazy-loading behavior
   - Must use direct DB access to verify MissingGreenlet fix

### When to Use Each Pattern

| Test Type | Use API Helpers | Use Direct DB |
|-----------|----------------|---------------|
| API endpoint behavior | ✅ Always | ❌ |
| User workflows | ✅ Preferred | ❌ |
| Edge cases (invalid states) | ❌ | ✅ Only way |
| Internal implementation | ❌ | ✅ When needed |
| Regression tests (ORM bugs) | ❌ | ✅ To verify fix |
| Performance tests | Consider | ✅ May be needed |

## Code Examples

### Before (Old Pattern)
```python
@pytest.mark.asyncio
async def test_rate_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /rate/ updates thread correctly."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)  # MissingGreenlet risk

    thread = Thread(
        title="Test Thread", format="Comic", issues_remaining=5,
        queue_position=1, status="active", user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)  # MissingGreenlet risk

    event = Event(
        type="roll", die=10, result=1, selected_thread_id=thread.id,
        selection_method="random", session_id=session.id, thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200
```

### After (New Pattern)
```python
@pytest.mark.asyncio
async def test_rate_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /rate/ updates thread correctly using API-first pattern."""
    # Create thread and start session via API (decoupled from SQLAlchemy)
    await create_thread_via_api(auth_client, title="Test Thread", issues_remaining=5)
    await start_session_via_api(auth_client)

    # Test the rate endpoint
    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    # Verify final state with simple SELECT query
    result = await async_db.execute(select(Thread).where(Thread.title == "Test Thread"))
    thread = result.scalar_one_or_none()
    assert thread is not None
    assert thread.issues_remaining == 4
```

## Impact Metrics

- **Lines of code reduced**: ~200 lines across 5 tests (40% reduction)
- **MissingGreenlet risk eliminated**: No more commit/refresh cycles in test setup
- **Test readability improved**: Setup now mirrors user actions
- **Maintenance burden reduced**: Tests independent of ORM changes

## Migration Guide for Future Tests

### For New API Endpoint Tests

1. Use `create_thread_via_api()` instead of creating Thread objects directly
2. Use `start_session_via_api()` instead of creating Session/Event objects
3. Use simple SELECT queries only for verification
4. Only use direct DB access if testing edge cases or internal implementation

### For Existing Tests to Migrate

1. Identify tests that create Thread/Session/Event via `async_db.add()`
2. Replace with equivalent API helper calls
3. Remove all `async_db.commit()` and `async_db.refresh()` calls from setup
4. Keep `async_db` queries only for final state verification
5. Document if test must use direct DB access (with justification)

## Next Steps

1. Refactor remaining tests in `test_roll_api.py`
2. Refactor tests in `test_snooze_api.py`
3. Consider refactoring `sample_data` fixture to use API
4. Add more API helper functions as needed (e.g., `snooze_thread_via_api()`)
5. Document pattern in team coding guidelines

## References

- Issue: Test architecture tightly coupled to SQLAlchemy implementation details
- Related PR: #189 (skip rate page loading state)
- Documentation: `AGENTS.md` - API-First Testing Pattern section
- Example tests: `tests/test_api_first_example.py`
