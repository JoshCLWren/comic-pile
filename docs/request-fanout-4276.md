# Request fan-out trace for #4276

Scope: frontend/transport fan-out for Queue, Roll, and the Read/Rate → next Roll
loop. Traced against the actual TanStack callers in `frontend/src` and the Rust
ingress in `api/native_roll.rs` / `native/roll-service/src`.

## Transport trace

- Cold Roll: `useRollBootstrap` (`frontend/src/hooks/useRollBootstrap.ts`) calls
  `rollBootstrapApi.get(timezone)` (`frontend/src/services/rollBootstrapApi.ts`),
  which resolves the reading session with `POST /v2/reading-sessions` and then
  reads the projection with `GET /v2/roll/bootstrap` (both Rust,
  `api/native_roll.rs` routes).
- Read/Rate → next Roll: `useRate` (`frontend/src/hooks/useRate.ts`) commits the
  rating, then calls `fetchAndPublishRollBootstrap`
  (`frontend/src/hooks/rollMutationReconciliation.ts`), which fetches the same
  bootstrap and publishes it to the cache. Roll page then uses the published
  snapshot; no page-level second fetch exists.
- Queue cold load (`frontend/src/pages/QueuePage/QueuePage.tsx` plus
  `useQueueThreadCards`): one bounded `threads.list` page, one excluded-library
  page, one current-session read (per-row snooze state), one batched
  `POST /v2/reading-boundaries`, one batched legacy blocking read (only when the
  canonical read reports `unavailable`, the default deployment — see #4025),
  and one batched crossover read. Each family is batched to one request; no
  per-card fetch exists (#2979).
- Warm Roll revisit: `invalidateRollBootstrapOnNavigation`
  (`frontend/src/query/cacheEffects.ts`) marks the bootstrap stale without
  fetching on the way out; the next mount refetches.

## Removed request

`GET /v2/roll/bootstrap` is read-only in Rust (`reading_session::bootstrap_once`
runs a read-only transaction and 404s with "No active session" when none
exists). The session POST is only needed until one resolution has succeeded for
the client. `rollBootstrapApi.get` now resolves the session once per client
lifetime (once more if the browser timezone changes) and re-resolves exactly
once if the read-only projection answers 404 (session gap lapsed, or a
different reader signed in within the same client lifetime). Authentication and
ownership stay server-side; the client never sends a user id.

| Scenario | Before | After |
| --- | --- | --- |
| Cold Roll load | `POST /v2/reading-sessions` + `GET /v2/roll/bootstrap` | unchanged |
| Bootstrap refetch (retry probe, post-mutation reconciliation, undo refresh, Roll re-entry) | `POST /v2/reading-sessions` + `GET /v2/roll/bootstrap` | `GET /v2/roll/bootstrap` only |
| Session gap lapsed / different reader | `POST` + 404 `GET` | `POST` + 404 `GET` + one `POST` + one `GET` (bounded recovery) |
| Cold Queue load | 6 batched reads (list, excluded, session, boundaries, legacy blocking, crossovers) | unchanged (see "Not in this change") |
| Read/Rate → next Roll | rate PATCH + bootstrap `POST` + `GET` | rate PATCH + bootstrap `GET` |

SQL effect (code-derived, not profiled): each removed POST removed one
session-write transaction on the Rust service (`reading_session::initialize`:
per-user advisory lock, user validation, session resolution/insert, timezone
persistence). The bootstrap read queries are unchanged.

## Evidence

- `frontend/src/unit/rollBootstrapTimezone.test.ts` — session POST count across
  refetches, concurrent-first-fetch sharing, 404 re-resolution, and auth/503
  non-retry cases.
- `frontend/src/unit/coreRouteRequestBudget.test.tsx` — exact transport counts
  for Roll cold load and the move-front bootstrap refresh.
- `frontend/src/test/p0-roll-selection.spec.ts` — Chromium budget: post-mutation
  refresh is one `GET /v2/roll/bootstrap` and zero `POST /v2/reading-sessions`.
- Local run (this session): `pnpm exec vitest run` over the request-scope files
  (68 tests) and `pnpm run typecheck` / `eslint` / `build` — green. Chromium
  specs require a local backend and are covered by CI, not claimed locally.

## Not measured / not in this change

- No production wall time, Rust CPU, or Vercel Active CPU measurement was taken;
  this doc claims no billing savings. Request-count reductions are not billing
  measurements.
- The Queue's double blocking read (canonical boundaries batch plus the legacy
  fallback batch while the evaluator is switched off) is intentionally kept in
  this change; removing that UI surface is owned by #4441, and #4405 owns
  sessionless Roll semantics. Eligibility, ordering, payloads, and frontend
  semantics are otherwise unchanged.
