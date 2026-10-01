# Plan: Remove the reading-session/auth-session naming foot gun

## Issue Overview
ComicPile uses "session" to describe durable reading-history records, while authentication code also talks about user/login sessions. This naming collision contributed to the password-reset incident fixed in #2996, where auth recovery called `delete_all_sessions_for_user()` but operated on reading sessions rather than authentication state.

## Goal
Make the domain boundary between **reading history** and **authentication state** explicit in names, APIs, repositories, and tests.

## Scope
- Rename reading-history concepts to use explicit domain-specific names like `ReadingSession`, `ReadingSessionRepository`, etc.
- Ensure auth code doesn't encounter ambiguous `Session` abstractions that could be mistaken for login/session-token state
- Update all related files, imports, API endpoints, tests, and documentation
- Handle migration/backward-compatibility concerns

## Files to Rename

### Core Model and Repository Files
1. `app/models/session.py` → `app/models/reading_session.py`
2. `app/repositories/session_repository.py` → `app/repositories/reading_session_repository.py`
3. `app/schemas/session.py` → `app/schemas/reading_session.py`
4. `app/api/session.py` → `app/api/reading_session.py`
5. `comic_pile/session.py` → `comic_pile/reading_session.py`

### Service Files
6. `app/services/session_service.py` → `app/services/reading_session_service.py`
7. `app/services/session_response.py` → `app/services/reading_session_response.py`
8. `app/services/session_history_projection.py` → `app/services/reading_session_history_projection.py`

### API Route Updates
9. Update `app/main.py` to mount the new reading session routes
10. Update API endpoint paths from `/api/sessions/*` to `/api/reading-sessions/*`

### Test Files
11. Rename test files: `tests/test_session_*.py` → `tests/test_reading_session_*.py`
12. Update imports in all test files
13. Add regression test to prevent auth code from calling destructive reading-session helpers

### Frontend Files
14. Update frontend API client imports and endpoint references
15. Update frontend query keys and cache effects

### Documentation
16. Update developer guidance for domain nouns with multiple meanings
17. Search repository for `Session` uses and document intentionally retained ambiguous cases

## Implementation Steps

### Phase 1: Core Model and Repository (High Priority)
1. Rename `app/models/session.py` to `app/models/reading_session.py`
2. Update all imports and references
3. Rename `app/repositories/session_repository.py` to `app/repositories/reading_session_repository.py`
4. Update all imports and references
5. Update database migration references

### Phase 2: API and Schema Files
6. Rename `app/schemas/session.py` to `app/schemas/reading_session.py`
7. Rename `app/api/session.py` to `app/api/reading_session.py`
8. Update route registration in `app/main.py`
9. Update API endpoint paths
10. Update `comic_pile/session.py` to `comic_pile/reading_session.py`

### Phase 3: Service Files
11. Rename service files with updated imports
12. Update all service dependencies and references

### Phase 4: Frontend Updates
13. Update frontend API client imports
14. Update query keys and cache effects
15. Update any hardcoded API paths

### Phase 5: Tests and Validation
16. Rename test files and update imports
17. Add regression test to prevent auth code from calling reading-session helpers
18. Verify all tests pass
19. Run focused validation on the changes

### Phase 6: Documentation and Cleanup
20. Update documentation
21. Search for and document intentionally retained ambiguous cases
22. Clean up any remaining references

## Key Acceptance Criteria
1. Reading-history model no longer exposed as bare `Session` to application code
2. Repository/service helpers use explicit reading-domain names (no ambiguous `delete_all_sessions_for_user()` helpers)
3. Audit and rename ambiguous `session` terminology where practical
4. Auth code doesn't import/depend on reading-session helpers without explicit justification
5. Add regression test to prevent auth code from calling destructive reading-session helpers
6. Tests verify password changes preserve reading history
7. Handle migration/backward-compatibility concerns
8. Search repository for `Session` uses and document intentionally retained ambiguous cases
9. Update developer guidance for domain nouns with multiple meanings

## Migration Strategy
- Keep backward compatibility aliases during the transition
- Update imports systematically to avoid breaking changes
- Use explicit domain names in new code
- Document the transition plan for developers

## Risk Mitigation
- The `delete_all_sessions_for_user` function is particularly dangerous - ensure auth code can't accidentally call it
- Verify that authentication-related session management remains untouched
- Ensure all existing functionality continues to work after renaming
- Add tests to prevent future naming collisions