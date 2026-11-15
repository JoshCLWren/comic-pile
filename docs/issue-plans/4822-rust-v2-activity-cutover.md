# Issue #4822: Rust v2 Activity Cutover Implementation Plan

## Issue Summary

**P1 user-visible correctness / historical audit omission.** History omits sessionless snoozes and ratings, showing impossible dice jumps. This is Rust cutover completion work, not post-Rust UX or a proposal to repair Python sessions.

**Related Issues:** #4335, #4405

## Root Cause

Native Rust `native/roll-service/src/dice_mutation.rs::persist_in_transaction` writes durable, **owner-scoped** dice events with `user_id`, `session_id = NULL`. The Rust Roll offer path still stores roll events on legacy session `1018133`.

`frontend/src/pages/HistoryPage.tsx` uses `useSessions()` (old session summaries); `frontend/src/pages/SessionPage.tsx` uses `useSessionDetails()` (old session timeline).

`frontend/src/services/api-sessions.ts` still fetches `/v1/sessions/` and `/v1/sessions/{id}/details`. `app/services/session_response.py::build_ladder_path` filters `Event.session_id == session_id`, `type IN ('rate','snooze','undo')`, excluding the new sessionless dice events. Thus UI shows the d6/d8 rolls without the actual snoozes/rating.

This directly violates Roll simplification: event-derived dice, one Roll/Reroll flow, no reading sessions #4405's approved **one chronological owner-scoped activity history, no sessions** contract.

## Production Evidence

Read-only production evidence, `user_id = 1`:

| Central time | event id | type | session_id | die | die_after | issue/thread |
| --- | --- | --- | --- | --- | --- | --- |
| 09:42:35.028 | 1050511 | roll | 1018133 | d6 | NULL | issue 1121330, thread 3153 |
| 09:46:25.467 | 1050513 | roll | 1018133 | d8 | NULL | issue 25301, thread 3469 |
| 09:46:25.515 | 1050512 | snooze | NULL | d6 | d8 | thread 3153 |
| 09:46:34.066 | 1050515 | roll | 1018133 | d10 | NULL | issue 52329, thread 8417 |
| 09:46:34.105 | 1050514 | snooze | NULL | d8 | d10 | thread 3469 |
| 10:01:54.388 | 1050517 | rate (issue command receipt) | NULL | NULL | d8 | Astro City: Astra #2, issue 52329, rating 4.5 |
| 10:01:54.440 | 1050516 | rate (dice command) | NULL | d10 | d8 | same issue/rating |

**Important:** The d8/d10 *resulting rolls have timestamps slightly earlier than the causal snooze rows*. Naively ordering by `timestamp, id` or appending these rows will misrepresent cause/effect. The rate pair is **one user action** and must not be duplicated in the user-facing timeline.

## Implementation Requirements

### 1. Build a bounded, owner-scoped Rust **resource GET**

Create `GET /api/v2/activity` endpoint using one SQL statement inclusive of authenticated ownership.

**SQL Requirements:**
- Query `events` table with `WHERE user_id = $1`
- Include all event types: `roll`, `snooze`, `rate`, `manual_die`, `reset_dice`
- Return chronological user activity with stable cursor pagination
- Include fields: `event_id`, `type`, `timestamp`, `die_before`, `die_after`, `rating`, `issue_id`, `thread_id`, `thread_title`, `issue_number` as available

**Pagination:**
- Cursor-based pagination (timestamp DESC, id DESC) with stable opaque tokens
- Support forward/backward pagination via `before`/`after` cursor parameters

**Owner Isolation:**
- Only authenticated user's events returned
- No leakage of other users' events

### 2. Derive reader-visible *logical actions*

Retain underlying audit rows but coalesce related events into logical actions:

**Rate Pair Coalescing:**
- Coalesce `issue_command_key`/`dice_command_key` rate pair into **one rating display**
- Do not erase either event
- Do not merge unrelated repeated ratings
- Show direct reads/ratings even when they do not change the die

