# Native Roll bootstrap behavior oracle (v1)

The wire contract already exists: FastAPI's `app.openapi()` operation
`GET /api/v2/roll/bootstrap`, its `RollV2BootstrapResponse` component and referenced
components. Export it with `python scripts/export_openapi_schema.py --output /tmp/roll-openapi.json`.
`frontend/src/generated/openapi.ts` is generated from that same contract. Do not
introduce a second Rust-specific schema or hand-maintained field inventory.

`tests/test_roll_v2_golden.py` supplements OpenAPI with complete Python HTTP JSON
and before/after durable state in `tests/fixtures/roll-v2/v1/`. Tests validate
responses through the existing Pydantic model and verify the OpenAPI operation's
response reference, timezone parameter, and bearer security. The production
handler and Python evaluator remain the oracle; native output must not be used
to regenerate these expectations.

## Reproduce

Use Python 3.14 and `uv sync --frozen --all-extras`. Set `TEST_DATABASE_URL` and
`DATABASE_URL` to the same **disposable local PostgreSQL test database**. Shared
fixtures truncate test data and refuse non-test database names. Never point this
suite at a reader's library, a read-only testuser snapshot, or production.

```sh
uv run pytest tests/test_roll_v2_golden.py tests/test_roll_v2_contract.py \
  tests/test_option_e_runtime.py tests/test_roll_v2_projection.py -q --no-cov
bash scripts/check-python-ci-lint.sh
```

The decision clock is 2026-01-04 12:00 UTC. Model session/snapshot defaults and
bandwidth initialization use that clock too; authentication uses real short-lived
synthetic credentials generated in memory. No tokens are stored in JSON. Each
case seeds its own owner and library using database-generated keys. JSON maps
those keys to ordinal identities per domain; ordering, nulls, numbers, labels,
fixed timestamps and all response fields remain significant. Repeated GETs must
return identical payloads and leave the post-first-request state unchanged.
Tests only read checked-in expectations. Changing an expectation requires an
explicitly reviewed Python-contract change and fresh isolated Python capture.

## Scenario matrix

All happy-path fixtures use Option E enabled with a local-only approval reference.
Unless specified, Alpha and Beta each have two unread issues, queue positions
1 and 2, no mappings, and a recent existing d6 reading session with uninitialized
bandwidth. `before` and `after` capture reading-session fields, issue read state,
event count, and full undo snapshot content.

| Fixture | Distinguishing setup / behavior |
| --- | --- |
| new_session | No prior session; creates session and session-start undo snapshot |
| existing_session | Reuses recent unended row; initializes bandwidth once |
| no_eligible | Empty library; empty candidates and summaries, stable repeat GET |
| pending | Beta #1 remains pending; active thread retained |
| snoozed / skipped | Alpha excluded via the respective session ID collection |
| manual_die | Manual d4 overrides automatic die selection |
| auto_die | Synthetic session rate event with die_after=8; automatic ladder is evaluated by Python |
| last_read | Same session-scoped rating/read event projects Alpha #1 and read time |
| recovery | Strict Alpha #1 before pending Beta #1; structured blockers and readable prerequisite |
| strict | Alpha #1 before Beta #1 blocks Beta |
| loose | Same placements permit independent series frontiers |
| overlap | Strict placements plus confirmed per-thread volumes and approved Beta-over-Alpha overlap |
| timezone_valid | Whitespace-trimmed America/Chicago captured once |
| timezone_invalid | Invalid zone ignored; bootstrap succeeds with timezone unset |
| timezone_preserved | Existing Asia/Tokyo retained despite browser America/Chicago |
| auth_* | Missing/malformed/expired/refresh/revoked/deleted-user/missing-jti/password-change rejection; no reading writes or refresh rotation |

## Request flow and side effects

1. `get_current_user` verifies signed access JWT, expiry, string subject/jti and
   access token type, then loads the user with revocation in one owner lookup.
   Password-change epoch revokes older credentials. Reading-history sessions are
   not login credentials. The current User model has no disabled-user flag;
   native code must not invent one. Missing or invalid bearer credentials,
   expired signatures, non-access token types, revoked/missing jti, absent user,
   and changed password have their Python error JSON/header examples in auth fixtures.
2. `get_or_create` resolves the authenticated owner's recent unended reading
   session from the latest durable activity, preferring pending work. It
   initializes missing inferred bandwidth and commits once. New-session creation
   uses the per-process lock and a per-user PostgreSQL advisory transaction lock,
   rechecks, and persists inferred bandwidth plus a session-start snapshot.
   Snapshot content captures issue tracking, thread state and session modes.
3. Browser timezone is the only query parameter. When stored timezone is null,
   strip it, accept a nonempty <=100-character IANA zone, persist and refresh.
   Invalid zones (including blank or too long values) are soft failures, not 422.
   An already captured timezone is never overwritten by this GET.
4. Load safe active-thread context, die/ladder, bandwidth and session mode. Load
   cross-session backoff/snooze exclusions and recovery for the preserved pending
   selection. Recovery is explanatory: it does not clear pending state or roll.
5. `get_v2_rollable_projection` consumes live validated Option E eligibility,
   applies exclusions before die limiting, and reads issue identities, canonical
   metadata, direct provider artwork URLs, reader stats, group routes and
   session-scoped last-read. Stored blocked/frontier flags are not authority.
6. `RollService.load_bootstrap_thread_data` derives owner-scoped snoozed/skipped/
   blocked/stale summaries and counts. OpenAPI models bound summary lists to 20;
   routes are capped at three with overflow count. V2 replaces v1 `roll_pool`
   with non-null-issue `rollable` and nullable `last_read`.

GET can create reading history, initialize bandwidth, capture timezone and write
an undo snapshot. It does not rate/read an issue, roll/select a new target,
change queue positions, rotate refresh credentials or emit a reading Event.
The golden before/after state makes these writes visible to native parity tests.

## Error boundary and remaining campaign work

Auth failure occurs before reading-history bootstrap. HTTP 422 validation remains
in the OpenAPI contract; timezone is a string and invalid IANA names are ignored.
Dependency outages use the application's stable 503 boundary (see
`tests/test_database_unavailability_contract.py`); unforeseen failures use its
500 handler. Cyclic/missing-reference Option E inputs fail closed; they must
never become successful partial candidate sets. Existing auth, recovery,
projection, route-versioning and Option E tests remain authoritative alongside
these examples.

These fixtures are synthetic examples, not proof of full native parity. They do
not replace catalog projection tests for ambiguous mappings, aggregate progress,
cover sanitization or route overflow, nor large-library query budgets,
concurrent session creation, cancellation, database outage fault injection,
legacy Option E-off mode, or every corrupt graph. #4303–#4310 implement those
contracts; #4311 must compare full Python/Rust status/JSON/database effects;
#4312 measures equivalent workloads; #4314 verifies the frontend.
All mutations, Queue/auth/catalog APIs, ingress deployment and rollback remain
outside this contract task. No production routing switch is authorized here;
#4313 retains the campaign cutover gates.
