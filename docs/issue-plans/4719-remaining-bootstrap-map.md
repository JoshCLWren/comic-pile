# Issue 4719: Remaining bootstrap map for #4299 deletion

## Status

Docs-only audit of every `GET /api/v2/roll/bootstrap` field still consumed on
`main` at `f68daf6ee`, so #4299 can retire the monolith field-by-field without
re-discovering callers. This record ships no runtime change, no new HTTP
request, and no visual change. #4729 (in review on
`rust/roll-die-sync-scoped-20261107`) is the die-state page-state slice and
is intentionally left untouched by this standalone map.

- Parent: #4335 (resource-oriented Rust API migration).
- Surface issue: #4719 (mount scoped Roll resources in the production caller).
- Retire issue: #4299 (`GET /api/v2/roll/bootstrap` deletion, blocked).
- Session prerequisite: #4343 current-session `GET` (blocked on #4405
  sessionless Roll).

## Owner objective

Retire `GET /api/v2/roll/bootstrap` only when no React or background caller
remains. A field may be deleted from the bootstrap projection only after its
last consumer reads a scoped resource carrying the same semantics, or the
consumer itself is deleted. This map records, for each field, the current
consumer and the scoped replacement status.

## Operations inventory

Per-operation destination and consumer basis. API version (`v2`) is a wire
contract version, not an implementation-language claim.

| Operation | Destination (checked-in route) | Observed runtime basis | Client consumers |
| --- | --- | --- | --- |
| `GET /api/v2/roll/bootstrap` | `api/native_roll.rs` (`vercel.json`) | Route configuration only; authenticated production Rust execution proof still required before #4299 closes | `frontend/src/services/rollBootstrapApi.ts` (`rollBootstrapApi.get`), `frontend/src/services/protectedRollMutationApi.ts` (`protectedRollMutationApi.bootstrap`) |
| `GET /api/v2/roll/die-state` | `api/native_roll.rs` (`vercel.json`) | Route configuration only | `frontend/src/services/rollResourcesApi.ts` via `useRollDieState` → `RollHeader dieState` |
| `GET /api/v2/roll/eligible-issue-ids` | `api/native_roll.rs` (`vercel.json`) | Route configuration only | `rollResourcesApi` via `useRollEligibleIssueIds` → `ThreadPool eligibleThreadIds` |
| `POST /api/v2/issues/cards` | `api/native_issue.rs` (`vercel.json`) | Route configuration only | `rollResourcesApi` via `useRollIssueCards` → `ThreadPool issueCards` |

On `main`, Roll cold load is 1 bootstrap `GET` plus the 3 scoped reads.
`useRollBootstrap` (`frontend/src/hooks/useRollBootstrap.ts`) owns the
`queryKeys.roll.bootstrap()` cache, the reading-session greeting
(`session_id` + `user_id`), the mutation-reconciliation event
(`comic-pile:roll-bootstrap-reconciled`), and invalidation of
`eligibleIssueIdsAll` after a reconciled mutation. `rollMutationReconciliation`
(`frontend/src/hooks/rollMutationReconciliation.ts`) separately drives
`fetchAndPublishRollBootstrap` and `recoverProtectedRollMutation`
(`pending_thread_id` staleness check via `protectedRollMutationApi.bootstrap`).

## Field map

Source type: `RollBootstrapResponse` in `frontend/src/types/rollBootstrap.ts`.
Wire type: `RollV2BootstrapResponse` in `frontend/src/types/rollV2.ts`
(`rollable` is adapted to `roll_pool` by
`frontend/src/services/adaptRollV2Bootstrap.ts`).

