# Changelog

## 2026-03-20

**CI & Infrastructure**
- E2E tests: disabled rate limiting in CI shards by adding TEST_ENVIRONMENT=true
- E2E tests: replaced flaky `networkidle` waits with deterministic element selectors

**Rating Flow**
- Rating slider now defaults to neutral (2.5) value instead of minimum
- Save & Complete button shown for last issue in thread

**Notifications**
- Session expiry now shows toast notification when session times out
- New Finish Session button for manual session cleanup

**Validation & Error Handling**
- Snooze at d20 max pool size now shows feedback message
- Manual die selection persists when rolling into snoozed threads
- Improved feedback when rolled die exceeds pool size
- Collection filter now available on roll API and get_roll_pool endpoint
- Validation prevents rating threads with 0 issues remaining
- Config validation errors now raise ValueError instead of silent fallback

**D10 Geometry**
- Centered d10 face numbers for better readability
- Prevented adjacent consecutive numbers on d10 faces

**Stale Thread Management**
- Stale thread count now displayed as indicator badge
- Test endpoint enabled for stale thread validation

## 2026-03-19

**Validation & Error Handling**
- Unsnooze endpoint now returns HTTP 404 for non-snoozed threads instead of silent no-op
- Move-to-position endpoint now returns HTTP 400 for out-of-range positions instead of silent clamping

**Roll Flow & Session Management**
- Manual die selection now persists across rating/snooze operations
- Override roll validates against blocked/completed threads with clear error messages
- Snooze state preserved when overriding to snoozed threads
- Completed threads removed from active slot after rating last issue
- Phantom roll events no longer created when snoozing

**UI Improvements**
- "Tap Die to Roll" instruction hidden when pool is empty
- Snoozed-offset badge hidden at d20 ceiling where it has no effect

## 2026-03-18

**Mobile UX Redesign (Complete)**
- Complete mobile UI overhaul with responsive design improvements
- Touch-optimized interface across all major screens
- Mobile-specific navigation and interaction patterns

**Dependency Blocking**
- Fixed dependency blocking to only block when next unread issue has unread prerequisite
- Improved `is_blocked` flag recalculation after dependency changes
- Dependency blocking now works correctly regardless of `next_unread_issue`

**Data Migration**
- Fixed off-by-one error in auto-migration that created phantom issues

## 2026-03-16

**Blocking & Reminders**
- Blocked threads now excluded from stale/reminder suggestions
- Improved stale thread detection to respect blocked status

**CI & Infrastructure**
- Updated CI setup actions for improved reliability
- Added utility scripts for development workflow

## 2026-03-14

**API Refactoring**
- Extracted shared Comic Pile API utilities to reduce code duplication
- Improved code organization across API endpoints

**Dependencies**
- Fixed issue dependencies to block threads regardless of `next_unread_issue` state

## 2026-03-09

**Issue Management Sweep**
- Comprehensive update to issue management across backend, frontend, migrations, and tests
- Improved issue tracking and display throughout the application

## 2026-03-08

**Issue Management Improvements**
- Fixed 500 error when creating duplicate issue-level or thread-level dependencies
- Fixed 500 error when deleting threads with Issue records
- Persist and display next issue number in the rating flow

**Bug Fixes**
- Fixed inconsistent timestamps on Session Details page
- Fixed thread editing modal closing unexpectedly

## 2026-03-06

**Authentication**
- Fixed repeated 401 Unauthorized errors in browser console during token refresh

## 2026-03-05

**Thread Blocking Usability**
- Complete overhaul of thread blocking UX
- Improved visibility and management of blocked threads

## 2026-03-03

- Roll/rate sequencing fix: `Save & Continue` no longer auto-selects a new pending thread.
- After a successful rate with `finish_session=false`, the session returns to roll state with
  `pending_thread_id=null`.
- Users must perform a new roll (or explicitly set pending) before submitting another rating.