**Causal Narrative:**
- Preserve causal narrative for reroll/snooze: **snoozed previous offer (d6→d8), then rolled new offer on d8**
- Handle timestamp inversions (snooze timestamps slightly earlier than resulting rolls)
- Use durable `roll_offer_key`/`dice_command_key` and source references where available
- No timestamp fabrication, no historical event rewrite
- Specify deterministic fallback for legacy records that lack linkage

### 3. Replace `/history` read path

Replace `/history` read path with the real owner-scoped activity resource, not a second/history-only shadow implementation.

**Frontend Changes:**
- Replace `frontend/src/pages/HistoryPage.tsx` to use new `useActivity` hook
- Remove dependency on `useSessions()` and `api-sessions.ts`
- Surface both snoozes, all rolls, the 4.5 rating, manual select/reset, and historic changes
- Keep legacy history safely readable until actual migration; retire old session history on same dependency path

**Backend Changes:**
- Add new Rust endpoint `GET /api/v2/activity`
- Integrate with existing `dice_mutation.rs` event persistence
- Remove or deprecate Python `/v1/sessions/{id}/details` endpoint

### 4. Reuse exact owned `issue_id`

Reuse exact owned `issue_id` for actionable comic UI where available.

**Fallback Handling:**
- Deleted thread or missing identity gets a safe historical label
- Never a fabricated mapping
- Preserve thread_id and issue_id for legacy records

### 5. Add comprehensive tests

**PostgreSQL Tests:**
- Unit tests for activity resource query
- Integration test for exact production scenario (09:42→10:01 sequence)
- Test timestamp inversions
- Test rate pair coalescing
- Test cross-user isolation
- Test pagination
- Test refresh behavior
- Test historical legacy events
- Test no duplicate steps

**Frontend Tests:**
- Unit tests for `useActivity` hook
- Unit tests for `HistoryPage` component
- E2E tests for activity flow

### 6. Required CI and Review

**Exact-Head CI:**
- All tests must pass
- Rust release build must compile cleanly
- Frontend typecheck must pass
- Frontend lint must pass

**Independent Semantic Review:**
- Review must verify:
  - Owner-scoped activity resource with single SQL statement
  - Chronological user activity with stable cursor pagination
  - Reader-visible logical actions with rate pair coalescing
  - Causal narrative preserved using durable keys
  - `/history` read path replaced with real owner-scoped activity resource
  - Exact owned issue_id for actionable comic UI
  - Disposable Postgres tests (unit tests pass, integration test requires CI)

**Production Deployment:**
- Deploy to Vercel
- Authenticate and verify production behavior

**Authenticated QA:**
- Owner sees: d6 → snooze to d8 → roll d8 → snooze to d10 → roll d10 → rated 4.5 → d8
- Event names and timestamps must be accurate
- No impossible dice jumps

## Factory Coordination

Treat as a focused executable Rust cutover child of #4335/#4405; do not block it on its parent epic.

Check existing active claims before editing shared Rust Roll/History/frontend files.

No preview DB, shadow mode, new paid service or Python extension.

Keep database unchanged: no repair/backfill is necessary because all actions are durable.

## Current Status

**PR #4991** was created with implementation but was **closed without merging**.

The implementation commit `73775e681` is NOT in main or the current branch.

The activity file `native/roll-service/src/activity.rs` does not exist yet.

## Implementation Steps

1. **Create Rust activity module** (`native/roll-service/src/activity.rs`)
   - Define activity types (ActivityEvent, ActivityResponse, ActivityThreadRef, ActivityIssueRef)
   - Implement SQL query for owner-scoped activity with cursor pagination
   - Implement rate pair coalescing logic
   - Add handler for `GET /api/v2/activity`

2. **Update Rust router** (`native/roll-service/src/lib.rs`)
   - Add activity module
   - Add activity route to OpenAPI
   - Update route inventory

