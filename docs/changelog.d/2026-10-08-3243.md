### Features

- **Performance Budget Enforcement**: Added hard startup and coroutine performance budgets to prevent pathological startup times and slow API requests. (#3243)
  
  - **Startup Performance**: Implemented 2.0s warning and 2.5s hard budget for application startup. Processes that cannot become ping-ready within 2.5s will fail initialization rather than continuing silently.
  - **Request Performance**: Added 500ms warning and 1000ms violation thresholds for warm API requests. Requests >=1000ms emit error-level `performance_budget_violation` while allowing completion.
  - **Bounded Await Primitive**: Introduced `run_bounded()` function for executing coroutines with explicit timeouts and performance monitoring, with proper cancellation semantics and no task leaks.
  - **Operation Attribution**: Enhanced startup diagnostics to identify which specific operations consume time during startup, replacing generic "startup took 72s" with detailed operation-level timing.
  - **Structured Telemetry**: Added performance warnings and violations with detailed context including route, duration, DB time/query count, deployment, and request ID for actionable performance work.

### Technical Changes

- **Performance Budgets Module**: New `app/performance_budgets.py` provides the core budget enforcement system with `PerformanceBudgetManager`, `PerformanceWarning`, and budget decorators.
- **Middleware Integration**: Updated `app/middleware/request_logging.py` to enforce request performance budgets with structured warnings and violations.
- **Startup Path Integration**: Modified `app/main.py` to apply performance budgets to startup events, heavy initialization, and Neon monitor startup.
- **Budget Configuration**: Updated `SLOW_REQUEST_THRESHOLD_MS` default from 1000ms to 500ms for warnings, with 1000ms now triggering violations.
- **Comprehensive Testing**: Added extensive test coverage for performance budgets including unit tests, integration tests, and edge case handling.

### Behavior Changes

- **Startup Failures**: Applications with startup times exceeding 2.5s will now fail fast with clear error messages instead of continuing with pathological performance.
- **Request Timeouts**: Individual coroutines can now be cancelled if they exceed their assigned budgets, preventing single slow operations from blocking the entire application.
- **Enhanced Monitoring**: All performance events now include detailed attribution and context, making it easier to identify and fix performance bottlenecks.
- **Backward Compatibility**: The changes maintain backward compatibility while adding new performance safeguards. Existing functionality continues to work as before.