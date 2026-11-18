# Issue #4589: Snooze/Unsnooze Fix Implementation Summary

## Problem
- Snoozing a pending roll lost the roll session, jumped the die (d6 → d12), and dropped snooze eligibility
- Unsnoozing was client-only with no server endpoint to restore state
- No rating saved, no History entry for the lost roll

## Root Cause
1. **Snooze (reroll)**: The Rust roll offer endpoint recorded a snooze event and advanced the die, but **did not persist the snoozed thread ID** to `session.snoozed_thread_ids`. The frontend only added it to a browser cookie.
2. **Unsnooze**: Was client-only (just removed from browser cookie) with no server endpoint to restore the previous pending roll and revert the die.

## Changes Made

### 1. Rust Backend (`native/roll-service/src/roll_offer.rs`)
- **Snooze persistence** (lines 412-424): Modified the `offer` function to append the snoozed thread ID to `session.snoozed_thread_ids` in the database
- **New unsnooze endpoint** (lines 492-660): Added `POST /api/v2/roll/unsnooze` that:
  - Validates the requested thread is the most recently snoozed one (LIFO)
  - Finds the original snooze event to get `die_before` for die reversion
  - Removes the thread from `session.snoozed_thread_ids`
  - Restores the snoozed thread as the pending roll
  - Records an `unsnooze` event with the reverted die
  - Returns the restored thread metadata

### 2. Route Registration (`native/roll-service/src/lib.rs`)
- Added `/api/v2/roll/unsnooze` POST route mapping to `roll_offer::unsnooze`

### 3. Route Fragment (`docs/api/route-fragments/roll.json`)
- Added the unsnooze operation to the v2 operations bucket
- Updated owned_path_patterns to include `^/api/v2/roll/unsnooze$`

### 4. Frontend API (`frontend/src/services/api-roll.ts`)
- Added `unsnooze(threadId)` function calling `/v2/roll/unsnooze`
- Updated `RollApi` interface to include `unsnooze` method

### 5. Queue Actions (`frontend/src/pages/QueuePage/useQueueThreadActions.ts`)
- Updated to use the server unsnooze endpoint instead of client-only cookie removal
- Added `unsnooze` to dependency injection
- Updated snooze/unsnooze toggle logic to call server endpoint

### 6. Tests
- Added unit test `unsnooze_request_shape_requires_explicit_thread_id_and_rejects_unknown_fields` in `roll_offer.rs`

## Behavior After Fix
1. **Snooze**: 
   - Persists the snoozed thread in `session.snoozed_thread_ids`
   - Advances the die (d6 → d8 → d10 → d12 → d20)
   - Selects a new roll offer

2. **Unsnooze**: 
   - Calls server endpoint that restores the original pending thread
   - Reverts the die to its pre-snooze size
   - Removes the thread from `snoozed_thread_ids`
   - Returns updated state so UI can rehydrate

## Route Generation
- Ran `python3 scripts/generate_route_burndown.py` to update `vercel.json` and `docs/api/v2-route-inventory.json`
- New v2 operation: `POST /api/v2/roll/unsnooze -> native-rust` (issue #4589)

## Verification
- `cargo check` passes
- Non-database unit tests pass (9/21 tests in roll_offer module - 12 are database tests requiring RUST_ROLL_TEST_DATABASE_URL)
- Route generation successful