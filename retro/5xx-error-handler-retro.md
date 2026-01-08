# 5xx Error Handler Implementation - Retro

## Summary

Implemented an automatic 5xx error handling and task creation system for the comic-pile API. The system automatically detects server errors, classifies them, and either creates debugging tasks or logs them based on error type.

## What Was Implemented

### 1. Error Handler Module (`app/api/error_handler.py`)

Created a new module with the following components:

- **ERROR_COUNTER**: Tracks total 5xx errors encountered
- **KNOWN_5XX_ERRORS**: Lookup table mapping error signatures to handling behavior
  - Database connection failures → CREATE TASK (HIGH priority)
  - Query timeouts → CREATE TASK (HIGH priority)
  - Constraint violations → CREATE TASK (HIGH priority)
  - Temporary server errors → LOG ONLY (LOW priority)

- **is_known_5xx_error()**: Checks if error matches known patterns
- **create_error_task()**: Creates tasks.json entry with full debugging info
- **handle_5xx_error()**: Main handler that decides task creation vs logging
- **get_error_stats()**: Returns current error statistics

### 2. Integration with FastAPI Error Handlers

Modified `app/main.py` to integrate error handler:

- **global_exception_handler**: Calls `handle_5xx_error()` for all unhandled exceptions
- **http_exception_handler**: Calls `handle_5xx_error()` for 5xx HTTP exceptions
- Added `/debug/5xx-stats` endpoint to view error statistics
- Added `/debug/trigger-500` endpoint for testing

### 3. Task Creation with Full Debugging Info

Each error task captures:

- Request body (with sensitive data redaction)
- API path
- HTTP method
- Path parameters
- Request headers
- Error message
- Full traceback
- Metadata: priority, status, task_type, estimated_effort

### 4. Test Suite (`tests/test_error_handler.py`)

Created comprehensive tests covering:

- Error detection for all known error types
- Task creation for known errors
- Logging behavior for temporary/unknown errors
- Error counter functionality
- Debugging info capture verification
- Full test coverage of all error handler functions

## What Worked Well

1. **Simple Integration**: Error handler integrates cleanly with existing FastAPI exception handlers
2. **Comprehensive Debugging**: Captures all relevant request context for troubleshooting
3. **Flexible Classification**: Easy to extend with new error types via KNOWN_5XX_ERRORS dictionary
4. **Type Safety**: Uses proper type annotations throughout (no Any types)
5. **Clean Separation**: Error handling logic isolated in dedicated module

## What Could Be Improved

1. **Line Length**: Some test functions have long lines (>100 chars) that need splitting
2. **Test Annotations**: Missing return type annotations for test functions (common in test files)
3. **Database Access**: Error handler doesn't have database session access for more sophisticated error tracking
4. **Rate Limiting**: No rate limiting on task creation to prevent spam on recurring errors
5. **Error Aggregation**: Multiple similar errors don't get aggregated into single task

## Testing

All 11 tests pass:
- Error pattern detection (4 tests)
- Task creation behavior (4 tests)
- Counter and statistics (3 tests)

## Files Modified

- `app/api/error_handler.py` (NEW)
- `app/main.py` (integration)
- `tests/test_error_handler.py` (NEW)

## Technical Decisions

1. **Pattern Matching**: Uses keyword matching instead of exact exception types for flexibility
2. **JSON Task Storage**: Writes directly to tasks.json for immediate agent pickup
3. **Counter In-Memory**: Simple dictionary counter (not persisted to database)
4. **Redaction Strategy**: Middleware already handles sensitive data redaction in request.state.request_body

## Next Steps (Future Enhancements)

1. Add database-backed error statistics
2. Implement error aggregation for recurring issues
3. Add rate limiting for task creation
4. Create error category hierarchy (DB, Network, Validation, etc.)
5. Add automated error trend analysis