3. **Create frontend types** (`frontend/src/types/activity.ts`)
   - ActivityEventType
   - ActivityThreadRef
   - ActivityIssueRef
   - ActivityEvent
   - ActivityResponse

4. **Create frontend query keys** (`frontend/src/query/queryKeys.ts`)
   - activity.list
   - activity.page

5. **Create frontend API service** (`frontend/src/services/api-activity.ts`)
   - activityApi with list/listAll methods

6. **Create frontend hook** (`frontend/src/hooks/useActivity.ts`)
   - useActivity (infinite query)
   - useActivityPage (single page)

7. **Update HistoryPage** (`frontend/src/pages/HistoryPage.tsx`)
   - Replace useSessions with useActivity
   - Implement chronological timeline
   - Implement grouped rate pairs
   - Add event type badges
   - Add thread/issue links
   - Add die progression display
   - Add rating details
   - Add infinite scrolling

8. **Add Rust unit tests** (`native/roll-service/src/activity.rs`)
   - Test SQL query construction
   - Test rate pair coalescing
   - Test cursor pagination
   - Test owner isolation

9. **Add Rust integration test**
   - Test exact production scenario from issue
   - Test timestamp inversions
   - Test rate pair coalescing
   - Test cross-user isolation
   - Test pagination
   - Test refresh behavior
   - Test historical legacy events
   - Test no duplicate steps

10. **Add frontend unit tests**
    - Test useActivity hook
    - Test HistoryPage component

11. **Update documentation**
    - Add API documentation for `/api/v2/activity`
    - Update route inventory

## Acceptance Criteria Checklist

- [ ] Owner-scoped activity resource with single SQL statement
- [ ] Chronological user activity with stable cursor pagination
- [ ] Reader-visible logical actions with rate pair coalescing
- [ ] Causal narrative preserved using durable roll_offer_key/dice_command_key
- [ ] `/history` read path replaced with real owner-scoped activity resource
- [ ] Exact owned issue_id for actionable comic UI
- [ ] Disposable Postgres tests (unit tests pass, integration test requires CI)
- [ ] Ready for exact-head CI, independent semantic review, production deployment, authenticated QA

## Verification

Once implemented, verify in production:

1. Navigate to History page
2. Verify sequence: d6 → snooze to d8 → roll d8 → snooze to d10 → roll d10 → rated 4.5 → d8
3. Verify event names and timestamps are accurate
4. Verify no impossible dice jumps
5. Verify cross-user isolation (can't see other users' events)
6. Verify pagination works correctly
7. Verify rate pairs are coalesced into single entries
8. Verify thread/issue links are correct

## Risk Assessment

**High Risk:**
- Timestamp inversions could cause incorrect ordering
- Rate pair coalescing could merge unrelated events
- Cross-user isolation could leak events

**Medium Risk:**
- Legacy records without linkage could break causal narrative
- Pagination cursor stability could be compromised

**Low Risk:**
- Frontend rendering changes
- Documentation updates

## Dependencies

- Rust Roll cutover (#4335) - already complete
- Roll simplification (#4405) - already complete
- Existing events table persistence (already in place)
- Existing authentication system (already in place)

## Rollback Plan

If implementation fails:

1. Revert activity.rs changes
2. Revert HistoryPage.tsx changes
3. Restore previous session-based history
4. Keep Python `/v1/sessions/{id}/details` endpoint functional

## Timeline Estimate

- Rust activity module: 2-3 hours
- Frontend types and hooks: 1-2 hours
- HistoryPage rewrite: 2-3 hours
- Tests: 2-3 hours
- Documentation: 1 hour
- **Total: 8-12 hours**

## Notes

- Do not extend Python v1 as the final fix
- Do not create shadow implementations
- Do not add new paid services
- Keep database unchanged (no repair/backfill needed)
- Focus on closure-critical behavior first, polish second
