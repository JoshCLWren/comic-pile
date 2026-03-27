# Changelog

## [unreleased]

* Enhanced expandable "N threads hidden" section with detailed blocking reasons
* Each blocked thread shows its primary blocking reason (e.g., "Blocked by Ultimate Spider-Man #5")
* For threads with multiple blockers, the most immediate blocker (by queue position) is shown first
* Clicking a thread navigates to queue page with automatic scroll to highlighted thread
* Mobile-optimized with 44px touch targets and scrollable list
* Shows first 10 threads with "show X more" toggle for larger lists
* Fixed show-all toggle resetting when section collapses
* Section hidden entirely when no threads are blocked
* Blocked threads list now respects the active collection filter, ensuring count and navigation are context-aware
* Fixed test expectations for new navigation behavior
* Fixed Python indentation errors in roll API endpoint
* Implemented missing `POST /roll/dismiss-pending` endpoint for canceling pending rolls
* Verified issue-level dependencies work correctly (closes #363)
