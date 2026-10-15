# Thread detail

**Route:** `/thread/:id`. Inspect and edit a series' issue order, progress, ratings and external identity.

## MQA-THREAD-001: Next unread and progress

**Setup:** QA thread with mixed read/unread issues.

**Test:** Inspect next unread, change one issue read/unread, reload and compare Queue/Roll.

**Expected:** Next unread follows stored issue order; progress persists across surfaces; unrelated issues remain unchanged.

## MQA-THREAD-002: Rating advances only intended issue

**Test:** Roll a QA series, rate it, then inspect issue, thread and History.

**Expected:** Rating attaches to the selected issue; progress advances exactly once, with consistent die and queue effects.

## MQA-THREAD-003: Special issue numbering

**Test:** Add or edit an Annual, Special, or fractional-number QA issue, then reopen detail.

**Expected:** Distinct issue identity/number/order persists; specials are not coalesced into ordinary numbered issues.

## MQA-THREAD-004: Per-issue provider identity

**Setup:** A QA thread with mixed resolved/unresolved ComicVine issues.

**Test:** Inspect individual issue indicators, explicitly map a correct issue and reload.

**Expected:** Only the approved issue mapping changes; issue-level and queue indicators agree.

## MQA-THREAD-005: Metadata edits preserve history

**Test:** Edit thread metadata without an explicit queue move or read/rate action.

**Expected:** Ratings, read state, reading-list membership, prerequisites and queue position are preserved.
