# Queue

**Route:** `/queue`. The queue contains the reader's durable ordered threads. Being present in Queue is not the same as being eligible in the current Roll pool.

## MQA-QUEUE-001: Ordering and positions persist

**Setup:** Several QA threads with distinct positions.

**Test:** Drag/reorder one and move another to front, then reload Queue and each thread page.

**Expected:** Displayed positions agree everywhere (Queue list, Thread page and pending Roll label), persist, and do not duplicate or lose rows. Regression history: #5263, fixed by #5429.

## MQA-QUEUE-002: Move to front affects the bounded pool

**Setup:** An eligible QA thread beyond the chosen die boundary.

**Test:** Move it to front and inspect Roll.

**Expected:** The thread enters the eligible die pool by new queue position; the selected die size remains unchanged.

## MQA-QUEUE-003: Snooze and re-admit

**Test:** Snooze a QA series, inspect its queue/roll state, then unsnooze or satisfy the relevant backoff rule.

**Expected:** Excluded series do not roll while excluded, without being deleted or silently re-prioritized; they return when eligible. Temporary snoozes are browser-scoped reroll exclusions that expire at local midnight or on Reset Dice ([#4405](https://github.com/JoshCLWren/comic-pile/issues/4405); UPDATE 2026-11-18). Durable exclusion is Remove from Queue, which is non-destructive and restorable from the excluded section.

## MQA-QUEUE-004: Blocked differs from out-of-pool

**Setup:** One QA series with an unread prerequisite and a different eligible series outside the die boundary.

**Test:** Inspect labels/explanations and attempt Roll.

**Expected:** True blockers name a real prerequisite; out-of-pool is not mislabeled blocked; neither ineligible series is selected.

## MQA-QUEUE-005: Mapping health agrees with owned issues

**Setup:** Fully, partly and unmapped QA threads.

**Test:** Compare indicators with their tracked issues; safely map one and revisit Queue.

**Expected:** Counts reflect real issue mapping state, not title similarity, and refresh after mapping. Fully confirmed series stay unobtrusive.

## MQA-QUEUE-006: Counts, canonical issue numbers, and sort order are truthful

**Setup:** A QA series containing issue #40 among eight owned issues, plus a Queue with filters and alternate sorts.

**Test:** Inspect Queue/Roll count labels and issue numbering; switch position, title and recently-added sorts; exercise Reposition from a filtered view.

**Expected:** Canonical issue number and ordinal progress are clearly different (never Issue 40 of 8). Count/copy distinguish zero, one, and many, including Map Series. Reposition uses the series' actual unfiltered Queue position. In a non-position sort, the interface explains that a position change affects position order, or makes the action unavailable; it must not suggest the current alternate sort will visibly rearrange. Reopening position sort shows the persisted correct rank.

## MQA-QUEUE-007: Search and clear use the latest query

**Setup:** Large QA Queue with known title matches and a controllably slow search response.

**Test:** Type quickly, clear with the labeled clear control, press Escape while focused in search, then immediately search another title; resolve the older response after the newer one. Check a narrow viewport and keyboard-only use.

**Expected:** Filtering/clear respond within the normal short debounce (under one second in normal local/test conditions), with visible accessible feedback during genuine remote delay. Older responses never overwrite the latest query, result counts, or empty state. Clear and Escape restore the unfiltered series set without mutating Queue order; focus remains sensible. If a filtered N of M count is shown, both numbers match the actual scope.

## MQA-QUEUE-008: Add/Edit Series drafts are safe and validated

**Setup:** QA series with both read and unread issues and an editable issue range.

**Test:** Make an unsaved change, Cancel, then edit again and attempt to close; stage issue removal; enter Already read as -1, 1.5, an over-maximum value, zero, and the maximum. Attempt to remove a ComicVine mapping.

**Expected:** Cancel discards the draft. Closing a dirty draft asks whether to discard; closing an unchanged draft does not. Staged issue removals clearly occur only on Save, while committed destructive work keeps explicit confirmation. Already read accepts integers from zero through the real maximum inclusive, with inline errors and disabled submit for invalid values, and server-side rejection if bypassed. Mapping removal uses an accessible app confirmation dialog, not a native window.confirm. Cancel/error never mutates persisted issues.

## MQA-QUEUE-009: Sibling mapping suggestions respect canonical identities

**Setup:** QA library with partially mapped issues, duplicate #2 and #20-22 identifiers, and similarly named but distinct ComicVine volumes.

**Test:** Correct one mapping and inspect suggested related issues before accepting any.

**Expected:** Only applicable unmapped or mismatched issues from the same canonical Thread/series are suggested. Stable identities deduplicate suggestions; already-correct issues are excluded or clearly non-actionable. Same-name, wrong-volume, or unrelated Thread issues are not suggested or auto-remapped. No mutation occurs without explicit approval.

## MQA-QUEUE-010: Confirmed edits promptly reconcile visible state

**Test:** Rename a QA series, mark it completed, inspect Queue and other open surfaces without hard refresh, then repeat while simulating failed mutations and stale query responses.

**Expected:** Confirmed title and active/completed state refresh promptly across affected views, including Queue position. Targeted cache invalidation prevents stale data from reappearing; failed operations never falsely show committed changes or lose persisted state. No unrelated Thread is affected.

**Tracking:** Approved Queue/dialog work [#3558](https://github.com/JoshCLWren/comic-pile/issues/3558); related QA regression [#3771](https://github.com/JoshCLWren/comic-pile/issues/3771). Keep separately tracked functional Queue bugs independent of this usability contract.


## MQA-QUEUE-011: Finished series stay listed

**Setup:** QA account with at least one completed series.

**Test:** Open Queue, expand Finished Series, reload and navigate away and back.

**Expected:** Completed series remain listed (read from the completed collection, not the active-only Queue rows). Source: #5171, fixed by #5297.

## MQA-QUEUE-012: Queue rows show the series cover when a confirmed cover exists

**Test:** Open Queue with one series whose next unread issue has a confirmed ComicVine mapping carrying a cover, one series whose only confirmed covers sit on later issues, and one series with no confirmed cover. Expand the page at phone and desktop widths.

**Expected:** The series with a confirmed cover shows the provider cover image at the start of its row, using the provider URL unchanged and reserving its frame before load (no layout shift). The later-issue series shows the first confirmed cover by issue position. The series without a confirmed cover shows the shared "No cover" placeholder, not a broken image or an empty gap. Covers never come from unconfirmed candidates.

**Tracking:** Part of the V2 covers work [#5433](https://github.com/JoshCLWren/comic-pile/issues/5433). Other views (Thread detail, History, Sessions, plans, CBL browser, Identity inbox, Creators, Crossovers) are not covered by this scenario yet.
