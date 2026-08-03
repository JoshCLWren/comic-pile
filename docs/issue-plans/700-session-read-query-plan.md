# Issue #700: bounded session-read query plan

## Goal

Consolidate the current-session and History read pipelines so their SQL and Python work stays bounded, while preserving session creation, pending-roll recovery, snoozes, ladder state, snapshots, ownership, cursor pagination, and response contracts.

This plan follows the benchmark harness merged in PR #721. It does not claim latency, query-count, or payload improvements until the implementation is measured with that harness.

## Current flow and concrete multipliers

`app/api/session.py` currently has two related read paths with duplicated work:

- `get_current_session()` loads every open session for a user and calls `is_active()` in Python until one qualifies. It then independently loads the latest action, selected or pending thread, unread count, next issue metadata, snapshot count, snoozed threads, ladder events, and current-die events.
- `list_sessions()` fetches the page and then separately loads latest roll events, snapshot counts, ladder events, and current-die events. It repeatedly filters those event lists and repeatedly searches `sessions_to_return` inside loops. Active migrated threads still invoke per-thread unread-count and next-issue reads.

The page itself is bounded, but the current shape performs duplicate event queries, O(page_size²) Python scans, and thread-dependent SQL.

## Stage 1: shared event projection and linear History assembly

### Production changes

In `app/api/session.py`:

1. Add a private typed projection for the event-derived fields needed by session summaries:
   - latest roll event per session;
   - ordered non-null `die_after` values for ladder construction;
   - latest non-null `die_after` per session.
2. Fetch the relevant events for all page session IDs once, ordered by `(session_id, timestamp, id)`.
3. Build dictionaries in one pass:
   - `sessions_by_id`;
   - `latest_roll_by_session`;
   - `die_path_by_session`;
   - `latest_die_by_session`.
4. Replace every per-session list comprehension and `next()` search with O(1) dictionary access.
5. Preserve manual-die precedence and use `(timestamp, id)` as the deterministic tie break.

### Tests

Extend the session API tests with assertions for:

- duplicate event timestamps resolved by event ID;
- manual die overriding event-derived die;
- no die events falling back to `start_die`;
- ladder ordering remaining chronological;
- deleted historical threads producing `active_thread=None`;
- first and later cursor pages returning unchanged ordering and tokens.

Add a SQL statement-count regression around History that compares one returned session with a full page and proves event-query count does not grow per session.

## Stage 2: bulk active-thread metadata for History

### Production changes

Reuse the grouped unread-count approach established by #693:

1. Collect selected thread IDs from `latest_roll_by_session`.
2. Load owned threads in one query.
3. Bulk-load unread issue counts for migrated thread IDs in one grouped query.
4. Bulk-load referenced `next_unread_issue_id` rows in one query.
5. Build `ActiveThreadInfo` from maps without calling `Thread.get_issues_remaining()` or `_fetch_thread_issue_metadata()` per thread.
6. Preserve the stored `threads.issues_remaining` value for unmigrated threads.

Keep the helper contract explicit so a future caller cannot silently fall back to N+1 reads.

### Tests

Cover mixed migrated and unmigrated threads, missing next-issue rows, completed threads, deleted threads, and a full History page. Assert bounded SQL statement count across 1, 50, and 200 sessions.

## Stage 3: bounded current-session selection and shared summary read

### Production changes

1. Replace loading every open session with a newest-first bounded candidate query. Fetch one candidate at a time only when expiry semantics require examining an older open row.
2. Extract a current-session summary loader that derives latest action, ladder path, current die, snapshot count, snoozed summaries, and active-thread metadata from explicit bounded queries.
3. Do not run concurrent statements through the same `AsyncSession`. Independent reads may be combined in SQL or performed sequentially with measured evidence.
4. Keep the existing deadlock retry boundary, ownership checks, cache behavior, and `get_or_create()` behavior unchanged.
5. Add phase timing fields through the existing structured request instrumentation rather than introducing a second logging format.

### Tests

Cover active and expired open sessions, no existing session, pending-thread precedence, selected-thread fallback, missing pending thread, snoozed rows, deadlock retry, snapshot presence, and cache invalidation compatibility.

## API and data compatibility

- No route, status code, pagination token, authentication, ownership, or response-field change is intended.
- No database migration is required.
- `SessionHistoryListResponse`, `SessionListItem`, and `SessionResponse` remain the public contracts.
- Collections are not introduced, preserved, or optimized by this work.

## Validation sequence

Run the narrowest affected checks first:

```bash
uv run pytest tests/test_session_api.py tests/test_session_pagination.py -q
uv run pytest tests/test_session_api.py tests/test_session_pagination.py --cov=app.api.session --cov-branch --cov-report=term-missing
uv run ruff check app/api/session.py tests/test_session_api.py tests/test_session_pagination.py
uv run ty check --error-on-warning
```

Then run the repository-required backend and API E2E matrix. After deployment, run `scripts/benchmark_session_reads.py` against local, preview, and production targets and record first-observed and steady-state results for:

- current session with and without an active session;
- first History page;
- a later cursor page;
- a session with many events.

Record status, duration, response bytes, `X-App-DB-Queries`, `Server-Timing`, request ID, and cache state. Compare against the pre-change report using the same account, page size, iteration count, and deployment-idle conditions.

## Rollback and containment

Each stage should be independently revertible:

- Stage 1 changes only in-memory event assembly and its tests.
- Stage 2 changes only History active-thread metadata loading and its tests.
- Stage 3 changes only current-session selection/summary loading and instrumentation.

Do not combine frontend cache migration, response-model redesign, or Collections removal into these stages. If measured query count or behavior regresses, revert the affected stage without removing the benchmark harness or changing public contracts.
