# Changelog

## 2026-03-25

**Roll Page Header Indicators (#366)**
- Added labels and tooltips to roll page header indicators (+1, snoozed, offset, active)
- Each indicator now has a visible text label or accessible tooltip with explanatory copy
- Interactive indicators have clear visual affordances (cursor-help, dashed borders)
- Tooltips explain what each value means and whether/how it can be changed
- Screen readers can read each indicator's label and value via aria-label attributes
- No layout changes to the roll page — tooltips fit within existing header space

## 2026-03-24

**Accessibility Improvements (#220)**
- Added `aria-label="Roll pool collection"` to ThreadPool container for screen reader support
- Added `role="dialog"`, `aria-modal="true"`, and `aria-labelledby` to Modal component
- Implemented focus trap in Modal component to keep focus within dialog
- Added focus return to trigger element on Modal close
- Fixed ESLint warnings for React hook dependencies in RollPage

**Documentation Updates (#220)**
- README.md: Added prominent async-only PostgreSQL warning and guidance
- docs/API.md: Documented dependency blocking behavior and issue-level endpoints
- docs/REACT_ARCHITECTURE.md: Added mobile usage guide and accessibility section
- Updated technology stack descriptions with current patterns

**Form Accessibility**
- Create Thread modal: All inputs now have associated labels with proper IDs
- Edit Thread modal: Improved label associations for title, format, issues, notes
- FormatSelect component: Added optional `id` prop for label association
- Rating slider: Already had proper aria-label, maintained consistency

**Issue Dependencies (#366)**
- Added dependency indicators (🔗) to issues with dependencies
- Added tooltips to show linked issues and threads on hover
- Added dependency status to issue list in queue edit modal
- Added mobile-friendly tooltips for dependency information
- Added edit icon next to issue number in rating view
- Added quick correction dialog for adjusting current issue number

## 2026-03-21

**Collection Management UI Redesign**
- Consolidated collection management into coherent toolbar on Roll and Queue pages
- Collection selector moved from ThreadPool to page header for better discoverability
- "+ New Collection" button now consistently available in header toolbar
- Unified collection filtering across Roll and Queue pages
- Improved mobile responsiveness with toolbar design

**Collections**
- Success toast notification now appears after creating a collection
- Toast includes collection name and auto-dismisses after 5 seconds
- No success message shown on validation or network errors

**Developer Tools**
- Added `GET /api/v1/threads/{thread_id}/dependency-order-check` endpoint to detect conflicts between dependency-implied reading order and issue position order
- Returns structured conflict data with issue IDs, positions, and dependency requirements for debugging

**Issue Dependencies**
- New API endpoint: GET /api/v1/issues/{issue_id}/dependencies returns issue-level dependency edges
- Dependency indicators (🔗) now shown on issues with incoming/outgoing dependencies
- Tooltip displays linked issues and threads on hover
- Authorization enforced: only shows dependencies for owned threads

**UI Polish**
- Issue list in queue edit modal now shows dependency status
- Mobile-friendly tooltips for dependency information

**Issue Number Correction**
- Added edit icon next to issue number in rating view
- Quick correction dialog allows adjusting current issue without leaving the rating page
- +/- buttons for easy issue number adjustment
- Validates issue number is within valid range (1 to total issues)
- Updates thread's issue tracking state automatically

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