| Bootstrap field | Current consumers on `main` | Scoped replacement | Blocker / deletion gate |
| --- | --- | --- | --- |
| `session_id` | `RollPage/index.tsx` undo session (`useSnapshots`), `handleUndoRating` (`undo.mutate`), `useRollBootstrap.ts` greeting (`trackSessionGreeting`) | None. No scoped GET carries session identity | #4343 current-session `GET` + #4405 sessionless decision |
| `user_id` | `useRollBootstrap.ts` greeting persistence | None in Roll scoped resources; identity belongs to auth/current-user surface, not a Roll GET | Move greeting to auth cache; delete with bootstrap |
| `current_die` | **Deleted from bootstrap wire** (#4352 contract-after). Formerly `useRollBootstrapSync.ts` page die state fallback; now `resolveRollSelectedDie` is scoped-only (`DieStateResponse.die` ?? d6). | `GET /v2/roll/die-state` `{ die }` (`DieStateResponse`) | Done (#4352 contract-after). The internal Rust `current_die` still bounds `offer_frontiers` but is no longer serialized. |
| `manual_die` | **Deleted from bootstrap wire** (#4352 contract-after). Formerly `useRollBootstrapSync.ts`, `useRatingView.ts` (`RatingViewData.manualDie`, now always `null`). | None needed. `DieStateResponse` exposes a single event-derived `die`; header convention (#4353) has no Auto/Manual segment | Done (#4352 contract-after). Bootstrap no longer serializes a manual pin. |
| `pending_thread_id` | `useRollPendingSession.ts` (rating-view hydration), `useRollActions.ts` (roll/pending flows), `RollPage/index.tsx` (`RollModals pendingThreadId`), `rollMutationReconciliation.ts` (committed check) | None | #4343 + #4405 |
| `last_rolled_result` | `useRollBootstrapSync.ts` (`setDiceState('rolled')`), `useRollPendingSession.ts`, `useRollActions.ts` | `DieStateResponse.last_roll` exists but is **global** across sessions; bootstrap reports the current session's pending roll. Substituting it lights a stale rolled state on a fresh idle die (see #4729). Not a replacement | Session-scoped pending projection or #4343 |
| `session_mode` | `RollHeader.tsx` → `ReadingModeControl` (`active_bandwidth/intent`, `bandwidth_source/confidence/version`) | None. `RollV2BootstrapResponse.bandwidth` is a separate wire field the frontend does not read | Session/sessionless `GET` or mode `GET` |
| `active_thread` | `useRollPendingSession.ts` (rating metadata), `useRollRating.ts` (`buildRatingThread`, `total_issues`), `useRollActions.ts` (pending metadata) | None | #4343 + #4405 |
| `roll_recovery` | `ReadingOrderGroups.tsx` → `RollRecoveryCard`; `switchPrerequisite` posts `POST /v1/roll/switch-prerequisite` | None | Recovery `GET` (or current-session `GET`) |
| `roll_pool` (`rollable` adapted) | `RollPage/index.tsx` `rollPool` → sliced `pool` → `ThreadPool` rows, `useRollPendingSession.ts` fallback, `useRollActions.ts` | Partial only: `eligible-issue-ids` orders `thread_ids`/`issue_ids`; `issue cards` supply `thread_title`/`issue_number`. Cards do not carry `format`, `tags`, `route_labels`, `overflow_routes_count`, `blocking_reasons` | Scoped display endpoint or extend cards to carry the row; until then `ThreadPool` sorts bootstrap rows by scoped order and overlays only card title/number |
| `snoozed_threads` | `RollPage/index.tsx` → `ThreadPool` snoozed section, `RollHeader.tsx` offset badge, `useRollModals.ts` override list, `useRollActions.ts` snooze check | None. Browser snooze cookie (`readRollSnoozes`) is the `eligible-issue-ids` input, not server snoozes | Server-snoozed `GET` or keep in current-session `GET` |
| `snoozed_count` | `RollPage/index.tsx` → `ThreadPool snoozedCount` | None (derivable as `snoozed_threads.length` once server snoozes have a home) | Same as `snoozed_threads` |
| `skipped_thread_ids`, `skipped_threads` | No RollPage/production consumer on `main`; present in types, fixtures, and tests | None needed for UI; server still sends them | Delete wire fields + shrink fixtures only when retiring bootstrap wholesale (#4299) |
| `pool_reason` | `RollPage/index.tsx` → `ThreadPool emptyPoolReason` (empty-pool copy) | None. Derived from the same Option E inputs as `rollable` but not exposed by any scoped endpoint | Scoped or current-session source for the empty-pool explanation |
| `last_read` | `RollPage/index.tsx` → `useRollLastRead` → `LastReadStrip` (cold-load seed; rate response seeds `roll.lastRead` cache on write) | None as a GET. The `roll.lastRead` cache is the write-side source | Last-read `GET` or make the rate-seeded cache authoritative for cold load |
| `timezone` | Request param `GET /v2/roll/bootstrap?timezone=` from `rollBootstrapApi`, echoed field; session timestamping via `POST /v2/reading-sessions` | `POST /v2/reading-sessions { timezone }` already owns timestamping; scoped reads take no timezone | Delete request/echo with bootstrap; keep session POST |

## Loading and error gate

`RollPage/index.tsx` holds the full page on `isBootstrapLoading` /
`isBootstrapError` (splash, retry, `401 → /login` in
`useRollBootstrapSync.ts`). The 3 scoped queries have independent
pending/error state. #4299 deletion requires promoting each surface's
scoped pending/error (or its replacement GET) to the gate for that surface,
not keeping bootstrap as a hard page gate. Background-only bootstrap reads
(`ReadingOrderGroups.tsx` recovery, `QueuePage.tsx` pending sync via
`useRollPendingSync`) must be re-pointed at their replacement reads when
they land; they currently share the `roll.bootstrap()` cache key.

## What #4719 already shipped (not deleted yet)

- Header die ladder reads `DieStateResponse.die` (`RollHeader`). Page die
  state is scoped-only `scopedDie ?? d6` (#4352 contract-after); the former
  `scopedDie ?? manualDie ?? currentDie` bootstrap fallback was removed with
  the bootstrap `current_die`/`manual_die` wire fields.
- `ThreadPool` renders `displayPool` by filtering bootstrap `pool` through
  scoped `thread_ids`, and overlays `thread_title` / `issue_number` from
  issue cards. Bootstrap remains the row source.
- Eligible IDs apply browser snoozes (`readRollSnoozes`) exactly as the
  offer does; the `coreRouteRequestBudget` suite pins the cold-load mix
  (1 session `POST` + 1 bootstrap `GET` + 1 die `GET` + 1 eligible `GET` +
  1 cards `POST`).

## Fixture and test impact for #4299

When a field is deleted, shrink `RollBootstrapResponse` fixtures and the
following suites in the same PR; do not widen baselines:

- `frontend/src/unit/coreRouteRequestBudget.test.tsx` (request counts),
  `rollMutationReconciliation.test.tsx`, `protectedRollMutationRecovery.test.ts`,
  `useRollBootstrap*.test.*`, `RollPage.*`, `rollDieModeReadout.test.tsx`,
  `ThreadPoolExclusionReasons.test.tsx`, `ReadingOrderGroups.test.tsx`,
  `LastReadStrip.test.tsx`.
- `frontend/src/test/` Playwright specs that read `/api/v2/roll/bootstrap`
  directly (`p0-roll-selection`, `reading-mode-acceptance`,
  `issue-3429-bootstrap-recovery`, etc.) move to the replacement read once
  its surface lands.

## Non-goals

This map does not remove the server route, the `vercel.json` entries, the
Python parity tooling, or any remaining bootstrap field. The bootstrap
`current_die`/`manual_die` wire fields were removed field-by-field by the
#4352 contract-after slice (die now scoped-only); retirement of the
`GET /api/v2/roll/bootstrap` endpoint itself remains #4299, blocked on
#4343/#4405, and `last_rolled_result` is retained for pending hydration
(session-scoped). It does not add a scoped replacement for
session/pending/recovery, does not change any Roll surface's loading,
empty, or error behavior, and does not claim production Rust execution
proof. Visual grammar: no frontend visual surface is touched, so no
`FRONTEND_VISUAL_GRAMMAR.md` role, spacing, typography, or overlay
primitive changes.
